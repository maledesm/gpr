@echo off
rem ===========================================================================
rem  Autopruebas del software, SIN hardware.
rem
rem  Correlas primero cuando algo no funciona: si pasan, el problema esta en el
rem  enlace o en la placa, no en el codigo. Ahorra depurar dos cosas a la vez.
rem ===========================================================================
title GPR - Autopruebas

cd /d "%~dp0"

set "PY=%USERPROFILE%\venvs\gpr-win\Scripts\python.exe"
if not exist "%PY%" set "PY=C:\Users\tinch\venvs\gpr-win\Scripts\python.exe"
if not exist "%PY%" (
  echo [ERROR] No encuentro el entorno de Python. Ver medir.bat.
  pause
  exit /b 1
)

set FALLOS=0

echo.
echo  === Protocolo binario: tramas, CRC y continuidad ===
"%PY%" "adquisicion\protocolo.py" --test || set FALLOS=1

echo.
echo  === Procesamiento: ventanas, FFT, filtros, distancia ===
"%PY%" "adquisicion\dsp.py" --test || set FALLOS=1

echo.
if "%FALLOS%"=="0" (
  echo  ==========================================================
  echo   TODO OK. El software esta sano.
  echo  ==========================================================
) else (
  echo  ==========================================================
  echo   HAY PRUEBAS QUE FALLAN. Revisar antes de medir.
  echo  ==========================================================
)
pause
exit /b %FALLOS%
