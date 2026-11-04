@echo off
rem ===========================================================================
rem  Compila plan_tpp.tex (plan de TPP) a PDF (pdflatex + biber) y borra toda la
rem  basura intermedia al terminar (.aux .bbl .bcf .blg .log .lof .lot .out
rem  .run.xml .toc). Solo queda plan_tpp.pdf.
rem
rem  Requiere una distribucion LaTeX con pdflatex y biber en el PATH
rem  (MiKTeX: https://miktex.org/download, con instalacion basica alcanza).
rem
rem  La primera vez que corre en una PC nueva, MiKTeX baja paquetes al vuelo
rem  y puede tardar varios minutos. Las corridas siguientes tardan ~20 s.
rem ===========================================================================
title GPR - Compilar plan de TPP

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

echo Compilando plan_tpp.tex...
echo.

pdflatex -interaction=nonstopmode -halt-on-error plan_tpp.tex >nul
if errorlevel 1 goto :error

biber plan_tpp >nul
if errorlevel 1 goto :error

pdflatex -interaction=nonstopmode -halt-on-error plan_tpp.tex >nul
if errorlevel 1 goto :error

pdflatex -interaction=nonstopmode -halt-on-error plan_tpp.tex >nul
if errorlevel 1 goto :error

del /q plan_tpp.aux plan_tpp.bbl plan_tpp.bcf plan_tpp.blg plan_tpp.lof plan_tpp.log plan_tpp.lot plan_tpp.out plan_tpp.run.xml plan_tpp.toc 2>nul

echo Listo: plan_tpp.pdf
echo.
exit /b 0

:error
echo.
echo  [ERROR] Fallo la compilacion. Revisa plan_tpp.log para el detalle
echo  ^(no se borro, junto con el resto de los archivos auxiliares^).
echo.
pause
exit /b 1
