@echo off
chcp 65001 >nul
title Hacim Radari - Kurulum
cd /d "%~dp0"

set PY=
where py >nul 2>&1 && set PY=py -3
if "%PY%"=="" ( where python >nul 2>&1 && set PY=python )
if "%PY%"=="" (
  echo Python bulunamadi. Kuruluyor ^(winget^)...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  echo.
  echo Python kuruldu. Bu pencereyi kapatip KUR_VE_CALISTIR.bat dosyasini tekrar calistirin.
  pause
  exit /b
)

if not exist ".venv\Scripts\python.exe" (
  echo Sanal ortam olusturuluyor...
  %PY% -m venv .venv || (echo Sanal ortam olusturulamadi & pause & exit /b 1)
)

echo Paketler kuruluyor / guncelleniyor...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || (echo Paket kurulumu basarisiz & pause & exit /b 1)

echo Uygulama baslatiliyor...
start "" ".venv\Scripts\pythonw.exe" app.py
