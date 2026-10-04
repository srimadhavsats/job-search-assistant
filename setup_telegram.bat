@echo off
REM Connects your Telegram bot to the job search. Paste the token from @BotFather when asked.
REM The token is saved only on this laptop (config\telegram.yaml). Do not share that file.
cd /d "%~dp0"
title Connect Telegram
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m jobhunter.tgbot --setup
if errorlevel 1 goto :end
echo.
echo Starting the bot in the background. It also starts by itself at every login.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$env:NO_PAUSE='1'; & '%~dp0schedule_job_search.ps1'"
echo.
echo Done. Open your bot in Telegram and tap "What now".
:end
echo.
pause
