"""Local-only, no-write test UI for the residence-card submission flow.

Run: python3 local_test_server.py
Open: http://127.0.0.1:8080
"""

import base64
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dotenv import load_dotenv

load_dotenv()

from main import _parse_card_payload
from services.ai_service import generate_report
from services.residence_card_service import extract_residence_card, validate_card

MAX_IMAGE_BYTES = 10 * 1024 * 1024

PAGE = """<!doctype html><meta charset=utf-8><title>Report bot — local test</title>
<style>body{font:16px system-ui;max-width:760px;margin:32px auto;padding:0 16px}textarea,input,button{width:100%;box-sizing:border-box;margin:8px 0;padding:10px}textarea{height:180px}button{cursor:pointer;background:#1769aa;color:#fff;border:0;border-radius:6px}pre{white-space:pre-wrap;background:#f5f5f5;padding:14px;border-radius:6px}</style>
<h1>Residence-card local test</h1><p>Dry-run only: this page never writes to Google Sheets.</p>
<label>Ảnh mặt trước (bắt buộc)</label><input id=front type=file accept="image/*">
<label>Ảnh mặt sau (tùy chọn)</label><input id=back type=file accept="image/*">
<label>Payload</label><textarea id=payload>株式会社アスラポート
NGUYEN DINH QUOC KHANH
藤平ラ−メン大阪店

Nội dung báo cáo để dịch.</textarea><button id=run>Kiểm tra dry-run</button><pre id=out>Đang kiểm tra cấu hình…</pre>
<script>
const out=document.querySelector('#out');
async function asData(file){return new Promise((ok,bad)=>{const r=new FileReader;r.onload=()=>ok(r.result);r.onerror=bad;r.readAsDataURL(file)})}
async function health(){out.textContent=JSON.stringify(await (await fetch('/health')).json(),null,2)} health();
document.querySelector('#run').onclick=async()=>{try{const front=frontEl=document.querySelector('#front').files[0];const back=document.querySelector('#back').files[0];if(!front)throw Error('Chọn ảnh mặt trước.');out.textContent='Đang kiểm tra…';const images=[await asData(front)];if(back)images.push(await asData(back));const response=await fetch('/test',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({payload:document.querySelector('#payload').value,images})});out.textContent=JSON.stringify(await response.json(),null,2)}catch(e){out.textContent='Lỗi: '+e.message}};
</script>"""


def _decode_image(data_url):
    if not isinstance(data_url, str) or "," not in data_url:
        raise ValueError("Anh upload khong hop le")
    encoded = data_url.split(",", 1)[1]
    data = base64.b64decode(encoded, validate=True)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Anh phai nho hon 10 MB")
    return data


def _preview(card, report, company, branch):
    return {
        "mode": "dry-run — no Google Sheets write",
        "cells": {
            "B2": f"{company}     {branch}",
            "B3": card["full_name"],
            "B4": card["date_of_birth"],
            "B5": card["address"],
            "E5": card["visa_expiry"],
            "B31": report["current_situation"],
            "B33": report["future_plan"],
        },
    }


class Handler(BaseHTTPRequestHandler):
    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._json(HTTPStatus.OK, {
                "server": "ready",
                "mode": "dry-run",
                "openai_vision": bool(os.getenv("OPENAI_API_KEY")),
                "google_sheets": bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
                and os.path.exists(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")),
            })
            return
        if self.path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if self.path != "/test":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 25 * 1024 * 1024:
                raise ValueError("Request qua lon hoac rong")
            request = json.loads(self.rfile.read(length))
            payload = _parse_card_payload(request.get("payload", ""))
            image_bytes = [_decode_image(item) for item in request.get("images", [])]
            if not os.getenv("OPENAI_API_KEY"):
                raise ValueError("Thieu OPENAI_API_KEY trong .env; khong the test OCR anh that")
            extracted = extract_residence_card(image_bytes)
            card = validate_card(extracted, payload["employee_name"])
            report = generate_report(payload["report_text"], card["full_name"])
            self._json(HTTPStatus.OK, _preview(card, report, payload["company_name"], payload["branch_name"]))
        except Exception as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc), "mode": "dry-run"})

    def log_message(self, _format, *_args):
        # Do not log request paths/body from a workflow containing personal data.
        return


if __name__ == "__main__":
    port = int(os.getenv("LOCAL_TEST_PORT", "8080"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Local dry-run test server: http://127.0.0.1:{port}")
    server.serve_forever()
