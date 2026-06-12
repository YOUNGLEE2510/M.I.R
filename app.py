import sys, os
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uuid, traceback, glob
from pathlib import Path

import mimetypes
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS

from config import FLASK_DEBUG, FLASK_PORT, DATASET_PATH, FAISS_INDEX_PATH, UPLOAD_FOLDER, MAX_UPLOAD_MB, BASE_DIR
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


# ── Fix B1: Auto-resolve file_path ────────────────────────────────────────────
def resolve_audio_path(doc: dict) -> str | None:
    """Resolve file_path: nếu path cũ không tồn tại, tìm file trong DATASET_PATH."""
    fp = doc.get("file_path", "")
    if fp and os.path.exists(fp):
        return fp

    # Thử reconstruct từ DATASET_PATH + instrument + filename
    instrument = doc.get("instrument", "")
    filename = doc.get("filename", "")
    if instrument and filename:
        candidate = os.path.join(DATASET_PATH, instrument, filename)
        if os.path.exists(candidate):
            return candidate

    # Thử tìm theo filename bất kỳ trong DATASET_PATH
    if filename:
        for dirpath, _, files in os.walk(DATASET_PATH):
            if filename in files:
                return os.path.join(dirpath, filename)

    return None


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


@app.route("/favicon.ico")
def favicon():
    return "", 204


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

    start = (page - 1) * per_page

    # Tối ưu hóa: Phân trang trực tiếp từ MongoDB (database-side pagination)
    if inst:
        total = db.col.count_documents({"instrument": {"$regex": inst, "$options": "i"}})
        paginated = db.search_by_instrument(inst, skip=start, limit=per_page)
    else:
        total = db.col.count_documents({})
        paginated = db.get_all(skip=start, limit=per_page)

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
    db = get_db()
    doc = db.get_by_id(record_id)
    if not doc:
        return jsonify({"error": "Not found", "deleted": False}), 404

    # Delete physical file on disk if exists
    fp = resolve_audio_path(doc)
    if fp and os.path.exists(fp):
        try:
            os.remove(fp)
        except Exception as e:
            print(f"[API] Lỗi xóa file vật lý {fp}: {e}")

    ok = db.delete_by_id(record_id)
    if not ok:
        return jsonify({"error": "Không thể xóa bản ghi khỏi CSDL", "deleted": False}), 500

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
    instrument = "".join(c for c in instrument if c.isalnum() or c in " _-").strip()
    instrument = instrument.replace(" ", "_").replace("-", "_")
    if not instrument:
        instrument = "unknown"
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

    try:
        f.save(path)
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

    # Fix B1: auto-resolve path
    fp = resolve_audio_path(doc)
    if not fp:
        return jsonify({"error": "File không tồn tại trên đĩa"}), 404

    mime, _ = mimetypes.guess_type(fp)
    mime = mime or "audio/wav"
    return send_file(fp, mimetype=mime,
                     download_name=doc.get("filename", "audio.wav"))


# ── Fix B1: Batch update file_path ────────────────────────────────────────────
@app.route("/api/fix-paths", methods=["POST"])
def fix_paths():
    """Batch update tất cả file_path trong MongoDB cho đúng máy hiện tại."""
    from bson import ObjectId
    from pymongo import UpdateOne

    db = get_db()
    all_recs = db.get_all(include_vectors=False)
    fixed, skipped, missing = 0, 0, 0
    operations = []

    for rec in all_recs:
        old_fp = rec.get("file_path", "")
        if old_fp and os.path.exists(old_fp):
            skipped += 1
            continue

        resolved = resolve_audio_path(rec)
        if resolved:
            new_fp = resolved.replace("\\", "/")
            operations.append(
                UpdateOne(
                    {"_id": ObjectId(rec["_id"])},
                    {"$set": {"file_path": new_fp}}
                )
            )
            fixed += 1
        else:
            missing += 1

    # Bulk write tất cả cùng lúc (nhanh hơn nhiều so với update_one từng cái)
    if operations:
        db.col.bulk_write(operations, ordered=False)

    return jsonify({
        "status": "OK",
        "fixed": fixed,
        "skipped": skipped,
        "missing": missing,
        "total": len(all_recs),
    })


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    db          = get_db()
    ping_result = db.ping()
    st          = db.stats()
    print("\n" + "═" * 55)
    print("  🎻 Musical Instrument Recognition System")
    print("═" * 55)
    print(f"  MongoDB : {ping_result['message']}")
    print(f"  Records : {st['total_files']} files in DB")

    # Fix B2: Auto-load FAISS index on startup
    fi = get_faiss()
    if os.path.exists(FAISS_INDEX_PATH):
        fi.load()
        print(f"  FAISS   : {fi.total} vectors loaded ✓")
    else:
        print(f"  FAISS   : Index chưa tồn tại (chạy batch_extract.py hoặc /api/index/build)")

    print(f"  URL     : http://localhost:{FLASK_PORT}")
    print("═" * 55 + "\n")
    app.run(debug=FLASK_DEBUG, port=FLASK_PORT, host="0.0.0.0")
