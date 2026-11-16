@echo off
title GPRv3 - Analizar
cd /d "%~dp0"
call "%~dp0_python.bat" || exit /b 1
echo  Sin argumentos abre la grabacion mas nueva de datos\.
"%PY%" "software\analizar.py" %*
echo.
pause
