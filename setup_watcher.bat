@echo off
REM Registers (or updates) the 24x7 watcher and the daily full search in Windows Task Scheduler.
REM Times and interval are at the top of schedule_job_search.ps1.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0schedule_job_search.ps1"
