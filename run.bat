@echo off
title Biometric Vault - Face Recognition Authentication System
color 0B

echo ========================================================
echo    BIOMETRIC VAULT - MULTI-USER ACCESS CONTROL SYSTEM
echo ========================================================
echo.

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [!] Virtual environment not detected. Creating venv...
    py -m venv venv
    call .\venv\Scripts\activate.bat
    pip install -r requirements.txt
)

echo [*] Starting Biometric Authentication Server...
echo [*] Opening Web Interface in your default browser...
start http://127.0.0.1:5000

.\venv\Scripts\python.exe app.py
pause
