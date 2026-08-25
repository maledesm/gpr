# Redacción de la tesis (LaTeX)

Acá vive el `.tex` de la tesis. Los dos tenemos una distribución LaTeX
instalada localmente (MiKTeX), así que **no se usa más Prism**: cada uno
compila en su propia PC.

## Compilar

Doble click en **`compilar.bat`**. Corre `pdflatex` + `biber` + `pdflatex` ×2
(el orden que pide `biblatex`), y al terminar borra toda la basura intermedia
(`.aux .bbl .bcf .blg .log .lof .lot .out .run.xml .toc`) — queda solo
`tesis_gpr_fmcw.pdf`. Primera vez en una PC nueva: MiKTeX baja paquetes al
vuelo y puede tardar varios minutos. Después de eso, ~20 segundos por
compilación.

Requiere MiKTeX (<https://miktex.org/download>, alcanza con la instalación
básica) o TeX Live, con `pdflatex` y `biber` en el `PATH`. Si `compilar.bat`
no los encuentra, avisa qué falta.

Si preferís la consola en vez del `.bat`, es lo mismo que hace el script:

```powershell
pdflatex -interaction=nonstopmode -halt-on-error tesis_gpr_fmcw.tex
biber tesis_gpr_fmcw
pdflatex -interaction=nonstopmode -halt-on-error tesis_gpr_fmcw.tex
pdflatex -interaction=nonstopmode -halt-on-error tesis_gpr_fmcw.tex
```

## Flujo de trabajo

1. `git pull` antes de tocar el `.tex` (avisarse si van a editar la misma
   sección al mismo tiempo, como con el resto del repo).
2. Editar `tesis_gpr_fmcw.tex`, compilar con `compilar.bat` y revisar el PDF.
3. `git add` / `commit` / `push`.

No se sube el `.pdf` compilado (queda en `.gitignore` como el resto de las
figuras), salvo que se agregue a mano con `git add -f` como figura final. Los
archivos auxiliares de la compilación (`.aux`, `.log`, etc.) también están en
`.gitignore` — `compilar.bat` ya los borra solo, pero por si corrés
`pdflatex`/`biber` a mano y algo queda tirado, no hace falta que te
preocupes por commitearlos.
