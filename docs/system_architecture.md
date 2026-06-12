# 🎻 Báo Cáo Kỹ Thuật: Hệ Thống Nhận Dạng & Tìm Kiếm Nhạc Cụ Bộ Dây

Tài liệu này thuyết minh chi tiết cấu trúc hệ thống, quy trình trích xuất đặc trưng âm thanh, sơ đồ khối và cơ chế tìm kiếm vector phục vụ cho mục đích trình bày và bảo vệ bài tập lớn.

> [!NOTE]
> **Phạm vi hệ thống**: Hệ thống được thiết kế và tối ưu chuyên biệt cho **07 loại nhạc cụ bộ dây** cốt lõi có trong cơ sở dữ liệu thực tế và báo cáo lý thuyết của Nhóm 10:
> - **Họ dây kéo (Bowed Strings):** Violin, Viola, Cello, Double Bass.
> - **Họ dây gảy (Plucked Strings):** Guitar, Mandolin, Banjo.

---

## 1. Sơ đồ khối & Quy trình xử lý (Yêu cầu 4.a)

Quy trình xử lý của hệ thống nhận dạng nhạc cụ đơn âm (nốt nhạc kéo dài 4-6s) được tóm tắt qua sơ đồ khối dưới đây:

```mermaid
graph TD
    A[🎵 File âm thanh truy vấn (.wav, .mp3)] --> B[⚙️ Tiền xử lý tín hiệu]
    B --> B1[Resample → 22050 Hz]
    B --> B2[Đưa về dạng Mono]
    B --> B3[Cắt bỏ khoảng lặng]
    B --> B4[Chuẩn hóa biên độ đỉnh]
    B4 --> C[📊 Trích xuất đặc trưng 100 chiều]
    C --> D[⚖️ Chuẩn hóa đặc trưng]
    D --> D1[Chuẩn hóa Z-score theo tập huấn luyện]
    D1 --> D2[Chuẩn hóa L2 về độ dài bằng 1]
    D2 --> E[🔍 Tìm kiếm tương đồng FAISS]
    E --> F[🗄️ Đọc Metadata từ MongoDB Atlas]
    F --> G[🏆 Trả về Top-5 Kết quả giống nhất]
```

### Chi tiết các bước quy trình:
1. **Tiền xử lý tín hiệu**:
   - **Resampling**: Đưa toàn bộ file âm thanh về cùng một tần số lấy mẫu ($f_s = 22050$ Hz) để đảm bảo tính đồng nhất cho việc phân tích phổ.
   - **Mono**: Chuyển tín hiệu âm thanh nổi (stereo) về mono (1 kênh) để giảm nhiễu kênh.
   - **Trim silence**: Loại bỏ khoảng lặng vô ích ở đầu và cuối tệp âm thanh bằng thuật toán dựa trên năng lượng tín hiệu (threshold = 20 dB).
   - **Normalise**: Chia biên độ tín hiệu cho biên độ đỉnh (peak value) để tránh ảnh hưởng của âm lượng to nhỏ (dynamics) khi so khớp âm sắc.
2. **Trích xuất đặc trưng**: Vector đặc trưng 100 chiều được tạo ra từ 10 nhóm đặc trưng phổ, âm sắc và thời gian.
3. **Chuẩn hóa đặc trưng**:
   - **Z-score**: Đồng bộ hóa thang đo của các đặc trưng bằng cách trừ đi trung bình và chia cho độ lệch chuẩn được thống kê từ toàn bộ cơ sở dữ liệu thực tế.
   - **L2 Normalization**: Chuẩn hóa vector đặc trưng về độ dài Euclidean bằng 1. Thao tác này biến phép đo khoảng cách Euclid sau đó trở thành phép đo Cosine Similarity (Tích vô hướng).
4. **Tìm kiếm FAISS**: Dùng thuật toán so khớp khoảng cách cực nhanh `IndexFlatIP` (Inner Product) của Facebook AI Similarity Search trên RAM để tìm ra Top-5 chỉ mục vector gần nhất.
5. **Truy hồi MongoDB**: Dùng chỉ mục FAISS để truy vấn hàng loạt (batch query) thông tin chi tiết (tên file, họ nhạc cụ, nốt nhạc, thời lượng) từ MongoDB Atlas và trả về phía giao diện Web.

---

## 2. Bộ thuộc tính nhận diện 100 chiều (Yêu cầu 2)

Hệ thống trích xuất một vector thuộc tính gồm **100 chiều**, được chia làm hai loại: **Đặc trưng tương đồng** (giúp gom cụm các âm sắc giống nhau) và **Đặc trưng phân biệt** (giúp tách biệt các lớp nhạc cụ khác nhau, ví dụ: dây kéo vs dây gảy).

| STT | Tên đặc trưng | Số chiều | Vai trò chính | Lý do lựa chọn và Giá trị thông tin |
| :--- | :--- | :---: | :---: | :--- |
| **1** | **MFCC Mean** | 40 | Tương đồng | Mel-Frequency Cepstral Coefficients biểu diễn phong bì phổ âm thanh theo thang Mel (tương thích cơ chế tai người). Trị trung bình đại diện cho màu sắc âm thanh đặc trưng (timbre) của nhạc cụ. |
| **2** | **MFCC Std** | 40 | Tương đồng | Độ lệch chuẩn của MFCC qua các khung hình mô tả sự biến thiên của màu âm theo thời gian, giúp phân biệt các âm sắc có tính động (như tiếng đàn gảy rung dây vs kéo vĩ). |
| **3** | **Chroma Mean** | 12 | Tương đồng | Chroma đại diện cho năng lượng phân bố trên 12 bán âm của thang âm quãng 8. Đặc trưng này giúp nhận diện cao độ hài âm và phân biệt các nốt nhạc giống nhau giữa các nhạc cụ. |
| **4** | **Spectral Centroid** | 2 | Phân biệt | Trọng tâm phổ tần số (trung bình & độ lệch chuẩn), thể hiện "độ sáng" của âm thanh. Nhạc cụ có âm vực cao (Violin) sẽ có centroid cao hơn nhạc cụ trầm (Cello, Double Bass). |
| **5** | **Spectral Rolloff** | 1 | Phân biệt | Tần số mà dưới đó chứa 85% năng lượng phổ. Hỗ trợ đắc lực trong việc phân biệt các âm thanh sáng sắc nét (bright) và các âm ấm đục (dark). |
| **6** | **Spectral Flux** | 1 | Phân biệt | Đo lường tốc độ biến động của phổ tần số giữa các khung hình kề nhau. Nhạc cụ gảy (Guitar, Banjo) có phổ biến đổi đột ngột lúc gảy dây (flux cao), còn dây kéo vĩ (Violin) có phổ biến đổi mềm mại hơn. |
| **7** | **Zero Crossing Rate (ZCR)** | 1 | Phân biệt | Tần suất tín hiệu đổi dấu. Nhạc cụ có tính nhạc (tonal) cao sẽ có ZCR thấp, trong khi tiếng ồn vĩ kéo sát hoặc tiếng ồn gảy móng sẽ có ZCR cao cục bộ. |
| **8** | **RMS Energy** | 1 | Tương đồng | Năng lượng hiệu dụng trung bình, thể hiện cường độ âm lượng vật lý và độ suy giảm năng lượng của nốt nhạc. |
| **9** | **Harmonic-to-Noise Ratio (HNR)** | 1 | Phân biệt | Tỷ lệ giữa thành phần hài hòa và nhiễu phổ. Tiếng nhạc cụ kéo vĩ chuẩn có HNR cao hơn nhiều so với tiếng đàn gảy dây nylon hoặc tiếng gõ đập. |
| **10**| **Onset Strength** | 1 | Phân biệt | Cường độ khi bắt đầu phát ra âm thanh. Giúp phân biệt cực kỳ hiệu quả giữa nhạc cụ dây kéo (Violin/Viola - onset tăng dần đều) và dây gảy (Guitar/Banjo - onset cực mạnh lúc chạm dây rồi giảm dần). |

---

## 3. Hệ CSDL & Cơ chế tìm kiếm (Yêu cầu 3)

Hệ thống kết hợp mô hình lưu trữ lai (Hybrid Storage):
1. **MongoDB Atlas (Cloud)**:
   - Lưu trữ metadata có cấu trúc của file âm thanh: tên file, đường dẫn đĩa cứng (`file_path`), tên nhạc cụ gán nhãn, họ nhạc cụ, nốt nhạc ước lượng, thời lượng, các giá trị đặc trưng vật lý trung bình, chỉ mục FAISS tương ứng, và vector đặc trưng 100 chiều (`feature_vector`).
   - Đảm bảo khả năng CRUD (Thêm, xóa, tìm kiếm theo tên) linh hoạt và đồng bộ thời gian thực.
2. **FAISS IndexFlatIP (RAM)**:
   - Lưu trữ ma trận vector đặc trưng kích thước $N \times 100$ để tính toán tích vô hướng Cosine trực tiếp trên RAM.
   - Nhờ cấu trúc chỉ mục phẳng phẳng phối hợp chuẩn hóa L2, việc so khớp khoảng cách đạt độ trễ cực thấp (dưới $1$ miligiây cho hàng ngàn bản ghi), vượt trội hoàn toàn so với việc truy vấn quét tuần tự của SQL/NoSQL truyền thống.

---

## 4. Kết quả trung gian & Đánh giá kết quả (Yêu cầu 4.b & 5)

### Kết quả trung gian khi truy vấn:
Khi người dùng tải lên một tệp âm thanh mới để tìm kiếm, hệ thống hiển thị:
- **Tần số cơ bản thực tế ($F_0$) và Ước lượng nốt nhạc** (ví dụ: $A4 = 440$ Hz).
- **Biểu đồ cột MFCC** biểu diễn năng lượng màu sắc âm thanh của file query.
- **Bảng đặc trưng chi tiết** (Centroid, ZCR, RMS, Onset Strength) trích xuất trực tiếp từ file query.
- **Biểu đồ đóng góp đặc trưng (Explainable Similarity)**: Phân rã độ tương đồng Cosine thành phần trăm đóng góp của từng nhóm (chỉ rõ kết quả giống nhau do âm sắc giống (MFCC), cao độ giống (Chroma), độ sáng giống (Spectral) hay nhịp lực giống (Dynamics)).

### Đánh giá kết quả nhận dạng:
- Dự án hỗ trợ công cụ đánh giá `evaluate.py` với **Stratified Sampling** đảm bảo mỗi nhạc cụ có đại diện trong mẫu đánh giá.
- Hệ thống đo lường cả **Micro-Average Precision@5** (trung bình theo mẫu) và **Macro-Average Precision@5** (trung bình theo lớp nhạc cụ — mỗi lớp đóng góp ngang nhau bất kể số lượng mẫu).
- **Overfitting Indicator**: Hiệu Micro – Macro; $|\text{Gap}| \leq 5\%$ cho thấy phân bố đánh giá cân bằng.
- Biểu đồ **Confusion Analysis** chỉ ra các lớp nhạc cụ hay bị hệ thống nhận nhầm (ví dụ: nhầm lẫn giữa Violin và Viola do dải tần số chồng lấn, hoặc nhầm giữa Guitar và Banjo do cùng thuộc họ dây gảy).
- Công cụ tối ưu `optimize.py` sử dụng **Stratified Train/Val Split (80/20)** với **L2 Regularization** để tối ưu trọng số đặc trưng mà không bị overfitting trên tập huấn luyện.

