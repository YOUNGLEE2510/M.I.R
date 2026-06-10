import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import faiss
from config import FAISS_INDEX_PATH, FEATURE_DIM
from database.mongo_client import get_db

_ID_MAP_PATH = FAISS_INDEX_PATH + ".ids"

# Threshold tham khảo – không dùng trong search() để tránh trả về list rỗng
# Caller (searcher.py) tự quyết định có lọc hay không
SIMILARITY_THRESHOLD = 0.3


class FaissIndex:

    def __init__(self):
        self.index: faiss.IndexFlatIP | None = None
        self.id_map: list[str] = []   # faiss position → mongo _id
        os.makedirs(os.path.dirname(FAISS_INDEX_PATH), exist_ok=True)

    # ── Build ───────────────────────────────────────────────
    def build(self, save: bool = True) -> int:
        """Load vectors từ MongoDB → build FAISS index."""
        db = get_db()
        records = db.get_all_with_vectors()

        if not records:
            print("[FAISS] No records in MongoDB.")
            return 0

        # Reset all faiss indices in DB to keep in sync
        db.reset_all_faiss_indices()

        vecs, self.id_map = [], []

        for r in records:
            v = np.array(r["feature_vector"], dtype=np.float32)
            # ⚠️ KHÔNG normalize lại (đã normalize ở extractor)
            vecs.append(v)
            self.id_map.append(str(r["_id"]))

        mat = np.vstack(vecs).astype(np.float32)

        # Fix #6: Auto-detect feature dimension từ dữ liệu thực tế
        dim = mat.shape[1]
        if dim != FEATURE_DIM:
            print(f"[FAISS] WARNING: Actual dim={dim} differs from config FEATURE_DIM={FEATURE_DIM}")

        # ✔ Cosine similarity → dùng Inner Product
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(mat)

        # Sync index → MongoDB (bulk – single round-trip)
        db.bulk_set_faiss_indices([
            (mid, i) for i, mid in enumerate(self.id_map)
        ])

        if save:
            self._save()

        return self.index.ntotal

    # ── Save / Load ─────────────────────────────────────────
    def _save(self):
        faiss.write_index(self.index, FAISS_INDEX_PATH)

        with open(_ID_MAP_PATH, "w") as f:
            f.write("\n".join(self.id_map))

        print(f"[FAISS] Saved: {self.index.ntotal} vectors -> {FAISS_INDEX_PATH}")

    def load(self) -> bool:
        if not os.path.exists(FAISS_INDEX_PATH):
            return False

        self.index = faiss.read_index(FAISS_INDEX_PATH)

        if os.path.exists(_ID_MAP_PATH):
            with open(_ID_MAP_PATH) as f:
                self.id_map = [line.strip() for line in f if line.strip()]

        print(f"[FAISS] Loaded: {self.index.ntotal} vectors")
        return True

    # ── Search ──────────────────────────────────────────────
    def search(self, query_vec: np.ndarray, k: int = 5) -> list[dict]:
        """
        Return:
        [
            {
                "mongo_id": str,
                "faiss_index": int,
                "similarity": float (%)
            }
        ]
        """

        if self.index is None:
            if not self.load():
                raise RuntimeError(
                    "FAISS index chưa được xây dựng. "
                    "Hãy chạy batch_extract.py hoặc rebuild index."
                )
        if self.index.ntotal <= 0:
            raise RuntimeError("FAISS index đang rỗng. Hãy ingest dữ liệu và build index.")

        # ✔ tránh lỗi khi k > số vector
        k = min(k, self.index.ntotal)

        # ✔ Flatten to 1D then reshape to (1, dim) for FAISS
        q = query_vec.astype(np.float32).flatten().reshape(1, -1)

        dists, idxs = self.index.search(q, k)

        results = []
        for dist, idx in zip(dists[0], idxs[0]):
            if idx < 0 or idx >= len(self.id_map):
                continue

            sim = max(0.0, float(dist))  # cosine similarity (0.0 → 1.0)

            results.append({
                "mongo_id":    self.id_map[idx],
                "faiss_index": int(idx),
                "similarity":  round(sim * 100, 2),
            })

        # sort giảm dần (FAISS IndexFlatIP đã sort, nhưng để chắc)
        results.sort(key=lambda x: x["similarity"], reverse=True)

        return results

    # ── Stats ───────────────────────────────────────────────
    @property
    def total(self) -> int:
        return self.index.ntotal if self.index else 0


# ── Singleton ──────────────────────────────────────────────
_inst: FaissIndex | None = None


def get_faiss() -> FaissIndex:
    global _inst
    if _inst is None:
        _inst = FaissIndex()
    return _inst