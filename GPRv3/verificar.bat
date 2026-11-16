@echo off
title GPRv3 - Verificar
cd /d "%~dp0"
call "%~dp0_python.bat" || exit /b 1
"%PY%" "software\verificar.py"
echo.
pause
