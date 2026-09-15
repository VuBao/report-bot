# Report Bot — Hướng dẫn Setup

Các sự cố production, nguyên nhân và checklist bắt buộc khi nâng model/SDK được
lưu tại [CASE_STUDY.md](CASE_STUDY.md). Phải đọc tài liệu này trước mỗi lần đổi
model hoặc cấu hình reasoning/token budget.

## Yêu cầu
- Python 3.11+
- Tài khoản Google Cloud (Service Account)
- OpenAI API Key
- Telegram Bot Token

---

## Bước 1 — Cài đặt thư viện

```bash
pip install -r requirements.txt
```

---

## Bước 2 — Cấu hình Google Cloud Service Account

1. Vào https://console.cloud.google.com
2. Tạo project mới (hoặc dùng project có sẵn)
3. Bật **Google Sheets API** và **Google Drive API**
4. Tạo **Service Account** → tải file JSON → đặt vào `config/service_account.json`
5. Vào từng Google Sheet → **Share** → thêm email của Service Account (quyền Editor)

---

## Bước 3 — Tạo Telegram Bot

1. Nhắn @BotFather trên Telegram → `/newbot`
2. Lưu token nhận được
3. Thêm bot vào group chat → cấp quyền đọc tin nhắn (Privacy Mode OFF)

---

## Bước 4 — Cấu hình .env

```bash
cp .env.example .env
```

Điền các giá trị vào `.env`:

```
TELEGRAM_BOT_TOKEN=xxx
AI_PROVIDER=auto
OPENAI_API_KEY=sk-xxx
OPENAI_MODEL=gpt-5
OPENAI_REPORT_REASONING_EFFORT=low
OPENAI_REVIEW_REASONING_EFFORT=low
OPENAI_VISION_MODEL=gpt-5
OPENAI_VISION_REASONING_EFFORT=low
OPENAI_VISION_VERIFY_REASONING_EFFORT=low
# Optional fallback only:
# ANTHROPIC_API_KEY=sk-ant-xxx
# ANTHROPIC_MODEL=claude-haiku-4-5
GOOGLE_SERVICE_ACCOUNT_JSON=./config/service_account.json
GOOGLE_DRIVE_FOLDER_ID=18YPY8be9mS0uHA5K2csUv5_cOb2RO6hC
# Mặc định là Sheet danh sách tháng 9–10/2026 mới. Chỉ khai báo khi cần đổi đích:
# CHECKLIST_SPREADSHEET_ID_OVERRIDE=1WszmJ-IwtbwzzkTQ0N7SeEtyPllQRKOX_H3JYdEG4ao
SHEET_RAMURA_ID=1Fc4HnFvL5TyMPxblJT19mCth5ppb4tyn
SHEET_BICHO_ID=1NjHNeUI7XQ_hjlZdv61kCz_MDyt_3Zdv
SHEET_TAKIKO_ID=1-9gjxRudRUyau1NBZ3Awlodo-JRrr7aa
```

`AI_PROVIDER=auto` sẽ dùng OpenAI khi có `OPENAI_API_KEY`. Anthropic chỉ là fallback tùy chọn nếu bạn tự cấu hình thêm.

Nếu deploy qua GitHub Actions, đặt các giá trị sau trong GitHub repository secrets để workflow tự cập nhật `.env` trên VPS:

- `OPENAI_API_KEY`
- `TELEGRAM_BOT_TOKEN`

Workflow hiện ghim model production ở `gpt-5`; thay đổi model phải đi qua pull
request/commit và các deployment gate trong `CASE_STUDY.md`, không đổi âm thầm
bằng repository secret.

---

## Bước 5 — Chạy bot

```bash
python3 main.py
```

---

## Cách sử dụng

Gửi tin nhắn vào group Telegram theo format:

```
ラムラ — NGUYEN ANH HAO

[Nội dung báo cáo bằng tiếng Việt hoặc Nhật...]
```

Hoặc:

```
ラムラ
NGUYEN ANH HAO

[Nội dung báo cáo bằng tiếng Việt hoặc Nhật...]
```

Bot sẽ tự động:
1. Nhận dạng công ty và tên ứng viên
2. Gửi sang AI provider được cấu hình để xử lý
3. Tìm label trong tab và điền nội dung vào cột B
4. Cập nhật ngày vào E2
5. Tô màu xanh nhạt các ô đã xử lý
6. Đổi màu tab
7. Đánh dấu CHECK LIST tại cột G (`△`). Sheet checklist mặc định là
   `1WszmJ-IwtbwzzkTQ0N7SeEtyPllQRKOX_H3JYdEG4ao`, theo format: B công ty,
   C số user, D tên, E ghi chú, F khu vực, G trạng thái.
8. Cập nhật tổng hợp dưới cột G: tổng user (đếm từ cột C), đã xử lý và còn lại.
   Hai số sau tự đổi khi trạng thái `△` tại cột G được thêm, xóa hoặc chỉnh sửa.

### Nhập form từ thẻ ngoại kiều

Chỉ bật OCR sau khi đã xác nhận Telegram bot hoạt động bình thường bằng cách đặt `RESIDENCE_CARD_ENABLED=true` trong môi trường production. Mặc định OCR tắt để test luồng bot cơ bản.

Gửi **01 ảnh mặt trước thẻ**. Mặt sau là tùy chọn và có thể gửi cùng album. Bạn có thể đặt payload ở caption **hoặc** gửi nó bằng tin nhắn ngay sau ảnh (trong 5 phút). Payload bắt đầu bằng ba dòng không trống theo đúng thứ tự: tên công ty, tên chi nhánh, họ tên user. Nội dung báo cáo đặt sau ba dòng thông tin:

```text
株式会社アスラポート
藤平ラ−メン大阪店
NGUYEN DINH QUOC KHANH

[nội dung báo cáo]
```

Bot đọc toàn bộ trường cần thiết từ ảnh gốc ở lượt đầu. Vùng ADDRESS mặt trước được crop gần hết chiều ngang và đủ chiều cao cho cả hai bố cục thẻ, bao gồm địa chỉ xuống dòng, tên tòa nhà bằng Latin và số phòng ở dòng sau. Nếu địa chỉ đọc được đầy đủ, confidence đạt ngưỡng và model không đánh dấu còn nghi vấn, bot dùng ngay kết quả lượt đầu và không gọi OCR lần nữa. Chỉ khi địa chỉ thiếu, confidence thấp, dữ liệu mặt sau chưa đầy đủ hoặc model đặt `address_review_required=true`, bot mới chạy lượt hai: phóng lớn crop 3 lần, tăng tương phản/độ nét và đọc lại toàn bộ các dòng ADDRESS.

Nếu lượt hai vẫn không rõ, model trả tọa độ chuẩn hóa của ký tự hoặc đoạn nghi vấn. Bot vẽ khung đỏ lên ảnh crop và gửi lại qua Telegram để kiểm tra thủ công; nếu model không trả được tọa độ hợp lệ, toàn bộ vùng ADDRESS được khoanh đỏ. Trong trạng thái này, `XAC NHAN` bị khóa. Người gửi phải nhập `DIA CHI: [địa chỉ đúng]`, xem lại preview rồi mới xác nhận ghi form. Ảnh crop cảnh báo chỉ tồn tại trong lúc gửi phản hồi, không được giữ trong trạng thái xác nhận hoặc ghi vào log. Sau khi vượt qua validation, bot đối chiếu họ tên trong payload rồi gửi preview. Chỉ sau tin nhắn `XAC NHAN` từ chính người gửi ảnh, bot mới ghi form: `B2`, ngày tạo tại `E2`, `B3`, `B4`, `B5`, `E5`, và báo cáo dịch tại `B31`, `B33`. Chỉ vùng ngày sửa `E2:F2` và hai vùng báo cáo `B31:F31`, `B33:F33` được tô màu hoàn tất; các trường thẻ và màu tab giữ nguyên format của template. Nếu chưa có file của công ty, bot copy file `COPY` vào Drive folder để tạo form mới. Gửi `HUY` để bỏ yêu cầu.

Để tạo form mới được, service account phải có quyền **Editor** cho cả Drive folder đích và file `COPY`.

### Test local không ghi Sheet

Chạy `python3 local_test_server.py`, sau đó mở `http://127.0.0.1:8080`. Trang test nhận ảnh mặt trước (và mặt sau tùy chọn), chạy OCR + dịch + validation, rồi hiển thị chính xác các giá trị sẽ điền vào `B2`, `B3`, `B4`, `B5`, `E5`, `B31`, `B33`. Chế độ này không gọi API Google Sheets và không ghi dữ liệu production.

---

## Xử lý lỗi thường gặp

| Lỗi | Nguyên nhân | Cách xử lý |
|-----|------------|------------|
| Không nhận ra công ty | Tên công ty không có trong message | Thêm tên công ty vào message |
| Không tìm được tên ứng viên | Tên không viết HOA | Viết tên dạng: NGUYEN VAN A |
| Trùng lặp — dừng xử lý | Tab đã có dữ liệu từ lần trước | Xử lý thủ công hoặc xóa dữ liệu cũ |
| Tab không tồn tại | Tên tab trong sheet khác tên ứng viên | Kiểm tra tab name trong Google Sheet |

---

## Cấu trúc project

```
report-bot/
├── main.py                  # Entry point — Telegram bot
├── requirements.txt
├── .env.example
├── config/
│   ├── sheet_config.py      # Mapping công ty, màu, vị trí ô
│   └── service_account.json # (Bạn tự đặt vào — KHÔNG commit)
├── services/
│   ├── ai_service.py        # Gọi OpenAI API
│   └── sheet_service.py     # Gọi Google Sheets API
└── utils/
    └── parser.py            # Nhận dạng công ty + tên ứng viên
```
# auto-deploy test
