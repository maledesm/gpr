# Mediciones del sistema

Medidas físicas del banco GPRv2: las bocinas, cómo están armadas y los
blancos. Es de donde salen los números de la simulación
(`simulaciones_meep/parametros.py` y el bloque de la bocina de
`simular.bat`).

Los cables tienen su propia carpeta, con las mediciones del VNA:
[`docs/CABLES/`](../docs/CABLES/). Las capturas del radar están en
[`datos/capturas/`](../datos/capturas/).

## Las bocinas: [`mediciones_antena.png`](mediciones_antena.png)

Croquis tomado por Martín. Cómo se lee cada cota (confirmado por Santiago el
2026-09-22):

> **Todo se midió POR FUERA.** La bocina es de **chapa fina** (~1 mm, a
> confirmar), no tiene paredes gruesas.

| cota | qué es | se usa en la simulación |
|---|---|---|
| **18 cm** | ancho de la guía de onda (sección de 18 × 9 cm) | sí: es el lado que entra en el plano 2D y fija el corte del modo guiado |
| **9 cm** (rectángulo en la vista de frente) | el lado corto de la guía | no: queda fuera del plano 2D |
| **30,5 × 30,5 cm** | la boca, cuadrada | sí |
| **52,5 cm** | largo total, del fondo a la boca | sí |
| **33,5 cm** | tramo **recto** de la guía, del fondo hasta donde se abre la bocina | sí |
| — | el **flare** (la parte que se abre) es lo que queda: 52,5 − 33,5 = **19 cm** | sí (se calcula) |
| **5,9 y 5,4 cm** | distancia de los **conectores** (las sondas) al fondo, uno en cada bocina. No se anotó cuál es cuál | sí: se toma 5,9 para TX y 5,4 para RX. La diferencia pesa 2,5 mm de distancia aparente |
| **29,5 cm** | del fondo al conector del **soporte de PVC** | no |
| **3,5 cm** | radio del soporte de PVC | no |
| rectángulo de arriba, **30,4 × 22,4 cm**, 4 agujeros, **H = 13,5 cm** | la **caja del radar** | no |

Martín anotó 52,5 de largo total; la suma de las partes puede dar ~53 cm. Los
0,5 cm de diferencia no cambian nada que se vea con la resolución del radar
(14,4 cm).

### Cómo las usa la simulación

La onda ve la superficie **interior** de la chapa, así que la simulación
resta el espesor de la chapa a cada medida exterior:

| | por fuera | por dentro (chapa de 1 mm) |
|---|---|---|
| guía | 18 cm | 17,8 cm → corte del modo en **842 MHz** |
| boca | 30,5 cm | 30,3 cm |
| largo | 52,5 cm | 52,4 cm |

MEEP no resuelve una chapa de 1 mm con celdas de 7,5 mm, así que las paredes
se simulan de 1 cm, pero **hacia afuera** de la superficie interior. Así lo
que ve la onda queda donde corresponde.

El corte del modo guiado importa: el VCO arranca en 942 MHz, apenas arriba
de los 842, y cerca del corte la onda viaja más lenta que c. Eso es parte de
lo que las bocinas agregan a la distancia aparente. Antes del 2026-09-22 la
simulación tenía la guía de 17 cm por dentro (corte en 882 MHz) y el tramo
recto de 29,5 cm (la cota del soporte, mal leída).

Para cambiar cualquiera de estas medidas no hace falta tocar código: están
en el bloque "La bocina" de [`simular.bat`](../simular.bat), en centímetros y
por fuera, igual que en el croquis.

## El armado en el banco

| | valor | de dónde |
|---|---|---|
| hueco entre las bocas, borde a borde | **10 cm** (centros a 40,5 cm) | medido en el banco, 2026-09-21 |
| placa metálica (blanco) | **~70 cm** de ancho | medido en el banco, 2026-09-21 |
| distancia de la boca a la placa en las capturas | **1 m** | `datos/capturas/` |
| cables de antena | 2 × RG-213 de 1 m (nuevos) o RG-58 de 3 m y 2,6 m (viejos) | ver `docs/CABLES/` |

## Falta medir o confirmar

- **Espesor de la chapa.** Se supone 1 mm; la diferencia entre 0,5 y 2 mm
  mueve la guía interior unos pocos mm.
- **Cuál conector (5,9 o 5,4 cm) es de la bocina TX.**
- **Si las bocinas están paralelas** o giradas una hacia la otra. La
  simulación las pone paralelas, mirando de frente a la placa.
- **Cuánto entra la sonda en la guía** (el largo del vivo del conector). La
  simulación 2D no lo usa, pero sirve para una versión 3D.
