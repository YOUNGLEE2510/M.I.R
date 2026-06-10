"""
optimize.py – Tối ưu trọng số đặc trưng để đạt Precision@5 >= 70% cho MỌI nhạc cụ.

Thuật toán: Simulated Annealing + Fully Vectorized Evaluation
- Mục tiêu chính: min_instrument_accuracy >= 70%
- Mục tiêu phụ: tối đa macro-average precision (tránh bias về nhạc cụ có nhiều mẫu)
- Sử dụng Stratified Train/Val Split (80/20) để tránh data leakage
- Tối ưu trên train set, đánh giá trên val set

Usage:
    python optimize.py              # Chạy tối ưu mặc định (1000 iteration)
    python optimize.py -n 2000      # Chạy 2000 iteration
    python optimize.py --apply      # Tự động cập nhật config.py
"""

import sys
import os
import random
import math
import copy
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
from database.mongo_client import get_db
from config import FEATURE_WEIGHTS

# Nhóm đặc trưng và chỉ mục tương ứng trong vector 100 chiều
GROUPS = {
    'mfcc_mean': (0, 40),
    'mfcc_std':  (40, 80),
    'chroma':    (80, 92),
    'centroid':  (92, 94),
    'rolloff':   (94, 95),
    'flux':      (95, 96),
    'zcr':       (96, 97),
    'rms':       (97, 98),
    'hnr':       (98, 99),
    'onset':     (99, 100),
}

# ── Constraint: giới hạn weight tránh overfitting ──
WEIGHT_BOUNDS = {
    'mfcc_mean': (0.05, 5.0),
    'mfcc_std':  (0.05, 5.0),
    'chroma':    (0.01, 0.5),      # Lower bound 0.01 (không triệt tiêu hoàn toàn)
    'centroid':  (0.05, 10.0),
    'rolloff':   (0.05, 10.0),
    'flux':      (0.05, 10.0),
    'zcr':       (0.05, 10.0),
    'rms':       (0.05, 10.0),
    'hnr':       (0.05, 10.0),
    'onset':     (0.05, 10.0),
}

# Tỷ lệ max/min weight tối đa cho phép
MAX_WEIGHT_RATIO = 100.0

# Hệ số regularization L2
L2_LAMBDA = 0.01


def get_weight_vector(group_weights: dict) -> np.ndarray:
    """Tạo vector trọng số 100 chiều từ trọng số nhóm."""
    w = np.ones(100, dtype=np.float32)
    for name, (start, end) in GROUPS.items():
        w[start:end] = group_weights[name]
    return w


def stratified_split(recs, val_ratio=0.2, seed=42):
    """Stratified Train/Val Split – đảm bảo tỷ lệ mỗi nhạc cụ được giữ.

    Args:
        recs: list of records from MongoDB
        val_ratio: tỷ lệ validation set (mặc định 20%)
        seed: random seed

    Returns:
        train_indices, val_indices: numpy arrays of indices
    """
    rng = random.Random(seed)

    # Nhóm theo nhạc cụ
    inst_groups = {}
    for i, r in enumerate(recs):
        inst = r["instrument"]
        inst_groups.setdefault(inst, []).append(i)

    train_indices = []
    val_indices = []

    for inst, indices in sorted(inst_groups.items()):
        shuffled = indices.copy()
        rng.shuffle(shuffled)
        n_val = max(1, int(len(shuffled) * val_ratio))  # ít nhất 1 mẫu val
        val_indices.extend(shuffled[:n_val])
        train_indices.extend(shuffled[n_val:])

    return np.array(train_indices), np.array(val_indices)


def prepare_data(recs):
    """Chuẩn bị dữ liệu cho evaluation nhanh.

    Returns:
        raw_vecs: (N, 100) float32 – vectors đã bỏ trọng số config
        instruments: list[str]
        inst_indices: dict[str, np.ndarray] – chỉ mục theo nhạc cụ
    """
    w_config = get_weight_vector(FEATURE_WEIGHTS)
    w_config = np.where(w_config == 0, 1e-9, w_config)

    N = len(recs)
    raw_vecs = np.zeros((N, 100), dtype=np.float32)
    instruments = []

    for i, r in enumerate(recs):
        v = np.array(r["feature_vector"], dtype=np.float32)
        raw_vecs[i] = v / w_config
        instruments.append(r["instrument"])

    # Build index per instrument
    inst_indices = {}
    for i, inst in enumerate(instruments):
        inst_indices.setdefault(inst, []).append(i)
    inst_indices = {k: np.array(v) for k, v in inst_indices.items()}

    return raw_vecs, instruments, inst_indices


def evaluate_fast(raw_vecs, instruments, inst_indices, group_weights,
                  query_indices=None, gallery_indices=None, k=5):
    """Đánh giá Precision@K FULLY VECTORIZED.

    Hỗ trợ train/val split:
      - query_indices: các mẫu dùng làm query (val set)
      - gallery_indices: các mẫu dùng làm gallery (train set)
      Nếu None, dùng toàn bộ dataset (leave-one-out style).
    """
    w = get_weight_vector(group_weights)
    N = raw_vecs.shape[0]

    # Apply weights and L2 normalize
    weighted = raw_vecs * w  # (N, 100)
    norms = np.linalg.norm(weighted, axis=1, keepdims=True)
    norms = np.where(norms < 1e-9, 1.0, norms)
    normed = weighted / norms  # (N, 100)

    if query_indices is not None and gallery_indices is not None:
        # Train/Val mode: query từ val, search trong train
        q_normed = normed[query_indices]      # (Q, 100)
        g_normed = normed[gallery_indices]     # (G, 100)

        # Similarity matrix: (Q, G)
        sim_matrix = q_normed @ g_normed.T

        Q = len(query_indices)
        G = len(gallery_indices)
        actual_k = min(k, G)

        # Top-K indices trong gallery
        if G > actual_k:
            top_k_idx = np.argpartition(sim_matrix, -actual_k, axis=1)[:, -actual_k:]
            rows = np.arange(Q)[:, None]
            top_k_sims = sim_matrix[rows, top_k_idx]
            sorted_order = np.argsort(-top_k_sims, axis=1)
            top_k_idx = top_k_idx[rows, sorted_order]
        else:
            top_k_idx = np.argsort(-sim_matrix, axis=1)[:, :actual_k]

        # Map gallery indices back to global
        instruments_arr = np.array(instruments)
        query_instruments = instruments_arr[query_indices][:, None]   # (Q, 1)
        gallery_instruments = instruments_arr[gallery_indices]
        hit_instruments = gallery_instruments[top_k_idx]              # (Q, k)
        correct = (query_instruments == hit_instruments)
        precisions = correct.sum(axis=1) / actual_k

        # Per-instrument (trên query set)
        inst_acc = {}
        for inst in set(instruments_arr[query_indices]):
            mask = instruments_arr[query_indices] == inst
            inst_prec = precisions[mask]
            if len(inst_prec) > 0:
                inst_acc[inst] = float(inst_prec.mean()) * 100

    else:
        # Full dataset mode (leave-one-out)
        sim_matrix = normed @ normed.T
        np.fill_diagonal(sim_matrix, -np.inf)

        actual_k = min(k, N - 1)
        if N > actual_k + 1:
            top_k_idx = np.argpartition(sim_matrix, -actual_k, axis=1)[:, -actual_k:]
            rows = np.arange(N)[:, None]
            top_k_sims = sim_matrix[rows, top_k_idx]
            sorted_order = np.argsort(-top_k_sims, axis=1)
            top_k_idx = top_k_idx[rows, sorted_order]
        else:
            top_k_idx = np.argsort(-sim_matrix, axis=1)[:, :actual_k]

        instruments_arr = np.array(instruments)
        query_instruments = instruments_arr[:, None]
        hit_instruments = instruments_arr[top_k_idx]
        correct = (query_instruments == hit_instruments)
        precisions = correct.sum(axis=1) / actual_k

        inst_acc = {}
        for inst, indices in inst_indices.items():
            inst_prec = precisions[indices]
            inst_acc[inst] = float(inst_prec.mean()) * 100

    # Macro-average: mỗi nhạc cụ đóng góp ngang nhau
    macro_avg = float(np.mean(list(inst_acc.values()))) if inst_acc else 0.0
    # Micro-average: trung bình theo sample
    micro_avg = float(precisions.mean()) * 100 if len(precisions) > 0 else 0.0

    min_acc = min(inst_acc.values()) if inst_acc else 0.0
    return macro_avg, micro_avg, inst_acc, min_acc


def clip_weights(weights: dict) -> dict:
    """Áp dụng constraints cho weights: bounds + max ratio."""
    clipped = {}
    for name, val in weights.items():
        lo, hi = WEIGHT_BOUNDS.get(name, (0.01, 15.0))
        clipped[name] = max(lo, min(hi, val))

    # Enforce max weight ratio
    vals = list(clipped.values())
    max_w = max(vals)
    min_w = min(vals)
    if min_w > 0 and max_w / min_w > MAX_WEIGHT_RATIO:
        # Scale min weights up to meet constraint
        target_min = max_w / MAX_WEIGHT_RATIO
        for name in clipped:
            if clipped[name] < target_min:
                clipped[name] = target_min

    return clipped


def mutate_weights(weights: dict, temperature: float) -> dict:
    """Mutation thông minh với constraint enforcement."""
    new_w = copy.deepcopy(weights)

    discriminative = ['onset', 'centroid', 'hnr', 'flux', 'zcr', 'rolloff', 'rms']
    timbral = ['mfcc_mean', 'mfcc_std']
    pitch = ['chroma']

    # 55% discriminative, 35% timbral, 10% pitch
    r = random.random()
    if r < 0.55:
        group = random.choice(discriminative)
    elif r < 0.90:
        group = random.choice(timbral)
    else:
        group = random.choice(pitch)

    scale = temperature * 0.5
    lo, hi = WEIGHT_BOUNDS.get(group, (0.01, 15.0))

    if group == 'chroma':
        delta = random.gauss(0, scale * 0.05)
        new_w[group] = max(lo, min(hi, new_w[group] + delta))
    elif group in ['onset', 'centroid', 'zcr']:
        factor = random.gauss(1.0, scale * 0.25)
        new_w[group] = max(lo, min(hi, new_w[group] * factor))
    elif group in ['mfcc_mean', 'mfcc_std']:
        factor = random.gauss(1.0, scale * 0.15)
        new_w[group] = max(lo, min(hi, new_w[group] * factor))
    else:
        factor = random.gauss(1.0, scale * 0.2)
        new_w[group] = max(lo, min(hi, new_w[group] * factor))

    # 25% chance: mutate a second group
    if random.random() < 0.25:
        group2 = random.choice(list(GROUPS.keys()))
        if group2 != group:
            lo2, hi2 = WEIGHT_BOUNDS.get(group2, (0.01, 15.0))
            factor2 = random.gauss(1.0, scale * 0.12)
            new_w[group2] = max(lo2, min(hi2, new_w[group2] * factor2))

    return clip_weights(new_w)


def l2_penalty(weights: dict) -> float:
    """L2 regularization penalty – ngăn weights quá extreme."""
    return sum(v ** 2 for v in weights.values())


def simulated_annealing(raw_vecs, instruments, inst_indices,
                        train_idx, val_idx,
                        n_iterations=1000, initial_temp=2.0,
                        cooling_rate=0.996, target_min=70.0):
    """Simulated Annealing với Train/Val Split.

    - Tối ưu trên train set
    - Đánh giá (và chọn best) trên val set
    - Tránh data leakage
    """
    random.seed(42)
    np.random.seed(42)

    N = raw_vecs.shape[0]
    n_train = len(train_idx)
    n_val = len(val_idx)
    print(f"[OPT] Dataset: {N} total, Train: {n_train}, Val: {n_val}")
    print(f"[OPT] Evaluating on TRAIN set each iteration, selecting best by VAL set")

    # Start from current config weights
    current_w = clip_weights(dict(FEATURE_WEIGHTS))

    # Evaluate on both sets
    train_macro, train_micro, train_inst, train_min = evaluate_fast(
        raw_vecs, instruments, inst_indices, current_w,
        query_indices=train_idx, gallery_indices=train_idx
    )
    val_macro, val_micro, val_inst, val_min = evaluate_fast(
        raw_vecs, instruments, inst_indices, current_w,
        query_indices=val_idx, gallery_indices=train_idx
    )

    best_w = copy.deepcopy(current_w)
    best_val_macro = val_macro
    best_val_min = val_min
    best_val_inst = val_inst
    best_train_macro = train_macro

    current_train_macro = train_macro
    current_train_min = train_min
    current_train_inst = train_inst

    temp = initial_temp
    no_improve_count = 0
    accepted = 0

    print(f"\n[START] Train Macro: {train_macro:.1f}%, Val Macro: {val_macro:.1f}%, Val Min: {val_min:.1f}%")
    print(f"  {'Nhạc cụ':<20} {'Train':>8} {'Val':>8} {'Status':>8}")
    for inst in sorted(val_inst):
        t_acc = train_inst.get(inst, 0)
        v_acc = val_inst.get(inst, 0)
        flag = " ⚠️" if v_acc < target_min else " ✓"
        print(f"  {inst:<20} {t_acc:>7.1f}% {v_acc:>7.1f}%{flag}")

    t_start = time.time()

    for i in range(n_iterations):
        new_w = mutate_weights(current_w, temp)

        # Evaluate on TRAIN set (nhanh, dùng để chấp nhận/từ chối)
        new_train_macro, _, new_train_inst, new_train_min = evaluate_fast(
            raw_vecs, instruments, inst_indices, new_w,
            query_indices=train_idx, gallery_indices=train_idx
        )

        # Objective: macro-average + min penalty + regularization
        def score(macro_a, min_a, inst_a, weights):
            penalty = sum(
                max(0, target_min - acc) ** 2
                for acc in inst_a.values()
            )
            bonus = 100.0 if min_a >= target_min else 0.0
            reg = L2_LAMBDA * l2_penalty(weights)
            return min_a * 2 + macro_a * 1.5 - penalty * 0.5 + bonus - reg

        current_score = score(current_train_macro, current_train_min,
                              current_train_inst, current_w)
        new_score = score(new_train_macro, new_train_min,
                          new_train_inst, new_w)
        delta = new_score - current_score

        if delta > 0 or random.random() < math.exp(delta / max(temp, 0.01)):
            current_w = new_w
            current_train_macro = new_train_macro
            current_train_min = new_train_min
            current_train_inst = new_train_inst
            accepted += 1

            # Đánh giá trên VAL set để chọn best (chống overfitting)
            new_val_macro, _, new_val_inst, new_val_min = evaluate_fast(
                raw_vecs, instruments, inst_indices, new_w,
                query_indices=val_idx, gallery_indices=train_idx
            )

            # Chọn best theo VAL score (không phải train!)
            if (new_val_min > best_val_min + 0.05 or
                (abs(new_val_min - best_val_min) < 0.05 and
                 new_val_macro > best_val_macro)):
                best_w = copy.deepcopy(new_w)
                best_val_macro = new_val_macro
                best_val_min = new_val_min
                best_val_inst = new_val_inst
                best_train_macro = new_train_macro
                no_improve_count = 0

                flag = "🎯" if best_val_min >= target_min else "📈"
                print(f"  [{i:>4}] {flag} ValMacro: {best_val_macro:.1f}%, "
                      f"ValMin: {best_val_min:.1f}%, "
                      f"TrainMacro: {new_train_macro:.1f}%, T={temp:.3f}")
            else:
                no_improve_count += 1
        else:
            no_improve_count += 1

        temp *= cooling_rate

        # Reheat if stuck
        if no_improve_count > 100:
            temp = max(temp, initial_temp * 0.4)
            no_improve_count = 0
            current_w = copy.deepcopy(best_w)
            current_train_macro = best_train_macro
            # Re-evaluate train
            _, _, current_train_inst, current_train_min = evaluate_fast(
                raw_vecs, instruments, inst_indices, best_w,
                query_indices=train_idx, gallery_indices=train_idx
            )

    elapsed = time.time() - t_start
    print(f"\n[TIME] {elapsed:.1f}s ({elapsed/n_iterations*1000:.0f}ms/iter), "
          f"accepted: {accepted}/{n_iterations}")

    return best_w, best_val_macro, best_train_macro, best_val_inst, best_val_min


def apply_to_config(weights: dict):
    """Ghi trọng số tối ưu vào config.py."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    import re
    pattern = r"FEATURE_WEIGHTS\s*=\s*\{[^}]+\}"
    new_block = "FEATURE_WEIGHTS = {\n"
    for k in sorted(weights.keys()):
        new_block += f"    '{k}': {weights[k]:.6f},\n"
    new_block += "}"

    new_content = re.sub(pattern, new_block, content)

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    print(f"[CONFIG] Đã cập nhật FEATURE_WEIGHTS trong {config_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="Tối ưu trọng số đặc trưng cho Precision@5 >= 70% mỗi nhạc cụ (anti-overfitting)"
    )
    parser.add_argument("-n", "--iterations", type=int, default=1000,
                        help="Số iteration (mặc định: 1000)")
    parser.add_argument("--target", type=float, default=70.0,
                        help="Mục tiêu min accuracy %% (mặc định: 70)")
    parser.add_argument("--val-ratio", type=float, default=0.2,
                        help="Tỷ lệ validation set (mặc định: 0.2)")
    parser.add_argument("--apply", action="store_true",
                        help="Tự động ghi kết quả vào config.py")
    args = parser.parse_args()

    print("═" * 60)
    print("  FEATURE WEIGHT OPTIMIZATION (Anti-Overfitting)")
    print("  Simulated Annealing + Stratified Train/Val Split")
    print("═" * 60)

    db = get_db()
    print(f"[DB] {db.ping()['message']}")

    recs = db.get_all_with_vectors()
    print(f"[DB] Loaded {len(recs)} records.")

    if len(recs) < 50:
        print("[ERROR] Cần ít nhất 50 bản ghi.")
        return

    from collections import Counter
    inst_count = Counter(r["instrument"] for r in recs)
    print(f"\n[INFO] Phân bố nhạc cụ:")
    for inst, cnt in sorted(inst_count.items()):
        print(f"  • {inst}: {cnt} mẫu")

    # ── Stratified Train/Val Split ──
    print(f"\n[SPLIT] Stratified split: {1-args.val_ratio:.0%} train / {args.val_ratio:.0%} val")
    train_idx, val_idx = stratified_split(recs, val_ratio=args.val_ratio)
    print(f"[SPLIT] Train: {len(train_idx)} samples, Val: {len(val_idx)} samples")

    # Hiển thị phân bố split
    instruments = [recs[i]["instrument"] for i in range(len(recs))]
    train_insts = Counter(instruments[i] for i in train_idx)
    val_insts = Counter(instruments[i] for i in val_idx)
    print(f"\n  {'Nhạc cụ':<20} {'Train':>8} {'Val':>8} {'Total':>8}")
    print(f"  {'─'*20} {'─'*8} {'─'*8} {'─'*8}")
    for inst in sorted(inst_count):
        print(f"  {inst:<20} {train_insts.get(inst,0):>8} {val_insts.get(inst,0):>8} "
              f"{inst_count[inst]:>8}")

    # Prepare data once
    print("\n[PREP] Chuẩn bị dữ liệu...")
    raw_vecs, instruments_list, inst_indices = prepare_data(recs)
    print(f"[PREP] Done: {raw_vecs.shape}")

    best_w, val_macro, train_macro, val_inst, val_min = simulated_annealing(
        raw_vecs, instruments_list, inst_indices,
        train_idx, val_idx,
        n_iterations=args.iterations, target_min=args.target
    )

    # ── Final evaluation on FULL dataset (for reference) ──
    full_macro, full_micro, full_inst, full_min = evaluate_fast(
        raw_vecs, instruments_list, inst_indices, best_w
    )

    print("\n" + "═" * 60)
    print("  KẾT QUẢ TỐI ƯU (ANTI-OVERFITTING)")
    print("═" * 60)
    print(f"  Val Macro Precision@5  : {val_macro:.1f}%")
    print(f"  Train Macro Precision  : {train_macro:.1f}%")
    print(f"  Full Dataset Macro     : {full_macro:.1f}%")
    print(f"  Full Dataset Micro     : {full_micro:.1f}%")
    print(f"  Overfitting Gap        : {train_macro - val_macro:.1f}% (Train - Val)")
    print(f"  Min Instrument (Val)   : {val_min:.1f}%")
    print(f"  Target                 : {args.target:.1f}%")
    target_met = val_min >= args.target
    print(f"  Status                 : {'✅ ĐẠT MỤC TIÊU' if target_met else '⚠️ CHƯA ĐẠT'}")

    print(f"\n  {'Nhạc cụ':<22} {'Val':>8} {'Train':>8} {'Full':>8} {'Status':>8}")
    print(f"  {'─'*22} {'─'*8} {'─'*8} {'─'*8} {'─'*8}")
    for inst in sorted(full_inst):
        v_acc = val_inst.get(inst, 0)
        t_acc = full_inst.get(inst, 0)
        flag = "  ✅" if v_acc >= args.target else "  ⚠️"
        print(f"  {inst:<22} {v_acc:>7.1f}% {train_macro:>7.1f}% {t_acc:>7.1f}%{flag}")

    print(f"\n  Optimal Weights:")
    for k in sorted(best_w.keys()):
        print(f"    '{k}': {best_w[k]:.6f},")

    print(f"\n  Weight Ratio (max/min): {max(best_w.values())/max(min(best_w.values()), 1e-9):.1f}x")

    if args.apply:
        apply_to_config(best_w)
    else:
        print(f"\n  💡 Chạy lại với --apply để tự động cập nhật config.py")

    print("═" * 60)


if __name__ == "__main__":
    main()
