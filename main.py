# main.py
import os
import logging
import asyncio
import time
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from utils.parser import detect_employee_name, detect_company_name
from utils.drive_finder import (
    find_spreadsheet_id,
    find_spreadsheet_id_strict,
    find_or_create_company_spreadsheet,
)
from services.ai_service import generate_report
from services.sheet_service import process_employee_sheet, mark_checklist
from services.residence_card_service import (
    extract_residence_card,
    validate_card,
    write_residence_card_form,
)

load_dotenv()
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
for noisy_logger in ("httpx", "httpcore", "telegram", "telegram.ext"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

CARD_ALBUMS = {}
CARD_CONFIRMATIONS = {}
CARD_ALBUM_WAIT_SECONDS = 2
CARD_CONFIRMATION_TTL_SECONDS = 15 * 60

FORMAT_HINT = (
    "Format dung:\n"
    "<TEN CONG TY> — <TEN UNG VIEN IN HOA>\n"
    "<noi dung bao cao>\n\n"
    "Hoac:\n"
    "<TEN CONG TY>\n"
    "<TEN UNG VIEN IN HOA>\n"
    "<noi dung bao cao>"
)

CARD_FORMAT_HINT = (
    "Gui anh mat truoc the ngoai kieu (anh mat sau la tuy chon), kem caption theo mau:\n\n"
    "株式会社アスラポート\n"
    "NGUYEN DINH QUOC KHANH\n"
    "藤平ラ−メン大阪店\n\n"
    "[noi dung bao cao]"
)


def _parse_card_payload(text):
    lines = [line.strip() for line in (text or "").splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    if len(lines) < 4 or not all(lines[:3]):
        raise ValueError("Thieu cong ty, ho ten, chi nhanh hoac noi dung bao cao")
    report_text = "\n".join(lines[3:]).strip()
    if not report_text:
        raise ValueError("Thieu noi dung bao cao")
    return {
        "company_name": lines[0],
        "employee_name": lines[1],
        "branch_name": lines[2],
        "report_text": report_text,
    }


async def _download_card_images(bot, file_ids):
    images = []
    for file_id in file_ids:
        telegram_file = await bot.get_file(file_id)
        images.append(bytes(await telegram_file.download_as_bytearray()))
    return images


async def _finalize_card_album(key, bot):
    await asyncio.sleep(CARD_ALBUM_WAIT_SECONDS)
    album = CARD_ALBUMS.pop(key, None)
    if not album:
        return
    message = album["message"]
    if len(album["file_ids"]) not in {1, 2}:
        await message.reply_text("Chi gui 01 anh mat truoc, hoac toi da 02 anh the.\n\n" + CARD_FORMAT_HINT)
        return
    await _prepare_card_submission(message, album["file_ids"], album["caption"], bot)


async def _prepare_card_submission(message, file_ids, caption, bot):
    try:
        payload = _parse_card_payload(caption)
        images = await _download_card_images(bot, file_ids)
        extracted = await asyncio.to_thread(extract_residence_card, images)
        # Image data is deliberately discarded after extraction and never kept in state/logs.
        card_values = validate_card(extracted, payload["employee_name"])
        spreadsheet_id, file_name = await asyncio.to_thread(
            find_spreadsheet_id_strict, payload["company_name"]
        )
        report = await asyncio.to_thread(
            generate_report, payload["report_text"], card_values["full_name"]
        )
    except Exception as exc:
        logger.exception("[CARD PREPARE ERROR] %s", exc)
        await message.reply_text(f"Chua ghi du lieu: {exc}")
        return

    chat_id = message.chat_id
    CARD_CONFIRMATIONS[chat_id] = {
        "expires_at": time.monotonic() + CARD_CONFIRMATION_TTL_SECONDS,
        "user_id": message.from_user.id if message.from_user else None,
        "payload": payload,
        "card_values": card_values,
        "report": report,
        "spreadsheet_id": spreadsheet_id,
        "file_name": file_name,
        "company_form_will_be_created": spreadsheet_id is None,
    }
    form_notice = (
        "Chua co form cua cong ty: se tao tu COPY sau khi xac nhan.\n"
        if spreadsheet_id is None else ""
    )
    await message.reply_text(
        "Kiem tra truoc khi ghi (chi nguoi gui album moi duoc xac nhan):\n\n"
        f"Cong ty + chi nhanh: {payload['company_name']}     {payload['branch_name']}\n"
        f"Ho ten: {card_values['full_name']}\n"
        f"Ngay sinh: {card_values['date_of_birth']}\n"
        f"Dia chi: {card_values['address']}\n"
        f"Han visa: {card_values['visa_expiry']}\n\n"
        f"{form_notice}"
        "Bao cao se duoc dich va ghi vao B31/B33. Tra loi XAC NHAN de ghi, hoac HUY de bo qua."
    )


async def handle_card_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.photo:
        return
    if not message.media_group_id:
        await _prepare_card_submission(
            message,
            [message.photo[-1].file_id],
            message.caption or "",
            context.bot,
        )
        return
    key = (message.chat_id, message.media_group_id)
    album = CARD_ALBUMS.setdefault(key, {
        "file_ids": [],
        "caption": "",
        "message": message,
        "task": None,
    })
    album["file_ids"].append(message.photo[-1].file_id)
    if message.caption and not album["caption"]:
        album["caption"] = message.caption
    previous_task = album.get("task")
    if previous_task and not previous_task.done():
        previous_task.cancel()
    album["task"] = asyncio.create_task(_finalize_card_album(key, context.bot))


async def _handle_card_confirmation(message):
    chat_id = message.chat_id
    pending = CARD_CONFIRMATIONS.get(chat_id)
    if not pending:
        return False
    if pending["expires_at"] < time.monotonic():
        CARD_CONFIRMATIONS.pop(chat_id, None)
        await message.reply_text("Yeu cau xac nhan da het han. Vui long gui lai album the.")
        return True
    if pending["user_id"] is not None and message.from_user and pending["user_id"] != message.from_user.id:
        await message.reply_text("Chi nguoi da gui album the moi co the xac nhan hoac huy.")
        return True

    command = " ".join(message.text.strip().upper().split())
    if command == "HUY":
        CARD_CONFIRMATIONS.pop(chat_id, None)
        await message.reply_text("Da huy. Chua co du lieu nao duoc ghi vao Sheet.")
        return True
    if command not in {"XAC NHAN", "XACNHAN"}:
        await message.reply_text("Yeu cau dang cho xac nhan. Tra loi XAC NHAN hoac HUY.")
        return True

    CARD_CONFIRMATIONS.pop(chat_id, None)
    try:
        spreadsheet_id = pending["spreadsheet_id"]
        company_form_created = False
        if spreadsheet_id is None:
            spreadsheet_id, _, company_form_created = await asyncio.to_thread(
                find_or_create_company_spreadsheet,
                pending["payload"]["company_name"],
            )
        result = await asyncio.to_thread(
            write_residence_card_form,
            spreadsheet_id,
            pending["payload"]["company_name"],
            pending["payload"]["branch_name"],
            pending["card_values"],
            pending["report"]["current_situation"],
            pending["report"]["future_plan"],
        )
    except Exception as exc:
        logger.exception("[CARD WRITE ERROR] %s", exc)
        await message.reply_text(f"Khong the hoan tat ghi form: {exc}")
        return True

    try:
        checked = await asyncio.to_thread(
            mark_checklist,
            pending["card_values"]["full_name"],
            pending["payload"]["company_name"],
        )
    except Exception as exc:
        logger.exception("[CARD CHECKLIST ERROR] %s", exc)
        checked = None
    checklist_status = (
        "da cap nhat" if checked is True
        else "khong tim thay ten de cap nhat" if checked is False
        else "co loi khi cap nhat (form da ghi thanh cong)"
    )
    await message.reply_text(
        f"Da ghi form va xac minh thanh cong cho tab {result['tab_name']}. "
        f"{'Da tao form moi cho cong ty. ' if company_form_created else ''}"
        f"CHECK LIST: {checklist_status}."
    )
    return True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return
    if await _handle_card_confirmation(message):
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
    app.add_handler(MessageHandler(filters.PHOTO, handle_card_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    logger.info("Bot dang chay...")
    app.run_polling()

if __name__ == "__main__":
    main()
