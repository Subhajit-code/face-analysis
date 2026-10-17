@echo off
title FaceVault - Mobile App & Web Launcher
color 0A

echo ==================================================================
echo    FACEVAULT BIOMETRIC 2FA - MOBILE APP & HTTPS LAUNCHER
echo ==================================================================
echo.

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo [!] Virtual environment not detected.
    exit /b 1
)

echo [*] Launching FaceVault in Mobile HTTPS Mode...
echo [*] Mobile Camera Access & PWA App Installation: READY
echo.

.\venv\Scripts\python.exe app.py --ssl --host 0.0.0.0
pause
