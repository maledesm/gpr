@echo off
rem ===========================================================================
rem  Compila tesis_gpr_fmcw.tex a PDF (pdflatex + biber) y borra toda la
rem  basura intermedia al terminar (.aux .bbl .bcf .blg .log .lof .lot .out
rem  .run.xml .toc). Solo queda tesis_gpr_fmcw.pdf.
rem
rem  Requiere una distribucion LaTeX con pdflatex y biber en el PATH
rem  (MiKTeX: https://miktex.org/download, con instalacion basica alcanza).
rem
rem  La primera vez que corre en una PC nueva, MiKTeX baja paquetes al vuelo
rem  y puede tardar varios minutos. Las corridas siguientes tardan ~20 s.
rem ===========================================================================
title GPR - Compilar tesis

cd /d "%~dp0"

where pdflatex >nul 2>nul
if errorlevel 1 (
    echo.
    echo  [ERROR] No encuentro pdflatex en el PATH.
    echo  Instala MiKTeX ^(https://miktex.org/download^) o TeX Live y volve a intentar.
    echo.
    pause
    exit /b 1
)

where biber >nul 2>nul
if errorlevel 1 (
    echo.
    echo  [ERROR] No encuentro biber en el PATH ^(hace falta para la bibliografia^).
    echo  En MiKTeX se instala solo la primera vez que se necesita; si tenes
    echo  instalacion basica y "instalar paquetes automaticamente" desactivado,
    echo  activalo en el MiKTeX Console.
    echo.
    pause
    exit /b 1
)

echo Compilando tesis_gpr_fmcw.tex...
echo.

pdflatex -interaction=nonstopmode -halt-on-error tesis_gpr_fmcw.tex >nul
if errorlevel 1 goto :error

biber tesis_gpr_fmcw >nul
if errorlevel 1 goto :error

pdflatex -interaction=nonstopmode -halt-on-error tesis_gpr_fmcw.tex >nul
if errorlevel 1 goto :error

pdflatex -interaction=nonstopmode -halt-on-error tesis_gpr_fmcw.tex >nul
if errorlevel 1 goto :error

del /q tesis_gpr_fmcw.aux tesis_gpr_fmcw.bbl tesis_gpr_fmcw.bcf tesis_gpr_fmcw.blg tesis_gpr_fmcw.lof tesis_gpr_fmcw.log tesis_gpr_fmcw.lot tesis_gpr_fmcw.out tesis_gpr_fmcw.run.xml tesis_gpr_fmcw.toc 2>nul

echo Listo: tesis_gpr_fmcw.pdf
echo.
exit /b 0

:error
echo.
echo  [ERROR] Fallo la compilacion. Revisa tesis_gpr_fmcw.log para el detalle
echo  ^(no se borro, junto con el resto de los archivos auxiliares^).
echo.
pause
exit /b 1
