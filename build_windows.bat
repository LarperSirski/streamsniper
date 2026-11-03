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
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 (
    echo [ERROR] Build dependencies could not be installed.
    pause
    exit /b 1
)
set "APP_NAME=StreamSniper"
tasklist /FI "IMAGENAME eq StreamSniper.exe" /NH | findstr /I /C:"StreamSniper.exe" >nul
if not errorlevel 1 set "APP_NAME=StreamSniper-Updated"
tasklist /FI "IMAGENAME eq StreamSniper-Updated.exe" /NH | findstr /I /C:"StreamSniper-Updated.exe" >nul
if not errorlevel 1 set "APP_NAME=StreamSniper-Updated-2"
".venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --onefile --windowed --name "%APP_NAME%" --icon "%~dp0ui\StreamSniper.ico" --distpath . --workpath build\pyinstaller --specpath build --add-data "%~dp0ui\StreamSniper.ico;ui" --collect-all yt_dlp --collect-all googleapiclient --collect-all google_auth_oauthlib --collect-all keyring --collect-all PIL main.py
if errorlevel 1 (
    echo [ERROR] Executable build failed.
    pause
    exit /b 1
)
echo Built %APP_NAME%.exe in this folder.
endlocal