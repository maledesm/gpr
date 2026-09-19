@echo off
rem ===========================================================================
rem  GPRv2 - Experimento: la triangular sale con dos lineas. Graba 60 s del
rem  stream crudo (con las tres lecturas del ADC por iteracion que emite el
rem  firmware del experimento) y dice si el estado cambia entre conversiones
rem  o entre iteraciones. Ver GPRv2/CLAUDE.md.
rem
rem  Doble click: graba y analiza. Arrastrarle un experimento_adc3_*.txt
rem  encima: solo analiza ese archivo.
rem ===========================================================================
title GPRv2 - Experimento ADC x3

cd /d "%~dp0"

call :buscar_python || exit /b 1

echo.
echo  ==========================================================
echo   GPRv2 - Experimento: tres lecturas del ADC por iteracion
echo  ==========================================================
echo   Antes de seguir:
echo     - El ESP32 con el firmware que emite "#v3,..." cargado
echo     - El generador andando, como en una medicion normal
echo     - El Monitor Serie del Arduino IDE CERRADO
echo.
echo   Graba 60 s y analiza. El stream queda en datos\experimento_adc3_*.txt
echo  ==========================================================

"%PY%" "analisis\experimento_adc3.py" %1

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
echo     %USERPROFILE%\venvs\gpr-win\Scripts\python.exe
echo     C:\Users\tinch\venvs\gpr-win\Scripts\python.exe
echo.
pause
exit /b 1
