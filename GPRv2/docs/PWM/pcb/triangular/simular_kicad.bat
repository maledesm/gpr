@echo off
rem GPRv2 - Simula el esquematico de KiCad en LTspice.
rem 1) simular_kicad.py exporta el netlist de triangular.kicad_sch y arma triangular_kicad.cir
rem 2) se abre en el LTspice 24 y arranca solo (-Run). Tarda ~1 minuto.
rem Guarda el esquematico en KiCad antes de correrlo.

cd /d "%~dp0"

py simular_kicad.py
if errorlevel 1 (
    echo.
    echo Fallo la exportacion del netlist. Revisa el mensaje de arriba.
    pause
    exit /b 1
)

start "" "C:\Program Files\LTC\LTspice.exe" -Run "%~dp0triangular_kicad.cir"
