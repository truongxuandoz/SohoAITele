@echo off
chcp 65001 >nul
cd /d "%~dp0"
title SoHo AI - Monitor

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Tao moi truong ao...
    python -m venv .venv
    if errorlevel 1 (
        echo Khong tao duoc venv. Kiem tra Python da cai chua.
        pause
        exit /b 1
    )
    echo [2/2] Cai thu vien...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

echo.
echo ============================================================
echo   SoHo AI Monitor
echo   Mo trinh duyet:  http://127.0.0.1:8787
echo   Bot se TU DONG khoi dong kem dashboard.
echo   Dong cua so nay = bot dung.
echo ============================================================
echo.

".venv\Scripts\python.exe" -m soho.dashboard

echo.
echo Dashboard dung. Bot cung da dung theo.
pause
