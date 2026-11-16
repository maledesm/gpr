@echo off
title GPRv3 - En vivo, sin banco
cd /d "%~dp0"
call "%~dp0_python.bat" || exit /b 1
"%PY%" "software\vivo.py" --sintetico
echo.
pause
