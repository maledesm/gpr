@echo off
rem ===========================================================================
rem  GPRv2 - Radargrama en tiempo real. Doble click, o desde consola.
rem  Es grabar.bat pero sin esperar: dibuja mientras graba.
rem ===========================================================================
title GPRv2 - En vivo

rem %~dp0 es la carpeta de ESTE archivo. Usarla en vez de una ruta fija hace que
rem el repo se pueda mover, renombrar o clonar en otra maquina sin tocar nada.
rem El /d es imprescindible: sin el, "cd" no cambia de unidad.
cd /d "%~dp0"

call :buscar_python || exit /b 1

echo.
echo  ==========================================================
echo   GPRv2 - Radargrama en tiempo real
echo  ==========================================================
echo   Antes de seguir:
echo     - El ESP32 enchufado y el generador andando
echo     - El Monitor Serie del Arduino IDE CERRADO
echo     - Telemetry Viewer cerrado
echo.
echo   Los primeros segundos dicen "calibrando la triangular":
echo   esta midiendo el periodo del generador, es normal.
echo.
echo   En la ventana:  slider rampas/columna, sliders piso y techo,
echo                   'e' cambia el eje, 'a' autoescala, 'q' sale.
echo.
echo   OJO: sobrescribe datos\captura.csv, igual que grabar.bat.
echo  ==========================================================

"%PY%" "analisis\vivo.py"

echo.
pause
exit /b 0


:buscar_python
set "PY=%USERPROFILE%\venvs\gpr-win\Scripts\python.exe"
if exist "%PY%" exit /b 0
set "PY=C:\Users\tinch\venvs\gpr-win\Scripts\python.exe"
if exist "%PY%" exit /b 0
echo.
echo  [ERROR] No encuentro el entorno de Python de adquisicion.
echo.
echo  Se busco en:
echo     %USERPROFILE%\venvs\gpr-win\Scripts\python.exe
echo     C:\Users\tinch\venvs\gpr-win\Scripts\python.exe
echo.
echo  Tiene que ser un venv de WINDOWS: el ESP32 es un puerto COM
echo  y WSL 2 no lo ve. Ver medir.bat en la raiz del repo.
echo.
pause
exit /b 1
