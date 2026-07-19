@echo off
chcp 65001 > nul
title Пикси: Твой ИИ-напарник (UE5)

cd /d "%~dp0"

if "%GEMINI_API_KEY%"=="" (
    if exist ".env" (
        for /f "usebackq delims=" %%a in (.env) do set %%a
    )
)

if "%GEMINI_API_KEY%"=="" (
    echo [Ошибка] Переменная GEMINI_API_KEY не задана.
    echo Задайте ключ: set GEMINI_API_KEY=ваш-ключ
    echo Или создайте файл .env рядом с main.py
    pause
    exit /b 1
)

:loop
cls
echo [Система] Установка английской раскладки для текущего окна...
powershell -Command "$w = Add-Type -MemberDefinition '[DllImport(\"user32.dll\")] public static extern IntPtr GetForegroundWindow(); [DllImport(\"user32.dll\")] public static extern bool PostMessage(IntPtr hWnd, uint Msg, int wParam, int lParam);' -Name Win32 -PassThru; [void]$w::PostMessage($w::GetForegroundWindow(), 0x50, 0, 0x04090409)"
timeout /t 1 > nul

echo [Система] Запуск Пикси...
python main.py

echo.
echo [Система] Пикси отключилась или истек таймаут сессии (10 мин).
echo [Система] Автоматический перезапуск потока через 2 секунды...
timeout /t 2 > nul
goto loop
