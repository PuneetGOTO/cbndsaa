@echo off
chcp 65001 > nul
title Discord Lottery Bot

echo.
echo ==========================================
echo    Discord Lottery Bot - Windows Startup
echo ==========================================
echo.

REM Check if Python is installed
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found, please install Python 3.8+
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [OK] Python is installed
echo.

REM Check if requirements.txt exists
if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found
    pause
    exit /b 1
)

REM Check if .env file exists
if not exist ".env" (
    if exist ".env.example" (
        echo [INFO] .env not found, creating from .env.example...
        copy ".env.example" ".env" > nul
        echo [OK] .env file created successfully
        echo.
        echo [WARNING] Please edit .env file and set your DISCORD_TOKEN
        echo Press any key to open .env file for editing...
        pause > nul
        notepad .env
        echo.
        echo After editing, please run this script again
        pause
        exit /b 0
    ) else (
        echo [ERROR] .env.example file not found
        pause
        exit /b 1
    )
)

echo [INFO] Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install dependencies
    pause
    exit /b 1
)

echo.
echo [OK] Dependencies check completed
echo.
echo [INFO] Starting Discord Lottery Bot...
echo ==========================================
echo.

REM Start the bot
python bot.py

echo.
echo [INFO] Bot stopped
pause
