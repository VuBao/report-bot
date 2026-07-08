# Report Bot — Hướng dẫn Setup

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
OPENAI_MODEL=gpt-4o
# Optional fallback only:
# ANTHROPIC_API_KEY=sk-ant-xxx
# ANTHROPIC_MODEL=claude-haiku-4-5
GOOGLE_SERVICE_ACCOUNT_JSON=./config/service_account.json
GOOGLE_DRIVE_FOLDER_ID=18YPY8be9mS0uHA5K2csUv5_cOb2RO6hC
SHEET_CHECKLIST_ID=1ldjiNnLFE18FNW8k6-n5ARsXY28fBu3ejzX9jxnJN4c
SHEET_RAMURA_ID=1Fc4HnFvL5TyMPxblJT19mCth5ppb4tyn
SHEET_BICHO_ID=1NjHNeUI7XQ_hjlZdv61kCz_MDyt_3Zdv
SHEET_TAKIKO_ID=1-9gjxRudRUyau1NBZ3Awlodo-JRrr7aa
```

`AI_PROVIDER=auto` sẽ dùng OpenAI khi có `OPENAI_API_KEY`. Anthropic chỉ là fallback tùy chọn nếu bạn tự cấu hình thêm.

Nếu deploy qua GitHub Actions, đặt các giá trị sau trong GitHub repository secrets để workflow tự cập nhật `.env` trên VPS:

- `OPENAI_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `OPENAI_MODEL` nếu muốn override model

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
7. Đánh dấu CHECK LIST cột E

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
