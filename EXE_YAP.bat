@echo off
chcp 65001 >nul
title Hacim Radari - EXE derleme
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Once KUR_VE_CALISTIR.bat dosyasini bir kez calistirin.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" -m pip install pyinstaller || (echo PyInstaller kurulamadi & pause & exit /b 1)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --onefile --windowed --name HacimRadari ^
  --collect-all webull --collect-submodules google.protobuf --collect-data tzdata app.py || (echo Derleme basarisiz & pause & exit /b 1)

if exist config.json copy /y config.json dist\config.json >nul
echo.
echo Bitti! dist\HacimRadari.exe hazir. Masaustune kisayol olusturabilirsiniz.
explorer dist
pause
