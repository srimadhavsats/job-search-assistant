@echo off
REM One-click job search. Double-click this file (or the desktop shortcut).
REM Extra options are passed through, e.g.:  run_jobs.bat --only linkedin,naukri   or   run_jobs.bat --days 30
REM Scheduled runs set JOBHUNTER_SCHEDULED=1: no Excel pop-up, no "press any key" at the end.
cd /d "%~dp0"
title Job Search
set PYTHONIOENCODING=utf-8
if defined JOBHUNTER_SCHEDULED set JOBHUNTER_NO_OPEN=1

if not exist ".venv\Scripts\python.exe" (
  echo First time setup - installing, this takes a few minutes...
  call "%~dp0setup.bat" || goto :fail
)

.venv\Scripts\python.exe -m jobhunter.main %*
if errorlevel 1 goto :fail

REM set JOBHUNTER_NO_OPEN=1 to skip opening Excel
if defined JOBHUNTER_NO_OPEN goto :done
echo.
echo Opening the Excel file...
REM Always the main workbook: results saved while it was open are merged into it automatically.
if exist "output\Jobs.xlsx" start "" "output\Jobs.xlsx"
:done
echo.
if not defined JOBHUNTER_SCHEDULED pause
exit /b 0

:fail
echo.
echo Something went wrong - see the messages above.
if not defined JOBHUNTER_SCHEDULED pause
exit /b 1
