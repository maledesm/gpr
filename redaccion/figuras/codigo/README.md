# Figuras del código (GPRv2)

Generadas desde el fuente. **No se editan a mano.**

## Tres vistas, porque son tres preguntas distintas

Un solo diagrama con todas las llamadas no se entiende: `vivo_rapido.py`
tiene 53 funciones y 81 llamadas, y dibujadas todas juntas quedan al mismo
nivel, sin jerarquía y sin por dónde empezar a leer. Un grafo de llamadas no
es un diagrama de flujo.

| Vista | Pregunta que responde | Dónde usarla |
|---|---|---|
| `mapa_proyecto` | ¿Qué piezas hay y cuál depende de cuál? | Abrir el capítulo de software |
| `modulos_*` | ¿Cómo se reparten las responsabilidades dentro de este archivo? | **El cuerpo de la tesis** |
| `llamadas_*` | ¿Quién llama exactamente a quién? | Apéndice, o consulta puntual |

En `modulos_*` las cajas son las **clases y las funciones de nivel superior**,
no los métodos: las llamadas entre métodos de dos clases se agregan en una
sola flecha con la cantidad al lado, y cada caja dice cuántos métodos agrupa.
`vivo_rapido.py` pasa de 53 cajas a 7.

## Regenerar

Si cambió el código, desde `GPRv2/`:

```
graphify update .
```

Re-parsea los fuentes y actualiza `GPRv2/graphify-out/graph.json`. No usa
modelo de lenguaje ni tiene costo.

Después, desde `GPRv2/docs/`:

```
python diagrama_llamadas.py
```

Por defecto genera `proyecto` + `modulos`, que son las dos útiles. Opciones:
`--vista completo` (el apéndice), `--listar`, `--archivo vivo_rapido`,
`--formato png`, `--todos`.

Requiere Graphviz (`dot`) en el PATH.

## Incluir en la tesis

```latex
\begin{figure}[H]
  \centering
  \includegraphics[width=\linewidth]{figuras/codigo/modulos_vivo_rapido.pdf}
  \caption{Estructura de \texttt{analisis/vivo\_rapido.py}. Las cajas son las
  clases y las funciones de nivel superior; entre paréntesis, la cantidad de
  métodos que agrupa cada clase. El número sobre una flecha es la cantidad de
  llamadas distintas entre las dos cajas. \texttt{main()} tiene doble borde
  por ser el punto de entrada. Diagrama generado a partir del AST del fuente.}
  \label{fig:modulos_vivo_rapido}
\end{figure}
```

Son PDF vectoriales: escalan sin pixelarse y el texto queda seleccionable.

## Cómo leerlas

- **Doble borde**: punto de entrada (`setup`, `loop`, `main`, ISR).
- **Número sobre la flecha**: cantidad de llamadas agregadas (solo en `modulos_*`).
- **Flecha punteada**: llamada indirecta.
- **Caja gris clara** (solo en `llamadas_*`): método de un objeto externo
  (`.write()`, `.begin()`), o sea de una biblioteca.
- Cada caja dice `archivo:línea`.

## Qué NO muestran

Las flechas salen del AST: son llamadas e imports escritos literalmente en el
código. Todas las aristas están marcadas `EXTRACTED`, ninguna inferida por un
modelo de lenguaje. Eso las hace citables, pero deja afuera todo lo que no es
una llamada escrita:

- punteros a función y tablas de despacho,
- las ISR: el hardware las dispara, ninguna línea las llama. Se dibujan igual,
  con doble borde y sin flechas entrantes, porque **que aparezcan sueltas es
  el dato**. En `modulos_adquisicion` eso es `isrSync()`,
- callbacks registrados en tiempo de ejecución (`attachInterrupt`, el stack
  de I2S, los widgets de matplotlib),
- lo que expanden las macros.

En el firmware esto no es menor: **el sincronismo entre el barrido y el
muestreo pasa justamente por esos enlaces**, y no está dibujado. Si una
figura de firmware va en la tesis, ese camino hay que explicarlo en el texto.

Tampoco se dibujan los nodos `rationale` que arma graphify a partir de los
docstrings: en `vivo_rapido.py` son 40 de 47 nodos y tapaban por completo las
7 que importan.

## Estado actual

`mapa_proyecto` — 15 archivos, 13 dependencias. Muestra que
`correccion_no_linealidad.py` es la biblioteca núcleo (la importan siete
archivos) y que `generador_chirp.ino` + `tabla_chirp.h` son un subsistema
aparte, sin conexión con el resto.

| Archivo | `modulos_*` | `llamadas_*` |
|---|---|---|
| `analisis/vivo_rapido.py` | 7 cajas, 9 relaciones | 53 funciones, 81 llamadas |
| `analisis/vivo.py` | 5 cajas, 6 relaciones | 39 funciones, 53 llamadas |
| `analisis/cables_vna.py` | 16 cajas, 18 relaciones | 16 funciones, 18 llamadas |
| `analisis/verificar_rapido.py` | 15 cajas, 24 relaciones | 15 funciones, 24 llamadas |
| `analisis/correccion_no_linealidad.py` | 14 cajas, 15 relaciones | 14 funciones, 15 llamadas |
| `firmware/adquisicion/adquisicion.ino` | 10 cajas, 9 relaciones | 10 funciones, 9 llamadas |
| `analisis/proceso_rapido.py` | 8 cajas, 3 relaciones | 8 funciones, 3 llamadas |
| `analisis/experimento_adc3.py` | 6 cajas, 5 relaciones | 6 funciones, 5 llamadas |

Los archivos sin clases (los `.ino` y los módulos de funciones sueltas como
`cables_vna.py`) dan la misma figura en las dos vistas: no hay nada que
agregar. La diferencia se nota solo donde hay clases.

`generador_chirp.ino` no aparece: no tiene ninguna llamada entre funciones
propias. `setup()`, `loop()` y la ISR no se llaman entre sí — todo el trabajo
lo hace la ISR sobre la tabla precalculada. Para generarla igual:
`python diagrama_llamadas.py --archivo generador_chirp --todos`.
