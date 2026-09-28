@echo off
rem ===========================================================================
rem  GPRv2 - Radargrama en tiempo real, VERSION RAPIDA. Doble click, o consola.
rem  Mismo programa y misma ventana que vivo.bat, pero un refresco cuesta ~35 ms
rem  en vez de ~150, asi que la pantalla deja de ir a tirones. Graba el mismo
rem  formato de CSV. vivo.bat queda sin tocar, por si hace falta comparar.
rem ===========================================================================
title GPRv2 - En vivo (rapido)

rem %~dp0 es la carpeta de ESTE archivo. Usarla en vez de una ruta fija hace que
rem el repo se pueda mover, renombrar o clonar en otra maquina sin tocar nada.
rem El /d es imprescindible: sin el, "cd" no cambia de unidad.
cd /d "%~dp0"

call :buscar_python || exit /b 1

echo.
echo  ==========================================================
echo   GPRv2 - Radargrama en tiempo real (rapido)
echo  ==========================================================
echo   Antes de seguir:
echo     - El ESP32 enchufado y el generador andando
echo     - El Monitor Serie del Arduino IDE CERRADO
echo     - Telemetry Viewer cerrado
echo.
echo   Los primeros segundos dicen "calibrando la triangular":
echo   esta midiendo el periodo del generador, es normal.
echo.
echo   En la ventana:  cuadros de texto a la izquierda (Enter aplica),
echo                   botones debajo. Teclas: 'e' cambia el eje,
echo                   'a' autoescala el color, 'f' fondo auto (MTI),
echo                   'q' sale.
echo.
echo   El panel de la derecha muestra "ms/cuadro": si se acerca a 200,
echo   bajale la ventana o subile rampas/fila.
echo.
echo   Cada corrida graba un par de CSV NUEVOS en datos\ con la fecha
echo   y la hora en el nombre (captura_dd-mm-aaaa_hh-mm-ss.csv y su
echo   triangular_...). No pisa nada. Los cuadros de la izquierda
echo   arrancan como quedaron la ultima vez.
echo  ==========================================================

"%PY%" "analisis\vivo_rapido.py"

echo.
pause
exit /b 0


:buscar_python
set "PY=%USERPROFILE%\venvs\gpr-win\Scripts\python.exe"
if exist "%PY%" exit /b 0
set "PY=C:\Users\tinch\venvs\gpr-win\Scripts\python.exe"
if exist "%PY%" exit /b 0

rem Sin venv, cualquier Python de Windows sirve SI tiene los paquetes: se
rem prueba importandolos, que es la unica forma honesta de saberlo. Sin esto,
rem en una maquina sin el venv el .bat moria con un mensaje que hablaba de
rem "el ESP32 es un puerto COM", y parecia que el problema era la placa cuando
rem el puerto ni siquiera se habia abierto. (Paso en el laboratorio, 28/09.)
call :probar "py.exe" && exit /b 0
for /f "delims=" %%P in ('where python 2^>nul') do call :probar "%%P" && exit /b 0
for /f "delims=" %%P in ('where python3 2^>nul') do call :probar "%%P" && exit /b 0

echo.
echo  [ERROR] No encuentro un Python con los paquetes que hacen falta.
echo.
echo  OJO: esto NO tiene nada que ver con la placa. El puerto todavia no se
echo  abrio, asi que el ESP32 puede estar perfectamente enchufado.
echo.
echo  Se busco el venv en:
echo     %USERPROFILE%\venvs\gpr-win\Scripts\python.exe
echo     C:\Users\tinch\venvs\gpr-win\Scripts\python.exe
echo  y despues cualquier Python del PATH que pueda importar
echo  serial, numpy, scipy, pandas y matplotlib.
echo.
echo  Para dejarlo andando de una vez:
echo     python -m venv "%USERPROFILE%\venvs\gpr-win"
echo     "%USERPROFILE%\venvs\gpr-win\Scripts\pip" install -r ..\requirements.txt
echo.
echo  Tiene que ser un Python de WINDOWS: el ESP32 es un puerto COM
echo  y WSL 2 no lo ve.
echo.
pause
exit /b 1


rem Deja %PY% apuntando a %~1 si ese interprete tiene todos los paquetes.
:probar
if "%~1"=="" exit /b 1
"%~1" -c "import serial,numpy,scipy,pandas,matplotlib" >nul 2>&1
if errorlevel 1 exit /b 1
set "PY=%~1"
echo  (sin venv gpr-win: uso %~1)
exit /b 0
