# Blueprint — nhập dữ liệu thẻ ngoại kiều

## Trạng thái

Thiết kế này đã được triển khai trong code. Cần kiểm tra tích hợp trên một spreadsheet test trước khi bật dùng cho dữ liệu production. Luồng báo cáo định kỳ và Google Drive folder hiện tại vẫn giữ nguyên.

## Mục tiêu đã chốt

Khi gửi Telegram gồm **01 ảnh mặt trước thẻ ngoại kiều** (mặt sau là tùy chọn) và nội dung có **công ty + họ tên + tên chi nhánh**, bot sẽ trích xuất và điền vào form của đúng ứng viên trong file Google Sheet của công ty. Bot vẫn dịch nội dung báo cáo và điền vào hàng 31, 33 như luồng hiện tại.

| Dữ liệu được điền | Nguồn duy nhất |
| --- | --- |
| Họ tên | Trường `氏名 / NAME` ở mặt trước thẻ |
| Ngày tháng năm sinh | Trường `生年月日 / DATE OF BIRTH` ở mặt trước |
| Địa chỉ | `住居地 / ADDRESS`; ưu tiên địa chỉ thay đổi được ghi rõ ở mặt sau nếu có, nếu không dùng địa chỉ ở mặt trước |
| Hạn visa | `在留期間満了日 / THE EXPIRY DATE OF THE PERIOD OF STAY` — không dùng ngày hiệu lực của chính thẻ nếu hai ngày khác nhau |
| Tên chi nhánh | Do người gửi ghi trong caption/tin nhắn; không suy đoán từ thẻ |

Không đọc, ghi, log hay trả lại số thẻ, quốc tịch, giới tính, tư cách lưu trú, điều kiện lao động hoặc dữ liệu khác không thuộc năm trường trên.

## Cú pháp gửi Telegram đã xác nhận

Gửi ảnh **mặt trước** thẻ ngoại kiều kèm caption theo đúng mẫu, hoặc gửi payload bằng tin nhắn liền sau ảnh (tối đa 5 phút). Có thể gửi thêm mặt sau trong cùng album nếu cần; ảnh thứ hai không phải điều kiện bắt buộc. Phần nội dung báo cáo bắt đầu từ dòng thứ tư:

```text
株式会社アスラポート
NGUYEN DINH QUOC KHANH
藤平ラ−メン大阪店

[nội dung báo cáo để dịch]
```

Quy ước bắt buộc:

| Dòng | Ý nghĩa | Ví dụ |
| --- | --- | --- |
| 1 | Tên công ty | `株式会社アスラポート` |
| 2 | Họ tên ứng viên | `NGUYEN DINH QUOC KHANH` |
| 3 | Tên chi nhánh | `藤平ラ−メン大阪店` |
| 4 trở đi | Nội dung báo cáo cần dịch | ghi chú phỏng vấn |

Tên công ty dùng để chọn file trong Google Drive folder hiện hữu. Tên ứng viên từ dòng 2 phải khớp **chính xác sau chuẩn hóa** với tên `氏名 / NAME` đọc từ thẻ; không khớp thì dừng, không ghi. Tên chi nhánh được giữ nguyên văn.

## Luồng xử lý

```text
Telegram ảnh mặt trước (mặt sau tùy chọn) + công ty + họ tên + chi nhánh + nội dung báo cáo
        ↓
Kiểm tra đủ dữ liệu đầu vào và nhận diện mặt trước/mặt sau
        ↓
Vision/OCR trả JSON có cấu trúc + mức tin cậy cho từng trường
        ↓
Kiểm tra chéo, chuẩn hóa ngày và áp dụng quy tắc an toàn
        ↓
Tìm file công ty trong Drive folder hiện hữu → tìm/tạo tab đúng ứng viên
        ↓
Điền các ô đích đã cố định của form, đồng thời dịch báo cáo
        ↓
Ghi có kiểm soát dữ liệu form + B31/B33 → đọc lại để xác minh → phản hồi Telegram
```

Bot vẫn dùng Drive folder `18YPY8be9mS0uHA5K2csUv5_cOb2RO6hC`. Tên chi nhánh không tham gia fuzzy-match để chọn file; nó chỉ được điền vào trường chi nhánh của form sau khi file và ứng viên đã được xác định chính xác. Nếu chưa có workbook đúng tên công ty, sau `XAC NHAN` bot sẽ copy file `COPY` (`1AmqZyGFUGETnWJdRzOJ1yR2A1Y8NUwfOouhN9MKXGbw`) vào folder này, đặt tên bằng tên công ty, rồi dùng nó làm form mới.

## Yêu cầu chính xác — không ghi sai

1. Bắt buộc có một ảnh mặt trước có thể đọc được. Bot PASS ngay nếu đọc chắc chắn đủ năm trường từ mặt trước. Mặt sau là tùy chọn và chỉ dùng để lấy địa chỉ thay đổi rõ ràng; ảnh mờ/cắt góc/sai loại giấy tờ hoặc thiếu trường bắt buộc sẽ bị từ chối.
2. Vision/OCR phải trả dữ liệu JSON theo schema cố định, gồm giá trị gốc nhìn thấy, giá trị chuẩn hóa và `confidence` cho từng trường. Không được tự suy diễn phần bị che, mờ hoặc thiếu.
3. Ngày sinh và hạn visa phải khớp định dạng ngày hợp lệ. Hạn visa chỉ lấy từ nhãn `在留期間満了日`; nếu chỉ đọc được `このカードは…まで有効` thì bot dừng và yêu cầu ảnh rõ hơn.
4. Nếu mặt sau có mục `住居地記載欄` đã điền, bot chỉ sử dụng mục có ngày ghi nhận mới nhất khi đọc rõ cả ngày và địa chỉ. Nếu không thể xác định thứ tự/một ký tự, bot dừng — không chọn đại một địa chỉ.
5. Họ tên dòng 2 và họ tên trên thẻ phải giống nhau sau khi chuẩn hóa khoảng trắng, full-width/half-width và chữ hoa. Không khớp → không ghi. Tên tab ứng viên cũng phải khớp duy nhất theo quy tắc này; không fuzzy-match để tự chọn tab.
6. Nếu chưa có workbook của công ty, bot copy workbook `COPY` sau `XAC NHAN`. Trong workbook đó, nếu chưa có tab ứng viên thì bot chỉ được tạo tab từ đúng template `MALE`/`FEMALE` sau khi giới tính trên thẻ đọc rõ. Không rõ giới tính hoặc không có template → không ghi.
7. Các ô đích cố định phải còn đúng cấu trúc form (bao gồm merge range); nếu template khác cấu trúc trong ảnh, bot dừng thay vì đổi số hàng/cột theo suy đoán.
8. Trước khi ghi, bot gửi bản xem trước 5 trường form, chi nhánh và trạng thái "báo cáo sẽ được dịch vào B31/B33", rồi yêu cầu người gửi trả lời `XAC NHAN`. Chỉ sau xác nhận mới ghi.
9. Khi ghi dùng một batch update nguyên tử; sau đó đọc lại toàn bộ ô đã ghi và chỉ báo hoàn tất khi giá trị đọc lại khớp dữ liệu đã xác nhận. Lỗi giữa chừng phải báo lỗi, không đánh dấu checklist/report là hoàn tất.

## Mapping form Sheets đã xác nhận

Theo form trong ảnh, các ô giá trị (hoặc ô đầu của vùng merge) là cố định như sau:

| Dữ liệu | Ô đích | Giá trị ghi |
| --- | --- | --- |
| Công ty + chi nhánh | `B2` (vùng merge `B2:D2`) | `株式会社アスラポート     藤平ラ−メン大阪店` — công ty, 5 khoảng trắng, chi nhánh |
| Họ tên | `B3` (vùng merge `B3:C3`) | Họ tên trên thẻ, sau khi đối chiếu với dòng 2 |
| Ngày sinh | `B4` | Ngày sinh trên thẻ, định dạng ngày Nhật thống nhất |
| Địa chỉ | `B5` (vùng merge `B5:D5`) | Địa chỉ hợp lệ mới nhất theo quy tắc mặt trước/mặt sau |
| Hạn visa | `E5` (vùng merge `E5:F5`) | `在留期間満了日` trên thẻ |
| Báo cáo — hiện trạng | `B31` | Nội dung Nhật đã dịch hoàn chỉnh |
| Báo cáo — mục tiêu tương lai | `B33` | Nội dung Nhật đã dịch hoàn chỉnh |

`B31` và `B33` thay thế việc dò label/hàng tương lai khác nhau trong luồng cũ cho feature này. Các hàng báo cáo chỉ được ghi sau khi dữ liệu đầu vào và kết quả dịch đã qua kiểm tra.

Trước khi bật cho dữ liệu production, cần chạy chế độ **dry-run chỉ đọc** trên ít nhất một form của mỗi công ty để xác nhận các merge range `B2:D2`, `B3:C3`, `B5:D5`, `E5:F5`, vị trí `B31`, `B33` không thay đổi. Kết quả dry-run chỉ trả địa chỉ ô, không trả dữ liệu thẻ vào log.

## Thiết kế kỹ thuật dự kiến

- Mở rộng Telegram handler để nhận một `PHOTO` mặt trước hoặc album tối đa hai ảnh; caption phải đi kèm ảnh/album.
- Tạo `services/residence_card_service.py`: tải ảnh Telegram vào bộ nhớ tạm, gọi model hỗ trợ vision với prompt JSON schema, kiểm tra dữ liệu và xóa file tạm ở cả nhánh thành công/lỗi.
- Tạo `services/employee_form_service.py`: xác định/tạo tab ứng viên từ template giới tính, kiểm tra cấu trúc form, tạo preview, batch-update `B2/B3/B4/B5/E5/B31/B33` và read-back verification.
- Tạo trạng thái tác vụ tạm theo `chat_id` + `message_id`, tự hết hạn sau 15 phút nếu không nhận `XAC NHAN`; không lưu ảnh hoặc dữ liệu trích xuất lâu hơn phiên này.
- Thêm audit tối thiểu không chứa PII: thời điểm, `chat_id`, ID file, tab đã chọn, kết quả `preview/confirmed/failed`, mã lỗi. Không log ảnh, OCR raw response, số thẻ hay các giá trị năm trường.
- Tách hẳn command mới khỏi `handle_message` tạo báo cáo hiện tại để ảnh thẻ không bị gửi nhầm vào prompt báo cáo định kỳ, nhưng tái sử dụng `generate_report` cho phần nội dung từ dòng 4 trở đi.

## Phản hồi Telegram

- Thiếu ảnh, ba dòng định danh hoặc nội dung báo cáo: hướng dẫn gửi lại đúng album và mẫu công ty + họ tên + chi nhánh.
- Không đủ rõ hoặc confidence thấp: chỉ nêu trường cần chụp lại, không đoán giá trị.
- Không tìm thấy/mơ hồ file, tab hay cấu trúc form: dừng, nêu lỗi kỹ thuật và không ghi gì.
- Preview hợp lệ: hiển thị đúng năm trường, tên chi nhánh và thông báo sẽ ghi báo cáo vào `B31/B33`; yêu cầu `XAC NHAN` hoặc `HUY`.
- Thành công: xác nhận đã ghi vào file + tab (không lặp lại dữ liệu thẻ trong group chat).

## Tiêu chí nghiệm thu

1. Một ảnh mẫu mặt trước đọc được: lấy đúng tên, ngày sinh, địa chỉ và `在留期間満了日`; PASS không cần mặt sau.
2. Mặt sau có thay đổi địa chỉ rõ ràng: dùng đúng địa chỉ mới nhất, không dùng địa chỉ cũ.
3. Ảnh mờ, thiếu mặt trước, thiếu một trong ba dòng định danh/nội dung báo cáo, tên dòng 2 không khớp thẻ, hai tab trùng tên, sai cấu trúc form hoặc confidence thấp: không có bất kỳ thay đổi nào trên Sheet.
4. Không có lần ghi nào trước `XAC NHAN`; mọi lần ghi thành công đều read-back đúng năm trường.
5. Unit tests cho chuẩn hóa ngày/tên, chọn địa chỉ và kiểm tra mapping ô; integration test dùng spreadsheet test riêng, không dùng file production.

## Điểm cần xác nhận trước khi triển khai

1. Caption theo mẫu `Công ty:` / `Chi nhánh:` ở trên có chấp nhận được không, hay bạn muốn một format khác?
2. Bạn xác nhận bước `XAC NHAN` trước khi ghi là bắt buộc chứ? Blueprint đề xuất bắt buộc để bảo đảm không điền sai.
3. Cần cung cấp quyền đọc cho service account vào Drive folder và một spreadsheet/test form để xác nhận cấu trúc/merge range thực tế trước khi bật ghi production.
