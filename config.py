import os
from dotenv import load_dotenv

load_dotenv()

# ── MongoDB Atlas ──
MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb+srv://ducanh2510:25102004@cluster0.ry2llwz.mongodb.net/?appName=Cluster0",
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
# Thứ tự: đặt tên dài trước tên ngắn để tránh substring match sai
INSTRUMENT_FAMILIES = {
    "bowed_string":   ["violin", "viola", "cello", "contrabass", "double_bass", "erhu"],
    "plucked_string": ["guitar", "bass_guitar", "ukulele", "mandolin", "harp",
                       "banjo", "sitar", "dan_tranh", "dan_ty_ba", "dan_bau"],
}
