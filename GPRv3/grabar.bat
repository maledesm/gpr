@echo off
title GPRv3 - Grabar
cd /d "%~dp0"
call "%~dp0_python.bat" || exit /b 1
echo  Graba el crudo a datos\captura_FECHA.gpr3. Uso: grabar.bat [segundos]
"%PY%" "software\grabar.py" %*
echo.
pause
