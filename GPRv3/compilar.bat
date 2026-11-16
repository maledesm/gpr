@echo off
rem Compila el firmware con arduino-cli. Con un puerto, ademas lo carga:
rem     compilar.bat          solo compila
rem     compilar.bat COM5     compila y carga (Monitor Serie cerrado)
title GPRv3 - Compilar firmware
cd /d "%~dp0"
set "ACLI=arduino-cli"
where arduino-cli >nul 2>&1 || set "ACLI=%ProgramFiles%\Arduino CLI\arduino-cli.exe"
set "PLACA=esp32:esp32:nologo_esp32c3_super_mini"
if "%~1"=="" (
    "%ACLI%" compile --fqbn %PLACA% "firmware\adquisicion_sync"
) else (
    "%ACLI%" compile --fqbn %PLACA% --upload -p %1 "firmware\adquisicion_sync"
)
echo.
pause
