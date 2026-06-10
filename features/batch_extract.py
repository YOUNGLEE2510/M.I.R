import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
from tqdm import tqdm
from features.extractor import AudioFeatureExtractor
from database.mongo_client import get_db
from search.faiss_index import FaissIndex
from config import DATASET_PATH, INSTRUMENT_FAMILIES
from utils import parse_note_from_filename

AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".aif", ".aiff"}


def family_of(instrument: str) -> str:
    """Exact match: tên nhạc cụ phải khớp chính xác với 1 entry trong family."""
    low = instrument.lower()
    for fam, members in INSTRUMENT_FAMILIES.items():
        if low in members:
            return fam
    return "unknown"


def collect(root: str) -> list[dict]:
    items = []
    for dirpath, _, files in os.walk(root):
        instrument = os.path.basename(dirpath).lower().replace(" ", "_").replace("-", "_")
        if dirpath == root:
            continue
        for fn in files:
            if os.path.splitext(fn)[1].lower() in AUDIO_EXTS:
                items.append({
                    "filename": fn,
                    "file_path": os.path.join(dirpath, fn).replace("\\", "/"),
                    "instrument": instrument,
                    "instrument_family": family_of(instrument),
                    "labeled_note": parse_note_from_filename(fn),
                })
    return items


def run(rebuild_index: bool = True):
    print("=" * 58)
    print("  BATCH FEATURE EXTRACTION")
    print("=" * 58)

    db = get_db()
    print(f"[DB] {db.ping()['message']}")

    files = collect(DATASET_PATH)
    if not files:
        print(f"\n[WARN] Không tìm thấy file âm thanh trong: {DATASET_PATH}")
        print("  Hãy thêm file âm thanh vào data/Strings_wav/<nhac_cu>/")
        return

    # Statistics
    from collections import Counter
    by_inst = Counter(f["instrument"] for f in files)
    print(f"\n[INFO] Tìm thấy {len(files)} files:")
    for inst, cnt in sorted(by_inst.items()):
        print(f"  • {inst}: {cnt} files")

    # ── Fix #5: Kiểm tra trùng lặp, bỏ qua file đã extract ──
    existing = set(db.get_existing_filenames())
    new_files = [f for f in files if f["filename"] not in existing]
    skipped = len(files) - len(new_files)
    if skipped:
        print(f"\n[INFO] Bỏ qua {skipped} files đã có trong DB")
    if not new_files:
        print("[INFO] Tất cả files đã được xử lý. Không có gì mới.")
        if rebuild_index:
            print("\n[FAISS] Đang xây dựng lại chỉ mục...")
            idx = FaissIndex()
            total = idx.build(save=True)
            print(f"[FAISS] Đã index {total} vectors")
        return

    print(f"[INFO] Sẽ xử lý {len(new_files)} files mới\n")

    extractor = AudioFeatureExtractor()
    err = 0

    # ══════════════════════════════════════════════════════════
    # PASS 1 – Thu thập raw vectors (TRƯỚC khi scale)
    # Mục đích: refit Z-score scaler từ dữ liệu THỰC (raw), không
    # phải từ vectors đã scaled+normalized (lỗi logic cũ).
    # Raw vectors chỉ ~1.8 MB cho 4500 files → giữ trong memory ổn.
    # ══════════════════════════════════════════════════════════
    print("[Pass 1/2] Đang trích xuất raw features...")
    pass1_infos:    list[dict]       = []
    pass1_raw_vecs: list[np.ndarray] = []
    pass1_metas:    list[dict]       = []

    for info in tqdm(new_files, desc="Pass 1 – raw extract"):
        try:
            raw_vec, meta = extractor.extract_raw(info["file_path"])
            pass1_infos.append(info)
            pass1_raw_vecs.append(raw_vec)
            pass1_metas.append(meta)
        except Exception as e:
            tqdm.write(f"  [SKIP] {info['filename']}: {e}")
            err += 1

    if not pass1_infos:
        print("[ERROR] Không có file nào được xử lý thành công.")
        return

    # ── Refit scaler từ raw vectors thực ────────────────────
    print(f"\n[Scaler] Fitting Z-score stats từ {len(pass1_raw_vecs)} raw vectors...")
    AudioFeatureExtractor.refit_scaler(pass1_raw_vecs)
    # Invalidate cache → scale_features() sẽ load stats mới từ file
    AudioFeatureExtractor._scaler_mean = None
    AudioFeatureExtractor._scaler_std  = None

    # ══════════════════════════════════════════════════════════
    # PASS 2 – Áp dụng scaler đúng rồi lưu vào MongoDB
    # Không cần đọc lại file âm thanh — raw_vec đã có trong memory.
    # ══════════════════════════════════════════════════════════
    print("\n[Pass 2/2] Đang scale và lưu vào DB...")
    ok = 0
    for info, raw_vec, meta in tqdm(
        zip(pass1_infos, pass1_raw_vecs, pass1_metas),
        total=len(pass1_infos),
        desc="Pass 2 – store",
    ):
        try:
            vec = extractor.scale_features(raw_vec)
            vec = extractor.apply_weights(vec)
            vec = extractor.l2_normalize(vec)
            record = {**info, **meta, "feature_vector": vec.tolist()}
            db.insert_one(record)
            ok += 1
        except Exception as e:
            tqdm.write(f"  [SKIP] {info['filename']}: {e}")
            err += 1

    print(f"\n[DONE] {ok} thành công, {err} lỗi")

    if rebuild_index and ok > 0:
        print("\n[FAISS] Đang xây dựng chỉ mục...")
        idx = FaissIndex()
        total = idx.build(save=True)
        print(f"[FAISS] Đã index {total} vectors")

    st = db.stats()
    print(f"\n[DB]  Tổng số bản ghi: {st['total_files']}")


if __name__ == "__main__":
    run()
