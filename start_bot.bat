@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Eroare: mediul virtual .venv nu exista.
    echo Creeaza-l cu: py -m venv .venv
    pause
    exit /b 1
)

if not exist ".env" (
    echo Eroare: fisierul .env nu exista.
    echo Copiaza .env.example in .env si completeaza BOT_TOKEN si ADMIN_IDS.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" bot.py
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo Botul s-a oprit cu codul %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
