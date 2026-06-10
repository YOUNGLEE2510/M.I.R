# 🎻 Musical Instrument Recognition System

Hệ thống nhận dạng và tìm kiếm tiếng **nhạc cụ bộ dây** dựa trên đặc trưng âm thanh.

- **Database**: MongoDB Atlas
- **Search**: FAISS (Cosine Similarity)
- **Feature**: 100-dim vector (MFCC, Chroma, Spectral...)
- **UI**: Flask + Web Interface

---

## Cài đặt

```bash
pip install -r requirements.txt
```

---

## Quy trình sử dụng

### Bước 1 – Chuẩn bị dữ liệu
Đặt file âm thanh vào thư mục tương ứng (mặc định):
```
data/Strings_wav/
  violin/    ← violin_01.wav, violin_02.wav ...
  guitar/    ← guitar_01.wav ...
  cello/     ← cello_01.wav ...
```
Bạn có thể đổi đường dẫn dữ liệu bằng biến môi trường `DATASET_PATH`.

### Bước 2 – Trích xuất đặc trưng & lưu MongoDB
```bash
python features/batch_extract.py
```

### Bước 3 – Khởi động Web App
```bash
python app.py
```
Mở trình duyệt: **http://localhost:5000**

### Bước 4 – Rebuild FAISS Index (khi thêm dữ liệu mới)
- Nhấn nút **Rebuild FAISS Index** trên giao diện web, **hoặc**
- `POST http://localhost:5000/api/index/build`

---

## API Endpoints

| Method | URL | Mô tả |
|--------|-----|--------|
| GET  | `/api/ping` | Kiểm tra MongoDB |
| GET  | `/api/stats` | Thống kê CSDL |
| GET  | `/api/records` | Danh sách tất cả records |
| GET  | `/api/instruments` | Danh sách nhạc cụ |
| POST | `/api/ingest` | Thêm file vào DB |
| POST | `/api/search` | Tìm kiếm Top-K |
| POST | `/api/index/build` | Rebuild FAISS index |
| GET  | `/api/audio/<id>` | Stream file âm thanh |
| POST | `/api/fix-paths` | Batch fix đường dẫn file |

---

## Cấu trúc dự án
```
├── app.py                  # Flask main app
├── config.py               # Cấu hình
├── evaluate.py             # CLI evaluation
├── optimize.py             # Tối ưu trọng số (Simulated Annealing)
├── utils.py                # Tiện ích
├── requirements.txt
├── .env                    # MongoDB URI + FLASK_DEBUG
├── data/Strings_wav/       # Thư mục chứa audio (mặc định)
├── database/
│   └── mongo_client.py     # MongoDB CRUD
├── features/
│   ├── extractor.py        # AudioFeatureExtractor
│   └── batch_extract.py    # Batch processing (2-pass)
├── search/
│   ├── faiss_index.py      # FAISS index manager
│   └── searcher.py         # AudioSearcher
├── faiss_index/            # Saved FAISS index files
├── templates/index.html    # Web UI
└── static/
    ├── style.css
    └── app.js
```

## Đặc trưng âm thanh (100 chiều)

| Đặc trưng | Chiều | Vai trò |
|-----------|-------|---------|
| MFCC mean | 40 | Màu âm – similarity |
| MFCC std  | 40 | Động học – similarity |
| Chroma mean | 12 | Hòa âm – similarity |
| Spectral Centroid | 2 | Độ sáng – discrimination |
| Spectral Rolloff | 1 | Phổ tần – discrimination |
| Spectral Flux | 1 | Onset – discrimination |
| ZCR | 1 | Tonal/noise – discrimination |
| RMS Energy | 1 | Cường độ – similarity |
| HNR | 1 | Hài hòa – discrimination |
| Onset Strength | 1 | Dây kéo vs gảy – discrimination |
