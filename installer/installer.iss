; installer.iss — Inno Setup script for Pixie Assistant
;
; Собирает установщик Windows для Pixie:
;   - копирует main.exe (собранный через Nuitka) и папку ue58_recipes
;   - регистрирует протокол pixie:// (для авто-применения лицензионного ключа
;     из письма, см. licensing.try_apply_from_argv + main.py)
;   - создаёт ярлыки на рабочем столе и в меню "Пуск"
;   - создаёт ключ реестра HKCU\Software\Pixie (используется licensing.py
;     для хранения machine_id; сами настройки хранятся в config.json рядом
;     с exe, а не в реестре)
;
; Соберите main.py в exe ПЕРЕД запуском Inno Setup:
;   nuitka --standalone --onefile --windows-disable-console ^
;          --windows-icon-from-ico=icon.ico ^
;          --output-dir=dist --output-filename=Pixie.exe main.py
;
; Затем скомпилируйте этот файл через Inno Setup Compiler (ISCC.exe):
;   ISCC.exe installer.iss
;
; Требуется Inno Setup 6+: https://jrsoftware.org/isinfo.php

#define MyAppName "Pixie"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Pixie Assistant"
#define MyAppURL "https://dmanucharyan-del.github.io/pixie-ai/"
#define MyAppExeName "Pixie.exe"

; Пути относительно этого .iss файла — подправьте под свою структуру,
; если main.py собран в другую директорию.
#define SourceDist "..\command-line\python\dist"
#define SourcePython "..\command-line\python"

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
; У нас нет EV Code Signing на старте (см. план) — просто без подписи.
; Пользователям Windows SmartScreen может показать предупреждение при
; первом запуске установщика/приложения, пока не наберётся репутация
; или вы не отправите бинарник на проверку в Microsoft.
OutputDir=output
OutputBaseFilename=PixieSetup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; lowest — ставим в %LOCALAPPDATA%\Programs без прав администратора и без UAC
; (проще для пользователей, не требует запроса на подтверждение UAC).
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#MyAppName}
UsePreviousAppDir=yes
ArchitecturesInstallIn64BitMode=x64



[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; Главный exe, собранный Nuitka (--onefile). Подправьте путь при необходимости.
Source: "{#SourceDist}\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; Папка с рецептами UE 5.8 (нужна только для Pro-функций, но копируется всегда —
; guard на уровне licensing.is_pro_active() блокирует доступ без подписки).
Source: "{#SourcePython}\ue58_recipes\*"; DestDir: "{app}\ue58_recipes"; Flags: ignoreversion recursesubdirs createallsubdirs

; Шаблон конфигурации — при первом запуске main.py создаст/дополнит config.json
; в папке приложения. Если у вас уже есть готовый config.json без секретов,
; можно скопировать его сюда.
Source: "{#SourcePython}\config.json"; DestDir: "{app}"; Flags: onlyifdoesntexist

; Публичный ключ RSA — обязателен, приватный НИКОГДА не должен сюда попасть.
Source: "{#SourcePython}\public_key.pem"; DestDir: "{app}"; Flags: ignoreversion; Check: FileExists(ExpandConstant('{#SourcePython}\public_key.pem'))

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
