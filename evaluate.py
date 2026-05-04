"""
evaluate.py – CLI Precision evaluation
Usage: python evaluate.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import random
import numpy as np
from tqdm import tqdm
from database.mongo_client import get_db
from search.faiss_index import FaissIndex


def run(sample_size: int = 50, k: int = 5, seed: int = 42):
    print("═" * 55)
    print("  Precision Evaluation")
    print("═" * 55)

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

    sample      = random.sample(recs, min(sample_size, len(recs)))
    by_inst: dict[str, list] = {}
    all_scores:  list[float] = []

    for rec in tqdm(sample, desc="Evaluating"):
        q_vec = np.array(rec["feature_vector"], dtype=np.float32)
        q_id  = str(rec["_id"])
        q_ins = rec.get("instrument", "unknown")

        hits = fi.search(q_vec, k=k + 1)
        hits = [h for h in hits if h["mongo_id"] != q_id][:k]
        if not hits:
            continue

        docs = {str(r["_id"]): r for r in [db.get_by_id(h["mongo_id"]) for h in hits] if r}
        correct = sum(1 for h in hits if docs.get(h["mongo_id"], {}).get("instrument") == q_ins)
        p = correct / len(hits)
        all_scores.append(p)
        by_inst.setdefault(q_ins, []).append(p)

    overall = sum(all_scores) / len(all_scores) * 100 if all_scores else 0
    print(f"\n{'─'*45}")
    print(f"  Overall Precision@{k} : {overall:.1f}%")
    print(f"{'─'*45}")
    print(f"  {'Nhạc cụ':<22} {'Precision':>12}  {'Mẫu':>6}")
    print(f"  {'─'*22} {'─'*12}  {'─'*6}")
    for inst in sorted(by_inst):
        v   = by_inst[inst]
        avg = sum(v) / len(v) * 100
        print(f"  {inst:<22} {avg:>11.1f}%  {len(v):>6}")
    print(f"{'─'*45}")
    print(f"  Tổng mẫu đánh giá: {len(all_scores)}")
    print("═" * 55)


if __name__ == "__main__":
    run()
