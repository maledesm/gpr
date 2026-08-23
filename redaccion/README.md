# Redacción de la tesis (LaTeX)

Acá vive el `.tex` de la tesis que se está escribiendo en Prism.

Flujo de trabajo:
1. Santiago exporta el `.tex` actual desde Prism y lo sube a esta carpeta
   (reemplazando el archivo existente).
2. Claude edita el `.tex` acá, sección por sección, incorporando bancos de
   trabajo, curvas y resultados del resto del repo.
3. Santiago sube el `.tex` actualizado de vuelta a Prism y compila para
   revisar el resultado.
4. Se hace `git add` / `commit` / `push` como con el resto del repo.

No se sube el `.pdf` compilado (queda en `.gitignore` como el resto de las
figuras), salvo que se agregue a mano con `git add -f` como figura final.
