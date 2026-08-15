@echo off
rem ===========================================================================
rem  Abre el graficador sobre la ultima captura, sin grabar nada.
rem  Para revisar mediciones viejas con el ESP32 desconectado.
rem
rem  Se le puede arrastrar un .csv encima para abrir ese en particular.
rem ===========================================================================
title GPR - Grafico

cd /d "%~dp0"

call :buscar_python || exit /b 1

rem %1 es el archivo arrastrado sobre el .bat, si lo hubo. Sin argumento, el
rem graficador toma solo el CSV mas reciente de datos\.
"%PY%" "adquisicion\graficarserial.py" %1

if errorlevel 1 pause
exit /b 0


:buscar_python
set "PY=%USERPROFILE%\venvs\gpr-win\Scripts\python.exe"
if exist "%PY%" exit /b 0
set "PY=C:\Users\tinch\venvs\gpr-win\Scripts\python.exe"
if exist "%PY%" exit /b 0
echo.
echo  [ERROR] No encuentro el entorno de Python de adquisicion.
echo  Ver medir.bat para las instrucciones de instalacion.
echo.
pause
exit /b 1
