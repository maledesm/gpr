@echo off
rem ===========================================================================
rem  Medir con la placa de audio (U-Phoria UMC22): graba y abre el grafico.
rem  Es el gemelo de medir.bat, para cuando se digitaliza por la placa de
rem  sonido en vez del PCM1808 + ESP32.
rem  Doble click, o desde consola.
rem ===========================================================================
title GPR - Medicion (placa de audio)

rem %~dp0 es la carpeta de ESTE archivo. Usarla en vez de una ruta fija hace que
rem el repo se pueda mover, renombrar o clonar en otra maquina sin tocar nada.
rem El /d es imprescindible: sin el, "cd" no cambia de unidad.
cd /d "%~dp0"

call :buscar_python || exit /b 1

echo.
echo  ==========================================================
echo   GPR FMCW - Medicion por placa de audio
echo  ==========================================================
echo   Antes de seguir:
echo     - La UMC22 enchufada por USB
echo     - La senal en la entrada 2 (INSTRUMENT), con el divisor
echo     - Nada mas usando la placa (Audacity, Zoom, el navegador)
echo  ==========================================================

"%PY%" "adquisicion_audio\medir_audio.py"

echo.
echo  ----------------------------------------------------------
echo   Las capturas quedan en:  %~dp0datos   (CSV + WAV)
echo  ----------------------------------------------------------
pause
exit /b 0


:buscar_python
set "PY=%USERPROFILE%\venvs\gpr-win\Scripts\python.exe"
if exist "%PY%" exit /b 0
set "PY=C:\Users\tinch\venvs\gpr-win\Scripts\python.exe"
if exist "%PY%" exit /b 0
rem Ultimo recurso: el Python del sistema. Anda si tiene numpy y sounddevice.
where python >nul 2>nul && (set "PY=python" & exit /b 0)
echo.
echo  [ERROR] No encuentro el entorno de Python de adquisicion.
echo.
echo  Se busco en:
echo     %USERPROFILE%\venvs\gpr-win\Scripts\python.exe
echo     C:\Users\tinch\venvs\gpr-win\Scripts\python.exe
echo     python en el PATH
echo.
echo  Para crearlo:
echo     python -m venv "%USERPROFILE%\venvs\gpr-win"
echo     "%USERPROFILE%\venvs\gpr-win\Scripts\python.exe" -m pip install sounddevice numpy scipy pyqtgraph PyQt6
echo.
echo  Tiene que ser un venv de WINDOWS: WSL 2 no ve la placa de sonido.
echo.
pause
exit /b 1
