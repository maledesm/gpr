@echo off
rem ===========================================================================
rem  GPRv2 - Simulacion MEEP de la placa metalica. Doble click, o consola.
rem
rem  Corre las dos mitades de la simulacion en orden:
rem    1. el FDTD (MEEP) adentro de WSL, en el env conda "meep"
rem    2. el procesamiento de radar en Windows, con el pipeline de analisis\
rem  y al final abre las figuras.
rem
rem  Para probar otra cosa, cambia los valores del bloque de abajo y volve a
rem  correrlo. NO hace falta tocar ningun .py: los valores de referencia (los
rem  del croquis y del VNA) viven en simulaciones_meep\parametros.py, y lo que
rem  se ponga aca los pisa solo para esta corrida.
rem ===========================================================================
title GPRv2 - Simulacion MEEP

rem ###########################################################################
rem ##                    LO QUE SE PUEDE CAMBIAR                            ##
rem ##  Dejar un valor VACIO (ej: "set TAU_INTERNO_NS=") usa el de           ##
rem ##  parametros.py. Se acepta coma o punto decimal.                       ##
rem ###########################################################################

rem Que correr:
rem    placa    placa a DIST_PLACA + escena vacia      (~10 s)
rem    barrido  placa a cada distancia de BARRIDO       (~20 s) -> pendiente y offset
rem    todo     las dos cosas
set QUE=todo

rem Distancia del plano de apertura de las bocinas a la placa [m]
set DIST_PLACA=1.00

rem Distancias para el barrido [m], separadas por espacios
set BARRIDO=0.75 1.00 1.25 1.50

rem Hueco entre las bocas de las dos bocinas, de borde a borde [m]
rem (0 = bocas pegadas; los centros quedan a 30,5 cm + este hueco)
set SEPARACION_BOCAS=0.10

rem Ancho de la placa en el plano de la simulacion [m]
set PLACA_ANCHO=0.70

rem Cables:  medido  = S21 de los RG-213 medido con el VNA (lo mas real)
rem          ideal   = retardo puro, sin perdidas
rem          ninguno = sin cables
set CABLE=medido

rem Retardo interno del radar (splitter, mezclador, LNA) [ns]. No esta
rem medido: 0 hasta tener una captura real de la placa para despejarlo.
set TAU_INTERNO_NS=0

rem Celdas por unidad MEEP (0,15 m). 20 = 7,5 mm. 30 es mas fino y tarda ~3x.
set RESOLUCION=20

rem ###########################################################################
rem ##                  DE ACA PARA ABAJO NO HACE FALTA TOCAR                ##
rem ###########################################################################

cd /d "%~dp0"
set "SIM=%~dp0simulaciones_meep"

rem Las variables llegan a Python con el prefijo GPR_SIM_. Para que crucen a
rem WSL hay que nombrarlas en WSLENV: si no, Linux no las ve.
set "GPR_SIM_DIST_PLACA=%DIST_PLACA%"
set "GPR_SIM_BARRIDO=%BARRIDO%"
set "GPR_SIM_SEPARACION_BOCAS=%SEPARACION_BOCAS%"
set "GPR_SIM_PLACA_ANCHO=%PLACA_ANCHO%"
set "GPR_SIM_CABLE=%CABLE%"
set "GPR_SIM_TAU_INTERNO_NS=%TAU_INTERNO_NS%"
set "GPR_SIM_RESOLUCION=%RESOLUCION%"
rem Los scripts de Windows abren solos la figura que generan.
set "GPR_SIM_ABRIR=1"
set "VARS=GPR_SIM_DIST_PLACA:GPR_SIM_BARRIDO:GPR_SIM_SEPARACION_BOCAS:GPR_SIM_PLACA_ANCHO:GPR_SIM_CABLE:GPR_SIM_TAU_INTERNO_NS:GPR_SIM_RESOLUCION"
if defined WSLENV (set "WSLENV=%WSLENV%:%VARS%") else (set "WSLENV=%VARS%")

if /i not "%QUE%"=="placa" if /i not "%QUE%"=="barrido" if /i not "%QUE%"=="todo" (
    echo.
    echo  [ERROR] QUE=%QUE%  -- tiene que ser placa, barrido o todo.
    goto :fin_error
)

call :buscar_python || goto :fin_error

echo.
echo  ==========================================================
echo   GPRv2 - Simulacion MEEP de la placa metalica
echo  ==========================================================
echo   que           %QUE%
echo   placa a       %DIST_PLACA% m     (barrido: %BARRIDO%)
echo   hueco bocas   %SEPARACION_BOCAS% m    ancho placa %PLACA_ANCHO% m
echo   cables        %CABLE%        tau interno %TAU_INTERNO_NS% ns
echo   resolucion    %RESOLUCION% celdas/u
echo  ==========================================================

echo.
echo  [1/3] Verificando parametros...
"%PY%" "%SIM%\parametros.py" || goto :fin_error

rem --- 1. FDTD en WSL --------------------------------------------------------
if /i "%QUE%"=="barrido" goto :meep_barrido
echo.
echo  [2/3] MEEP: placa a %DIST_PLACA% m y escena vacia (WSL)...
wsl -d Ubuntu --cd "%SIM%" -- bash correr_meep.sh placa vacio
if errorlevel 1 goto :error_wsl
if /i "%QUE%"=="placa" goto :radar

:meep_barrido
echo.
echo  [2/3] MEEP: barrido de distancia %BARRIDO% (WSL)...
wsl -d Ubuntu --cd "%SIM%" -- bash correr_meep.sh barrido
if errorlevel 1 goto :error_wsl

rem --- 2. Radar en Windows ---------------------------------------------------
:radar
echo.
echo  [3/3] Radar: cables + batido + pipeline de analisis\ ...
pushd "%SIM%"
rem Los scripts anotan en _abrir.txt las figuras que generan; se abren al final.
if exist "salidas\_abrir.txt" del "salidas\_abrir.txt"
if /i not "%QUE%"=="barrido" (
    "%PY%" correr.py || (popd & goto :fin_error)
)
if /i not "%QUE%"=="placa" (
    "%PY%" barrido.py || (popd & goto :fin_error)
)
popd

rem --- 3. Abrir las figuras --------------------------------------------------
rem Con el visor que Windows tenga asociado a .png. Si una figura estaba
rem abierta de la corrida anterior, el script la guardo con la hora en el
rem nombre, y es esa la que se abre.
if exist "%SIM%\salidas\_abrir.txt" (
    for /f "usebackq delims=" %%F in ("%SIM%\salidas\_abrir.txt") do start "" "%%F"
)


echo.
echo  Listo. Las figuras y los .npz quedan en simulaciones_meep\salidas\
echo.
pause
exit /b 0


:error_wsl
echo.
echo  [ERROR] Fallo la parte de MEEP adentro de WSL. Revisar:
echo     - que exista la distro Ubuntu:   wsl -l -v
echo     - que exista el env conda meep:  wsl -d Ubuntu -- ls ~/miniconda3/envs
echo     - el mensaje de error de arriba
goto :fin_error

:fin_error
echo.
pause
exit /b 1


:buscar_python
rem Primero el venv del banco, como vivo_rapido.bat. Si no esta (maquina sin
rem el venv), cualquier Python del PATH que tenga numpy, scipy, pandas y
rem matplotlib: el lado Windows de la simulacion no usa el puerto serie.
set "PY=%USERPROFILE%\venvs\gpr-win\Scripts\python.exe"
if exist "%PY%" exit /b 0
set "PY=C:\Users\tinch\venvs\gpr-win\Scripts\python.exe"
if exist "%PY%" exit /b 0
for /f "delims=" %%P in ('where python 2^>nul') do (
    "%%P" -c "import numpy, scipy, pandas, matplotlib" >nul 2>&1 && (
        set "PY=%%P"
        exit /b 0
    )
)
echo.
echo  [ERROR] No encuentro un Python con numpy, scipy, pandas y matplotlib.
echo  Se busco el venv gpr-win y todos los python del PATH.
exit /b 1
