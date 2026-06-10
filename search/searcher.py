import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from collections import defaultdict
from features.extractor import AudioFeatureExtractor
from search.faiss_index import get_faiss
from database.mongo_client import get_db


class AudioSearcher:

    def __init__(self):
        self.ext   = AudioFeatureExtractor()
        self.faiss = get_faiss()
        self.db    = get_db()

    def search(self, audio_path: str, k: int = 5) -> dict:
        if not os.path.isfile(audio_path):
            raise FileNotFoundError(f"File không tồn tại: {audio_path}")

        # ── 1. Extract features ─────────────────────────────
        meta = self.ext.extract_all(audio_path)

        # Fix #2: truyền vector 1D cho FAISS (faiss_index.py sẽ tự reshape)
        q_vec = np.array(meta["feature_vector"], dtype=np.float32)

        # ── 2. FAISS search ────────────────────────────────
        raw = self.faiss.search(q_vec, k=k)

        # ── 3. Enrich với MongoDB (batch – fix N+1) ────────
        faiss_ids = [hit["faiss_index"] for hit in raw]
        batch_docs = self.db.get_by_faiss_ids(faiss_ids, include_vectors=True)
        docs_by_fidx = {doc["faiss_index"]: doc for doc in batch_docs if doc}

        results = []
        inst_scores = defaultdict(float)
        note_votes = defaultdict(int)
        for rank, hit in enumerate(raw, 1):
            doc = docs_by_fidx.get(hit["faiss_index"])
            if doc is None:
                continue

            instrument = doc.get("instrument", "unknown")
            labeled_note = doc.get("labeled_note", "unknown")
            sim = float(hit["similarity"])
            inst_scores[instrument] += sim
            if labeled_note and labeled_note != "unknown":
                note_votes[labeled_note] += 1

            results.append({
                "rank":              rank,
                "similarity":        sim,
                "filename":          doc.get("filename", ""),
                "instrument":        instrument,
                "instrument_family": doc.get("instrument_family", "unknown"),
                "labeled_note":      labeled_note,
                "duration":          doc.get("duration", 0),
                "spectral_centroid": doc.get("spectral_centroid", 0),
                "zcr":               doc.get("zcr", 0),
                "rms":               doc.get("rms", 0),
                "onset_strength":    doc.get("onset_strength", 0),
                "_id":               str(doc.get("_id", "")),
                "file_path":         doc.get("file_path", ""),
                "feature_vector":    doc.get("feature_vector", []),
            })

        # ── 4. Optional: detect unknown instrument ─────────
        if results:
            max_sim = results[0]["similarity"]
            best_inst = max(inst_scores.items(), key=lambda x: x[1])[0]
            if max_sim < 50.0:   # bạn có thể tune threshold
                predicted_label = "unknown"
            else:
                predicted_label = best_inst
        else:
            predicted_label = "unknown"

        if note_votes:
            top_note = max(note_votes.items(), key=lambda x: x[1])[0]
        else:
            top_note = meta.get("dominant_note", "unknown")

        return {
            "query": {
                "filename":          os.path.basename(audio_path),
                "duration":          meta["duration"],
                "sample_rate":       meta["sample_rate"],
                "spectral_centroid": meta["spectral_centroid"],
                "zcr":               meta["zcr"],
                "rms":               meta["rms"],
                "onset_strength":    meta["onset_strength"],
                "dominant_f0_hz":    meta["dominant_f0_hz"],
                "dominant_note":     meta["dominant_note"],
                "pitch_range":       meta["pitch_range"],
                "mfcc_mean":         meta["mfcc_mean"],
                "feature_vector":    meta["feature_vector"],
            },
            "prediction": predicted_label,
            "predicted_pitch_note": top_note,
            "predicted_pitch_range": meta.get("pitch_range", "unknown"),
            "results": results,
        }