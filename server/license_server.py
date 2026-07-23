"""
license_server.py — FastAPI-сервер для управления лицензиями Pixie Pro.

Эндпоинты:
  POST /license/validate       — проверка отзыва ключа (вызывается клиентом)
  GET  /license/by-order       — выдача ключа после оплаты (success.html polling)
  POST /license/lost           — восстановление ключа по email
  POST /webhook/lava           — webhook от Lava.top
  POST /webhook/nowpayments    — webhook от NowPayments

ВСЕ секреты читаются строго из .env (python-dotenv).
Никаких паролей/ключей в коде!
"""

from __future__ import annotations

import json
import os
import smtplib
import sqlite3
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import dotenv
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

# ---------------------------------------------------------------------------
# Загрузка .env — все секреты ТОЛЬКО отсюда
# ---------------------------------------------------------------------------
dotenv.load_dotenv()

PRIVATE_KEY_PATH = os.getenv("PRIVATE_KEY_PATH", "./private_key.pem")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./pixie_licenses.db")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.yandex.ru")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "pixie.ai.delivery@ya.ru")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Pixie Pro License")
LAVA_WEBHOOK_SECRET = os.getenv("LAVA_WEBHOOK_SECRET", "")
NOWPAYMENTS_API_KEY = os.getenv("NOWPAYMENTS_API_KEY", "")
NOWPAYMENTS_IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET", "")
SECRET_KEY = os.getenv("SECRET_KEY", "")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "https://pixie-ai.pro").split(",")
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# ---------------------------------------------------------------------------
# Загрузка приватного ключа RSA
# ---------------------------------------------------------------------------
_private_key = None


def _get_private_key():
    global _private_key
    if _private_key is not None:
        return _private_key
    pem_path = Path(PRIVATE_KEY_PATH)
    if not pem_path.exists():
        raise RuntimeError(f"Приватный ключ не найден: {PRIVATE_KEY_PATH}")
    pem = pem_path.read_bytes()
    from cryptography.hazmat.primitives import serialization
    _private_key = serialization.load_pem_private_key(pem, password=None)
    return _private_key


# ---------------------------------------------------------------------------
# База данных (SQLite)
# ---------------------------------------------------------------------------
def _get_db_path() -> str:
    """Извлекает путь к файлу БД из DATABASE_URL вида sqlite:///./path"""
    if DATABASE_URL.startswith("sqlite:///"):
        return DATABASE_URL[len("sqlite:///"):]
    return "pixie_licenses.db"


def _init_db():
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            license_key TEXT NOT NULL,
            plan TEXT NOT NULL DEFAULT 'monthly',
            expiry TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            paid INTEGER NOT NULL DEFAULT 0,
            revoked INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_licenses_email ON licenses(email)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_licenses_order_id ON licenses(order_id)
    """)
    conn.commit()
    conn.close()


def _db_connect() -> sqlite3.Connection:
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# SMTP / Email (Яндекс Почта)
# ---------------------------------------------------------------------------
def _send_email(to_email: str, subject: str, body_text: str) -> bool:
    """Отправляет письмо через SMTP Яндекс.Почты (ssl/tls на порту 465)."""
    if not SMTP_PASSWORD:
        print("[SMTP] Пароль не настроен — письмо не отправлено")
        return False
    try:
        msg = MIMEText(body_text, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = f"{SMTP_FROM_NAME} <{SMTP_FROM}>"
        msg["To"] = to_email

        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to_email], msg.as_string())
        print(f"[SMTP] Письмо отправлено на {to_email}")
        return True
    except Exception as exc:
        print(f"[SMTP] Ошибка отправки на {to_email}: {exc}")
        return False


# ---------------------------------------------------------------------------
# Генерация ключа (RSA-подпись payload)
# ---------------------------------------------------------------------------
def _generate_license_key(email: str, plan: str, days: int, machine_id: Optional[str] = None) -> tuple[str, str]:
    """Генерирует лицензионный ключ и возвращает (key, expiry_iso)."""
    now = datetime.now(timezone.utc)
    expiry = now.replace(hour=23, minute=59, second=59)  # конец дня
    from datetime import timedelta
    expiry += timedelta(days=days)

    payload = {
        "user_id": str(uuid.uuid4()),
        "email": email,
        "plan": plan,
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiry": expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "features": 15,  # Features.PRO_ALL
        "machine_id": machine_id,
    }

    private_key = _get_private_key()
    payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = private_key.sign(
        payload_bytes,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )

    def _b64url_encode(data: bytes) -> str:
        import base64
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    key = f"{_b64url_encode(payload_bytes)}.{_b64url_encode(signature)}"
    return key, payload["expiry"]


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Pixie License Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    _init_db()
    print(f"[Server] База данных инициализирована: {_get_db_path()}")
    print(f"[Server] SMTP: {SMTP_USER} @ {SMTP_HOST}:{SMTP_PORT}")


# ========================== ЭНДПОИНТЫ ==========================

# ---------- 1. Проверка отзыва (POST) ----------
class ValidateRequest(BaseModel):
    key: str


@app.post("/license/validate")
def validate_license(req: ValidateRequest):
    """Проверяет, не отозван ли ключ. Вызывается клиентом раз в 24ч."""
    conn = _db_connect()
    row = conn.execute(
        "SELECT revoked FROM licenses WHERE license_key = ?", (req.key.strip(),)
    ).fetchone()
    conn.close()

    if row is None:
        return {"valid": False, "reason": "Key not found"}
    return {"valid": not row["revoked"], "reason": "ok" if not row["revoked"] else "revoked"}


# ---------- 2. Выдача ключа после оплаты (success.html polling) ----------
@app.get("/license/by-order")
def get_license_by_order(order_id: str):
    """Polling endpoint для success.html. Возвращает ключ, когда он готов."""
    conn = _db_connect()
    row = conn.execute(
        "SELECT license_key, plan, expiry, paid FROM licenses WHERE order_id = ?",
        (order_id.strip(),),
    ).fetchone()
    conn.close()

    if row is None:
        return {"ready": False, "message": "Order not found"}

    if not row["paid"]:
        return {"ready": False, "message": "Payment not confirmed yet"}

    import base64
    payload_bytes = row["license_key"].split(".")[0]
    try:
        payload_bytes += "=" * ((-len(payload_bytes)) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_bytes))
        email = payload.get("email", "")
    except Exception:
        email = ""

    return {
        "ready": True,
        "license_key": row["license_key"],
        "plan": row["plan"],
        "expiry": row["expiry"],
        "pixie_uri": f"pixie://license/{row['license_key']}",
        "email": email,
    }


# ---------- 3. Восстановление ключа по email ----------
class LostKeyRequest(BaseModel):
    email: EmailStr


@app.post("/license/lost")
def lost_key(req: LostKeyRequest):
    """Ищет лицензию по email и отправляет ключ повторно (если SMTP настроен)."""
    email = req.email.strip().lower()
    conn = _db_connect()
    rows = conn.execute(
        "SELECT license_key, plan, expiry FROM licenses WHERE email = ? AND paid = 1 ORDER BY id DESC LIMIT 1",
        (email,),
    ).fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail="No license found for this email")

    row = rows[0]
    key = row["license_key"]

    sent = _send_email(
        to_email=email,
        subject="Your Pixie Pro License Key",
        body_text=(
            f"Hello!\n\n"
            f"Here is your Pixie Pro license key:\n\n{key}\n\n"
            f"Plan: {row['plan']}\n"
            f"Valid until: {row['expiry']}\n\n"
            f"To activate, open Pixie → Settings → Paste the key and click Activate.\n\n"
            f"Or click this link:\npixie://license/{key}\n\n"
            f"Thank you for your purchase!\n-- Pixie Team"
        ),
    )

    return {"sent": sent, "email": email, "found": True}


# ---------- 4. Webhook от Lava.top ----------
class LavaWebhook(BaseModel):
    # Типичные поля webhook от Lava.top; реальная структура может отличаться
    order_id: str
    status: str
    email: Optional[str] = None
    plan: Optional[str] = "monthly"


@app.post("/webhook/lava")
async def lava_webhook(req: Request):
    """Обрабатывает webhook от Lava.top после успешной оплаты."""
    # Верификация подписи (если Lava предоставляет signature в заголовках)
    # В реальности нужно проверять подпись через LAVA_WEBHOOK_SECRET
    body = await req.json()
    order_id = body.get("order_id", body.get("orderId", ""))
    status = body.get("status", "").lower()
    email = body.get("email", "")
    plan = body.get("plan", body.get("product_id", "monthly"))

    if not order_id:
        raise HTTPException(status_code=400, detail="Missing order_id")

    if status not in ("success", "completed", "paid"):
        return {"status": "skipped", "reason": f"Unhandled status: {status}"}

    # Определяем план и срок
    plan_map = {"monthly": 30, "yearly": 365, "lifetime": 36500}
    days = plan_map.get(plan, 30)

    # Генерируем ключ
    key, expiry = _generate_license_key(email or f"guest_{order_id}@temp", plan, days)

    conn = _db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO licenses (order_id, email, license_key, plan, expiry, paid) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (order_id, email or f"guest_{order_id}@temp", key, plan, expiry),
    )
    conn.commit()
    conn.close()

    # Отправляем ключ на email (если он указан)
    if email:
        _send_email(
            to_email=email,
            subject="Your Pixie Pro license key is ready!",
            body_text=(
                f"Thank you for your purchase!\n\n"
                f"Your Pixie Pro license key:\n\n{key}\n\n"
                f"Plan: {plan}\nValid until: {expiry[:10]}\n\n"
                f"Open Pixie → Settings → Paste the key and click Activate.\n\n"
                f"Or click: pixie://license/{key}\n\n-- Pixie Team"
            ),
        )

    return {"status": "ok", "order_id": order_id, "email": email, "plan": plan}


# ---------- 5. Webhook от NowPayments ----------
@app.post("/webhook/nowpayments")
async def nowpayments_webhook(req: Request):
    """Обрабатывает IPN-уведомление от NowPayments."""
    body = await req.json()
    # В реальности: верификация подписи через NOWPAYMENTS_IPN_SECRET
    order_id = body.get("order_id", "")
    status = body.get("payment_status", "").lower()
    email = body.get("email", "")
    plan = body.get("plan", "monthly")

    if not order_id:
        raise HTTPException(status_code=400, detail="Missing order_id")

    if status not in ("finished", "confirmed"):
        return {"status": "skipped", "reason": f"Unhandled status: {status}"}

    plan_map = {"monthly": 30, "yearly": 365, "lifetime": 36500}
    days = plan_map.get(plan, 30)

    key, expiry = _generate_license_key(email or f"guest_{order_id}@temp", plan, days)

    conn = _db_connect()
    conn.execute(
        "INSERT OR REPLACE INTO licenses (order_id, email, license_key, plan, expiry, paid) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (order_id, email or f"guest_{order_id}@temp", key, plan, expiry),
    )
    conn.commit()
    conn.close()

    if email:
        _send_email(to_email=email, subject="Your Pixie Pro license key is ready!",
                     body_text=f"Thank you! Your Pixie Pro key:\n\n{key}\n\nPlan: {plan}\nExpires: {expiry[:10]}")

    return {"status": "ok", "order_id": order_id}


# ---------- Health check ----------
@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


# ========================== ЗАПУСК ==========================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=HOST, port=PORT)