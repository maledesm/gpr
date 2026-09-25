@echo off
rem ===========================================================================
rem  Rehace todo lo del zener de proteccion del VCO:
rem    1. simular_zener.py  corre las seis variantes en LTspice (~6 min)
rem    2. graficar_zener.py arma zener_vertice.png y zener_falla.png
rem    3. tolerancias.py    los numeros del apendice de la tesis
rem
rem  Antes hay que tener pcb/triangular/triangular_kicad.cir al dia
rem  (lo genera pcb/triangular/simular_kicad.bat desde el esquematico).
rem ===========================================================================
title GPRv2 - Zener de proteccion

cd /d "%~dp0"

set PY=C:\Users\tinch\venvs\gpr-win\Scripts\python.exe
if not exist "%PY%" set PY=py

echo.
echo  [1/3] Simulando en LTspice (tarda unos 6 minutos)...
"%PY%" simular_zener.py
if errorlevel 1 goto :error

echo.
echo  [2/3] Armando las figuras...
"%PY%" graficar_zener.py
if errorlevel 1 goto :error

echo.
echo  [3/3] Tolerancias...
"%PY%" tolerancias.py
if errorlevel 1 goto :error

echo.
echo  Listo. Las figuras de la tesis se copian a mano a
echo  redaccion\figuras\triangular\.
pause
exit /b 0

:error
echo.
echo  [ERROR] Fallo un paso. Mira la salida de arriba.
pause
exit /b 1
