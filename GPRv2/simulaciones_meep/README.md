# Simulaciones MEEP del banco GPRv2

Recrea la medición de las bocinas contra la placa metálica, con los cables y
el procesamiento reales del banco.

> **La explicación completa** (la física, cada paso, cada parámetro, cómo leer
> cada figura y qué es cada pico) está en **[COMO_FUNCIONA.md](COMO_FUNCIONA.md)**.
> Este README es solo para correrlo.

## Cómo se corre

**Doble click en `GPRv2/simular.bat`.** Arriba de todo tiene un bloque con lo
que se puede cambiar: nombre de la corrida, qué correr, distancia de la placa,
barrido, hueco entre las bocas, ancho de la placa, **las medidas de la bocina**
(en cm y por fuera, como el croquis), carga de la sonda, cables, retardo
interno, resolución y Tprf. Corre MEEP en WSL, después el
procesamiento en Windows, y abre las figuras. Los valores del `.bat` pisan los
de `parametros.py` solo para esa corrida, vía variables `GPR_SIM_*`; dejar uno
vacío usa el de `parametros.py`.

Cada corrida queda en **su propia carpeta**, `salidas/<NOMBRE>/`:

| archivo | qué es |
|---|---|
| `escena.png` | el campo Ez en tres instantes, con el metal encima |
| `espectro.png` | la FFT en Hz, con cada pico explicado |
| `barrido.png` | frecuencia del eco contra distancia real, con la recta ideal `4B·d/(c·Tprf)` |
| `resumen_placa.txt`, `resumen_barrido.txt` | lo que sale por consola, encabezado con los parámetros usados |
| `H_*.npz` | lo que calculó MEEP |

Nada de `salidas/` entra a git: se regenera corriendo el `.bat`.

`NOMBRE` vacío arma el nombre solo con los parámetros (`nombre_auto()` en
`parametros.py`): siempre la geometría, y el resto solo si se aparta de la
referencia. Por ejemplo `placa1.00m_hueco10cm_ancho70cm`,
`placa1.00m_hueco10cm_ancho70cm_sonda-corto` o
`barrido0.75-1.50m_hueco10cm_ancho70cm_cable-ideal_tau1.5ns`. Con el mismo
nombre, la corrida nueva pisa a la anterior.

A mano, paso por paso (sin `GPR_SIM_NOMBRE`, los dos lados arman el mismo
nombre automático):

```bash
# 1. FDTD, en WSL (env conda `meep`). ~4 s por escena.
wsl -d Ubuntu -- bash /mnt/c/Users/mogic/Tesis/gpr/GPRv2/simulaciones_meep/correr_meep.sh            # placa a 1 m + vacío
wsl -d Ubuntu -- bash /mnt/c/Users/mogic/Tesis/gpr/GPRv2/simulaciones_meep/correr_meep.sh barrido    # placa a 0,75/1/1,25/1,5 m

# 2. Radar, en el Python de Windows (el mismo de vivo_rapido.py)
python correr.py      # placa a 1 m: escena.png, espectro.png, resumen_placa.txt
python barrido.py     # recta d_ap = a*d_real + b -> barrido.png, resumen_barrido.txt
```

## Cómo está armado

| archivo | corre en | qué hace |
|---|---|---|
| `parametros.py` | los dos | geometría (del croquis [`mediciones/mediciones_antena.png`](../mediciones/mediciones_antena.png), leído en [`mediciones/README.md`](../mediciones/README.md)), banda, retardos, lo que pisa el `.bat`, nombre de la carpeta |
| `escena.py` | WSL / meep | FDTD 2D de banda ancha → `H(f)` sonda TX → sonda RX |
| `radar.py` | Windows | `H(f)` + cables (S21 **medido** con el VNA) + τ interno → batido → pipeline de `analisis/` |
| `correr.py`, `barrido.py` | Windows | placa a una distancia, y barrido de distancias |

**Por qué banda ancha y no un chirp como `chirp_v7.py`.** La escena es
lineal e invariante, así que queda descripta por `H(f)`, y el batido es
`½·Re{H(f(t))}` leído a lo largo de la rampa. Con eso el FDTD no depende del
Tprf, se usa la rampa real de 50 ms con la curva medida del VCO, y el batido
sintético pasa por **las mismas funciones** que una captura: `eje_theta()`,
`remuestrear()`, `fs_theta()`. Derivación en
[COMO_FUNCIONA.md](COMO_FUNCIONA.md#2-la-idea-central-hf-en-vez-de-un-chirp).

**La carga de la sonda (`SONDA`).** En el banco cada sonda está conectada a
50 Ω y se lleva lo que vuelve a entrar a la bocina; en MEEP no hay 50 Ω. Con
`adaptada` (la de siempre) la guía no tiene corto y termina en el PML, que
absorbe como una carga perfecta. Con `corto` la bocina es una cavidad cerrada
que devuelve todo. El banco está entre las dos. Ver
[COMO_FUNCIONA.md](COMO_FUNCIONA.md#5-la-carga-de-la-sonda-sonda).

## Resultados (2026-09-22, 2D, resolución 20)

Bocina de 18 cm de guía, 33,5 de tramo recto, 19 de flare y boca de 30,5
(por fuera, chapa de 1 mm). Placa de 70 cm, bocas separadas 10 cm (centros a
40,5 cm), 2 m de RG-213 con el S21 medido. Rampa 50 ms (Tprf 100 ms): **138,6 Hz/m =
4B/(c·Tprf)** con B = 1039,6 MHz; resolución 14,4 cm.

| placa a 1 m | modelo | sonda adaptada | sonda corto |
|---|---|---|---|
| eco, sin cables | 1,469 m | **1,593 m** | 1,662 m |
| eco, con cables | 2,924 m | **3,049 m = 423 Hz** | 3,119 m = 432 Hz |
| acoplamiento directo, con cables | 2,126 m | 2,088 m = 290 Hz | 2,156 m = 299 Hz |
| rebote adentro de la bocina (D) | — | −30 dB | −4 dB |

La tabla es **sin retardo interno** (`TAU_INTERNO_NS=0`), para separar lo
que pone cada pieza. Con los **4 ns por defecto** todo se corre +0,60 m =
+83 Hz: el eco con cables cae en **506 Hz**, y la captura del banco lo da
en ~505.

Barrido de distancia, `d_ap = a·d_real + b`:

- **pendiente a = 0,997** → 138,2 Hz/m simulados contra 138,6 del ideal.
  Todo lo que no es aire es un offset puro. La pendiente no depende del
  Tprf (a 80 ms: 172,8 contra 173,3 Hz/m) ni de la sonda.
- **offset de los cables: 1,456 m** simulado contra 1,455 m del VNA.
- **offset de las bocinas: 0,595 m** (adaptada) o **0,660 m** (corto). De eso,
  0,469 m es el largo físico sonda→apertura, y el resto (0,13 a 0,19 m) es
  exceso: cerca del corte del modo guiado la onda viaja más lenta que c, y
  con el corto se suma la parte que va y vuelve al fondo.

## Limitaciones que hay que tener presentes

- **2D.** Pierde el 1/r² y el recorte de la placa en la otra dimensión: las
  POSICIONES valen, los NIVELES no se comparan con el banco.
- **El acoplamiento directo sale ~46 dB por debajo del eco**, y en el banco es
  lo más fuerte de la pantalla. MEEP solo ve el camino por el aire; en el
  banco domina la fuga interna (splitter, mezclador, cables juntos). Es lo que
  trata `docs/refs/park2018_leakage_internal_delay.pdf`.
- **`TAU_INTERNO = 4 ns` está ajustado, no medido**: es lo que hace
  coincidir el eco con la captura del banco (cables de 1 m, placa a 1 m,
  ~505 Hz), y depende del modelo de la sonda (3,5 a 4 ns). Para medirlo
  directo: barrel entre los cables de TX y RX, sin antenas. Ver
  [COMO_FUNCIONA.md](COMO_FUNCIONA.md#comparación-con-el-banco-2026-09-22).
- **La sonda es un extremo o el otro**: el banco adapta bien a ~1,5 GHz y peor
  en los bordes de la banda.
- Las paredes se simulan de 1 cm (la grilla no resuelve 1 mm), puestas
  **hacia afuera** de la cara interior: la guía queda de 17,8 cm por dentro,
  como la real. Falta confirmar el espesor de la chapa, cuál conector es el
  de TX y si las bocinas están paralelas: ver
  [`mediciones/README.md`](../mediciones/README.md).
