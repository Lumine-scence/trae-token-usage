@echo off
title TRAE Token Usage - One-click Key Capture
cd /d "%~dp0"
setlocal enabledelayedexpansion

set "PY=C:\Program Files (x86)\Microsoft Visual Studio\Shared\Python39_64\python.exe"

if not exist "%PY%" (
  echo [ERROR] Python 3.9 ^(VS^) not found at:
  echo   %PY%
  echo Install it, or edit the PY path at the top of this batch file.
  echo.
  pause >nul
  exit /b 1
)

echo ============================================================
echo   One-click Key Capture ^(run once, then no terminal needed^)
echo ============================================================
echo.
echo   If a re-capture is triggered, your current TRAE AI session
echo   will be interrupted for a few seconds and then recover.
echo.
"%PY%" capture_key_once.py
echo.
if "%ERRORLEVEL%"=="0" (
  echo [OK] done - you can close this window.
) else (
  echo [FAIL] see messages above. Make sure TRAE is running, then retry.
)
echo.
pause >nul