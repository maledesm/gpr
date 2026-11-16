@echo off
rem Deja en %PY% un Python de Windows con los paquetes de GPRv3. Lo llaman
rem los demas .bat; no se usa solo.
set "PY=%USERPROFILE%\venvs\gpr-win\Scripts\python.exe"
if exist "%PY%" exit /b 0
for %%P in (py.exe python.exe python3.exe) do (
    "%%P" -c "import serial,numpy,scipy,matplotlib,pyqtgraph,PyQt6" >nul 2>&1 && (
        set "PY=%%P"
        exit /b 0
    )
)
echo.
echo  [ERROR] No encuentro un Python con los paquetes que hacen falta.
echo  Esto NO tiene que ver con la placa: el puerto todavia no se abrio.
echo.
echo  Para dejarlo andando:
echo     python -m venv "%USERPROFILE%\venvs\gpr-win"
echo     "%USERPROFILE%\venvs\gpr-win\Scripts\pip" install -r requirements.txt
echo.
pause
exit /b 1
