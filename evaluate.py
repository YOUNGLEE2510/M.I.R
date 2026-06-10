"""
evaluate.py – CLI Precision evaluation với anti-overfitting metrics
Usage: python evaluate.py          # Đánh giá 50 mẫu (stratified)
       python evaluate.py --all    # Đánh giá toàn bộ dataset
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import random
import numpy as np
from collections import defaultdict
from tqdm import tqdm
from database.mongo_client import get_db
from search.faiss_index import FaissIndex


def stratified_sample(recs, sample_size: int, seed: int = 42) -> list:
    """Stratified sampling – đảm bảo mỗi nhạc cụ có đại diện trong evaluation.

    Lấy tối thiểu min(3, n) mẫu từ mỗi nhạc cụ, phần còn lại random.
    """
    rng = random.Random(seed)

    # Nhóm theo nhạc cụ
    by_inst = defaultdict(list)
    for r in recs:
        by_inst[r.get("instrument", "unknown")].append(r)

    n_instruments = len(by_inst)
    if sample_size >= len(recs):
        return recs  # Lấy toàn bộ

    # Phase 1: lấy tối thiểu mỗi nhạc cụ
    min_per_inst = min(3, sample_size // n_instruments)
    selected = []
    remaining = []

    for inst, inst_recs in by_inst.items():
        shuffled = inst_recs.copy()
        rng.shuffle(shuffled)
        n_take = min(min_per_inst, len(shuffled))
        selected.extend(shuffled[:n_take])
        remaining.extend(shuffled[n_take:])

    # Phase 2: fill phần còn lại random
    n_remaining = sample_size - len(selected)
    if n_remaining > 0:
        rng.shuffle(remaining)
        selected.extend(remaining[:n_remaining])

    return selected


def run(sample_size: int = 50, k: int = 5, seed: int = 42):
    print("═" * 60)
    print("  Precision Evaluation (Anti-Overfitting)")
    print("═" * 60)

    # Fix #7: seed cố định cho kết quả tái lập
    random.seed(seed)
    print(f"[SEED] {seed}")

    db = get_db()
    print(f"[DB] {db.ping()['message']}")

    recs = db.get_all_with_vectors()
    if len(recs) < 10:
        print("[ERROR] Cần ít nhất 10 bản ghi. Hãy chạy batch_extract.py trước.")
        return

    fi = FaissIndex()
    if not fi.load():
        print("[ERROR] FAISS index chưa tồn tại. Hãy chạy batch_extract.py hoặc gọi /api/index/build.")
        return

    # ── Stratified sampling ──
    if sample_size >= len(recs):
        sample = recs
        print(f"[EVAL] Đánh giá trên TOÀN BỘ {len(recs)} mẫu")
    else:
        sample = stratified_sample(recs, sample_size, seed)
        print(f"[EVAL] Stratified sampling: {len(sample)} mẫu từ {len(recs)} tổng")

    by_inst: dict[str, list] = {}
    all_scores: list[float] = []

    # Tối ưu hóa: Xây dựng lookup map để tránh gọi MongoDB trong vòng lặp (giảm N+1 query)
    id_to_instrument = {str(r["_id"]): r.get("instrument", "unknown") for r in recs}

    # ── Confusion tracking ──
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for rec in tqdm(sample, desc="Evaluating"):
        q_vec = np.array(rec["feature_vector"], dtype=np.float32)
        q_id  = str(rec["_id"])
        q_ins = rec.get("instrument", "unknown")

        hits = fi.search(q_vec, k=k + 1)
        hits = [h for h in hits if h["mongo_id"] != q_id][:k]
        if not hits:
            continue

        correct = 0
        for h in hits:
            hit_inst = id_to_instrument.get(h["mongo_id"], "unknown")
            if hit_inst == q_ins:
                correct += 1
            else:
                confusion[q_ins][hit_inst] += 1

        p = correct / len(hits)
        all_scores.append(p)
        by_inst.setdefault(q_ins, []).append(p)

    # ── Micro-average (overall) ──
    micro_avg = sum(all_scores) / len(all_scores) * 100 if all_scores else 0

    # ── Macro-average (per-class mean) ──
    per_class_avg = {}
    for inst, scores in by_inst.items():
        per_class_avg[inst] = sum(scores) / len(scores) * 100

    macro_avg = sum(per_class_avg.values()) / len(per_class_avg) if per_class_avg else 0

    # ── Print results ──
    print(f"\n{'═'*60}")
    print(f"  KẾT QUẢ ĐÁNH GIÁ")
    print(f"{'═'*60}")
    print(f"  Micro-Average Precision@{k} : {micro_avg:.1f}%  (trung bình theo mẫu)")
    print(f"  Macro-Average Precision@{k} : {macro_avg:.1f}%  (trung bình theo lớp)")
    print(f"  Overfitting Indicator      : {micro_avg - macro_avg:+.1f}%  (Micro - Macro)")
    if abs(micro_avg - macro_avg) > 5:
        print(f"  ⚠️  Gap > 5%: có dấu hiệu bias về nhạc cụ có nhiều mẫu")
    else:
        print(f"  ✅ Gap ≤ 5%: phân bố đánh giá cân bằng")
    print(f"{'─'*60}")

    print(f"  {'Nhạc cụ':<22} {'Precision':>12}  {'Mẫu':>6}  {'Status':>8}")
    print(f"  {'─'*22} {'─'*12}  {'─'*6}  {'─'*8}")
    min_acc = 100.0
    for inst in sorted(by_inst):
        v = by_inst[inst]
        avg = per_class_avg[inst]
        min_acc = min(min_acc, avg)
        flag = "  ✅" if avg >= 70.0 else "  ⚠️"
        print(f"  {inst:<22} {avg:>11.1f}%  {len(v):>6}{flag}")

    print(f"{'─'*60}")
    print(f"  Min Instrument Precision : {min_acc:.1f}%")
    print(f"  Tổng mẫu đánh giá       : {len(all_scores)}")

    # ── Confusion Analysis ──
    if confusion:
        print(f"\n{'─'*60}")
        print(f"  CONFUSION ANALYSIS (Top sai lầm)")
        print(f"{'─'*60}")
        # Flatten and sort by count
        errors = []
        for true_inst, preds in confusion.items():
            for pred_inst, count in preds.items():
                errors.append((true_inst, pred_inst, count))
        errors.sort(key=lambda x: -x[2])

        print(f"  {'Thực tế':<18} {'→ Nhận nhầm':>18} {'Lần':>6}")
        print(f"  {'─'*18} {'─'*18} {'─'*6}")
        for true_inst, pred_inst, count in errors[:10]:
            print(f"  {true_inst:<18} → {pred_inst:<16} {count:>6}")

    print(f"{'═'*60}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Đánh giá độ chính xác Precision@K của hệ thống nhận diện nhạc cụ")
    parser.add_argument("-n", "--sample-size", type=int, default=50, help="Số lượng mẫu ngẫu nhiên dùng để đánh giá (mặc định: 50)")
    parser.add_argument("-a", "--all", action="store_true", help="Đánh giá trên toàn bộ cơ sở dữ liệu")
    parser.add_argument("-k", type=int, default=5, help="Giá trị K cho Precision@K (mặc định: 5)")
    parser.add_argument("-s", "--seed", type=int, default=42, help="Seed ngẫu nhiên (mặc định: 42)")

    args = parser.parse_args()

    # --all: dùng sample_size cực lớn để run() tự lấy toàn bộ
    # (tránh gọi get_all_with_vectors() 2 lần lãng phí)
    sample_size = 10**9 if args.all else args.sample_size
    run(sample_size=sample_size, k=args.k, seed=args.seed)
