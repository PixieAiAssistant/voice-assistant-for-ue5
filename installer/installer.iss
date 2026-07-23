; installer.iss — Inno Setup script for Pixie Assistant
;
; Собирает установщик Windows для Pixie:
;   - копирует ВСЮ папку dist\Pixie (собранную PyInstaller в режиме --onedir:
;     Pixie.exe + все DLL/зависимости рядом — это НАМЕРЕННО отличается от
;     Nuitka/PyInstaller --onefile: единый самораспаковывающийся exe гораздо
;     чаще ложно детектится антивирусами/SmartScreen как троян, а обычная
;     папка с обычным exe — почти никогда)
;   - копирует папку ue58_recipes (Pro-контент, доступ блокируется в коде
;     через licensing.is_pro_active(), поэтому копировать безопасно всегда)
;   - регистрирует протокол pixie:// (для авто-применения лицензионного ключа
;     из письма, см. licensing.try_apply_from_argv + main.py)
;   - создаёт ярлыки на рабочем столе и в меню "Пуск"
;   - создаёт ключ реестра HKCU\Software\Pixie (используется licensing.py
;     для хранения machine_id; сами настройки хранятся в config.json рядом
;     с exe — создаётся автоматически при первом запуске онбордингом,
;     поэтому в установщик не кладём)
;
; Соберите main.py в exe ПЕРЕД запуском Inno Setup (PyInstaller, --onedir):
;   cd agent
;   pyinstaller --noconfirm --onedir --windowed --name Pixie ^
;       --collect-all google.genai --collect-all customtkinter ^
;       --hidden-import=onboarding --hidden-import=app_shell ^
;       --hidden-import=ui_theme --hidden-import=presets ^
;       --icon=icon.ico main.py
;
; Затем скомпилируйте этот файл через Inno Setup Compiler (ISCC.exe):
;   ISCC.exe installer.iss
;   (CI передаёт версию релиза через /DMyAppVersion="1.2.0")
;
; Требуется Inno Setup 6+: https://jrsoftware.org/isinfo.php

#define MyAppName "Pixie"
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "Pixie Assistant"
#define MyAppURL "https://pixie-ai.pro/"
#define MyAppExeName "Pixie.exe"

; Пути относительно этого .iss файла — подправьте под свою структуру,
; если main.py собран в другую директорию.
#define SourceDist "..\agent\dist"
#define SourcePython "..\agent"

[Setup]
AppId={{B3B9F0B0-6E6B-4C60-9C0E-PIXIE00000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; У нас нет EV Code Signing на старте — установщик и exe без подписи.
; Windows SmartScreen может показать предупреждение "Unknown publisher" при
; первом запуске, пока не наберётся репутация или пока не будет куплен
; Authenticode-сертификат. Это ожидаемо и указано в описании релиза на GitHub.
OutputDir=output
; Имя файла ФИКСИРОВАННОЕ (без версии), чтобы на сайте можно было дать
; постоянную прямую ссылку на скачивание последнего релиза:
;   https://github.com/<org>/<repo>/releases/latest/download/PixieSetup.exe
; Версия всё равно видна пользователю в самом установщике (AppVersion) и
; в названии GitHub Release.
OutputBaseFilename=PixieSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; lowest — ставим в %LOCALAPPDATA%\Programs без прав администратора и без UAC
; (проще для пользователей, не требует запроса на подтверждение UAC).
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
UsePreviousAppDir=yes
ArchitecturesInstallIn64BitMode=x64compatible



[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Вся папка PyInstaller --onedir (Pixie.exe + все DLL/зависимости рядом).
; Именно поэтому Source указывает на "\Pixie\*", а не на один exe-файл.
Source: "{#SourceDist}\Pixie\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; Папка с рецептами UE 5.8 (нужна только для Pro-функций, но копируется всегда —
; guard на уровне licensing.is_pro_active() блокирует доступ без подписки).
Source: "{#SourcePython}\ue58_recipes\*"; DestDir: "{app}\ue58_recipes"; Flags: ignoreversion recursesubdirs createallsubdirs

; Публичный ключ RSA — обязателен, приватный НИКОГДА не должен сюда попадать.
Source: "{#SourcePython}\public_key.pem"; DestDir: "{app}"; Flags: ignoreversion; Check: FileExists(ExpandConstant('{#SourcePython}\public_key.pem'))

; config.json НЕ копируем: main.py/config_loader.py создаёт его автоматически
; при первом запуске (через онбординг-wizard), так что в установщике
; отсутствие файла — это правильное поведение, а не упущение.

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; --- Регистрация протокола pixie:// ---
; После установки клик по ссылке pixie://license/<KEY> из письма запускает
; Pixie.exe с этой ссылкой в качестве аргумента (sys.argv[1] в main.py),
; который парсится licensing.try_apply_from_argv().
Root: HKCU; Subkey: "Software\Classes\pixie"; ValueType: string; ValueName: ""; ValueData: "URL:Pixie Protocol"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\pixie"; ValueType: string; ValueName: "URL Protocol"; ValueData: ""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\pixie\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"",1"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\pixie\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey

; --- HKCU\Software\Pixie: место для machine_id (создаётся автоматически
; самим приложением через licensing.save_machine_id_to_registry, но ключ
; создаём заранее, чтобы деинсталлятор мог его аккуратно убрать). ---
Root: HKCU; Subkey: "Software\Pixie"; Flags: uninsdeletekeyifempty

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Удаляем состояние лицензии/конфиг при полном удалении, чтобы не оставлять
; ключи на диске (пользователь может переустановить и активировать заново).
Type: files; Name: "{app}\pixie_license_state.json"
Type: files; Name: "{app}\config.json"
