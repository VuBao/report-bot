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

## 2026-09-15 — GPT-5 tạo/review báo cáo trả JSON rỗng

### Dấu hiệu và phạm vi

- OCR thẻ đã hoàn tất nhưng bước `generate_report()` thất bại.
- Bot chạy đủ bốn vòng rồi báo `Expecting value: line 1 column 1` với preview
  nội dung rỗng.
- Lỗi xảy ra trước preview và ghi Sheet, nên dữ liệu production không bị ghi dở.
- Log cũ không gắn nhãn draft/review và không có token metadata, nên không thể
  kết luận response rỗng đến từ bước nào trong hai bước đó.

### Nguyên nhân và yếu tố góp phần

1. Lớp OpenAI text trả raw content mà không kiểm tra JSON. Output rỗng chỉ bị
   phát hiện ở parser phía ngoài.
2. GPT-5 draft dùng reasoning `medium` với 6.000 token; review dùng `medium` với
   2.500 token. Reasoning có thể chiếm hết completion budget trước visible JSON.
3. Outer loop coi lỗi định dạng giống một draft sai fact, nên lặp lại toàn bộ
   pipeline tối đa bốn lần. Việc này vừa chậm vừa có thể phát sinh nhiều chi phí
   nhưng không thay đổi cấu hình gây lỗi.
4. Không có log `operation=report_draft/report_review`, `finish_reason` và token
   breakdown nên không xác định nhanh tầng bị lỗi.
5. Regression test migration chỉ kiểm tra request parameter và JSON thành công,
   chưa mô phỏng text completion HTTP thành công nhưng content rỗng.

### Bản sửa và invariant mới

- Draft và review dùng reasoning `low`; vẫn giữ review độc lập để kiểm tra facts.
- Lớp OpenAI kiểm tra JSON ngay sau response. Nếu GPT-5 trả rỗng/JSON lỗi, retry
  đúng một lần với `minimal`: draft tối đa 8.000 token, review 4.000 token.
- Mỗi log lỗi có stage, lần thử, `finish_reason`, completion/reasoning token và
  cờ output rỗng; không log prompt hoặc raw report.
- Nếu recovery vẫn thất bại, dừng sớm thay vì tái tạo draft bốn vòng. Outer loop
  bốn vòng chỉ dành cho báo cáo có JSON hợp lệ nhưng chưa qua fact-check/detail.
- Các test recovery và bounded failure phải được giữ khi đổi model/endpoint.

## 2026-09-15 — ADDRESS một hoặc hai dòng bị trích xuất thiếu

### Mẫu lỗi

Địa chỉ trên thẻ có số phòng `201` bị chia theo bố cục vật lý: chữ số `2` nằm
ở cuối dòng trên, còn `01` nằm ở đầu dòng dưới. OCR trả:

`東京都品川区二葉3丁目11番5号 インベスト西大井 2`

thay vì:

`東京都品川区二葉3丁目11番5号 インベスト西大井 201`

### Nguyên nhân

1. Prompt cũ yêu cầu nối mọi dòng bằng một khoảng trắng, nhưng không định nghĩa
   ngoại lệ khi một token số bị chia qua ranh giới dòng.
2. Model lượt một trả confidence cao và không bật `address_review_required`, nên
   policy “chỉ verify khi nghi vấn” đã bỏ qua crop lượt hai.
3. Code chỉ dùng confidence/model doubt để quyết định verify; chưa có heuristic
   cho địa chỉ kết thúc bằng fragment số phòng ngắn sau tên tòa nhà.
4. Chốt so sánh hai lượt coi lượt một confidence cao là reliable, nên ngay cả
   khi ép verify, kết quả đầy đủ `201` cũng có thể bị từ chối vì khác `2`.
5. Regression suite có địa chỉ hai dòng và tên tòa nhà, nhưng chưa có fixture
   `2 | 01`, nên không phát hiện lỗi bố cục này.

### Bản sửa và invariant tổng quát

- Lượt OCR đầu nhận đồng thời ảnh thẻ đầy đủ và vùng ADDRESS đã crop/phóng lớn.
  Vì vậy model có cả ngữ cảnh để xác định mặt thẻ lẫn đủ độ phân giải để đọc đến
  hai mép của trường ADDRESS, nhưng vẫn chỉ phát sinh một API call khi kết quả rõ.
- Schema bắt buộc trả `front_address_line_count` và `front_address_lines`, chứa
  nguyên văn từng dòng vật lý theo thứ tự trên xuống. Áp dụng giống nhau cho địa
  chỉ một dòng và hai dòng, không phụ thuộc tên tòa nhà hay dạng số phòng.
- Code bỏ khoảng trắng rồi đối chiếu phép nối tất cả dòng vật lý với
  `front_address.value`. Thiếu/thừa dù chỉ một ký tự, sai số dòng, dòng rỗng hoặc
  metadata không hợp lệ đều kích hoạt lượt crop verify thứ hai.
- Với token bị chia tại ranh giới dòng, ví dụ `2` ở cuối dòng trên và `01` ở đầu
  dòng dưới, giá trị cuối phải là `201`; không được bỏ số `0` hoặc tự chèn khoảng
  trắng vào giữa một token. Quy tắc này chỉ là một ví dụ của phép đối chiếu độ
  phủ ký tự, không phải điều kiện duy nhất của bản sửa.
- Địa chỉ một hoặc hai dòng đã đủ ký tự, confidence cao và không có tín hiệu nghi
  vấn sẽ không gọi lượt hai. Lượt hai chỉ chạy khi thiếu/mismatch/confidence thấp
  hoặc model chủ động yêu cầu review.
- Heuristic số phòng ngắn vẫn giữ làm lớp cảnh báo phụ, không tự đoán hay bổ sung
  ký tự. Nếu crop vẫn không xác nhận đủ dữ liệu, bot chuyển manual review và
  highlight vùng ADDRESS thay vì ghi một địa chỉ có vẻ hợp lý vào Sheet.
- Regression suite phải có cả địa chỉ một dòng, hai dòng hoàn chỉnh, hai dòng bị
  thiếu ký tự, và tình huống crop lượt hai vẫn không thể xác nhận.

## 2026-09-16 — Có ngày sinh nhưng form không tự ghi tuổi

### Nguyên nhân và invariant

- Luồng cũ chỉ ghi ngày sinh vào `B4`; ô tuổi `C4` chưa có mapping nên luôn trống,
  dù `D4` của template đã có nhãn `才`.
- Tuổi không được suy ra bởi AI và không được tính bằng phép trừ năm đơn thuần.
  Bot tính tuổi tròn từ ngày sinh đã validate, tại đúng ngày lập báo cáo theo múi
  giờ `Asia/Tokyo`; chỉ cộng thêm một tuổi khi đã tới ngày sinh nhật trong năm.
- Ngày 29/02 được tăng tuổi vào 01/03 trong năm không nhuận. Ngày sinh tương lai
  phải bị từ chối.
- Ngày lập báo cáo và tuổi phải dùng cùng một `report_date`, sau đó ghi `B4` và
  `C4` trong cùng batch update và cùng cơ chế read-back verification.
- Trước khi ghi, form phải còn nhãn `才` tại `D4`; nếu template đổi cấu trúc, bot
  dừng thay vì suy đoán một ô tuổi khác.
