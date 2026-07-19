"""
issue_license.py — локальный CLI для тестовой выдачи лицензий (dev/QA).

В продакшене выдачей ключей занимается server/license_server.py на VPS
(по вебхуку от Lava.top/NowPayments). Этот скрипт нужен только для
локальной разработки и тестирования licensing.py без реального платежа.

Использование:
    python issue_license.py --email test@example.com --plan monthly --days 30
    python issue_license.py --email test@example.com --plan yearly --days 365 --machine-id <ID>

Требует private_key.pem рядом (сгенерируйте через gen_keys.py).
"""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from licensing import Features, sign_license_payload

BASE_DIR = Path(__file__).resolve().parent
PRIVATE_PATH = BASE_DIR / "private_key.pem"


def load_private_key():
    if not PRIVATE_PATH.exists():
        raise SystemExit("private_key.pem не найден. Сначала запустите gen_keys.py")
    pem = PRIVATE_PATH.read_bytes()
    return serialization.load_pem_private_key(pem, password=None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Выдать тестовый лицензионный ключ Pixie Pro")
    parser.add_argument("--email", required=True)
    parser.add_argument("--plan", choices=["monthly", "yearly", "lifetime"], default="monthly")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--machine-id", default=None, help="Опционально — привязать к конкретному устройству")
    args = parser.parse_args()

    private_key = load_private_key()

    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=args.days)

    payload = {
        "user_id": str(uuid.uuid4()),
        "email": args.email,
        "plan": args.plan,
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expiry": expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "features": Features.PRO_ALL,
        "machine_id": args.machine_id,
    }

    key = sign_license_payload(payload, private_key)

    print("\n=== Лицензионный ключ ===")
    print(key)
    print("\n=== pixie:// ссылка ===")
    print(f"pixie://license/{key}")
    print("\nPayload:")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
