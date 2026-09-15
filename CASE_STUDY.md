# Case studies vận hành Report Bot

Tài liệu này lưu các sự cố production, nguyên nhân và deployment gate bắt buộc.
Mục tiêu là ngăn cùng một lớp lỗi quay lại khi đổi model, SDK hoặc cấu hình AI.

## 2026-09-15 — GPT-5 OCR trả nội dung rỗng thay vì JSON

### Phạm vi ảnh hưởng

- Luồng bị lỗi: lượt hai đọc lại vùng `ADDRESS` đã crop và phóng lớn.
- Thông báo Telegram: `Chua ghi du lieu: AI doc the khong tra ve JSON hop le`.
- Sheet không bị ghi vì lỗi xảy ra trước preview và `XAC NHAN`.
- OCR lượt một đã chạy; lỗi phát sinh ở lời gọi verify địa chỉ.

### Bằng chứng production

Log ghi nhận `json.loads()` nhận chuỗi rỗng và phát sinh
`JSONDecodeError: Expecting value: line 1 column 1`. Traceback xác định lỗi ở
`_call_vision()` trong lần gọi verify địa chỉ. Phiên bản lúc xảy ra sự cố không
ghi `finish_reason` hoặc token usage, vì vậy không được khẳng định các giá trị
đó cho request production đã lỗi.

### Nguyên nhân gốc và yếu tố góp phần

1. Parser giả định mọi response thành công ở tầng HTTP đều có `content` chứa
   JSON hợp lệ. Không có nhánh xử lý `content=""`, output bị cắt hoặc refusal.
2. GPT-5 là reasoning model. `max_completion_tokens` bao gồm cả reasoning token
   và token nội dung trả về. OCR verify dùng reasoning `medium` với ngân sách
   3.000 token, nên có khả năng model dùng hết ngân sách trước khi sinh JSON.
3. JSON mode chỉ ràng buộc định dạng của nội dung được sinh ra; nó không bảo đảm
   sẽ có nội dung nếu request kết thúc trước phần trả lời.
4. Không có retry chuyên biệt khi response rỗng hoặc JSON không hoàn chỉnh.
5. Log thiếu các metadata không chứa PII như `finish_reason`, số completion token
   và reasoning token, làm chậm việc xác định nguyên nhân.
6. Unit test cũ chỉ mock response JSON thành công. Test không mô phỏng response
   HTTP thành công nhưng `content` rỗng do hết completion budget.
7. Kiểm tra quyền truy cập model bằng Models API chỉ chứng minh API key thấy được
   `gpt-5`; nó không kiểm chứng luồng vision, reasoning budget hoặc JSON output.

### Bản sửa

- Dùng reasoning `low` cho cả hai lượt OCR; chất lượng địa chỉ vẫn được bảo vệ
  bằng crop phóng lớn, lượt đọc độc lập, confidence gate và manual review.
- Ngân sách OCR thông thường là 4.000 completion token.
- Nếu GPT-5 trả nội dung rỗng hoặc JSON lỗi, retry đúng một lần với reasoning
  `minimal` và ngân sách 6.000 token.
- Nếu retry vẫn lỗi, dừng trước preview/ghi Sheet và trả thông báo lỗi.
- Log chỉ metadata chẩn đoán: số lần thử, `finish_reason`, output có rỗng không,
  completion token và reasoning token. Không log ảnh hoặc OCR raw text.
- Thêm regression test mô phỏng `finish_reason=length`, content rỗng và toàn bộ
  completion token bị reasoning sử dụng; test phải chứng minh lần retry trả JSON.

### Vì sao không dùng reasoning cao cho OCR

OCR trường cố định là tác vụ phiên âm ký tự, không phải bài toán cần lập luận dài.
Reasoning cao hơn có thể tăng độ trễ và chiếm output budget nhưng không bảo đảm
đọc đúng hơn. Cơ chế nâng chất lượng chính là ảnh crop rõ, hai lượt độc lập,
đối chiếu kết quả, confidence threshold và yêu cầu người dùng sửa địa chỉ khi
còn nghi vấn.

### Deployment gate bắt buộc cho lần đổi model/SDK tiếp theo

Không deploy thay đổi model nếu chưa hoàn thành toàn bộ checklist sau:

1. Đọc tài liệu chính thức của đúng model về endpoint, image input, JSON hoặc
   structured output, tham số không hỗ trợ và cách tính output/reasoning token.
2. Chạy test request builder cho cả model mới và fallback; xác nhận model mới
   không nhận tham số cũ không tương thích.
3. Chạy test response lỗi tối thiểu gồm: content rỗng, JSON bị cắt, `length`,
   refusal, API timeout và retry thất bại.
4. Cài `requirements.txt` trong môi trường sạch, chạy `pip check` và toàn bộ test.
5. Chạy integration test bằng ảnh tổng hợp hoặc ảnh test không chứa PII qua API
   thật. Kiểm tra cả lượt một và lượt verify crop; Models API không thay thế bước này.
6. Xác nhận thứ tự ưu tiên biến môi trường trên VPS. Các biến chuyên biệt như
   `OPENAI_REPORT_MODEL` và `OPENAI_VISION_MODEL` có thể ghi đè `OPENAI_MODEL`.
7. Deploy canary, kiểm tra commit, đúng một process, cấu hình model/reasoning thực
   tế và log khởi động trước khi nhận dữ liệu thật.
8. Theo dõi tỷ lệ output rỗng/JSON lỗi sau deploy. Chỉ log metadata, tuyệt đối
   không log dữ liệu thẻ hoặc raw OCR response.
9. Chuẩn bị rollback bằng model/config cũ; rollback không được bỏ qua validation,
   confidence gate, manual review hoặc bước `XAC NHAN`.

### Regression test phải được giữ lại

Test `test_empty_gpt5_output_retries_with_minimal_reasoning` là test chống tái
phát cho sự cố này. Không xóa hoặc nới assertion khi đổi model. Nếu API mới có
response schema khác, phải chuyển test sang schema mới nhưng vẫn giữ invariant:

- response rỗng không được đưa thẳng vào `json.loads()` rồi kết thúc luồng;
- chỉ retry hữu hạn;
- retry dùng cấu hình tiết kiệm reasoning budget hơn;
- thất bại cuối cùng không được ghi Sheet;
- log chẩn đoán không chứa PII.
