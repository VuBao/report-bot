# main.py
import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from utils.parser import detect_employee_name, detect_company_name
from utils.drive_finder import find_spreadsheet_id
from services.ai_service import generate_report
from services.sheet_service import process_employee_sheet, mark_checklist

load_dotenv()
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
for noisy_logger in ("httpx", "httpcore", "telegram", "telegram.ext"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

FORMAT_HINT = (
    "Format dung:\n"
    "<TEN CONG TY> — <TEN UNG VIEN IN HOA>\n"
    "<noi dung bao cao>\n\n"
    "Hoac:\n"
    "<TEN CONG TY>\n"
    "<TEN UNG VIEN IN HOA>\n"
    "<noi dung bao cao>"
)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    try:
        raw_text = message.text.strip()
        logger.info(f"[INPUT] {raw_text[:80]}...")

        employee_name = detect_employee_name(raw_text)
        if not employee_name:
            logger.info("Khong tim duoc ten ung vien.")
            await message.reply_text("Khong tim duoc ten ung vien in HOA.\n\n" + FORMAT_HINT)
            return

        company_name = detect_company_name(raw_text)
        if not company_name:
            await message.reply_text("Khong tim duoc ten cong ty.\n\n" + FORMAT_HINT)
            return

        logger.info(f"[DETECT] Cong ty: {company_name} | Ung vien: {employee_name}")

        try:
            spreadsheet_id, file_name = find_spreadsheet_id(company_name)
        except Exception as e:
            logger.exception(f"[DRIVE ERROR] {e}")
            await message.reply_text(f"Loi tim Google Drive/Sheet: {e}")
            return

        if not spreadsheet_id:
            await message.reply_text(f"Khong tim thay Sheet cho: {company_name}")
            return

        await message.reply_text(f"Dang xu ly {employee_name} - {file_name}")

        try:
            ai_result = generate_report(raw_text, employee_name)
        except Exception as e:
            logger.exception(f"[AI ERROR] {e}")
            await message.reply_text(f"Loi AI: {e}")
            return

        try:
            result = process_employee_sheet(
                spreadsheet_id=spreadsheet_id,
                tab_name=employee_name,
                row_future=36,
                current_situation=ai_result["current_situation"],
                future_plan=ai_result["future_plan"],
            )
        except Exception as e:
            logger.exception(f"[SHEET ERROR] {e}")
            await message.reply_text(f"Loi ghi sheet: {e}")
            return

        if not result["success"]:
            await message.reply_text(f"Loi ghi sheet: {result['error']}")
            return

        try:
            checked = mark_checklist(employee_name, company_name)
            # Neu la nhan vien moi, them note vao checklist
            if result.get("is_new_employee"):
                from services.sheet_service import add_checklist_note
                add_checklist_note(employee_name, company_name, "Cần thêm thông tin cá nhân đang còn thiếu")
        except Exception as e:
            logger.exception(f"[CHECKLIST ERROR] {e}")
            await message.reply_text(f"Da ghi sheet, nhung loi CHECK LIST: {e}")
            return

        checklist_status = "Da check CHECK LIST" if checked else "Khong tim thay ten trong CHECK LIST"
        await message.reply_text(f"Hoan tat {employee_name} - {file_name} - {checklist_status}")
        logger.info(f"[DONE] {employee_name} - {file_name}")
    except Exception as e:
        logger.exception(f"[UNHANDLED ERROR] {e}")
        await message.reply_text(f"Loi khong mong muon: {e}")


def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN chua duoc cau hinh")
    app = ApplicationBuilder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot dang chay...")
    app.run_polling()

if __name__ == "__main__":
    main()
