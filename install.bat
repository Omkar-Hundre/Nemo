@echo off
setlocal enabledelayedexpansion
title NEMO Windows Installer
cd /d "%~dp0"

echo ==========================================================
echo        NEMO - Developer Operating Assistant
echo ==========================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install.ps1"

echo.
echo Press any key to exit installer...
pause >nul

