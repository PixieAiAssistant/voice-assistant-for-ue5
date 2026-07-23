import os
import sys
import ctypes
import traceback


def _fatal_startup_error(exc: BaseException) -> None:
    """Показывает ошибку запуска пользователю и пишет её в лог-файл рядом с .exe.

    Критично для собранного .exe: там используется --windows-console-mode=disable,
    поэтому без этой обёртки любой сбой при старте (например, из-за отсутствующей
    DLL, битого модуля после Nuitka-компиляции и т.п.) был бы абсолютно молчаливым —
    окно просто не появляется, и пользователь не понимает, что случилось.
    """
    try:
        base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(base, "pixie_startup_error.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        log_path = "(не удалось записать лог)"
    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            f"Pixie не смогла запуститься:\n\n{type(exc).__name__}: {exc}\n\n"
            f"Подробности записаны в файл:\n{log_path}",
            "Pixie — ошибка запуска",
            0x10,  # MB_ICONERROR
        )
    except Exception:
        pass
    sys.exit(1)


try:
    import asyncio
    import logging
    from logging.handlers import RotatingFileHandler
    import pyaudio
    import subprocess
    import io
    import mss
    import time
    import pyperclip
    from PIL import Image
    from pypdf import PdfReader
    from google import genai
    from google.genai import types
except BaseException as _startup_import_exc:
    _fatal_startup_error(_startup_import_exc)

# ---------- Nuitka/Windows совместимость ----------

# WindowsSelectorEventLoopPolicy нужен для стабильной работы asyncio-сокетов
# после компиляции через Nuitka (ProactorEventLoop может вести себя иначе).
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

from config_loader import load_config, BASE_DIR as CONFIG_BASE_DIR
import licensing

# ---------- Обработка протокола pixie://license/<KEY> из аргументов запуска ----------
# Inno Setup регистрирует pixie:// с флагом "%1" в команде запуска — при клике
# по ссылке из письма Windows передаёт её как sys.argv[1] уже запущенному/новому процессу.
_pixie_uri_result = licensing.try_apply_from_argv(sys.argv)
if _pixie_uri_result is not None:
    print(f"[Система]: Применение лицензии из ссылки pixie://... valid={_pixie_uri_result.valid} reason={_pixie_uri_result.reason}")

# ---------- DPI-осведомлённость ----------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass


pyautogui_available = True
try:
    import pyautogui
    pyautogui.FAILSAFE = False
except ImportError:
    pyautogui_available = False

LOG_DIR = str(CONFIG_BASE_DIR)
LOG_FILE = os.path.join(LOG_DIR, "pixie_agent.log")

# Загружаем config.json один раз при старте (имя ассистента, голос, язык, пути, лицензия)
APP_CONFIG = load_config()

# ---------- Первый запуск: дружелюбный онбординг вместо ручного редактирования JSON ----------
# Если пользователь ещё не прошёл настройку (или не указан API-ключ) — показываем
# анимированный wizard (customtkinter): тема, API-ключ, имя/голос/характер, UE-проект, GDD.
# Пользователю не нужно ни открывать консоль, ни редактировать config.json руками.
if not APP_CONFIG.get("onboarding_complete") or not APP_CONFIG.get("gemini_api_key"):
    try:
        from onboarding import run_onboarding
        APP_CONFIG = run_onboarding(edit_mode=False)
    except BaseException as _onboarding_exc:
        _fatal_startup_error(_onboarding_exc)

# ---------- Домашний экран (дашборд): показывается на каждом запуске ----------
# Даёт кнопки Start / Settings / Get Pro без необходимости трогать консоль или файлы.
try:
    from app_shell import run_dashboard
    _dashboard_action = run_dashboard()
except BaseException as _dashboard_exc:
    _fatal_startup_error(_dashboard_exc)

if _dashboard_action != "start":
    sys.exit(0)

# После онбординга/дашборда конфиг мог измениться (Settings) — перечитываем.
APP_CONFIG = load_config()
ASSISTANT_NAME = APP_CONFIG.get("assistant_name", "Pixie")
VOICE_NAME = APP_CONFIG.get("voice_name", "Aoede")
APP_LANGUAGE = APP_CONFIG.get("language", "en")
try:
    from presets import UI_LANGUAGES as _UI_LANGUAGES
    APP_LANGUAGE_CODE = _UI_LANGUAGES.get(APP_LANGUAGE, {}).get("code", "en-US")
    APP_LANGUAGE_LABEL = _UI_LANGUAGES.get(APP_LANGUAGE, {}).get("label", "English")
except Exception:
    APP_LANGUAGE_CODE = "en-US"
    APP_LANGUAGE_LABEL = "English"
if APP_CONFIG.get("gemini_api_key"):
    # Строгая очистка API-ключа перед установкой в окружение
    _raw_key = APP_CONFIG["gemini_api_key"]
    _clean_key = _raw_key.strip().split("\n")[0].strip()
    os.environ.setdefault("GEMINI_API_KEY", _clean_key)

# ---------- ПРОКСИ: HTTP_PROXY / HTTPS_PROXY ----------
# Gemini Live API использует websockets и google.genai.Client().
# Если в системе заданы HTTP_PROXY/HTTPS_PROXY (например, через VPN-клиент
# с TUN-интерфейсом или корпоративный прокси), библиотеки urllib3/httpx
# и aiohttp должны их автоматически подхватить. Явно логируем для отладки.
_proxy_http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or ""
_proxy_https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or ""
if _proxy_http or _proxy_https:
    print(f"[Система]: Обнаружен HTTP-прокси: HTTP={_proxy_http or '—'}, HTTPS={_proxy_https or '—'}")
    # Для aiohttp (используется google-genai под капотом) также устанавливаем
    # переменные в нижнем регистре, так как aiohttp смотрит на http_proxy/https_proxy
    if _proxy_http and not os.environ.get("http_proxy"):
        os.environ["http_proxy"] = _proxy_http
    if _proxy_https and not os.environ.get("https_proxy"):
        os.environ["https_proxy"] = _proxy_https
else:
    print("[Система]: HTTP-прокси не обнаружен (работаем напрямую)")



def _load_env_file() -> None:
    """Загружает GEMINI_API_KEY и др. из .env рядом с main.py (не перезаписывает os.environ)."""
    env_path = os.path.join(LOG_DIR, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        print(f"[Система]: Не удалось прочитать .env: {exc}")


_load_env_file()

logger = logging.getLogger("pixie_agent")
logger.setLevel(logging.DEBUG)

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
file_handler.setLevel(logging.DEBUG)
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
console_handler.setLevel(logging.INFO)
logger.addHandler(console_handler)

logger.debug("Logger initialized. Log file: %s", LOG_FILE)

# ---------- НАСТРОЙКИ ----------
FORMAT = pyaudio.paInt16
CHANNELS = 1
INPUT_RATE = 48000
OUTPUT_RATE = 48000
INPUT_CHUNK = 3072
OUTPUT_CHUNK = 1024
STREAM_FPS = 0.2  
VIDEO_WIDTH = 1280
VIDEO_HEIGHT = 720
JPEG_QUALITY = 40

# Сколько подряд "настоящих" ошибок соединения (не GoAway) допускается,
# прежде чем агент сдастся и завершит процесс (тогда его должен поднять .bat).
MAX_CONSECUTIVE_CONNECTION_ERRORS = 8

PROTECTED_PATHS = ["windows", "system32", "program files", "boot", "recovery"]

def is_path_safe(path: str) -> bool:
    lowered_path = path.lower()
    for protected in PROTECTED_PATHS:
        if protected in lowered_path:
            return False
    return True

def minimize_our_console():
    """Автоматически сворачивает окно этого терминала при старте."""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 6) # SW_MINIMIZE
    except:
        pass

# ---------- ИНСТРУМЕНТЫ УПРАВЛЕНИЯ ОКНАМИ И ВВОДА ----------
def focus_window(title_part: str) -> str:
    try:
        user32 = ctypes.windll.user32
        found = []
        
        def enum_handler(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    if title_part.lower() in buff.value.lower():
                        found.append(hwnd)
                        return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(enum_handler), 0)
        
        if found:
            user32.ShowWindow(found[0], 9)  # SW_RESTORE
            time.sleep(0.05)
            user32.SetForegroundWindow(found[0])
            return f"✅ Фокус успешно переведен на окно, содержащее '{title_part}'"
        return f"❌ Окно с текстом '{title_part}' не найдено. Убедись, что приложение запущено!"
    except Exception as e:
        return f"Ошибка фокусировки окна: {str(e)}"

def type_text(text: str) -> str:
    if not pyautogui_available: return "PyAutoGUI не доступен"
    try:
        pyperclip.copy(text)
        time.sleep(0.05)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.05)
        return f"✅ Текст успешно отправлен в активное окно (вслепую): {text[:50]}..."
    except Exception as e: 
        return f"Ошибка ввода текста: {str(e)}"

def press_key(key: str) -> str:
    if not pyautogui_available: return "PyAutoGUI не доступен"
    try:
        k = key.strip().lower()
        if k in ["`", "~", "тильда", "grave", "win+space", "win_space", "winspace"]:
            pyautogui.hotkey('win', 'space')
            return "Клавиша: Win+Space (смена раскладки клавиатуры)"
        
        if '+' in key: 
            pyautogui.hotkey(*key.split('+'))
        else: 
            pyautogui.press(key)
        time.sleep(0.05)
        return f"Клавиша: {key}"
    except Exception as e: return f"Ошибка: {str(e)}"

def minimize_current_window() -> str:
    if not pyautogui_available: return "PyAutoGUI не доступен"
    try:
        pyautogui.hotkey('alt', 'space')
        time.sleep(0.05)
        pyautogui.press('n')
        return "Свёрнуто"
    except Exception as e: return f"Ошибка: {str(e)}"

def close_current_window() -> str:
    """Закрыть активное переднее окно Windows через taskkill.
    Alt+F4 НЕ используется — он может закрыть не то окно.
    Работает через GetForegroundWindow + GetWindowThreadProcessId + taskkill /pid.
    Защита: не даёт закрыть собственный процесс агента."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "❌ Нет активного окна (GetForegroundWindow вернул 0)."

        # Заголовок окна
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value or "(без заголовка)"

        # PID процесса
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        our_pid = os.getpid()

        if pid.value == our_pid:
            return "❌ Это консоль самого агента — не буду закрывать."

        proc = subprocess.run(
            f'taskkill /pid {pid.value} /f',
            shell=True, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
        )
        out = (proc.stdout or proc.stderr or '').strip()
        if proc.returncode == 0:
            return f"✅ Закрыто окно '{title}' (PID {pid.value})"
        return f"❌ Ошибка закрытия '{title}' (PID {pid.value}): {out[:200]}"
    except Exception as e:
        return f"❌ close_current_window: {e}"

def close_window_by_name(name: str) -> str:
    """Закрыть окно/процесс по имени exe или части заголовка через taskkill.
    НЕ требует фокуса — самый надёжный способ для голосового ассистента."""
    try:
        if not name.strip():
            return "❌ Укажи имя процесса или окна (например: notepad, notepad.exe, Блокнот)."
        nm = name.strip()
        # 1) По имени образа процесса (notepad.exe / notepad)
        exe = nm if nm.lower().endswith('.exe') else nm + '.exe'
        p1 = subprocess.run(
            f'taskkill /im "{exe}" /f',
            shell=True, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
        )
        o1 = (p1.stdout or p1.stderr or '').strip()
        if p1.returncode == 0:
            return f"✅ Закрыто по процессу '{exe}': {o1[:200]}"

        # 2) Если по exe не найдено — по точному заголовку окна
        p2 = subprocess.run(
            f'taskkill /fi "WINDOWTITLE eq {nm}" /f',
            shell=True, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
        )
        o2 = (p2.stdout or p2.stderr or '').strip()
        if p2.returncode == 0:
            return f"✅ Закрыто по заголовку '{nm}': {o2[:200]}"

        # 3) Если и по заголовку пусто — попробуем по частичному совпадению заголовка
        p3 = subprocess.run(
            f'taskkill /fi "WINDOWTITLE ge {nm}" /f',
            shell=True, capture_output=True, text=True,
            encoding='utf-8', errors='replace',
        )
        o3 = (p3.stdout or p3.stderr or '').strip()
        if p3.returncode == 0:
            return f"✅ Закрыто по части заголовка '{nm}': {o3[:200]}"
        return f"❌ Окно/процесс '{nm}' не найдено. /im: {o1[:120]} | /fi: {o2[:120]}"
    except Exception as e:
        return f"❌ Ошибка закрытия: {e}"

def show_desktop() -> str:
    if not pyautogui_available: return "PyAutoGUI не доступен"
    try:
        pyautogui.hotkey('win', 'd')
        return "Рабочий стол"
    except Exception as e: return f"Ошибка: {str(e)}"

from ue_bridge import (
    get_bridge,
    run_with_args,
    LIST_ACTORS_SCRIPT,
    FIND_ACTORS_SCRIPT,
    GET_ACTOR_INFO_SCRIPT,
    SELECT_ACTORS_SCRIPT,
    FOCUS_ACTORS_SCRIPT,
    SET_PROPERTY_SCRIPT,
    GET_SELECTION_SCRIPT,
    COMMON_ACTOR_PROPERTIES,
)
from ue_tools import (
    ue_get_project_context,
    ue_list_assets,
    ue_find_assets,
    ue_list_actor_components,
    ue_get_blueprint_info,
    ue_set_blueprint_property,
    ue_configure_camera,
    ue_compile_blueprint,
    ue_open_asset,
    ue_run_console,
    ue_load_level,
    ue_teleport_actor,
    ue_set_component_property,
    ue_inspect_properties,
    ue_spawn_actor,
    ue_delete_actor,
    ue_duplicate_actor,
    ue_save_level,
    ue_play_in_editor,
    ue_stop_play_in_editor,
    ue_set_actor_label,
    ue_attach_actor,
)

from ue58_core import UE58_API_CHEATSHEET
from ue_script_library import (
    build_index,
    search_library,
    load_snippet,
    get_recipes_manifest,
    UE58_ERROR_CATALOG,
)

async def _ue(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)

def _run_ue_script(script_body: str) -> str:
    return get_bridge().run_and_format(script_body)

# ---------- FREE/PRO: все UE-инструменты защищены licensing.requires_pro ----------
# Windows-функции (focus_window, type_text, press_key, manage_file,
# execute_terminal_command и т.д.) остаются в Free без ограничений.
# Все ue_* инструменты (акторы, Blueprint, камера, execute_unreal_python)
# доступны только при активной подписке Pixie Pro.

@licensing.requires_pro("UE actor tools")
def ue_list_actors(query: str = "", class_filter: str = "", limit: int = 40) -> str:
    return run_with_args(
        LIST_ACTORS_SCRIPT,
        query=query,
        class_filter=class_filter,
        limit=max(1, min(limit, 100)),
    )

# NOTE: ue_list_actors no longer uses LIST_ACTORS_SCRIPT.format().
# All argument injection is done safely via run_with_args()/_py_literal().

@licensing.requires_pro("UE actor tools")
def ue_find_actors(name_part: str = "", label_part: str = "", class_part: str = "") -> str:
    if not any([name_part.strip(), label_part.strip(), class_part.strip()]):
        return "❌ Укажи хотя бы один фильтр: name_part, label_part или class_part."
    return run_with_args(
        FIND_ACTORS_SCRIPT,
        name_part=name_part.strip(),
        label_part=label_part.strip(),
        class_part=class_part.strip(),
    )

@licensing.requires_pro("UE actor tools")
def ue_get_actor_info(identifier: str, properties: str = "") -> str:
    if not identifier.strip():
        return "❌ Укажи имя или label актора."
    prop_list = [p.strip() for p in properties.split(",") if p.strip()] if properties else COMMON_ACTOR_PROPERTIES
    return run_with_args(
        GET_ACTOR_INFO_SCRIPT,
        identifier=identifier.strip(),
        properties=prop_list,
    )

@licensing.requires_pro("UE actor tools")
def ue_select_actors(identifiers: str) -> str:
    ids = [x.strip() for x in identifiers.split(",") if x.strip()]
    if not ids:
        return "❌ Передай имена или labels через запятую."
    return run_with_args(SELECT_ACTORS_SCRIPT, identifiers=ids)

@licensing.requires_pro("UE actor tools")
def ue_focus_actors(identifiers: str) -> str:
    ids = [x.strip() for x in identifiers.split(",") if x.strip()]
    if not ids:
        return "❌ Передай имена или labels через запятую."
    return run_with_args(FOCUS_ACTORS_SCRIPT, identifiers=ids)

@licensing.requires_pro("UE actor tools")
def ue_set_property(identifier: str, property_name: str, value: str, component_class: str = "") -> str:
    if not identifier.strip() or not property_name.strip():
        return "❌ Нужны identifier и property_name."
    return run_with_args(
        SET_PROPERTY_SCRIPT,
        identifier=identifier.strip(),
        property_name=property_name.strip(),
        value=value,
        component_class=component_class.strip(),
    )

@licensing.requires_pro("UE tools")
def ue_get_selection() -> str:
    return _run_ue_script(GET_SELECTION_SCRIPT)

@licensing.requires_pro("execute_unreal_python")
def _sync_execute_unreal(script_code: str) -> str:
    return _run_ue_script(script_code)

async def execute_unreal_python(script_code: str) -> str:
    return await asyncio.to_thread(_sync_execute_unreal, script_code)

async def ue_list_actors_async(query: str = "", class_filter: str = "", limit: int = 40) -> str:
    return await asyncio.to_thread(ue_list_actors, query, class_filter, limit)

async def ue_find_actors_async(name_part: str = "", label_part: str = "", class_part: str = "") -> str:
    return await asyncio.to_thread(ue_find_actors, name_part, label_part, class_part)

async def ue_get_actor_info_async(identifier: str, properties: str = "") -> str:
    return await asyncio.to_thread(ue_get_actor_info, identifier, properties)

async def ue_select_actors_async(identifiers: str) -> str:
    return await asyncio.to_thread(ue_select_actors, identifiers)

async def ue_focus_actors_async(identifiers: str) -> str:
    return await asyncio.to_thread(ue_focus_actors, identifiers)

async def ue_set_property_async(identifier: str, property_name: str, value: str, component_class: str = "") -> str:
    return await asyncio.to_thread(ue_set_property, identifier, property_name, value, component_class)

async def ue_get_selection_async() -> str:
    return await asyncio.to_thread(ue_get_selection)

async def ue_get_project_context_async() -> str:
    return await _ue(ue_get_project_context)

async def ue_list_assets_async(folder_path="/Game", query="", class_filter="", recursive=True, limit=60) -> str:
    return await _ue(ue_list_assets, folder_path, query, class_filter, recursive, limit)

async def ue_find_assets_async(query="", class_filter="", limit=40) -> str:
    return await _ue(ue_find_assets, query, class_filter, limit)

async def ue_list_actor_components_async(identifier: str) -> str:
    return await _ue(ue_list_actor_components, identifier)

async def ue_get_blueprint_info_async(blueprint_path: str, class_properties: str = "") -> str:
    return await _ue(ue_get_blueprint_info, blueprint_path, class_properties)

async def ue_set_blueprint_property_async(blueprint_path, property_name, value, component_name="") -> str:
    return await _ue(ue_set_blueprint_property, blueprint_path, property_name, value, component_name)

async def ue_configure_camera_async(target, mode="custom", apply_to="both", arm_length="", camera_pitch="", camera_yaw="") -> str:
    return await _ue(ue_configure_camera, target, mode, apply_to, arm_length, camera_pitch, camera_yaw)

async def ue_compile_blueprint_async(blueprint_path: str) -> str:
    return await _ue(ue_compile_blueprint, blueprint_path)

async def ue_open_asset_async(asset_path: str) -> str:
    return await _ue(ue_open_asset, asset_path)

async def ue_run_console_async(command: str) -> str:
    return await _ue(ue_run_console, command)

async def ue_load_level_async(level_path: str) -> str:
    return await _ue(ue_load_level, level_path)

async def ue_teleport_actor_async(identifier: str, location: str = "", rotation: str = "") -> str:
    return await _ue(ue_teleport_actor, identifier, location, rotation)

async def ue_set_component_property_async(identifier, property_name, value, component_name="", component_class="") -> str:
    return await _ue(ue_set_component_property, identifier, property_name, value, component_name, component_class)

async def ue_inspect_properties_async(target, properties, component_name="") -> str:
    return await _ue(ue_inspect_properties, target, properties, component_name)

async def ue_spawn_actor_async(class_path: str, location: str = "", rotation: str = "", label: str = "") -> str:
    return await _ue(ue_spawn_actor, class_path, location, rotation, label)

async def ue_delete_actor_async(identifier: str) -> str:
    return await _ue(ue_delete_actor, identifier)

async def ue_duplicate_actor_async(identifier: str, offset: str = "", label: str = "") -> str:
    return await _ue(ue_duplicate_actor, identifier, offset, label)

async def ue_save_level_async(save_all: bool = False) -> str:
    return await _ue(ue_save_level, save_all)

async def ue_play_in_editor_async() -> str:
    return await _ue(ue_play_in_editor)

async def ue_stop_play_in_editor_async() -> str:
    return await _ue(ue_stop_play_in_editor)

async def ue_set_actor_label_async(identifier: str, new_label: str) -> str:
    return await _ue(ue_set_actor_label, identifier, new_label)

async def ue_attach_actor_async(child_identifier: str, parent_identifier: str, socket_name: str = "") -> str:
    return await _ue(ue_attach_actor, child_identifier, parent_identifier, socket_name)


async def ue_library_search_async(query: str, limit: int = 6) -> str:
    return await _ue(search_library, query, limit)

async def ue_library_load_snippet_async(script_id: str, max_chars: int = 3500) -> str:
    return await _ue(load_snippet, script_id, max_chars)

async def ue_library_reindex_async() -> str:
    return await _ue(build_index, True)

def manage_file(action: str, path: str, content: str = "") -> str:
    if not is_path_safe(path): return "Безопасность: доступ к системным папкам запрещён."
    try:
        if action == "write":
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f: f.write(content)
            return f"Записано: {path}"
        elif action == "read":
            if not os.path.exists(path): return "Нет файла."
            with open(path, "r", encoding="utf-8") as f: return f.read()
        elif action == "list":
            if not os.path.exists(path): return "Нет папки."
            return "\n".join(os.listdir(path))
        return "?"
    except Exception as e: return f"Ошибка: {str(e)}"

def execute_terminal_command(command: str) -> str:
    logger.info("Terminal command: %s", command)
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            out, _ = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            logger.info("Process (PID %d) still running after 3s — keeping alive", proc.pid)
            return f"✅ Запущено (PID: {proc.pid})"

        out = (out or "").strip()
        if len(out) > 4000:
            out = out[:4000] + "\n… (вывод обрезан до 4000 символов)"

        msg = f"✅ Код возврата {proc.returncode}:\n{out}" if out else f"✅ Код возврата {proc.returncode} (без вывода)"
        logger.info("Terminal result (rc=%s): %s", proc.returncode, (out or "")[:200])
        return msg
    except Exception as e:
        logger.error("Terminal error: %s", e)
        return f"❌ Ошибка: {str(e)}"

# ---------- TOOLS (ПОЛНЫЕ ОПИСАНИЯ ДЛЯ ПРЕДОТВРАЩЕНИЯ СБОЕВ) ----------
tools_list = [
    types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="focus_window",
            description="Перевести фокус экрана на нужное приложение по части его названия (например: 'блокнот', 'notepad', 'unreal'). ОБЯЗАТЕЛЬНО вызывай перед вводом текста, чтобы переключиться с консоли.",
            parameters=types.Schema(
                type="OBJECT",
                properties={"title_part": types.Schema(type="STRING")},
                required=["title_part"]
            )
        ),
        types.FunctionDeclaration(
            name="type_text",
            description="Мгновенный ввод текста или кодовых команд в текущее активное окно (печать вслепую через буфер).",
            parameters=types.Schema(
                type="OBJECT",
                properties={"text": types.Schema(type="STRING")},
                required=["text"]
            )
        ),
        types.FunctionDeclaration(name="press_key", description="Нажатие клавиш клавиатуры (например, 'win+r', 'enter', 'win+space' — смена языка, '`' — тильда).", parameters=types.Schema(type="OBJECT", properties={"key": types.Schema(type="STRING")}, required=["key"])),
        types.FunctionDeclaration(name="minimize_current_window", description="Свернуть окно"),
                types.FunctionDeclaration(name="close_current_window", description="Закрыть активное переднее окно Windows через taskkill по PID. Определяет окно по GetForegroundWindow, узнаёт PID, убивает процесс. НЕ использует Alt+F4. Безопасно — не даст закрыть консоль самого агента.", parameters=types.Schema(type="OBJECT", properties={})),
        types.FunctionDeclaration(name="close_window_by_name", description="Закрыть окно или процесс ПО ИМЕНИ (exe или части заголовка) через taskkill — НЕ требует фокуса, самый надёжный способ. Например: 'notepad', 'notepad.exe', 'Блокнот', 'chrome'. Закроет все совпадения.", parameters=types.Schema(type="OBJECT", properties={"name": types.Schema(type="STRING", description="Имя .exe (notepad.exe) или часть заголовка окна (Блокнот)")}, required=["name"])),
        types.FunctionDeclaration(name="show_desktop", description="Рабочий стол"),
        types.FunctionDeclaration(
            name="ue_list_actors",
            description="Список акторов текущего уровня UE5. Можно фильтровать по подстроке в имени/label/классе. ВСЕГДА вызывай первым, если не знаешь точное имя объекта.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(type="STRING", description="Подстрока для поиска в name/label/class"),
                    "class_filter": types.Schema(type="STRING", description="Фильтр по классу, например StaticMeshActor"),
                    "limit": types.Schema(type="INTEGER", description="Макс. количество (до 100)"),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="ue_find_actors",
            description="Точный поиск акторов по части имени, label или класса. Возвращает JSON со списком совпадений.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "name_part": types.Schema(type="STRING"),
                    "label_part": types.Schema(type="STRING"),
                    "class_part": types.Schema(type="STRING"),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="ue_get_actor_info",
            description="Получить transform и свойства конкретного актора по имени или label.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "identifier": types.Schema(type="STRING", description="Имя или label актора"),
                    "properties": types.Schema(type="STRING", description="Список свойств через запятую, например: bHidden,Tags"),
                },
                required=["identifier"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_select_actors",
            description="Выделить акторы в Outliner по имени или label (несколько через запятую).",
            parameters=types.Schema(
                type="OBJECT",
                properties={"identifiers": types.Schema(type="STRING")},
                required=["identifiers"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_focus_actors",
            description="Выделить и сфокусировать viewport на акторах (лучше чем press_key 'f').",
            parameters=types.Schema(
                type="OBJECT",
                properties={"identifiers": types.Schema(type="STRING")},
                required=["identifiers"],
            ),
        ),
        types.FunctionDeclaration(
                    name="ue_set_property",
                    description="Изменить свойство актора или его компонента. identifier может быть 'ActorName' или 'ActorName.Camera' (точка = компонент). ЕСЛИ свойство не найдено на акторе — автоматически ищет Camera/SpringArm (auto_routed). value — строка или JSON: число, true/false, [x,y,z] для Vector/Rotator.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "identifier": types.Schema(type="STRING"),
                            "property_name": types.Schema(type="STRING"),
                            "value": types.Schema(type="STRING"),
                            "component_class": types.Schema(type="STRING", description="Опционально: StaticMeshComponent, PointLightComponent и т.д."),
                        },
                        required=["identifier", "property_name", "value"],
                    ),
                ),
        types.FunctionDeclaration(
            name="ue_get_selection",
            description="Показать, какие акторы сейчас выделены в редакторе UE5.",
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
        types.FunctionDeclaration(
            name="ue_get_project_context",
            description="Контекст проекта UE5: имя, карта, пути Content, GameMode, DefaultPawn, выделение. Вызывай в начале UE-задачи.",
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
        types.FunctionDeclaration(
            name="ue_list_assets",
            description="Список ассетов в папке Content Browser (/Game/...). Для поиска Blueprint, материалов, мешей в папках.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "folder_path": types.Schema(type="STRING", description="Папка, напр. /Game/Blueprints"),
                    "query": types.Schema(type="STRING", description="Фильтр по имени"),
                    "class_filter": types.Schema(type="STRING", description="Blueprint, Material, StaticMesh и т.д."),
                    "recursive": types.Schema(type="BOOLEAN"),
                    "limit": types.Schema(type="INTEGER"),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="ue_find_assets",
            description="Глобальный поиск ассетов по всему /Game — когда не знаешь папку. Для UE5.8 class_filter по World может работать нестабильно; при поиске уровней лучше использовать ue_list_assets с folder_path='/Game'.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(type="STRING"),
                    "class_filter": types.Schema(type="STRING"),
                    "limit": types.Schema(type="INTEGER"),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_list_actor_components",
            description="Дерево компонентов актора на уровне: SpringArm, Camera, mesh — с текущими параметрами камеры.",
            parameters=types.Schema(
                type="OBJECT",
                properties={"identifier": types.Schema(type="STRING")},
                required=["identifier"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_get_blueprint_info",
            description="Details Blueprint: компоненты SCS (SpringArm, Camera), Class Defaults. Путь: /Game/.../BP_Name.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "blueprint_path": types.Schema(type="STRING"),
                    "class_properties": types.Schema(type="STRING", description="Свойства CDO через запятую"),
                },
                required=["blueprint_path"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_set_blueprint_property",
            description="Изменить свойство в Blueprint (Details panel): component_name пустой = Class Defaults.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "blueprint_path": types.Schema(type="STRING"),
                    "property_name": types.Schema(type="STRING"),
                    "value": types.Schema(type="STRING"),
                    "component_name": types.Schema(type="STRING", description="Имя компонента в Blueprint, напр. SpringArm или Camera"),
                },
                required=["blueprint_path", "property_name", "value"],
            ),
        ),
        types.FunctionDeclaration(
                    name="ue_configure_camera",
                    description="Переключить камеру first_person/third_person/fix_horizon. Меняет SpringArm TargetArmLength, Camera RelativeRotation pitch и RelativeLocation (для first_person). apply_to: instance|blueprint|both.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "target": types.Schema(type="STRING", description="Имя актора ИЛИ путь Blueprint /Game/..."),
                            "mode": types.Schema(type="STRING", description="first_person | third_person | fix_horizon | custom"),
                            "apply_to": types.Schema(type="STRING", description="instance | blueprint | both"),
                            "arm_length": types.Schema(type="STRING", description="Длина SpringArm, напр. 0 или 350"),
                            "camera_pitch": types.Schema(type="STRING", description="Pitch камеры, 0 = горизонт"),
                            "camera_yaw": types.Schema(type="STRING"),
                        },
                        required=["target"],
                    ),
                ),
        types.FunctionDeclaration(
                    name="ue_set_component_property",
                    description="Изменить свойство КОМПОНЕНТА на акторе уровня по имени/классу компонента. БЕЗОПАСНЕЕ чем ue_set_property для relative_location, relative_rotation, field_of_view, target_arm_length — укажи component_name='Camera' или component_name='SpringArm'.",
                    parameters=types.Schema(
                        type="OBJECT",
                        properties={
                            "identifier": types.Schema(type="STRING"),
                            "property_name": types.Schema(type="STRING"),
                            "value": types.Schema(type="STRING"),
                            "component_name": types.Schema(type="STRING"),
                            "component_class": types.Schema(type="STRING"),
                        },
                        required=["identifier", "property_name", "value"],
                    ),
                ),
        types.FunctionDeclaration(
            name="ue_inspect_properties",
            description="Прочитать конкретные свойства актора, компонента или Blueprint asset.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "target": types.Schema(type="STRING"),
                    "properties": types.Schema(type="STRING", description="TargetArmLength,RelativeRotation,field_of_view,..."),
                    "component_name": types.Schema(type="STRING"),
                },
                required=["target", "properties"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_compile_blueprint",
            description="Скомпилировать и сохранить Blueprint после правок.",
            parameters=types.Schema(
                type="OBJECT",
                properties={"blueprint_path": types.Schema(type="STRING")},
                required=["blueprint_path"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_open_asset",
            description="Открыть ассет/Blueprint в редакторе UE.",
            parameters=types.Schema(
                type="OBJECT",
                properties={"asset_path": types.Schema(type="STRING")},
                required=["asset_path"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_run_console",
            description="Выполнить безопасную консольную команду UE (debug, camera, game). open/changelevel/servertravel/map/travel команды запрещены — для карт и телепорта используй ue_load_level/ue_teleport_actor.",
            parameters=types.Schema(
                type="OBJECT",
                properties={"command": types.Schema(type="STRING")},
                required=["command"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_load_level",
            description="Загрузить уровень/карту UE5.8 по пути /Game/....",
            parameters=types.Schema(
                type="OBJECT",
                properties={"level_path": types.Schema(type="STRING")},
                required=["level_path"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_teleport_actor",
            description="Телепортировать актёра на указанную позицию/вращение в текущем уровне.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "identifier": types.Schema(type="STRING"),
                    "location": types.Schema(type="STRING", description="[x,y,z] или 'x,y,z'"),
                    "rotation": types.Schema(type="STRING", description="[pitch,yaw,roll] или 'pitch,yaw,roll'"),
                },
                required=["identifier"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_spawn_actor",
            description="Создать нового актора на уровне из класса движка (StaticMeshActor, PointLight, CameraActor...) или Blueprint (/Game/...). Используй перед ue_set_property для настройки нового объекта.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "class_path": types.Schema(type="STRING", description="Имя класса движка или путь Blueprint /Game/..."),
                    "location": types.Schema(type="STRING", description="[x,y,z]"),
                    "rotation": types.Schema(type="STRING", description="[pitch,yaw,roll]"),
                    "label": types.Schema(type="STRING", description="Опционально: label для нового актора"),
                },
                required=["class_path"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_delete_actor",
            description="Удалить (destroy) актора с уровня по имени/label.",
            parameters=types.Schema(
                type="OBJECT",
                properties={"identifier": types.Schema(type="STRING")},
                required=["identifier"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_duplicate_actor",
            description="Дублировать существующего актора со смещением (offset [x,y,z], по умолчанию [100,0,0]).",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "identifier": types.Schema(type="STRING"),
                    "offset": types.Schema(type="STRING", description="[x,y,z]"),
                    "label": types.Schema(type="STRING", description="Опционально: label для копии"),
                },
                required=["identifier"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_save_level",
            description="Сохранить текущий уровень (save_all=true — сохранить все изменённые пакеты проекта).",
            parameters=types.Schema(
                type="OBJECT",
                properties={"save_all": types.Schema(type="BOOLEAN")},
            ),
        ),
        types.FunctionDeclaration(
            name="ue_play_in_editor",
            description="Запустить Play In Editor (протестировать игру прямо в редакторе).",
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
        types.FunctionDeclaration(
            name="ue_stop_play_in_editor",
            description="Остановить Play In Editor.",
            parameters=types.Schema(type="OBJECT", properties={}),
        ),
        types.FunctionDeclaration(
            name="ue_set_actor_label",
            description="Переименовать (изменить label в Outliner) актора на уровне.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "identifier": types.Schema(type="STRING"),
                    "new_label": types.Schema(type="STRING"),
                },
                required=["identifier", "new_label"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_attach_actor",
            description="Прикрепить (attach) одного актора к другому, опционально к именованному socket-у.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "child_identifier": types.Schema(type="STRING"),
                    "parent_identifier": types.Schema(type="STRING"),
                    "socket_name": types.Schema(type="STRING"),
                },
                required=["child_identifier", "parent_identifier"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_library_search",

            description="Поиск UE 5.8 Python примеров в локальной библиотеке (recipes + E:\\UE_5.8). Только заголовки — экономит лимиты API. Вызывай перед execute_unreal_python.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "query": types.Schema(type="STRING", description="camera, blueprint, sequencer, asset, subobject..."),
                    "limit": types.Schema(type="INTEGER"),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="ue_library_load_snippet",
            description="Загрузить фрагмент скрипта по id из ue_library_search. max_chars ограничивает размер.",
            parameters=types.Schema(
                type="OBJECT",
                properties={
                    "script_id": types.Schema(type="STRING"),
                    "max_chars": types.Schema(type="INTEGER"),
                },
                required=["script_id"],
            ),
        ),
        types.FunctionDeclaration(name="execute_unreal_python", description="Python в UE 5.8 — только после ue_* или ue_library_search. НЕ используй API 5.1-5.3!", parameters=types.Schema(type="OBJECT", properties={"script_code": types.Schema(type="STRING")}, required=["script_code"])),
        types.FunctionDeclaration(name="manage_file", description="Чтение, запись или список файлов на диске. action: write (создать/перезаписать файл с content), read (прочитать), list (список папки). Для записи кода/python-скриптов, текстовых файлов, конфигов.", parameters=types.Schema(type="OBJECT", properties={"action": types.Schema(type="STRING", description="write | read | list"), "path": types.Schema(type="STRING", description="Полный путь к файлу или папке"), "content": types.Schema(type="STRING", description="Только для write — содержимое файла")}, required=["action", "path"])),
        types.FunctionDeclaration(name="execute_terminal_command", description="Выполнить команду в системном терминале Windows (cmd). Быстрые CLI-команды (dir, echo, git status, python -c) возвращают вывод. Для GUI-приложений (notepad, проводник, браузер) и долгих CLI-задач — запускает и сразу возвращает PID, не блокируя агента (таймаут 3с).", parameters=types.Schema(type="OBJECT", properties={"command": types.Schema(type="STRING", description="Команда для выполнения в cmd.exe (shell). Укажи полный путь, если нужно.")}, required=["command"]))
    ])
]

# ---------- SYSTEM INSTRUCTION (English, name/language/personality/project from config.json) ----------
def _build_system_instruction() -> str:
    from presets import DEFAULT_PERSONALITY, DEFAULT_PROJECT_TYPE, PERSONALITY_PRESETS, PROJECT_TYPES, UI_LANGUAGES as _UI_LANGUAGES_BUILD

    name = ASSISTANT_NAME
    personality_key = APP_CONFIG.get("personality", DEFAULT_PERSONALITY)
    personality_prompt = PERSONALITY_PRESETS.get(
        personality_key, PERSONALITY_PRESETS[DEFAULT_PERSONALITY]
    )["prompt"]
    project_key = APP_CONFIG.get("project_type", DEFAULT_PROJECT_TYPE)
    project_prompt = PROJECT_TYPES.get(project_key, PROJECT_TYPES[DEFAULT_PROJECT_TYPE])["prompt"]

    # === ИСПРАВЛЕНИЕ: читаем язык напрямую из APP_CONFIG (который перезагружен
    # после дашборда/настроек), а не из модульных глобалов APP_LANGUAGE_CODE/LABEL,
    # которые были установлены ДО того, как пользователь мог изменить язык в Settings.
    _lang_key = APP_CONFIG.get("language", "en")
    _lang_info = _UI_LANGUAGES_BUILD.get(_lang_key, _UI_LANGUAGES_BUILD["en"])
    _lang_code = _lang_info.get("code", "en-US")
    _lang_label = _lang_info.get("label", "English")

    return (
        f"You are {name} — an AI dev-buddy assistant for Windows and Unreal Engine 5. "
        f"Your personality/style: {personality_prompt}.\n"
        f"{project_prompt}\n"
        f"🗣️ SPOKEN LANGUAGE: Always speak and respond ONLY in {_lang_label} ({_lang_code}), "
        f"regardless of the language used internally in this prompt. This is the user's chosen language — "
        f"never switch to another language unless the user explicitly asks you to.\n"

        "You have no physical mouse — you control the Windows interface via keyboard actions and code inside the engine.\n"
        "\n"
        f"ACTIVATION: You react and respond only when addressed by your name '{name}'.\n"
        "\n"

        "🖥️ FULL PC CONTROL (unrestricted Windows assistant):\n"
        "You are a full-featured voice assistant for Windows. You can perform ANY action on the PC:\n"
        "- File operations via `manage_file` (create/read/list files and folders).\n"
        "- Terminal commands via `execute_terminal_command` (cmd.exe): fast CLI (dir, echo, git status) return output; GUI apps (notepad) launch without blocking.\n"
        "- Key presses via `press_key` (Win+R for Run, enter, 'win+space' — switch language, f, Ctrl+Shift+Esc, Alt+Tab, Win+D, Win+E — any combination).\n"
        "- Text input via `type_text` (paste into the active window via clipboard — works blind, trust the tool's response).\n"
        "- Window switching via `focus_window` (find a window by part of its title and bring it to focus).\n"
        "- Window management: `minimize_current_window` (minimize), `close_current_window` (close the active window via taskkill), `show_desktop` (Win+D — show desktop).\n"
        "- CLOSING windows: `close_current_window` closes the foreground window (by PID via taskkill). To close a specific app by name, use `close_window_by_name('notepad')`, `close_window_by_name('chrome')`. This works without focus, via taskkill /im or /fi WINDOWTITLE.\n"
        "Access to Windows system folders (Windows, System32, Program Files, Boot, Recovery) is FORBIDDEN — enforced by code, do not attempt to bypass it.\n"
        "Your tools are your interface to the PC. Combine them to solve any task.\n"
        "\n"
        "🚨 TOP PRIORITY RULES:\n"
        "1. WITHIN A SINGLE COMMAND, NEVER REPEAT THE SAME ACTION TWICE.\n"
        "   If an action has already been performed and its result shows no error in the console, do not repeat it.\n"
        "   Do not loop the same step 'just to check' — this breaks stability and creates redundant repeats.\n"
        "2. IF AN ACTION RESULTS IN AN ERROR, YOU MUST NOT REPEAT THAT EXACT ACTION AGAIN.\n"
        "   An error is a signal that the step is already confirmed invalid in the current context.\n"
        "   Further attempts to repeat the same step without changing the approach are forbidden.\n"
        "3. THE VIDEO STREAM IS NOT PROOF THAT A TASK WAS COMPLETED.\n"
        "   Due to latency it may show an outdated state, not the current one.\n"
        "   Do not rely on video as confirmation of a successful action.\n"
        "4. THE ONLY CRITERION FOR TASK COMPLETION IS THE ABSENCE OF AN ERROR IN YOUR CONSOLE.\n"
        "   If there's no error in the console after an action, consider the task done.\n"
        "   Do not use the visual stream, screenshots, assumptions, or 'it looks like' as grounds for a final status.\n"
        "\n"
        "🚨 WINDOW FOCUS RULE:\n"
        "Do not force a `focus_window` call before every single operation.\n"
        "When you open the target application, assume it already has normal focus at the moment it opens.\n"
        "Do not wait 5 seconds to 'see' the exact window title or focus confirmation via the video stream.\n"
        "Explicit focus switching is only needed in specific cases via precise hotkeys for a clear purpose: e.g. file search in Explorer, text search in a document, or navigation inside an already open window.\n"
        "If opening a window and typing text should happen in the same app, work directly from the already-open context — without unnecessary pre-focusing.\n"
        "\n"
        "🚨 STRICT RULE FOR FPS AND TEXT INPUT:\n"
        "Your video 'sight' frame rate is critically low (0.2 FPS — one frame every 5 seconds!). The screen picture lags badly.\n"
        "When you call `type_text` or `press_key`, the action happens INSTANTLY in the OS, but you will only see the change on video 5-10 seconds later.\n"
        "TYPE BLIND! Trust the text responses from the tools. Call `type_text` once — and immediately move on with the task. Never try to erase (ctrl+a -> backspace) or retype the same text again. Forget manual copy-paste debugging via ctrl+c/ctrl+v — everything works automatically.\n"
        "\n"
        "⌨️ LANGUAGE SWITCHING:\n"
        "To switch the keyboard layout between languages, always use `press_key` with the combo 'win+space' (or '`' — backtick, if win+space doesn't work).\n"
        "\n"
        "🎬 UNREAL ENGINE 5 — FULL CONTROL (carte blanche):\n"
        "You control UE5 via Python Remote Execution. Don't guess — always fetch data with tools first.\n"
        "CRITICAL RULE: your built-in knowledge about UE and Unreal is NOT a source of truth.\n"
        "For any UE task, the only source of truth is the `ue_*` tools and library snippets from `ue_library_search` / `ue_library_load_snippet`.\n"
        "Never write Python code from memory if you're not sure about the syntax or API call.\n"
        "MEMORY IS ALLOWED ONLY AS AN EMERGENCY FALLBACK WITHIN THIS SPECIFIC UE CONTEXT: only if `ue_*` calls fail, return an empty/incomplete result, or the library lacks the needed instructions.\n"
        f"In all other cases, {name} does NOT act from memory. Don't invent actor names, asset paths, components, coordinates, transforms or camera behavior without confirmation from `ue_*`.\n"
        "If a search by one name yields no result, don't claim the object doesn't exist and don't ask the user to search themselves.\n"
        "Keep searching more broadly via `ue_list_actors`, `ue_find_actors`, `ue_list_assets`, `ue_find_assets`, `ue_list_actor_components`, then move on to modification.\n"
        "Verify with tools first, then act, and only then report the final result.\n"
        "\n"
        "STARTING ANY UE TASK:\n"
        "1. `ue_get_project_context` — map, project, DefaultPawn.\n"
        "2. Looking for a file in Content → `ue_find_assets` or `ue_list_assets` with folder_path.\n"
        "3. Looking for an object on the level → `ue_list_actors` / `ue_find_actors`.\n"
        "4. If you can't find the object by one name, do NOT suggest the user search themselves.\n"
        "   Keep searching via `ue_find_assets`, `ue_list_assets`, `ue_list_actors`, `ue_find_actors`, `ue_list_actor_components`, and if needed `ue_library_search` for the right syntax.\n"
        "   Only report a result based on an actual search, not a guess.\n"
        "\n"
        "ACTORS ON THE LEVEL:\n"
        "- Components and camera → `ue_list_actor_components` (shows SpringArm target_arm_length, Camera relative_rotation).\n"
        "- BEFORE editing a component property (relative_location, relative_rotation, target_arm_length, field_of_view, etc.) — ALWAYS call `ue_list_actor_components` first to learn exact names and current values.\n"
        "- IMPORTANT: BP_SideScrollingCharacter has NO SpringArmComponent! The Camera attaches directly to the root.\n"
        "- Editing a component → `ue_set_component_property` (specify component_name='Camera').\n"
        "- Actor transform → `ue_set_property` with RelativeLocation (this moves the root component, WARNING: this moves the character, not the camera).\n"
        "- For relative_location, relative_rotation, field_of_view, target_arm_length — `ue_set_property` will AUTO-ROUTE to the appropriate component (Camera/SpringArm), but it's safer to use `ue_set_component_property` with component_name explicitly.\n"
        "\n"
        "BLUEPRINT / DETAILS PANEL:\n"
        "- Open and inspect → `ue_get_blueprint_info` (path /Game/.../BP_Name).\n"
        "- Edit a component property in a BP → `ue_set_blueprint_property` with component_name (SpringArm, Camera, ...).\n"
        "- Class Defaults → `ue_set_blueprint_property` without component_name.\n"
        "- After edits → `ue_compile_blueprint`. Open in editor → `ue_open_asset`.\n"
        "- Read properties → `ue_inspect_properties`.\n"
        "\n"
        "CAMERA (first person / third person / horizon):\n"
        "NEVER try to configure the camera blindly via press_key!\n"
        "Algorithm:\n"
        "1. `ue_list_actor_components` on the character OR `ue_get_blueprint_info` on the character's BP.\n"
        "2. `ue_configure_camera` with mode:\n"
        "   - first_person → SpringArm TargetArmLength=0, Camera RelativeLocation=[0,0,70] (head), RelativeRotation pitch=0\n"
        "   - third_person → TargetArmLength=350\n"
        "   - fix_horizon → Camera RelativeRotation pitch=0\n"
        "3. apply_to='both' to change both the level instance and the Blueprint (persistently).\n"
        "4. Verify the result via `ue_list_actor_components` or `ue_inspect_properties`.\n"
        "\n"
        "⚠️ BOUNDARIES OF WHAT PYTHON REMOTE EXECUTION CAN DO IN UE:\n"
        "Python Remote Execution in UE5.8 works great for: reading/writing properties (Details panel), Class Defaults, "
        "transforms, components, finding/spawning actors and assets, compiling Blueprints.\n"
        "BUT Python CANNOT create Event Graph Blueprint logic (Tick nodes, Event BeginPlay, Branch, graph node math, etc.) — "
        "this is an engine limitation, not a tooling one. Even if you find a CharacterMovementComponent and its Velocity via "
        "ue_inspect_properties/CDO — that will be ONE static value at read time, not a live link like 'walk speed → camera "
        "sway every frame'. Also, you often CANNOT reach CharacterMovementComponent on a Blueprint CDO directly via "
        "get_editor_property by variable name — search for it first via the component-based ue_* tools "
        "(ue_list_actor_components / ue_get_blueprint_info), not via raw Python code from memory.\n"
        "IF the user asks for something that depends on per-frame events/input (camera sway from speed, custom animations, "
        "custom movement mechanics, collision-based damage generation, etc.) — HONESTLY AND IMMEDIATELY explain that this "
        "must be done via the Blueprint's own Event Graph (Tick/Event Graph nodes), and Python can only read/change static "
        "properties. Don't try to fake it with endless repeated execute_unreal_python calls — instead offer a step-by-step "
        "node instruction (which nodes to add, what to connect them to) so the user can do it by hand, or suggest an "
        "alternative via the static tools available to you (e.g. fix a specific camera offset if dynamic sway isn't required).\n"
        "\n"
        "Asset paths always start with /Game/. Example: /Game/ThirdPerson/Blueprints/BP_ThirdPersonCharacter.\n"
        "Read the JSON responses from tools carefully — they contain exact names, paths and before/after values.\n"
        "`execute_unreal_python` — only after ue_* or ue_library_search/load_snippet.\n"
        "NEVER use UE 5.1–5.3 API (EditorLevelLibrary, EditorActorSubsystem.get_editor_world).\n"
        "\n"
        "SCRIPT LIBRARY (saving Gemini quota):\n"
        "1. Don't know the 5.8 syntax → `ue_library_search` (query: camera, blueprint, asset...).\n"
        "2. Found the right file → `ue_library_load_snippet` (only the fragment, not the whole engine!).\n"
        "3. Ready-made tasks → use ue_* tools first, they're already 5.8-compatible.\n"
        "4. When in doubt, always prefer the library and `ue_*` tools over your own memories of the UE API.\n"
        "5. If `ue_*` doesn't give an exact answer, keep searching and reading the real tool context instead of giving a 'pseudo-answer' from memory.\n"
        "\n"
        f"{UE58_ERROR_CATALOG}\n"
        f"{UE58_API_CHEATSHEET}"
    )


SYSTEM_INSTRUCTION = _build_system_instruction()

# ---------- ПОТОКИ ----------
async def audio_input_loop(session, p_audio, stop_event):
    input_stream = p_audio.open(format=FORMAT, channels=CHANNELS, rate=INPUT_RATE, input=True, frames_per_buffer=INPUT_CHUNK)
    try:
        while not stop_event.is_set():
            try:
                data = await asyncio.to_thread(input_stream.read, INPUT_CHUNK, False)
                downsampled_data = b''.join([data[i:i+2] for i in range(0, len(data), 6)])
                await session.send_realtime_input(audio=types.Blob(data=downsampled_data, mime_type="audio/pcm;rate=16000"))
            except:
                if not stop_event.is_set(): await asyncio.sleep(0.1)
    except asyncio.CancelledError: pass
    finally: input_stream.close()

async def video_input_loop(session, stop_event):
    try:
        with mss.MSS() as sct:
            monitor = sct.monitors[1]
            while not stop_event.is_set():
                try:
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    img.thumbnail((VIDEO_WIDTH, VIDEO_HEIGHT), Image.LANCZOS)
                    img_byte_arr = io.BytesIO()
                    img.save(img_byte_arr, format='JPEG', quality=JPEG_QUALITY)
                    await session.send_realtime_input(video=types.Blob(data=img_byte_arr.getvalue(), mime_type="image/jpeg"))
                except: pass
                await asyncio.sleep(1.0 / STREAM_FPS)
    except asyncio.CancelledError: pass

async def audio_playback_worker(queue, output_stream, stop_event):
    try:
        while not stop_event.is_set():
            try:
                data = await asyncio.wait_for(queue.get(), timeout=0.5)
                upsampled_data = b''.join([data[i:i+2] * 2 for i in range(0, len(data), 2)])
                await asyncio.to_thread(output_stream.write, upsampled_data)
                queue.task_done()
            except asyncio.TimeoutError: continue
    except asyncio.CancelledError: pass

async def audio_output_and_logic_loop(session, p_audio, audio_queue, stop_event, session_state):
    """
    session_state — общий dict с main(), через который сообщаем наружу:
      - session_state["handle"]: последний session_resumption handle (для быстрого reconnect)
      - session_state["reconnect"]: True, если нужно переподключиться (GoAway или ошибка)
      - session_state["reason"]: "go_away" | "error" | None

    ИСПРАВЛЕНИЕ (freeze ~1.5 мин каждые ~10 мин):
    Gemini Live API периодически присылает `go_away` ПЕРЕД тем, как форсированно
    закрыть соединение (у сессии есть максимальная длительность). Раньше этот сигнал
    вообще не обрабатывался: агент "молчал" до тех пор, пока сервер не разрывал сокет
    сам, что и создавало ощутимое зависание. Теперь мы реагируем на go_away сразу и
    сами инициируем быстрое переподключение, используя session_resumption handle —
    это не требует пересборки индекса библиотеки/GDD/контекста UE и происходит за
    секунды, а не полноценный перезапуск процесса.
    """
    output_stream = p_audio.open(format=FORMAT, channels=CHANNELS, rate=OUTPUT_RATE, output=True, frames_per_buffer=OUTPUT_CHUNK)
    playback_task = asyncio.create_task(audio_playback_worker(audio_queue, output_stream, stop_event))
    
    try:
        while not stop_event.is_set():
            try:
                async for response in session.receive():
                    if stop_event.is_set(): break

                    # --- Сохраняем handle для быстрого возобновления сессии ---
                    if getattr(response, "session_resumption_update", None):
                        update = response.session_resumption_update
                        if update.resumable and update.new_handle:
                            session_state["handle"] = update.new_handle
                            logger.debug("Session resumption handle обновлён")

                    # --- Сервер предупреждает о скором закрытии сессии ---
                    if getattr(response, "go_away", None):
                        time_left = getattr(response.go_away, "time_left", None)
                        logger.warning("Получен GoAway от Live API (time_left=%s) — упреждающий reconnect", time_left)
                        print(f"\n[Система]: Сессия скоро истечёт ({time_left}) — переподключаюсь без потери контекста...")
                        session_state["reconnect"] = True
                        session_state["reason"] = "go_away"
                        stop_event.set()
                        break

                    if response.server_content and response.server_content.model_turn:
                        for part in response.server_content.model_turn.parts:
                            if hasattr(part, 'text') and part.text:
                                print(f"\n[Пикси]: {part.text}")
                            if part.inline_data and part.inline_data.data:
                                audio_queue.put_nowait(part.inline_data.data)
                    
                    if response.tool_call:
                        for call in response.tool_call.function_calls:
                            logger.info("Tool call received: %s args=%s", call.name, call.args)
                            print(f"\n[Инструмент]: {call.name}")
                            result = "?"
                            if call.name == "focus_window":
                                result = focus_window(
                                    call.args.get("title_part", call.args.get("window_class", ""))
                                )
                            elif call.name == "type_text": result = type_text(call.args["text"])
                            elif call.name == "press_key": result = press_key(call.args["key"])
                            elif call.name == "minimize_current_window": result = minimize_current_window()
                            elif call.name == "close_current_window": result = close_current_window()
                            elif call.name == "close_window_by_name": result = close_window_by_name(call.args.get("name", ""))
                            elif call.name == "show_desktop": result = show_desktop()
                            elif call.name == "ue_list_actors":
                                result = await ue_list_actors_async(
                                    call.args.get("query", ""),
                                    call.args.get("class_filter", ""),
                                    call.args.get("limit", 40),
                                )
                            elif call.name == "ue_find_actors":
                                result = await ue_find_actors_async(
                                    call.args.get("name_part", ""),
                                    call.args.get("label_part", ""),
                                    call.args.get("class_part", ""),
                                )
                            elif call.name == "ue_get_actor_info":
                                result = await ue_get_actor_info_async(
                                    call.args["identifier"],
                                    call.args.get("properties", ""),
                                )
                            elif call.name == "ue_select_actors":
                                result = await ue_select_actors_async(call.args["identifiers"])
                            elif call.name == "ue_focus_actors":
                                result = await ue_focus_actors_async(call.args["identifiers"])
                            elif call.name == "ue_set_property":
                                result = await ue_set_property_async(
                                    call.args["identifier"],
                                    call.args["property_name"],
                                    call.args["value"],
                                    call.args.get("component_class", ""),
                                )
                            elif call.name == "ue_get_selection":
                                result = await ue_get_selection_async()
                            elif call.name == "ue_get_project_context":
                                result = await ue_get_project_context_async()
                            elif call.name == "ue_list_assets":
                                result = await ue_list_assets_async(
                                    call.args.get("folder_path", "/Game"),
                                    call.args.get("query", ""),
                                    call.args.get("class_filter", ""),
                                    call.args.get("recursive", True),
                                    call.args.get("limit", 60),
                                )
                            elif call.name == "ue_find_assets":
                                result = await ue_find_assets_async(
                                    call.args["query"],
                                    call.args.get("class_filter", ""),
                                    call.args.get("limit", 40),
                                )
                            elif call.name == "ue_list_actor_components":
                                result = await ue_list_actor_components_async(call.args["identifier"])
                            elif call.name == "ue_get_blueprint_info":
                                result = await ue_get_blueprint_info_async(
                                    call.args["blueprint_path"],
                                    call.args.get("class_properties", ""),
                                )
                            elif call.name == "ue_set_blueprint_property":
                                result = await ue_set_blueprint_property_async(
                                    call.args["blueprint_path"],
                                    call.args["property_name"],
                                    call.args["value"],
                                    call.args.get("component_name", ""),
                                )
                            elif call.name == "ue_configure_camera":
                                result = await ue_configure_camera_async(
                                    call.args["target"],
                                    call.args.get("mode", "custom"),
                                    call.args.get("apply_to", "both"),
                                    call.args.get("arm_length", ""),
                                    call.args.get("camera_pitch", ""),
                                    call.args.get("camera_yaw", ""),
                                )
                            elif call.name == "ue_set_component_property":
                                result = await ue_set_component_property_async(
                                    call.args["identifier"],
                                    call.args["property_name"],
                                    call.args["value"],
                                    call.args.get("component_name", ""),
                                    call.args.get("component_class", ""),
                                )
                            elif call.name == "ue_inspect_properties":
                                result = await ue_inspect_properties_async(
                                    call.args["target"],
                                    call.args["properties"],
                                    call.args.get("component_name", ""),
                                )
                            elif call.name == "ue_compile_blueprint":
                                result = await ue_compile_blueprint_async(call.args["blueprint_path"])
                            elif call.name == "ue_open_asset":
                                result = await ue_open_asset_async(call.args["asset_path"])
                            elif call.name == "ue_load_level":
                                logger.debug("Calling ue_load_level with args: %s", call.args)
                                result = await ue_load_level_async(call.args["level_path"])
                            elif call.name == "ue_teleport_actor":
                                logger.debug("Calling ue_teleport_actor with args: %s", call.args)
                                result = await ue_teleport_actor_async(
                                    call.args["identifier"],
                                    call.args.get("location", ""),
                                    call.args.get("rotation", ""),
                                )
                            elif call.name == "ue_run_console":
                                result = await ue_run_console_async(call.args["command"])
                            elif call.name == "ue_spawn_actor":
                                result = await ue_spawn_actor_async(
                                    call.args["class_path"],
                                    call.args.get("location", ""),
                                    call.args.get("rotation", ""),
                                    call.args.get("label", ""),
                                )
                            elif call.name == "ue_delete_actor":
                                result = await ue_delete_actor_async(call.args["identifier"])
                            elif call.name == "ue_duplicate_actor":
                                result = await ue_duplicate_actor_async(
                                    call.args["identifier"],
                                    call.args.get("offset", ""),
                                    call.args.get("label", ""),
                                )
                            elif call.name == "ue_save_level":
                                result = await ue_save_level_async(call.args.get("save_all", False))
                            elif call.name == "ue_play_in_editor":
                                result = await ue_play_in_editor_async()
                            elif call.name == "ue_stop_play_in_editor":
                                result = await ue_stop_play_in_editor_async()
                            elif call.name == "ue_set_actor_label":
                                result = await ue_set_actor_label_async(
                                    call.args["identifier"],
                                    call.args["new_label"],
                                )
                            elif call.name == "ue_attach_actor":
                                result = await ue_attach_actor_async(
                                    call.args["child_identifier"],
                                    call.args["parent_identifier"],
                                    call.args.get("socket_name", ""),
                                )

                            elif call.name == "ue_library_search":
                                result = await ue_library_search_async(
                                    call.args["query"],
                                    call.args.get("limit", 6),
                                )
                            elif call.name == "ue_library_load_snippet":
                                result = await ue_library_load_snippet_async(
                                    call.args["script_id"],
                                    call.args.get("max_chars", 3500),
                                )
                            elif call.name == "execute_unreal_python": result = await execute_unreal_python(call.args["script_code"])
                            elif call.name == "manage_file": result = manage_file(call.args["action"], call.args["path"], call.args.get("content", ""))
                            elif call.name == "execute_terminal_command": result = execute_terminal_command(call.args["command"])
                            else: result = f"Неизвестный инструмент: {call.name}"
                            print(f"[Результат]: {result}\n")
                            logger.info("Tool %s result: %s", call.name, result)
                            
                            try:
                                function_response = types.Part.from_function_response(name=call.name, response={"output": result})
                                await session.send_client_content(turns=[types.Content(role="user", parts=[function_response])])
                            except Exception as e:
                                print(f"[Ошибка отправки ответа инструменту]: {e}")
                
                if not stop_event.is_set(): await asyncio.sleep(0.1)
            except Exception as e:
                if not stop_event.is_set():
                    logger.error("Critical session error: %s", e)
                    logger.error(traceback.format_exc())
                    print(f"\n[Критическая ошибка сессии Live API]: {e}")
                    print("[Система]: Переподключаюсь...")
                    session_state["reconnect"] = True
                    session_state["reason"] = "error"
                    stop_event.set()
                    break
    except asyncio.CancelledError: pass
    finally:
        stop_event.set()
        playback_task.cancel()
        output_stream.close()

async def main():
    if not os.environ.get("GEMINI_API_KEY"):
        msg = (
            "API-ключ Gemini не найден.\n\n"
            "Задайте GEMINI_API_KEY одним из способов:\n"
            "  • в переменной окружения GEMINI_API_KEY;\n"
            "  • в config.json (поле \"gemini_api_key\") рядом с Pixie.exe;\n"
            "  • в файле .env рядом с Pixie.exe (см. .env.example)."
        )
        print(f"Ошибка: {msg}")
        try:
            ctypes.windll.user32.MessageBoxW(0, msg, "Pixie — не найден API-ключ", 0x30)  # MB_ICONWARNING
        except Exception:
            pass
        sys.exit(1)


    print("="*50)
    print(f"{ASSISTANT_NAME} – UE 5.8 Full Control [Blueprint + Camera + Content]")
    print("="*50)

    minimize_our_console()
    client = genai.Client()
    p_audio = pyaudio.PyAudio()
    model_id = "gemini-3.1-flash-live-preview"

    gdd_text_content = ""
    gdd_candidates = [APP_CONFIG.get("gdd_path", "./gdd.pdf"), "Document (1).pdf", "gdd.pdf", "gdd.txt"]
    for file_name in gdd_candidates:
        if file_name and os.path.exists(file_name):
            try:
                if file_name.endswith(".pdf"):
                    gdd_text_content = "".join([page.extract_text() for page in PdfReader(file_name).pages])
                else:
                    with open(file_name, "r", encoding="utf-8") as f: gdd_text_content = f.read()
                break
            except: pass

    dynamic_instruction = SYSTEM_INSTRUCTION
    recipes_manifest = get_recipes_manifest()
    if recipes_manifest:
        dynamic_instruction += f"\n\n--- {recipes_manifest}"

    print("\n[Система]: Индексация библиотеки UE Python...")
    try:
        idx_msg = await asyncio.to_thread(build_index)
        print(f"[Система]: {idx_msg}")
    except Exception as exc:
        print(f"[Система]: Индекс библиотеки пропущен: {exc}")

    if gdd_text_content:
        dynamic_instruction += f"\n\n--- GAME DESIGN DOCUMENT ---\n{gdd_text_content}"

    print("\n[Система]: Загрузка контекста Unreal Engine...")
    try:
        ue_ctx = await asyncio.to_thread(ue_get_project_context)
        if ue_ctx and not ue_ctx.startswith("❌"):
            dynamic_instruction += f"\n\n--- КОНТЕКСТ UE ПРИ СТАРТЕ ---\n{ue_ctx}"
            print("[Система]: Контекст UE загружен.")
            # ---------- Version-guard ----------
            # Pixie протестирована и поддерживается только на UE 5.8.x.
            # Если у пользователя другая версия движка — часть UE-инструментов
            # может работать некорректно (сигнатуры API меняются между версиями).
            # Явно предупреждаем вместо тихой поломки сцены/Blueprint.
            try:
                import re as _re
                m = _re.search(r'"engine_version"\s*:\s*"([^"]+)"', ue_ctx)
                detected_version = m.group(1) if m else ""
                if detected_version and not detected_version.startswith("5.8"):
                    print(
                        f"[Система]: ⚠️ Обнаружен Unreal Engine {detected_version}. "
                        "Pixie Pro протестирован только на UE 5.8 — часть UE-инструментов "
                        "может работать некорректно на других версиях движка."
                    )
            except Exception:
                pass
        else:
            print("[Система]: UE не подключён — контекст будет получен позже через ue_get_project_context.")
    except Exception as exc:
        print(f"[Система]: Не удалось загрузить контекст UE: {exc}")


    if APP_CONFIG.get("license_auto_check", True):
        pro_status = licensing.get_license_status()
        print(f"[Система]: Pixie Pro: {'активен ✅' if pro_status.valid else 'не активен (' + pro_status.reason + ')'}")

    # ---------- ЦИКЛ ПЕРЕПОДКЛЮЧЕНИЙ БЕЗ ПЕРЕЗАПУСКА ПРОЦЕССА ----------
    # ИСПРАВЛЕНИЕ: раньше main() подключался к Live API ОДИН раз, и при любом сбое/GoAway
    # (что происходит каждые ~10 минут — у сессии есть максимальная длительность)
    # процесс завершался через sys.exit(0), и агента поднимал только внешний .bat-цикл.
    # Это означало полный передозапуск python (заново парсили GDD PDF, переиндексировали
    # библиотеку UE-скриптов, заново тянули контекст UE) — отсюда и заметное "зависание".
    # Теперь переподключение происходит ВНУТРИ процесса с сохранённым session_resumption
    # handle — быстро и без потери индекса/контекста. Процесс завершается только при
    # серии настоящих ошибок соединения (не при штатных GoAway).
    resumption_handle = None
    consecutive_errors = 0
    first_connect = True

    try:
        while True:
            live_config = types.LiveConnectConfig(
                response_modalities=["AUDIO"],
                system_instruction=types.Content(parts=[types.Part.from_text(text=dynamic_instruction)]),
                tools=tools_list,
                speech_config=types.SpeechConfig(
                    language_code=APP_LANGUAGE_CODE,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE_NAME)
                    ),
                ),

                session_resumption=types.SessionResumptionConfig(handle=resumption_handle),
            )

            session_state = {"handle": resumption_handle, "reconnect": False, "reason": None}

            try:
                async with client.aio.live.connect(model=model_id, config=live_config) as session:
                    stop_event = asyncio.Event()
                    audio_queue = asyncio.Queue()
                    if first_connect:
                        print("\n[Система]: Пикси успешно подключена. Окно свернуто.")
                        first_connect = False
                    else:
                        print("\n[Система]: Пикси переподключена (контекст и библиотека сохранены).")
                    await asyncio.gather(
                        audio_input_loop(session, p_audio, stop_event),
                        video_input_loop(session, stop_event),
                        audio_output_and_logic_loop(session, p_audio, audio_queue, stop_event, session_state),
                    )
            except Exception as e:
                error_str = str(e)
                logger.error("Connection error: %s", error_str)
                logger.error(traceback.format_exc())
                print(f"[Ошибка подключения сессии]: {error_str}")
                session_state["reconnect"] = True
                session_state["reason"] = session_state.get("reason") or "error"

                # === ИСПРАВЛЕНИЕ: Ошибка геолокации 1007 / отсутствие сети ===
                # При ошибке "User location is not supported" (1007) или любой
                # сетевой ошибке показываем пользователю явное MessageBox-предупреждение
                # вместо молчаливого сворачивания в бесконечный reconnect-цикл.
                if any(phrase in error_str.lower() for phrase in [
                    "1007", "user location", "location is not supported", "geoblock",
                    "vpn", "blocked", "not supported for the api use",
                    "connection refused", "no route to host", "connection reset",
                    "timeout", "timed out", "name or service not known",
                    "temporary failure in name resolution",
                    "getaddrinfo failed", "[errno -2]", "[errno -3]",
                    "not supported for the api use",
                ]):
                    geo_msg = (
                        "Pixie не может подключиться к Gemini Live API.\n\n"
                        "Возможные причины:\n"
                        "  • Геоблокировка — включите VPN\n"
                        "  • Отсутствует подключение к интернету\n"
                        "  • Блокировка портов корпоративным/антивирусным ПО\n"
                        "  • Неверный DNS (попробуйте 8.8.8.8 / 1.1.1.1)\n\n"
                        "Проверьте соединение, включите VPN и нажмите OK."
                    )
                    try:
                        ctypes.windll.user32.MessageBoxW(
                            0, geo_msg, "Pixie — ошибка подключения (1007)", 0x30  # MB_ICONWARNING
                        )
                    except Exception:
                        pass
                    print(f"\n[Система]: {geo_msg}")

            resumption_handle = session_state.get("handle") or resumption_handle

            if session_state.get("reason") == "error":
                consecutive_errors += 1
            else:
                consecutive_errors = 0

            if not session_state.get("reconnect"):
                print("[Система]: Сессия завершена штатно — выхожу.")
                break

            if consecutive_errors > MAX_CONSECUTIVE_CONNECTION_ERRORS:
                print(
                    f"[Система]: {consecutive_errors} ошибок соединения подряд — "
                    "завершаю процесс для полного перезапуска (пусть поднимет .bat)."
                )
                break

            # === ИСПРАВЛЕНИЕ: Пауза перед переподключением ===
            # При ошибках сети/геоблокировки необходимо дать время VPN-туннелю
            # или DNS-серверу на восстановление. Без паузы reconnect уходит в
            # бесконечный цикл с миллисекундными попытками, что нагружает процессор
            # и не даёт сети стабилизироваться.
            if session_state.get("reason") == "error":
                logger.info("Пауза 3 секунды перед переподключением (ошибка соединения)")
                await asyncio.sleep(3.0)
            else:
                await asyncio.sleep(0.2)
    finally:
        p_audio.terminate()
        sys.exit(0)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except SystemExit:
        raise
    except BaseException as _main_exc:
        # ВАЖНО: собранный .exe запускается с --windowed (без консоли), поэтому
        # необработанное исключение внутри main() (например, pyaudio не нашёл
        # микрофон/динамики, ошибка сети при первом connect и т.п.) раньше приводило
        # к ПОЛНОСТЬЮ МОЛЧАЛИВОМУ падению процесса: окно дашборда закрывалось,
        # а никакого нового окна/сообщения не появлялось — пользователю казалось,
        # что кнопка "Start" вообще ничего не делает. Показываем явную ошибку.
        _fatal_startup_error(_main_exc)


