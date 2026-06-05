import os
from dotenv import load_dotenv

load_dotenv()

# ── MongoDB Atlas ──
# Fix D1: URI chỉ đọc từ file .env, không hardcode trong source code
MONGO_URI = os.getenv("MONGO_URI")
if not MONGO_URI:
    raise RuntimeError(
        "MONGO_URI chưa được cấu hình! "
        "Hãy tạo file .env với nội dung: MONGO_URI=mongodb+srv://..."
    )
MONGO_DB_NAME = "music_instrument_db"
MONGO_COLLECTION = "audio_files"

# ── Paths ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FAISS_INDEX_PATH = os.path.join(BASE_DIR, "faiss_index", "instruments.index")
# Ưu tiên biến môi trường, fallback về bộ dữ liệu Strings_wav trong dự án
DATASET_PATH = os.getenv("DATASET_PATH", os.path.join(BASE_DIR, "data", "Strings_wav"))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")

# ── Audio ──
SAMPLE_RATE = 22050
N_MFCC = 40
# FEATURE_DIM được tính tự động bởi extractor; giá trị mặc định dùng để tham khảo
FEATURE_DIM = 100

# ── Flask ──
FLASK_PORT = 5000
FLASK_DEBUG = True
MAX_UPLOAD_MB = 50   # Giới hạn upload file (MB)

# ── Instrument families ──
# Fix B3+B4: thêm "double bass" (tên folder có dấu cách) vào danh sách
# batch_extract.py sẽ chuẩn hóa thành "double_bass" nhưng cần cover cả 2 variant
INSTRUMENT_FAMILIES = {
    "bowed_string":   ["violin", "viola", "cello", "contrabass", "double_bass",
                        "double bass", "erhu"],
    "plucked_string": ["guitar", "bass_guitar", "ukulele", "mandolin", "harp",
                        "banjo", "sitar", "dan_tranh", "dan_ty_ba", "dan_bau"],
}

