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
OPENAI_API_KEY=sk-xxx
SHEET_CHECKLIST_ID=1ldjiNnLFE18FNW8k6-n5ARsXY28fBu3ejzX9jxnJN4c
SHEET_RAMURA_ID=1Fc4HnFvL5TyMPxblJT19mCth5ppb4tyn
SHEET_BICHO_ID=1NjHNeUI7XQ_hjlZdv61kCz_MDyt_3Zdv
SHEET_TAKIKO_ID=1-9gjxRudRUyau1NBZ3Awlodo-JRrr7aa
```

---

## Bước 5 — Chạy bot

```bash
python main.py
```

---

## Cách sử dụng

Gửi tin nhắn vào group Telegram theo format:

```
ラムラ — NGUYEN ANH HAO

[Nội dung báo cáo bằng tiếng Việt hoặc Nhật...]
```

Bot sẽ tự động:
1. Nhận dạng công ty và tên ứng viên
2. Gửi sang ChatGPT để xử lý
3. Điền vào ô B31 (tình hình) và B36/B33 (định hướng)
4. Cập nhật ngày vào E2
5. Tô màu xanh nhạt các ô đã xử lý
6. Đổi tab sang màu xanh dương
7. Check ✓ vào CHECK LIST cột E

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
