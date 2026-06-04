# main.py
# ============================================================
# TELEGRAM BOT — entry point
# ============================================================

import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)

from utils.parser import detect_company, detect_employee_name, get_spreadsheet_id, get_row_future
from services.ai_service import generate_report
from services.sheet_service import process_employee_sheet, mark_checklist

load_dotenv()
logging.basicConfig(
    format="%(asctime)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý mọi tin nhắn trong group chat."""
    message = update.message
    if not message or not message.text:
        return

    raw_text = message.text.strip()
    chat_id = message.chat_id

    logger.info(f"[INPUT] {raw_text[:80]}...")

    # ── Bước 0: Nhận dạng công ty ─────────────────────────────
    company_key = detect_company(raw_text)
    if not company_key:
        logger.info("Không nhận ra công ty — bỏ qua message.")
        return

    # ── Bước 0b: Nhận dạng ứng viên ───────────────────────────
    employee_name = detect_employee_name(raw_text)
    if not employee_name:
        await message.reply_text(
            "⚠️ Không tìm được tên ứng viên trong nội dung.\n"
            "Vui lòng đảm bảo tên viết HOA (vd: NGUYEN VAN A)."
        )
        return

    spreadsheet_id = get_spreadsheet_id(company_key)
    if not spreadsheet_id:
        await message.reply_text(
            f"⚠️ Không tìm thấy Spreadsheet ID cho công ty: {company_key}.\n"
            "Vui lòng kiểm tra file .env."
        )
        return

    tab_name = employee_name  # Tab name = tên ứng viên
    row_future = get_row_future(company_key)

    await message.reply_text(
        f"⏳ Đang xử lý báo cáo cho **{employee_name}** ({company_key})..."
    )

    # ── Bước 1: Gọi ChatGPT ───────────────────────────────────
    try:
        ai_result = generate_report(raw_text, employee_name)
        logger.info(f"[AI] Đã nhận kết quả cho {employee_name}")
    except Exception as e:
        logger.error(f"[AI ERROR] {e}")
        await message.reply_text(f"❌ Lỗi ChatGPT: {e}")
        return

    # ── Bước 2: Ghi vào Sheet ─────────────────────────────────
    result = process_employee_sheet(
        spreadsheet_id=spreadsheet_id,
        tab_name=tab_name,
        row_future=row_future,
        current_situation=ai_result["current_situation"],
        future_plan=ai_result["future_plan"],
    )

    if not result["success"]:
        if result["duplicate"]:
            await message.reply_text(
                f"⛔ **TRÙNG LẶP**: Tab '{tab_name}' đã có dữ liệu.\n"
                f"Chi tiết: {result['error']}\n"
                "Vui lòng xử lý thủ công."
            )
        else:
            await message.reply_text(
                f"❌ Lỗi ghi sheet: {result['error']}"
            )
        return

    # ── Bước 3: Check ✓ vào CHECK LIST ───────────────────────
    checked = mark_checklist(employee_name, company_key)
    checklist_status = "✓ Đã check CHECK LIST" if checked else "⚠️ Không tìm thấy tên trong CHECK LIST"

    # ── Bước 4: Thông báo hoàn tất ────────────────────────────
    await message.reply_text(
        f"✅ Hoàn tất báo cáo **{employee_name}**\n"
        f"📋 Công ty: {company_key}\n"
        f"📝 B31 và B36/B33 đã được điền\n"
        f"📅 Ngày cập nhật: đã ghi vào E2\n"
        f"🎨 Màu tab + ô đã cập nhật\n"
        f"{checklist_status}"
    )
    logger.info(f"[DONE] {employee_name} — {company_key}")


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN chưa được cấu hình trong .env")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot đang chạy... nhấn Ctrl+C để dừng.")
    app.run_polling()


if __name__ == "__main__":
    main()
