@echo off
:: ============================================================
:: TradeSage Build Script
:: Run this from the trading_system folder:
::   build.bat
:: Output: dist\TradeSage\TradeSage.exe
:: ============================================================

setlocal EnableDelayedExpansion
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

echo.
echo  ============================================
echo   TradeSage Build Script
echo  ============================================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH.
    echo         Install Python 3.10+ from https://python.org
    pause
    exit /b 1
)

:: Create venv if it doesn't exist
if not exist ".venv" (
    echo [1/5] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [1/5] Virtual environment already exists.
)

:: Activate venv
echo [2/5] Activating virtual environment...
call .venv\Scripts\activate.bat

:: Install/upgrade dependencies
echo [3/5] Installing dependencies...
pip install --upgrade pip --quiet
pip install PyQt5 requests pyinstaller --quiet
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

:: Clean previous build
echo [4/5] Cleaning previous build artifacts...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

:: Run PyInstaller
echo [5/5] Building TradeSage.exe with PyInstaller...
echo.
pyinstaller TradeSage.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. See output above for details.
    pause
    exit /b 1
)

:: Create required runtime folders inside dist
echo.
echo  Creating runtime folders...
if not exist "dist\TradeSage\config"  mkdir "dist\TradeSage\config"
if not exist "dist\TradeSage\logs"    mkdir "dist\TradeSage\logs"

:: Copy README
if exist "README.md" copy /Y "README.md" "dist\TradeSage\README.md" >nul

echo.
echo  ============================================
echo   BUILD SUCCESSFUL
echo  ============================================
echo.
echo   Executable: dist\TradeSage\TradeSage.exe
echo.
echo   To distribute: zip the entire dist\TradeSage\ folder.
echo   The .exe needs all files in that folder alongside it.
echo.
pause
