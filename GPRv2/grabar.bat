@echo off
rem ===========================================================================
rem  GPRv2 - Graba una captura por serie desde el ESP32 a CSV.
rem  Doble click, o desde consola.
rem ===========================================================================
title GPRv2 - Grabar

rem %~dp0 es la carpeta de ESTE archivo. Usarla en vez de una ruta fija hace que
rem el repo se pueda mover, renombrar o clonar en otra maquina sin tocar nada.
rem El /d es imprescindible: sin el, "cd" no cambia de unidad.
cd /d "%~dp0"

call :buscar_python || exit /b 1

echo.
echo  ==========================================================
echo   GPRv2 - Grabar captura
echo  ==========================================================
echo   Antes de seguir:
echo     - El ESP32 y el Uno enchufados
echo     - El Monitor Serie del Arduino IDE CERRADO
echo     - Telemetry Viewer cerrado
echo.
echo   El script manda 'run' solo, no hace falta que lo tipees.
echo   OJO: sobrescribe la captura anterior, siempre usa el mismo nombre.
echo  ==========================================================

"%PY%" "analisis\grabar_rampa.py"
if errorlevel 1 goto :fin

echo.
echo  ----------------------------------------------------------
echo   Captura en:  %~dp0datos\captura.csv
echo   Abriendo el grafico. Cerra la ventana para terminar.
echo  ----------------------------------------------------------
"%PY%" "analisis\graficar_captura.py"

:fin
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
