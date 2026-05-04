import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uuid, traceback, glob
from pathlib import Path

import mimetypes
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS

from config import FLASK_DEBUG, FLASK_PORT, DATASET_PATH, FAISS_INDEX_PATH, UPLOAD_FOLDER, MAX_UPLOAD_MB
from database.mongo_client import get_db
from features.extractor import AudioFeatureExtractor
from search.faiss_index import get_faiss, FaissIndex
from search.searcher import AudioSearcher
from utils import parse_note_from_filename

# ── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# Fix #9: Giới hạn upload file
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(os.path.dirname(FAISS_INDEX_PATH), exist_ok=True)
os.makedirs(DATASET_PATH, exist_ok=True)

# Fix #17: Cleanup upload folder on startup
for _leftover in glob.glob(os.path.join(UPLOAD_FOLDER, "q_*")):
    try:
        os.remove(_leftover)
    except OSError:
        pass

ALLOWED = {"wav", "mp3", "ogg", "flac", "aif", "aiff"}


def ok_ext(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED


def tmp_path(filename: str) -> str:
    ext = Path(filename).suffix
    return os.path.join(UPLOAD_FOLDER, f"q_{uuid.uuid4().hex}{ext}")


# ── Lazy searcher ─────────────────────────────────────────────────────────────
_searcher: AudioSearcher | None = None


def searcher() -> AudioSearcher:
    global _searcher
    if _searcher is None:
        _searcher = AudioSearcher()
    return _searcher


# ══════════════════════════════════════════════════════════════════════════════
# PAGES
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")


# ══════════════════════════════════════════════════════════════════════════════
# API – Health & Stats
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/ping")
def ping():
    return jsonify(get_db().ping())


@app.route("/api/stats")
def stats():
    data = get_db().stats()
    fi = get_faiss()
    fi.load()
    data["faiss_vectors"] = fi.total
    return jsonify(data)


# ══════════════════════════════════════════════════════════════════════════════
# API – Records
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/records")
def list_records():
    db   = get_db()
    inst = request.args.get("instrument", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(10, int(request.args.get("per_page", 50))))

    recs = db.search_by_instrument(inst) if inst else db.get_all()
    total = len(recs)

    # Fix #16: pagination
    start = (page - 1) * per_page
    end = start + per_page
    paginated = recs[start:end]

    return jsonify({
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page if total else 1,
        "records": paginated,
    })


@app.route("/api/instruments")
def list_instruments():
    instruments = get_db().list_instruments()
    return jsonify({"total": len(instruments), "instruments": instruments})


@app.route("/api/records/<record_id>")
def get_record(record_id):
    doc = get_db().get_by_id(record_id)
    if doc is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(doc)


@app.route("/api/records/<record_id>", methods=["DELETE"])
def delete_record(record_id):
    ok = get_db().delete_by_id(record_id)
    if not ok:
        return jsonify({"error": "Not found", "deleted": False}), 404

    # Fix #4: rebuild FAISS index after deletion to keep in sync
    try:
        fi = FaissIndex()
        total = fi.build(save=True)
        import search.faiss_index as fim
        fim._inst = fi
        return jsonify({"deleted": True, "faiss_rebuilt": True, "faiss_vectors": total})
    except Exception as e:
        return jsonify({"deleted": True, "faiss_rebuilt": False, "faiss_error": str(e)})


# ══════════════════════════════════════════════════════════════════════════════
# API – FAISS index
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/index/build", methods=["POST"])
def build_index():
    fi    = FaissIndex()
    total = fi.build(save=True)
    # Reset singleton so next search uses fresh index
    import search.faiss_index as fim
    fim._inst = fi
    return jsonify({"status": "OK", "indexed_vectors": total})


@app.route("/api/index/status")
def index_status():
    exists = os.path.exists(FAISS_INDEX_PATH)
    fi = get_faiss()
    if exists:
        fi.load()
    return jsonify({"index_exists": exists, "total_vectors": fi.total})


# ══════════════════════════════════════════════════════════════════════════════
# API – Ingest (add new file to DB)
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/ingest", methods=["POST"])
def ingest():
    if "file" not in request.files:
        return jsonify({"error": "Thiếu file"}), 400

    f = request.files["file"]
    if not ok_ext(f.filename):
        return jsonify({"error": f"Định dạng không hợp lệ. Hỗ trợ: {ALLOWED}"}), 400

    instrument = request.form.get("instrument", "unknown").strip().lower()
    family     = request.form.get("instrument_family", "unknown").strip()

    # Save to dataset folder
    save_dir = os.path.join(DATASET_PATH, instrument)
    os.makedirs(save_dir, exist_ok=True)
    safe_name = f"{instrument}_{uuid.uuid4().hex[:8]}{Path(f.filename).suffix}"
    save_path = os.path.join(save_dir, safe_name)
    f.save(save_path)

    try:
        ext    = AudioFeatureExtractor()
        feats  = ext.extract_all(save_path)
        record = {
            "filename":          safe_name,
            "file_path":         save_path.replace("\\", "/"),
            "instrument":        instrument,
            "instrument_family": family,
            "labeled_note":      parse_note_from_filename(f.filename),
            **feats,
        }
        rid = get_db().insert_one(record)
        return jsonify({"status": "OK", "record_id": rid, "filename": safe_name,
                        "instrument": instrument, "duration": feats["duration"]})
    except Exception as e:
        traceback.print_exc()
        os.remove(save_path)
        return jsonify({"error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# API – Search
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/search", methods=["POST"])
def search():
    if "file" not in request.files:
        return jsonify({"error": "Thiếu file"}), 400

    f = request.files["file"]
    if not ok_ext(f.filename):
        return jsonify({"error": f"Định dạng không hợp lệ. Hỗ trợ: {ALLOWED}"}), 400

    try:
        k = int(request.form.get("k", 5))
        k = max(1, min(k, 20))
    except (TypeError, ValueError):
        k = 5
    path = tmp_path(f.filename)
    f.save(path)

    try:
        result = searcher().search(path, k=k)
        return jsonify(result)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(path):
            os.remove(path)


# ══════════════════════════════════════════════════════════════════════════════
# API – Stream audio
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/audio/<record_id>")
def stream_audio(record_id):
    doc = get_db().get_by_id(record_id)
    if not doc:
        return jsonify({"error": "Not found"}), 404
    fp = doc.get("file_path", "")
    if not fp or not os.path.exists(fp):
        return jsonify({"error": "File không tồn tại trên đĩa"}), 404
    mime, _ = mimetypes.guess_type(fp)
    mime = mime or "audio/wav"
    return send_file(fp, mimetype=mime,
                     download_name=doc.get("filename", "audio.wav"))


# ══════════════════════════════════════════════════════════════════════════════
# API – Evaluate (Precision)
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/api/evaluate", methods=["POST"])
def evaluate():
    import random
    import numpy as np

    # Fix #7: Seed cố định cho kết quả tái lập được
    seed = int(request.form.get("seed", 42))
    random.seed(seed)

    db  = get_db()
    fi  = FaissIndex()
    if not fi.load():
        return jsonify({"error": "FAISS index chưa tồn tại. Hãy build index trước."}), 503

    all_recs = db.get_all_with_vectors()
    if len(all_recs) < 10:
        return jsonify({"error": "Cần ít nhất 10 bản ghi để đánh giá."}), 400

    sample      = random.sample(all_recs, min(50, len(all_recs)))
    by_inst: dict[str, list] = {}
    scores: list[float]      = []
    # confusion_matrix[actual][predicted] = count
    confusion: dict[str, dict[str, int]] = {}

    for rec in sample:
        q_vec = np.array(rec["feature_vector"], dtype=np.float32)
        q_id  = str(rec["_id"])
        q_ins = rec.get("instrument", "unknown")

        hits = fi.search(q_vec, k=6)
        hits = [h for h in hits if h["mongo_id"] != q_id][:5]
        if not hits:
            continue

        fetched = [db.get_by_id(h["mongo_id"]) for h in hits]
        db_recs = {r["_id"]: r for r in fetched if r is not None}
        correct = sum(1 for h in hits
                      if db_recs.get(h["mongo_id"], {}).get("instrument") == q_ins)
        p = correct / len(hits)
        scores.append(p)
        by_inst.setdefault(q_ins, []).append(p)

        # Top-1 predicted instrument for confusion matrix
        top1_doc = db_recs.get(hits[0]["mongo_id"], {}) if hits else {}
        pred_ins = top1_doc.get("instrument", "unknown")
        confusion.setdefault(q_ins, {})
        confusion[q_ins][pred_ins] = confusion[q_ins].get(pred_ins, 0) + 1

    overall = round(sum(scores) / len(scores) * 100, 2) if scores else 0
    per_inst = {
        inst: round(sum(v) / len(v) * 100, 2)
        for inst, v in by_inst.items()
    }
    return jsonify({
        "seed":                    seed,
        "sample_size":             len(scores),
        "overall_precision_at_5":  overall,
        "per_instrument":          per_inst,
        "confusion_matrix":        confusion,
    })


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    db   = get_db()
    ping = db.ping()
    st   = db.stats()
    print("\n" + "═" * 55)
    print("  🎻 Musical Instrument Recognition System")
    print("═" * 55)
    print(f"  MongoDB : {ping['message']}")
    print(f"  Records : {st['total_files']} files in DB")
    print(f"  URL     : http://localhost:{FLASK_PORT}")
    print("═" * 55 + "\n")
    app.run(debug=FLASK_DEBUG, port=FLASK_PORT, host="0.0.0.0")
