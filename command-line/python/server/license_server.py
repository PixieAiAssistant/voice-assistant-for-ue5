"""
license_server.py — сервер выдачи и управления лицензиями Pixie Pro.

Разворачивается на VPS (RuVDS и т.п.). Хранит только приватный RSA-ключ и
SQLite-базу выданных лицензий. НЕ хранит платёжные данные — только
webhook-события от платёжных провайдеров и email/plan/expiry.

Основной канал выдачи ключа — витрина на сайте (страница success.html
после оплаты дёргает GET /license/by-order?order_id=... и показывает ключ
прямо в браузере). Email (SMTP Яндекса) — дублирующий канал на случай,
если пользователь закрыл вкладку/потерял ссылку.

Эндпоинты:
    POST /webhook/lava          — вебхук об оплате от Lava.top
    POST /webhook/nowpayments   — вебхук об оплате от NowPayments (крипта)
    GET  /license/by-order      — публичный: получить ключ по order_id
                                    (для страницы "Спасибо за покупку" на сайте)
    GET  /license/generate      — вручную выдать ключ (защищено ADMIN_TOKEN)
    GET  /license/validate      — валидация ключа (опционально, для доп. проверки)
    GET  /license/revoke        — отозвать ключ (защищено ADMIN_TOKEN)
    POST /license/lost          — "забыл ключ": повторно высылает на email
                                    существующий актуальный ключ (по email)

Запуск (разработка):
    uvicorn license_server:app --reload --port 8000

Продакшен (за nginx/systemd, см. server/deploy/):
    uvicorn license_server:app --host 127.0.0.1 --port 8000 --workers 2

ВАЖНО: этот файл НЕ импортирует основной licensing.py (тот живёт в .exe
клиента), а дублирует минимально необходимую логику подписи ключа — чтобы
сервер и клиент можно было деплоить/обновлять независимо друг от друга.
Формат payload/ключа идентичен issue_license.py, см. docstring там.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import smtplib
import sqlite3
import ssl
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# ---------------------------------------------------------------------------
# Конфигурация через переменные окружения (.env на VPS, не коммитить!)
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
PRIVATE_KEY_PATH = Path(os.environ.get("PIXIE_PRIVATE_KEY_PATH", str(BASE_DIR / "private_key.pem")))
DB_PATH = Path(os.environ.get("PIXIE_LICENSE_DB", str(BASE_DIR / "licenses.db")))

ADMIN_TOKEN = os.environ.get("PIXIE_ADMIN_TOKEN", "")  # обязателен для /license/generate и /license/revoke
LAVA_WEBHOOK_SECRET = os.environ.get("LAVA_WEBHOOK_SECRET", "")
NOWPAYMENTS_IPN_SECRET = os.environ.get("NOWPAYMENTS_IPN_SECRET", "")

# --- SMTP Яндекс (дублирующая отправка ключа на email) ---
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.yandex.ru")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
SMTP_USER = os.environ.get("SMTP_USER", "")          # pixie.ai.delivery@ya.ru
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")  # пароль приложения Яндекса
SMTP_FROM_EMAIL = os.environ.get("SMTP_FROM_EMAIL", SMTP_USER)


PLAN_DAYS = {"monthly": 31, "yearly": 366, "lifetime": 36500}

# Битовая маска фич — держим в синхроне с Features.PRO_ALL из licensing.py
UE_ACTORS = 1 << 0
UE_BLUEPRINT = 1 << 1
UE_CAMERA = 1 << 2
UE_RECIPES = 1 << 3
PRO_ALL = UE_ACTORS | UE_BLUEPRINT | UE_CAMERA | UE_RECIPES


app = FastAPI(title="Pixie License Server", version="1.0")

# CORS: разрешаем сайту на GitHub Pages (и localhost при разработке) дёргать
# /license/lost и /license/validate напрямую из браузера через fetch().
ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("PIXIE_CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)



# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

@contextmanager
def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS licenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                email TEXT NOT NULL,
                plan TEXT NOT NULL,
                license_key TEXT NOT NULL,
                machine_id TEXT,
                issued_at TEXT NOT NULL,
                expiry TEXT NOT NULL,
                revoked INTEGER NOT NULL DEFAULT 0,
                payment_provider TEXT,
                payment_txn_id TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL,
                payload TEXT NOT NULL,
                received_at REAL NOT NULL
            )
            """
        )


init_db()


# ---------------------------------------------------------------------------
# RSA signing (идентично licensing.sign_license_payload)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _load_private_key():
    if not PRIVATE_KEY_PATH.exists():
        raise RuntimeError(
            f"private_key.pem не найден по пути {PRIVATE_KEY_PATH}. "
            "Сгенерируйте пару через gen_keys.py и скопируйте приватный ключ на VPS."
        )
    pem = PRIVATE_KEY_PATH.read_bytes()
    return serialization.load_pem_private_key(pem, password=None)


def sign_license_payload(payload: dict) -> str:
    private_key = _load_private_key()
    payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = private_key.sign(
        payload_bytes,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return f"{_b64url_encode(payload_bytes)}.{_b64url_encode(signature)}"


def generate_license(email: str, plan: str, machine_id: Optional[str] = None,
                      payment_provider: str = "", payment_txn_id: str = "") -> dict:
    if plan not in PLAN_DAYS:
        raise ValueError(f"Неизвестный план: {plan}")

    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=PLAN_DAYS[plan])
    user_id = str(uuid.uuid4())

    payload = {
        "user_id": user_id,
        "email": email,
        "plan": plan,
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiry": expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "features": PRO_ALL,
        "machine_id": machine_id,
    }
    license_key = sign_license_payload(payload)

    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO licenses (user_id, email, plan, license_key, machine_id,
                                   issued_at, expiry, revoked, payment_provider,
                                   payment_txn_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                user_id, email, plan, license_key, machine_id,
                payload["issued_at"], payload["expiry"], payment_provider,
                payment_txn_id, time.time(),
            ),
        )

    return {"license_key": license_key, "pixie_uri": f"pixie://license/{license_key}", "payload": payload}


def find_latest_license_by_email(email: str) -> Optional[sqlite3.Row]:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM licenses WHERE email = ? AND revoked = 0 ORDER BY created_at DESC LIMIT 1",
            (email,),
        ).fetchone()
        return row


def find_license_by_order_id(order_id: str) -> Optional[sqlite3.Row]:
    """Ищет лицензию по payment_txn_id (order_id платёжного провайдера).

    Используется страницей success.html на сайте: сразу после оплаты
    провайдер редиректит пользователя на сайт с ?order_id=..., и сайт
    дёргает этот эндпоинт, чтобы показать ключ прямо в браузере — это
    ОСНОВНОЙ канал получения ключа, email лишь дублирует его.
    """
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM licenses WHERE payment_txn_id = ? ORDER BY created_at DESC LIMIT 1",
            (order_id,),
        ).fetchone()
        return row



def revoke_license_by_key(license_key: str) -> bool:
    with db_conn() as conn:
        cur = conn.execute(
            "UPDATE licenses SET revoked = 1 WHERE license_key = ?", (license_key,)
        )
        return cur.rowcount > 0


def log_webhook_event(provider: str, payload: dict) -> None:
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO webhook_events (provider, payload, received_at) VALUES (?, ?, ?)",
            (provider, json.dumps(payload, ensure_ascii=False), time.time()),
        )


# ---------------------------------------------------------------------------
# Email (SMTP Яндекс, дублирующий канал — основной канал — сайт)
# ---------------------------------------------------------------------------

def send_license_email(email: str, license_key: str, plan: str, expiry: str) -> bool:
    """Отправляет письмо с ключом через SMTP Яндекса (SSL, порт 465).

    Это ДУБЛИРУЮЩИЙ канал: основной способ получить ключ — страница
    success.html на сайте сразу после оплаты (GET /license/by-order).
    Письмо нужно на случай, если пользователь закрыл вкладку браузера.
    """
    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"[license_server] SMTP не настроен — ключ для {email}: {license_key}")
        return False

    subject = "Your Pixie Pro license key"
    body = (
        f"Thanks for purchasing Pixie Pro ({plan})!\n\n"
        f"Your license key:\n{license_key}\n\n"
        f"Click to auto-apply (Windows, after installing Pixie):\n"
        f"pixie://license/{license_key}\n\n"
        f"Or paste the key manually into the Pixie activation window.\n\n"
        f"Valid until: {expiry}\n\n"
        f"Lost this email? Use the 'Lost key?' page on the website with this email address.\n"
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM_EMAIL
    msg["To"] = email

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=15) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM_EMAIL, [email], msg.as_string())
        return True
    except Exception as exc:
        print(f"[license_server] Ошибка отправки email через SMTP: {exc}")
        return False



# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------

def _verify_lava_signature(raw_body: bytes, signature_header: str) -> bool:
    """Lava.top подписывает вебхук HMAC-SHA256 секретом магазина.

    Точный алгоритм подписи нужно свериться с актуальной документацией
    Lava.top на момент интеграции — здесь заложена стандартная HMAC-схема,
    которую легко адаптировать под конкретный формат заголовка.
    """
    if not LAVA_WEBHOOK_SECRET:
        return True  # секрет не настроен — пропускаем (только для dev!)
    expected = hmac.new(LAVA_WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


def _verify_nowpayments_signature(raw_body: bytes, signature_header: str) -> bool:
    """NowPayments IPN подписывает тело запроса HMAC-SHA512 секретом IPN."""
    if not NOWPAYMENTS_IPN_SECRET:
        return True
    # NowPayments требует сортировки ключей JSON перед подписью — здесь
    # заложена упрощённая проверка, уточнить по документации при интеграции.
    expected = hmac.new(NOWPAYMENTS_IPN_SECRET.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature_header or "")


# ---------------------------------------------------------------------------
# Эндпоинты
# ---------------------------------------------------------------------------

@app.get("/")
def root():
    return {"service": "Pixie License Server", "status": "ok"}


@app.post("/webhook/lava")
async def webhook_lava(request: Request, x_lava_signature: str = Header(default="")):
    raw_body = await request.body()
    if not _verify_lava_signature(raw_body, x_lava_signature):
        raise HTTPException(status_code=403, detail="Неверная подпись вебхука")

    data = json.loads(raw_body.decode("utf-8"))
    log_webhook_event("lava", data)

    # Точные имена полей нужно свериться с документацией Lava.top при интеграции.
    email = data.get("buyer_email") or data.get("email")
    amount = data.get("amount") or data.get("sum")
    txn_id = data.get("order_id") or data.get("id") or ""
    status = (data.get("status") or "").lower()

    if not email:
        raise HTTPException(status_code=400, detail="email не найден в вебхуке")
    if status and status not in ("success", "paid", "completed"):
        return JSONResponse({"ok": True, "skipped": f"status={status}"})

    # Простое сопоставление суммы -> план. Уточнить точные суммы под текущий прайс.
    plan = "yearly" if amount and float(amount) >= 100 else "monthly"

    result = generate_license(email=email, plan=plan, payment_provider="lava", payment_txn_id=str(txn_id))
    send_license_email(email, result["license_key"], plan, result["payload"]["expiry"])
    return JSONResponse({"ok": True})


@app.post("/webhook/nowpayments")
async def webhook_nowpayments(request: Request, x_nowpayments_sig: str = Header(default="")):
    raw_body = await request.body()
    if not _verify_nowpayments_signature(raw_body, x_nowpayments_sig):
        raise HTTPException(status_code=403, detail="Неверная подпись вебхука")

    data = json.loads(raw_body.decode("utf-8"))
    log_webhook_event("nowpayments", data)

    email = data.get("order_description", "").split("email:")[-1].strip() if "email:" in data.get("order_description", "") else data.get("email")
    payment_status = (data.get("payment_status") or "").lower()
    txn_id = data.get("payment_id") or data.get("order_id") or ""
    price_amount = data.get("price_amount")

    if not email:
        raise HTTPException(status_code=400, detail="email не найден в вебхуке NowPayments")
    if payment_status not in ("finished", "confirmed"):
        return JSONResponse({"ok": True, "skipped": f"status={payment_status}"})

    plan = "yearly" if price_amount and float(price_amount) >= 100 else "monthly"

    result = generate_license(email=email, plan=plan, payment_provider="nowpayments", payment_txn_id=str(txn_id))
    send_license_email(email, result["license_key"], plan, result["payload"]["expiry"])
    return JSONResponse({"ok": True})


def _require_admin(token: Optional[str]) -> None:
    if not ADMIN_TOKEN or token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий admin token")


@app.get("/license/generate")
def license_generate(email: str = Query(...), plan: str = Query("monthly"),
                      machine_id: Optional[str] = Query(None),
                      token: Optional[str] = Query(None)):
    """Ручная выдача ключа (для тестов/ручной поддержки). Защищено ADMIN_TOKEN."""
    _require_admin(token)
    try:
        result = generate_license(email=email, plan=plan, machine_id=machine_id, payment_provider="manual")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    send_license_email(email, result["license_key"], plan, result["payload"]["expiry"])
    return result


@app.get("/license/revoke")
def license_revoke(key: str = Query(...), token: Optional[str] = Query(None)):
    _require_admin(token)
    ok = revoke_license_by_key(key)
    if not ok:
        raise HTTPException(status_code=404, detail="Ключ не найден")
    return {"revoked": True}


@app.get("/license/validate")
def license_validate(key: str = Query(...)):
    """Доп. онлайн-проверка (клиент по умолчанию проверяет офлайн через RSA).

    Используется опционально — например, страницей на сайте для проверки
    статуса ключа без запуска приложения.
    """
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM licenses WHERE license_key = ?", (key,)).fetchone()
    if not row:
        return {"valid": False, "reason": "Ключ не найден в базе"}
    if row["revoked"]:
        return {"valid": False, "reason": "Ключ отозван"}
    expiry_dt = datetime.strptime(row["expiry"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    if expiry_dt < datetime.now(timezone.utc):
        return {"valid": False, "reason": "Срок действия истёк", "expiry": row["expiry"]}
    return {"valid": True, "email": row["email"], "plan": row["plan"], "expiry": row["expiry"]}


@app.get("/license/by-order")
def license_by_order(order_id: str = Query(...)):
    """Публичный эндпоинт: получить ключ по order_id платёжного провайдера.

    ЭТО ОСНОВНОЙ канал доставки ключа. Флоу:
      1. Пользователь оплачивает на Lava.top/NowPayments с order_id в metadata.
      2. Провайдер шлёт вебхук на сервер -> generate_license(payment_txn_id=order_id).
      3. Провайдер редиректит браузер пользователя на
         https://pixie-ai.pro/success.html?order_id=...
      4. success.html дёргает этот эндпоинт и показывает ключ прямо на странице.

    Не считается секретом — order_id непредсказуем (генерируется платёжным
    провайдером/фронтендом при создании заказа) и известен только покупателю,
    только что совершившему оплату по этой ссылке.
    """
    row = find_license_by_order_id(order_id)
    if not row:
        return JSONResponse(
            {"ready": False, "reason": "Платёж пока не обработан. Подождите несколько секунд и обновите страницу."},
            status_code=202,
        )
    return {
        "ready": True,
        "license_key": row["license_key"],
        "pixie_uri": f"pixie://license/{row['license_key']}",
        "email": row["email"],
        "plan": row["plan"],
        "expiry": row["expiry"],
    }


@app.post("/license/lost")
def license_lost(email: str = Query(...)):
    """'Забыл ключ?' — повторно отправляет актуальный ключ на email.


    Снимает риск, описанный в плане: если письмо от SendGrid ушло в спам,
    пользователь может запросить повторную отправку сам, без обращения
    в поддержку.
    """
    row = find_latest_license_by_email(email)
    if not row:
        raise HTTPException(status_code=404, detail="Лицензии для этого email не найдено")
    sent = send_license_email(email, row["license_key"], row["plan"], row["expiry"])
    return {"sent": sent, "email": email}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
