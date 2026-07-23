"""
upload_site_only.py — безопасно заливает только файлы сайта (site/) на сервер,
НЕ трогая существующий nginx-конфиг (там уже настроен HTTPS через Certbot).

Использование:
    pip install paramiko
    python upload_site_only.py
"""
import os
import sys

try:
    import paramiko
except ImportError:
    print("Установите зависимость: pip install paramiko")
    sys.exit(1)

SSH_HOST = "194.87.248.151"
SSH_PORT = 22
SSH_USER = "root"
SSH_PASSWORD = "Pm2KydrqT5"  # noqa

REMOTE_SITE_DIR = "/opt/pixie/site"
LOCAL_SITE_DIR = os.path.join(os.path.dirname(__file__), "..", "site")


def main() -> None:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[*] Подключаюсь к {SSH_USER}@{SSH_HOST} ...")
    client.connect(SSH_HOST, port=SSH_PORT, username=SSH_USER, password=SSH_PASSWORD, timeout=20)
    print("[+] Подключено.")

    sftp = client.open_sftp()
    try:
        for name in os.listdir(LOCAL_SITE_DIR):
            local_path = os.path.join(LOCAL_SITE_DIR, name)
            if os.path.isfile(local_path):
                remote_path = f"{REMOTE_SITE_DIR}/{name}"
                print(f"[*] {local_path} -> {remote_path}")
                sftp.put(local_path, remote_path)
    finally:
        sftp.close()

    stdin, stdout, stderr = client.exec_command(f"chmod -R a+rX {REMOTE_SITE_DIR} && ls -la {REMOTE_SITE_DIR}")
    print(stdout.read().decode(errors="replace"))
    print(stderr.read().decode(errors="replace"))
    client.close()
    print("[+] Готово. Файлы сайта обновлены, nginx-конфиг не менялся.")


if __name__ == "__main__":
    main()
