@echo off
setlocal

cd /d "%~dp0"

if not exist "%~dp0venv\Scripts\python.exe" (
    echo Virtual environment not found.
    echo Run install.bat first.
    pause
    exit /b 1
)

"%~dp0venv\Scripts\python.exe" -m app.main
if errorlevel 1 (
    echo.
    echo Parser exited with an error.
    pause
    exit /b 1
)
