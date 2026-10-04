@echo off
REM One time install. Installs Python and Google Chrome if they are missing, then the packages.
REM Safe to run again. The steps are in setup.ps1.
cd /d "%~dp0"
title Job search setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
exit /b %errorlevel%
