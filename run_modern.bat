@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the Python virtual environment.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" -c "import PySide6, dotenv, requests, feedparser, yt_dlp" >nul 2>&1
if errorlevel 1 (
    echo Installing StreamSniper dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements-modern.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        pause
        exit /b 1
    )
)
".venv\Scripts\python.exe" main.py
if errorlevel 1 pause
endlocal
