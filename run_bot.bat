@echo off
chcp 65001 >nul
cd /d "%~dp0"
title SoHo AI Bot

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
echo === Kiem tra cau hinh ===
".venv\Scripts\python.exe" check_setup.py
echo.

echo === Khoi dong bot (Ctrl+C de dung) ===
:loop
".venv\Scripts\python.exe" -m soho.bot
echo.
echo Bot dung. Khoi dong lai sau 5 giay... (Ctrl+C de thoat han)
timeout /t 5 >nul
goto loop
