@echo off
rem ===========================================================================
rem  GPRv2 - Simulacion de los ARMONICOS del VCO contra las capturas del 28-09
rem
rem  1. MEEP de banda ancha (0,9 a 6,25 GHz) en WSL: placa a 0,70 / 0,80 /
rem     0,90 / 1,00 / 1,20 m y la escena vacia, con la sonda adaptada y con
rem     la sonda en corto. Unos minutos por escena.
rem  2. En Windows: armonicos, triangular, cadena de IF y el procesado de
rem     vivo_rapido, contra datos\capturas\placa_*cm_{cf,sf}.csv.
rem
rem  Las figuras y el resumen quedan en simulaciones_meep\armonicos\figuras\<sonda>\
rem  y los datos de MEEP en salidas\<sonda>\. Explicado en
rem  simulaciones_meep\armonicos\LEEME.md. Los parametros en
rem  simulaciones_meep\armonicos\parametros.py.
rem
rem  MEEP=0 saltea el paso 1 (si las escenas ya estan y solo cambio el modelo).
rem ===========================================================================
title GPRv2 - Armonicos del VCO

set MEEP=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"
set "SIM=%~dp0simulaciones_meep\armonicos"
set "PY=C:\Users\tinch\venvs\gpr-win\Scripts\python.exe"
if not exist "%PY%" set "PY=%USERPROFILE%\venvs\gpr-win\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

if "%MEEP%"=="0" goto :radar
if defined WSLENV (set "WSLENV=%WSLENV%:GPR_SIM_SONDA:GPR_SIM_NOMBRE") else (set "WSLENV=GPR_SIM_SONDA:GPR_SIM_NOMBRE")
for %%S in (adaptada corto) do (
    echo.
    echo  [MEEP] sonda %%S ...
    set "GPR_SIM_SONDA=%%S"
    set "GPR_SIM_NOMBRE=%%S"
    wsl -d Ubuntu --cd "%SIM%" -- bash correr_meep.sh barrido
    if errorlevel 1 goto :error
)

:radar
echo.
echo  [radar] sintesis y comparacion ...
pushd "%SIM%"
"%PY%" correr.py || (popd & goto :error)
popd
echo.
echo  Listo: figuras en simulaciones_meep\armonicos\figuras\
pause
exit /b 0

:error
echo.
echo  [ERROR] ver el mensaje de arriba.
pause
exit /b 1
