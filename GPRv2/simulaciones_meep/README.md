# Simulaciones MEEP del banco GPRv2

Recrea la medición de las bocinas contra la placa metálica, con los cables y
el procesamiento reales del banco.

## Cómo se corre

**Doble click en `GPRv2/simular.bat`.** Arriba de todo tiene un bloque con lo
que se puede cambiar (distancia de la placa, barrido, separación de las
bocinas, ancho de la placa, cables, retardo interno, resolución). Corre MEEP
en WSL, después el procesamiento en Windows, y abre las figuras. Los valores
del `.bat` pisan los de `parametros.py` solo para esa corrida, vía variables
`GPR_SIM_*`; dejar uno vacío usa el de `parametros.py`.

A mano, paso por paso:

```bash
# 1. FDTD, en WSL (env conda `meep`). ~3 s por escena.
wsl -d Ubuntu -- bash /mnt/c/Users/mogic/Tesis/gpr/GPRv2/simulaciones_meep/correr_meep.sh            # placa a 1 m + vacío
wsl -d Ubuntu -- bash /mnt/c/Users/mogic/Tesis/gpr/GPRv2/simulaciones_meep/correr_meep.sh barrido    # placa a 0,75/1/1,25/1,5 m

# 2. Radar, en el Python de Windows (el mismo de vivo_rapido.py)
python correr.py      # placa a 1 m: picos contra el modelo -> salidas/placa_1m.png
python barrido.py     # recta d_ap = a*d_real + b         -> salidas/barrido_distancia.png
```

## Cómo está armado

| archivo | corre en | qué hace |
|---|---|---|
| `parametros.py` | los dos | geometría (del croquis `GPRv2/medidas.png`), banda, retardos. Sin nada del barrido |
| `escena.py` | WSL / meep | FDTD 2D de banda ancha → `H(f)` sonda TX → sonda RX, en `salidas/H_*.npz` |
| `radar.py` | Windows | `H(f)` + cables (S21 **medido** con el VNA) + τ interno → batido → pipeline de `analisis/` |
| `correr.py`, `barrido.py` | Windows | las dos comparaciones |

**Por qué banda ancha y no un chirp como `chirp_v7.py`.** La escena es
lineal e invariante, así que queda descripta por `H(f)`, y el batido es
`½·Re{H(f(t))}` leído a lo largo de la rampa (derivación en `radar.py`). Con
eso el FDTD no depende del Tprf, se usa la rampa real de 50 ms con la curva
medida del VCO, y el batido sintético pasa por **las mismas funciones** que
una captura: `eje_theta()`, `remuestrear()`, `fs_theta()`.

## Resultados (2026-09-21, 2D, resolución 20)

Rampa 50 ms (Tprf 100 ms), 138,6 Hz/m, resolución 14,4 cm.

| | modelo | simulado |
|---|---|---|
| placa a 1 m, sin cables | 1,466 m | **1,637 m** |
| placa a 1 m, con 2 m de RG-213 | 2,921 m | **3,093 m = 429 Hz** |
| acoplamiento directo, con cables | 2,074 m | 2,085 m = 289 Hz |

Barrido de distancia, `d_ap = a·d_real + b`:

- **pendiente a = 0,993** → todo lo que no es aire es un offset puro.
- **offset de los cables: 1,456 m** simulado contra 1,455 m del VNA.
- **offset de las bocinas: 0,652 m**, de los cuales 0,466 m es el largo
  físico sonda→apertura y **0,186 m (1,24 ns ida y vuelta) es exceso**: la
  guía de 18 cm tiene el corte TE10 en 833 MHz y el VCO arranca en 942, así
  que viaja lenta cerca del corte. Eso explica ~7 cm; el resto es el flare y
  el centro de fase de la bocina (no está separado todavía).

## Limitaciones que hay que tener presentes

- **2D.** Pierde el 1/r² y el recorte de la placa en la otra dimensión: las
  POSICIONES valen, los NIVELES no se comparan con el banco.
- **El acoplamiento directo sale 40 dB por debajo del eco**, y en el banco es
  lo más fuerte de la pantalla. MEEP solo ve el camino por el aire; en el
  banco domina la fuga interna (splitter, mezclador, cables juntos). Es lo que
  trata `docs/refs/park2018_leakage_internal_delay.pdf`.
- **`TAU_INTERNO = 0`.** Splitter, mezclador y LNA no están medidos. Con una
  captura real de la placa a 1 m: `b` de la calibración − 1,456 (cables) −
  0,652 (bocinas) = retardo interno, sin suponer nada.
- Cotas del croquis a confirmar: sonda a 5,9 cm del corto y separación entre
  bocinas = una apertura (30,5 cm). Ver `parametros.py`.
