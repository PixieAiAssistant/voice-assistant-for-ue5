"""
gen_keys.py — одноразовая генерация пары RSA-ключей (2048 бит) для лицензий Pixie.

Использование:
    python gen_keys.py

Результат:
    private_key.pem  — ХРАНИТЬ ТОЛЬКО НА VPS / в менеджере паролей. НЕ коммитить в git!
    public_key.pem   — можно класть рядом с exe или вставлять в licensing.py (PUBLIC_KEY_PEM).

После генерации:
1. Скопируйте содержимое public_key.pem в licensing.py (переменная PUBLIC_KEY_PEM)
   ИЛИ просто держите файл public_key.pem рядом с exe (licensing.py подхватит его автоматически).
2. Загрузите private_key.pem на VPS в папку server/ (для license_server.py), либо
   используйте локально только для тестовой генерации ключей через issue_license.py.
3. Добавьте private_key.pem и *.pem с приватным ключом в .gitignore.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    print("Установите зависимость: pip install cryptography")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent
PRIVATE_PATH = BASE_DIR / "private_key.pem"
PUBLIC_PATH = BASE_DIR / "public_key.pem"


def main() -> None:
    if PRIVATE_PATH.exists() or PUBLIC_PATH.exists():
        answer = input(
            "Файлы ключей уже существуют. Перезаписать? Это СЛОМАЕТ все ранее выданные лицензии! (yes/no): "
        )
        if answer.strip().lower() != "yes":
            print("Отменено.")
            return

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    PRIVATE_PATH.write_bytes(private_pem)
    PUBLIC_PATH.write_bytes(public_pem)

    print(f"✅ Приватный ключ сохранён: {PRIVATE_PATH}")
    print(f"✅ Публичный ключ сохранён: {PUBLIC_PATH}")
    print("\n⚠️  ВАЖНО:")
    print("  - private_key.pem НЕЛЬЗЯ коммитить в git и НЕЛЬЗЯ класть в .exe.")
    print("  - Перенесите private_key.pem на VPS (для server/license_server.py) и удалите локальную копию")
    print("    (или храните в менеджере паролей).")
    print("  - Содержимое public_key.pem вставьте в licensing.py -> PUBLIC_KEY_PEM,")
    print("    либо просто оставьте файл public_key.pem рядом с main.py/exe.")


if __name__ == "__main__":
    main()
