"""
licensing.py — локальная проверка и управление лицензиями Pixie Pro.

Формат ключа (JWT-подобный, но проще):
    base64url(payload_json) + "." + base64url(signature)

payload_json:
    {
        "user_id": str,
        "email": str,
        "plan": "monthly" | "yearly" | "lifetime",
        "issued_at": "YYYY-MM-DDTHH:MM:SSZ",
        "expiry": "YYYY-MM-DDTHH:MM:SSZ",
        "features": int,       # bitmask (см. Features)
        "machine_id": str|None # если None — ключ не привязан к железу
    }

Подпись — RSA-PSS (SHA256) приватным ключом (хранится только на VPS/офлайн).
В .exe встраивается только публичный ключ (см. PUBLIC_KEY_PEM ниже).

ВАЖНО: приватный ключ НИКОГДА не должен попадать в репозиторий/exe.
Используйте gen_keys.py для генерации пары один раз, храните
private_key.pem в безопасном месте (VPS/менеджер паролей), а
public_key.pem вставьте сюда (или подгружайте из файла рядом).
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidSignature
    _CRYPTO_AVAILABLE = True
except ImportError:  # pragma: no cover - позволяет модулю импортироваться без cryptography
    _CRYPTO_AVAILABLE = False


# ---------------------------------------------------------------------------
# Пути / базовая директория (совместимо с Nuitka --onefile / --standalone)
# ---------------------------------------------------------------------------

def get_base_dir() -> Path:
    """Возвращает папку, где реально лежит .exe (или скрипт при разработке).

    В Nuitka/PyInstaller --onefile режиме __file__ указывает на временную
    распакованную папку, а не туда, где лежит сам .exe. Поэтому для путей,
    которые должны быть "рядом с программой" (config.json, лицензия,
    рецепты), нужно ориентироваться на sys.executable в frozen-режиме.
    """
    is_frozen = getattr(sys, "frozen", False) or "nuitka" in sys.modules or "__compiled__" in globals()
    if is_frozen:
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
LICENSE_STATE_PATH = BASE_DIR / "pixie_license_state.json"

# Публичный ключ (RSA, 2048 бит) — безопасно хранить в .exe/репозитории.
# Соответствует private_key.pem, развёрнутому на VPS (api.pixie-ai.pro) для
# подписи выдаваемых лицензий. Если рядом с exe лежит файл public_key.pem —
# он имеет приоритет (см. _load_public_key), это встроенное значение служит
# фолбэком для собранного .exe, если файл почему-то не был упакован.
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAin7fMnv4iDXDAfpHcVZL
adQfOWpRfgsRw/1gUmiz35/yhdBluoPLsUPCGCRXtrTLuTnu4UZw+hTcUXMT8u4V
g7aanklwuYl171O9kg6v2y1WVoV3qb5/DCg6Ami85E5XnXH3wpGKJX23FV7aaSlj
qH2rUeYRjP03DfQOeDSOHK0lX6nXKhW6+7jwz3LFU75/V4GNsJRZAyCNnSQNhbm7
vZIW1H3etZmOcdaQ7WFP8NleSmNcq+pQ2DGXqtIwLtCUirOrbBreiYxWDi4+Cs6R
M/jOhDkv50nUs45YhRYqoVaYYZ2y5cNgHve77kyZ+pIhQX1rhrZbYyPfH/xfMM7Z
OwIDAQAB
-----END PUBLIC KEY-----"""


REGISTRY_PATH = r"Software\Pixie"
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 часа

# Базовый URL сервера лицензий (VPS). Используется ТОЛЬКО для best-effort
# проверки отзыва раз в 24 часа — вся остальная проверка (подпись/срок/machine_id)
# полностью локальная и работает без интернета.
LICENSE_API_BASE = "https://api.pixie-ai.pro"
ONLINE_CHECK_TIMEOUT = 4  # секунд



class Features:
    """Битовая маска фич. Free = 0, Pro включает все биты ниже."""
    WINDOWS_ASSISTANT = 0  # всегда доступно, не флаг
    UE_ACTORS = 1 << 0
    UE_BLUEPRINT = 1 << 1
    UE_CAMERA = 1 << 2
    UE_RECIPES = 1 << 3
    UE_ALL = UE_ACTORS | UE_BLUEPRINT | UE_CAMERA | UE_RECIPES

    PRO_ALL = UE_ALL


PRO_PURCHASE_URL = "https://pixie-ai.pro/#pricing"



@dataclass
class LicenseCheckResult:
    valid: bool
    expiry: Optional[str] = None
    features: int = 0
    reason: str = ""
    email: Optional[str] = None
    plan: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "expiry": self.expiry,
            "features": self.features,
            "reason": self.reason,
            "email": self.email,
            "plan": self.plan,
        }


# ---------------------------------------------------------------------------
# Machine ID
# ---------------------------------------------------------------------------

def _get_machine_guid() -> str:
    """MachineGuid из HKLM\\SOFTWARE\\Microsoft\\Cryptography.

    Стабилен для конкретной установки Windows, не требует прав администратора
    для чтения. Более надёжен, чем MAC-адрес (не меняется при VPN/Docker/WSL)
    и серийник диска (иногда пустой без прав администратора).
    """
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        winreg.CloseKey(key)
        return str(value)
    except Exception:
        return ""


def _get_cpu_id() -> str:
    """Получает идентификатор процессора (дополняет MachineGuid)."""
    try:
        proc = subprocess.run(
            ["wmic", "cpu", "get", "ProcessorId"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines = [l.strip() for l in proc.stdout.splitlines() if l.strip() and "ProcessorId" not in l]
        if lines:
            return lines[0]
    except Exception:
        pass
    return platform.processor() or platform.machine() or "unknown-cpu"


def get_machine_id() -> str:
    """SHA256(MachineGuid + CPU ID) — стабильный ID железа/ОС."""
    guid = _get_machine_guid()
    cpu = _get_cpu_id()
    raw = f"{guid}|{cpu}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def _registry_obfuscation_key() -> bytes:
    # Простая защита от казуального просмотра значения в реестре (не криптостойкая,
    # и не должна быть таковой — реальная защита лежит в RSA-подписи самого ключа).
    return hashlib.sha256(b"pixie-registry-guard").digest()


def save_machine_id_to_registry(machine_id: str) -> None:
    try:
        import winreg
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH)
        obf = base64.b64encode(_xor_bytes(machine_id.encode("utf-8"), _registry_obfuscation_key())).decode("ascii")
        winreg.SetValueEx(key, "MachineIdObf", 0, winreg.REG_SZ, obf)
        winreg.CloseKey(key)
    except Exception:
        pass


def load_machine_id_from_registry() -> Optional[str]:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY_PATH)
        obf, _ = winreg.QueryValueEx(key, "MachineIdObf")
        winreg.CloseKey(key)
        raw = _xor_bytes(base64.b64decode(obf), _registry_obfuscation_key())
        return raw.decode("utf-8")
    except Exception:
        return None


def ensure_machine_id() -> str:
    """Возвращает стабильный machine_id, кешируя его в реестре при первом вызове."""
    cached = load_machine_id_from_registry()
    if cached:
        return cached
    mid = get_machine_id()
    save_machine_id_to_registry(mid)
    return mid


# ---------------------------------------------------------------------------
# RSA verify
# ---------------------------------------------------------------------------

def _b64url_decode(s: str) -> bytes:
    padding_needed = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * padding_needed))


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _load_public_key():
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("Пакет 'cryptography' не установлен. pip install cryptography")
    pem = PUBLIC_KEY_PEM
    pem_path = BASE_DIR / "public_key.pem"
    if pem_path.exists():
        pem = pem_path.read_text(encoding="utf-8")
    return serialization.load_pem_public_key(pem.encode("utf-8"))


def _parse_iso(dt_str: str) -> datetime:
    dt_str = dt_str.strip()
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    return datetime.fromisoformat(dt_str)


def verify_license(key: str, machine_id: Optional[str] = None) -> LicenseCheckResult:
    """Проверяет лицензионный ключ: подпись, срок действия, machine_id.

    Возвращает LicenseCheckResult(valid, expiry, features, reason).
    Не обращается в сеть — вся проверка полностью локальная.
    """
    if not key or not key.strip():
        return LicenseCheckResult(valid=False, reason="Ключ не указан")

    if not _CRYPTO_AVAILABLE:
        return LicenseCheckResult(valid=False, reason="Модуль cryptography не установлен")

    try:
        payload_part, sig_part = key.strip().split(".", 1)
    except ValueError:
        return LicenseCheckResult(valid=False, reason="Некорректный формат ключа")

    try:
        payload_bytes = _b64url_decode(payload_part)
        signature = _b64url_decode(sig_part)
    except Exception:
        return LicenseCheckResult(valid=False, reason="Не удалось декодировать ключ")

    try:
        public_key = _load_public_key()
        public_key.verify(
            signature,
            payload_bytes,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
    except InvalidSignature:
        return LicenseCheckResult(valid=False, reason="Неверная подпись ключа")
    except Exception as exc:
        return LicenseCheckResult(valid=False, reason=f"Ошибка проверки подписи: {exc}")

    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return LicenseCheckResult(valid=False, reason="Повреждённые данные ключа")

    expiry_str = payload.get("expiry")
    try:
        expiry_dt = _parse_iso(expiry_str) if expiry_str else None
    except Exception:
        expiry_dt = None

    if expiry_dt and expiry_dt < datetime.now(timezone.utc):
        return LicenseCheckResult(
            valid=False, expiry=expiry_str, features=payload.get("features", 0),
            reason="Срок действия лицензии истёк", email=payload.get("email"), plan=payload.get("plan"),
        )

    bound_machine = payload.get("machine_id")
    if bound_machine and machine_id and bound_machine != machine_id:
        return LicenseCheckResult(
            valid=False, expiry=expiry_str, features=payload.get("features", 0),
            reason="Лицензия привязана к другому устройству", email=payload.get("email"), plan=payload.get("plan"),
        )

    return LicenseCheckResult(
        valid=True,
        expiry=expiry_str,
        features=int(payload.get("features", 0)),
        reason="OK",
        email=payload.get("email"),
        plan=payload.get("plan"),
    )


def sign_license_payload(payload: dict, private_key) -> str:
    """Используется ГЕНЕРАТОРОМ лицензий (VPS), не самим приложением.

    Оставлено здесь для удобства тестирования локально (см. gen_keys.py).
    """
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("Пакет 'cryptography' не установлен")
    payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    signature = private_key.sign(
        payload_bytes,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256(),
    )
    return f"{_b64url_encode(payload_bytes)}.{_b64url_encode(signature)}"


# ---------------------------------------------------------------------------
# Кеш статуса Pro (24 часа) + apply/persist license_key
# ---------------------------------------------------------------------------

def _read_state() -> dict:
    if LICENSE_STATE_PATH.exists():
        try:
            return json.loads(LICENSE_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_state(state: dict) -> None:
    try:
        LICENSE_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _current_license_key() -> str:
    """Читает license_key из config.json (без циклического импорта config_loader)."""
    cfg_path = BASE_DIR / "config.json"
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            return (data.get("license_key") or "").strip()
        except Exception:
            return ""
    return ""


def _check_revoked_online(key: str) -> Optional[bool]:
    """Best-effort проверка отзыва ключа на сервере. Возвращает:
        True  — сервер явно сказал, что ключ отозван/невалиден
        False — сервер явно подтвердил валидность
        None  — сеть недоступна / сервер не ответил / ошибка (fail-open,
                локальная RSA-проверка остаётся единственным источником правды)

    Вызывается не чаще раза в 24 часа (см. is_pro_active), поэтому не мешает
    офлайн-работе — при отсутствии интернета приложение продолжает работать
    по локально проверенному ключу до истечения его срока действия.
    """
    try:
        import urllib.request
        import urllib.parse
        url = f"{LICENSE_API_BASE}/license/validate?" + urllib.parse.urlencode({"key": key})
        with urllib.request.urlopen(url, timeout=ONLINE_CHECK_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return not bool(data.get("valid", True))
    except Exception:
        return None


def is_pro_active(force_recheck: bool = False) -> bool:
    """True, если лицензия Pro валидна. Кеширует результат на 24 часа.

    Основная проверка полностью локальная (RSA-подпись, срок действия,
    machine_id) — работает без интернета. Раз в 24 часа (при устаревшем кеше)
    дополнительно делается best-effort онлайн-проверка отзыва ключа: если
    сервер недоступен, результат не меняется (fail-open), а если сервер явно
    подтвердил отзыв — лицензия блокируется немедленно.
    """
    key = _current_license_key()
    if not key:
        return False

    state = _read_state()
    now = time.time()
    same_key = state.get("license_key") == key
    fresh = same_key and (now - state.get("checked_at", 0) < CACHE_TTL_SECONDS)

    if fresh and not force_recheck:
        return bool(state.get("valid", False))

    machine_id = ensure_machine_id()
    result = verify_license(key, machine_id)

    if result.valid:
        revoked = _check_revoked_online(key)
        if revoked is True:
            result = LicenseCheckResult(
                valid=False, expiry=result.expiry, features=result.features,
                reason="Лицензия отозвана", email=result.email, plan=result.plan,
            )

    _write_state({
        "license_key": key,
        "valid": result.valid,
        "reason": result.reason,
        "expiry": result.expiry,
        "features": result.features,
        "checked_at": now,
    })
    return result.valid



def get_license_status() -> LicenseCheckResult:
    """Возвращает подробный статус (для UI/окна настроек), не только bool."""
    key = _current_license_key()
    if not key:
        return LicenseCheckResult(valid=False, reason="Лицензия не активирована")
    machine_id = ensure_machine_id()
    return verify_license(key, machine_id)


def apply_license_key(key: str, config_path: Optional[Path] = None) -> LicenseCheckResult:
    """Сохраняет ключ в config.json и сразу проверяет его."""
    cfg_path = config_path or (BASE_DIR / "config.json")
    data = {}
    if cfg_path.exists():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["license_key"] = key.strip()
    cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return is_pro_active_result(force_recheck=True)


def is_pro_active_result(force_recheck: bool = False) -> LicenseCheckResult:
    is_pro_active(force_recheck=force_recheck)
    return get_license_status()


def parse_pixie_uri(uri: str) -> Optional[str]:
    """Извлекает лицензионный ключ из ссылки вида pixie://license/<KEY>."""
    prefix = "pixie://license/"
    if uri.startswith(prefix):
        return uri[len(prefix):].strip()
    return None


def try_apply_from_argv(argv: list[str]) -> Optional[LicenseCheckResult]:
    """Проверяет sys.argv на pixie://license/... и применяет ключ при находке."""
    for arg in argv[1:]:
        key = parse_pixie_uri(arg)
        if key:
            return apply_license_key(key)
    return None


# ---------------------------------------------------------------------------
# Free/Pro guard
# ---------------------------------------------------------------------------

def requires_pro(feature_message: str = "UE-функции") -> Callable:
    """Декоратор для функций-инструментов: блокирует выполнение без активного Pro."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not is_pro_active():
                return (
                    f"❌ {feature_message} доступны только в Pixie Pro. "
                    f"Купить подписку: {PRO_PURCHASE_URL}"
                )
            return func(*args, **kwargs)
        return wrapper
    return decorator


def pro_guard_message() -> str:
    return f"❌ Доступно только в Pixie Pro. Купить: {PRO_PURCHASE_URL}"


# ---------------------------------------------------------------------------
# AES-GCM шифрование рецептов (ключ выводится из license_key)
# ---------------------------------------------------------------------------

def _recipe_key(license_key: str) -> bytes:
    return hashlib.sha256((license_key + "recipes").encode("utf-8")).digest()


def encrypt_recipe(data: bytes, license_key: str) -> bytes:
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("Пакет 'cryptography' не установлен")
    key = _recipe_key(license_key)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, data, None)
    return nonce + ct


def decrypt_recipe(data: bytes, license_key: str) -> bytes:
    if not _CRYPTO_AVAILABLE:
        raise RuntimeError("Пакет 'cryptography' не установлен")
    key = _recipe_key(license_key)
    aesgcm = AESGCM(key)
    nonce, ct = data[:12], data[12:]
    return aesgcm.decrypt(nonce, ct, None)


if __name__ == "__main__":
    # Небольшая диагностика при прямом запуске: python licensing.py
    print("Machine ID:", ensure_machine_id())
    status = get_license_status()
    print("License status:", status.as_dict())
