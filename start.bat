@echo off
title AI Video Generator

echo.
echo =========================================
echo   AI Video Generator -- Local Launcher
echo =========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed.
    echo Install from https://python.org then re-run.
    pause
    exit /b 1
)

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing dependencies...
pip install -q -r requirements.txt

where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo.
    echo WARNING: ffmpeg not found. Video rendering will fail.
    echo Download from https://ffmpeg.org/download.html
    echo.
)

echo.
echo Starting backend on http://localhost:8000 ...
echo Opening browser in 3 seconds...
echo Press Ctrl+C to stop.
echo.

start "" timeout /t 3 >nul && start http://localhost:8000

cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
