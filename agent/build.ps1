# 1. Очистка старых билдов
Remove-Item -Path "dist", "build", "*.spec" -Recurse -Force -ErrorAction SilentlyContinue

# 2. Запуск PyInstaller с указанием скрытых импортов
pyinstaller --noconfirm --onedir --windowed --name Pixie `
  --collect-all google.genai `
  --collect-all customtkinter `
  --hidden-import customtkinter `
  --hidden-import onboarding `
  --hidden-import app_shell `
  --hidden-import ui_theme `
  --hidden-import presets `
  --add-data "presets.py;." `
  main.py

# 3. Проверка результата
$exePath = "dist\Pixie\Pixie.exe"
if (Test-Path $exePath) {
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "УСПЕХ: Pixie.exe успешно собран!" -ForegroundColor Green
    Write-Host "Путь: $exePath" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
} else {
    Write-Host "ОШИБКА: Файл Pixie.exe не найден в dist/Pixie!" -ForegroundColor Red
}