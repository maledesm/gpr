@echo off
rem ===========================================================================
rem  Medir: graba una captura y abre el grafico en vivo.
rem  Doble click, o desde consola.
rem ===========================================================================
title GPR - Medicion

rem %~dp0 es la carpeta de ESTE archivo. Usarla en vez de una ruta fija hace que
rem el repo se pueda mover, renombrar o clonar en otra maquina sin tocar nada.
rem El /d es imprescindible: sin el, "cd" no cambia de unidad.
cd /d "%~dp0"

call :buscar_python || exit /b 1

echo.
echo  ==========================================================
echo   GPR FMCW - Medicion
echo  ==========================================================
echo   Antes de seguir:
echo     - El ESP32 enchufado
echo     - El Monitor Serie del Arduino IDE CERRADO
echo  ==========================================================

"%PY%" "adquisicion\medir.py"

echo.
echo  ----------------------------------------------------------
echo   Las capturas quedan en:  %~dp0datos
echo  ----------------------------------------------------------
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
echo  Para crearlo:
echo     python -m venv "%USERPROFILE%\venvs\gpr-win"
echo     "%USERPROFILE%\venvs\gpr-win\Scripts\python.exe" -m pip install pyserial numpy scipy pyqtgraph PyQt6
echo.
echo  Tiene que ser un venv de WINDOWS: el ESP32 es un puerto COM
echo  y WSL 2 no lo ve.
echo.
pause
exit /b 1
