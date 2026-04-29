@echo off
setlocal

cd /d "%~dp0"

echo Creating virtual environment...
py -3 -m venv venv
if errorlevel 1 (
    echo Failed to create venv. Make sure Python 3 is installed.
    pause
    exit /b 1
)

echo Upgrading pip...
"%~dp0venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 (
    echo Failed to upgrade pip.
    pause
    exit /b 1
)

echo Installing requirements...
"%~dp0venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install requirements.
    pause
    exit /b 1
)

echo Fetching Camoufox browser...
"%~dp0venv\Scripts\python.exe" -m camoufox fetch
if errorlevel 1 (
    echo Failed to fetch Camoufox browser.
    pause
    exit /b 1
)

echo.
echo Installation completed successfully.
pause
