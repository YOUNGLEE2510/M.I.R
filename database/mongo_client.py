import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from bson import ObjectId
import pymongo
from pymongo import MongoClient, ASCENDING
from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION


class MusicDB:
    """MongoDB Atlas client for the musical instrument recognition system."""

    def __init__(self):
        self._client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
        self._db = self._client[MONGO_DB_NAME]
        self.col = self._db[MONGO_COLLECTION]
        self._ensure_indexes()

    # ── Indexes ──────────────────────────────────────────────────────────────
    def _ensure_indexes(self):
        try:
            self.col.create_index([("instrument",        ASCENDING)])
            self.col.create_index([("instrument_family", ASCENDING)])
            self.col.create_index([("faiss_index",       ASCENDING)])
            self.col.create_index(
                [("filename", ASCENDING)],
                unique=True, sparse=True, name="unique_filename"
            )
        except Exception as e:
            print(f"[DB] Index warning: {e}")

    # ── Health ────────────────────────────────────────────────────────────────
    def ping(self) -> dict:
        try:
            self._client.admin.command("ping")
            return {"status": "OK",
                    "message": "Kết nối MongoDB Atlas thành công ✓",
                    "db": MONGO_DB_NAME}
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

    # ── Insert ────────────────────────────────────────────────────────────────
    def insert_one(self, record: dict) -> str:
        """Insert a record; upsert by filename if duplicate."""
        record.setdefault("created_at", datetime.now(timezone.utc))
        record.setdefault("faiss_index", -1)
        try:
            result = self.col.insert_one(record)
            return str(result.inserted_id)
        except pymongo.errors.DuplicateKeyError:
            upd = {k: v for k, v in record.items() if k != "_id"}
            self.col.update_one(
                {"filename": record["filename"]},
                {"$set": upd}
            )
            doc = self.col.find_one({"filename": record["filename"]}, {"_id": 1})
            return str(doc["_id"]) if doc else ""

    def insert_many(self, records: list) -> list:
        for r in records:
            r.setdefault("created_at", datetime.now(timezone.utc))
            r.setdefault("faiss_index", -1)
        try:
            result = self.col.insert_many(records, ordered=False)
            return [str(i) for i in result.inserted_ids]
        except pymongo.errors.BulkWriteError as bwe:
            # Return IDs of the successfully inserted documents
            inserted = bwe.details.get("insertedIds", {})
            return [str(v) for v in inserted.values()]

    # ── Read ──────────────────────────────────────────────────────────────────
    def get_all(self, include_vectors: bool = False, skip: int = 0, limit: int = 0) -> list:
        proj = {} if include_vectors else {"feature_vector": 0}
        cursor = self.col.find({}, proj)
        if skip > 0:
            cursor = cursor.skip(skip)
        if limit > 0:
            cursor = cursor.limit(limit)
        docs = list(cursor)
        for d in docs:
            d["_id"] = str(d["_id"])
        return docs

    def get_all_with_vectors(self) -> list:
        """Used by FAISS index builder."""
        docs = list(self.col.find(
            {},
            {"_id": 1, "filename": 1, "instrument": 1,
             "instrument_family": 1, "feature_vector": 1, "faiss_index": 1}
        ))
        for d in docs:
            d["_id"] = str(d["_id"])
        return docs

    def get_by_id(self, record_id: str) -> dict | None:
        try:
            doc = self.col.find_one({"_id": ObjectId(record_id)})
        except Exception:
            return None
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    def get_by_faiss_ids(self, faiss_ids: list, include_vectors: bool = False) -> list:
        proj = {} if include_vectors else {"feature_vector": 0}
        docs = list(self.col.find(
            {"faiss_index": {"$in": faiss_ids}},
            proj
        ))
        for d in docs:
            d["_id"] = str(d["_id"])
        return docs

    def search_by_instrument(self, name: str, skip: int = 0, limit: int = 0) -> list:
        cursor = self.col.find(
            {"instrument": {"$regex": name, "$options": "i"}},
            {"feature_vector": 0}
        )
        if skip > 0:
            cursor = cursor.skip(skip)
        if limit > 0:
            cursor = cursor.limit(limit)
        docs = list(cursor)
        for d in docs:
            d["_id"] = str(d["_id"])
        return docs

    def list_instruments(self) -> list[str]:
        vals = self.col.distinct("instrument")
        vals = [v for v in vals if isinstance(v, str) and v.strip()]
        return sorted(vals)

    def get_existing_filenames(self) -> list[str]:
        """Return a list of all filenames already in the DB."""
        return [doc["filename"] for doc in self.col.find({}, {"filename": 1, "_id": 0})
                if "filename" in doc]

    # ── Update ────────────────────────────────────────────────────────────────
    def set_faiss_index(self, record_id: str, idx: int):
        self.col.update_one(
            {"_id": ObjectId(record_id)},
            {"$set": {"faiss_index": idx}}
        )

    def reset_all_faiss_indices(self):
        self.col.update_many({}, {"$set": {"faiss_index": -1}})

    def bulk_set_faiss_indices(self, id_idx_pairs: list[tuple[str, int]]):
        """Batch-update faiss_index for many records in one bulk_write call."""
        from pymongo import UpdateOne
        if not id_idx_pairs:
            return
        ops = [
            UpdateOne({"_id": ObjectId(rid)}, {"$set": {"faiss_index": idx}})
            for rid, idx in id_idx_pairs
        ]
        self.col.bulk_write(ops, ordered=False)

    # ── Delete ────────────────────────────────────────────────────────────────
    def delete_all(self) -> int:
        result = self.col.delete_many({})
        return result.deleted_count

    def delete_by_id(self, record_id: str) -> bool:
        try:
            result = self.col.delete_one({"_id": ObjectId(record_id)})
            return result.deleted_count > 0
        except Exception:
            return False

    # ── Stats ─────────────────────────────────────────────────────────────────
    def stats(self) -> dict:
        total = self.col.count_documents({})
        by_instrument = list(self.col.aggregate([
            {"$group": {"_id": "$instrument", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]))
        by_family = list(self.col.aggregate([
            {"$group": {"_id": "$instrument_family", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]))
        indexed = self.col.count_documents({"faiss_index": {"$gte": 0}})
        return {
            "total_files": total,
            "indexed_in_faiss": indexed,
            "by_instrument": [{"instrument": x["_id"], "count": x["count"]} for x in by_instrument],
            "by_family":     [{"family": x["_id"], "count": x["count"]} for x in by_family],
        }

    def close(self):
        self._client.close()


# ── Singleton ──────────────────────────────────────────────────────────────
_instance: MusicDB | None = None


def get_db() -> MusicDB:
    global _instance
    if _instance is None:
        _instance = MusicDB()
    return _instance
