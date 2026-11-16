@echo off
title GPRv3 - En vivo
cd /d "%~dp0"
call "%~dp0_python.bat" || exit /b 1
echo  GPRv3 en vivo. Antes: el ESP32 enchufado, el generador andando y el
echo  Monitor Serie del Arduino IDE CERRADO. Teclas: e eje, a color, f fondo
echo  automatico, s captura, q salir.
"%PY%" "software\vivo.py" %*
echo.
pause
