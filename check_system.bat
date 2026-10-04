@echo off
REM System check ("test demo"): tests every job site with a tiny search, Chrome and CV rendering,
REM the workbook, the scheduled tasks, the watcher and the alerts. Changes nothing.
REM   check_system.bat --popup     also sends a test pop-up (and Telegram message if set up)
cd /d "%~dp0"
title Job search system check
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m jobhunter.doctor %*
echo.
pause
