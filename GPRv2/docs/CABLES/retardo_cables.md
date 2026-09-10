# El retardo de los cables en un FMCW

> Resuelto el 2026-09-05 en el banco. Explica por qué una placa a 1 m aparecía
> a varios metros, y por qué al mismo tiempo *acercarla bajaba la frecuencia y
> alejarla la subía*: el radar medía bien, sólo que desde otro origen.

## El punto de partida

Un FMCW **no mide la distancia al blanco**. Mide la **diferencia de retardo
entre las dos entradas del mezclador**, y recién después esa diferencia se
traduce a distancia suponiendo que todo el retardo fue aire.

Los cables están de un solo lado de esa diferencia. Entonces se suman.

```
  camino del LO  (corto)
      VCO ─ splitter ──────[ L_LO ]───────────────────────────────► mezclador (LO)

  camino de RF  (largo)
      VCO ─ splitter ──[ L_TX ]── antena TX ─)))  2R  (((─ antena RX ──[ L_RX ]── LNA ──► mezclador (RF)


  el mezclador ve la DIFERENCIA de los dos:

      Δt  =  (L_TX + L_RX − L_LO) / (v_p)   +   2R / c₀
             └────────── los cables ──────┘      └ el blanco ┘
                    NO depende del blanco         lo que se quiere medir
```

El montaje, dibujado como está sobre la mesa:

```
                        ┌──────────┐   L_LO ≈ 5 cm (conexion DIRECTA,
             VCO ──────►│ splitter ├─────────────────  sin cable)
                        └────┬─────┘                          │
                             │ L_TX = 3 m                     ▼
                        ┌────▼────┐                    ┌─────────────┐
                        │antena TX│                    │  mezclador  │──► IF
                        └────┬────┘                    └──────▲──────┘
                             │                                │
                             │  2R por el aire            ┌───┴───┐
                             │  (R = 1 m → 2 m)           │  LNA  │
                             │                            └───▲───┘
                        ┌────▼────┐      L_RX = 2,6 m         │
                        │antena RX├───────────────────────────┘
                        └─────────┘
```

**El camino del LO no tiene cable.** El splitter y el mezclador se conectan
directamente: son ~5 cm, que aportan 0,25 ns = 3,8 cm de distancia aparente,
muy por debajo de la resolución de 14,4 cm. Se desprecia en todos los
cálculos, así que **D ≈ L_TX + L_RX**.

No es una buena noticia: `L_LO` es el único término que RESTA, y no está
restando nada.

## La cuenta

Definiciones, con la notación del cuaderno:

| símbolo | qué es | valor del banco |
|---|---|---|
| `BW` | ancho de barrido | 1 GHz (943 → 1982 MHz medidos) |
| `T_PRF` | período de la triangular | 40 ms |
| `T_rampa` | **medio** período: la rampa de subida | 20 ms |
| `μ` | pendiente del chirp, `BW / T_rampa` | **50 GHz/s** |
| `v_p` | velocidad en el coaxil, `VF·c₀` | 2/3·c₀ ≈ 200 000 km/s |
| `D` | coaxil neto, `L_TX + L_RX − L_LO` | **5,55 m** (3 + 2,6 − 0,05) |
| `R` | distancia real al blanco | 1 m |

**1. Cuánto tarda la señal en los cables**

```
    Δt_c = D / v_p = 5,55 m / 200 000 km/s = 27,8 ns
```

**2. Cuánto "aire" le parece eso al radar** — la distancia aparente `D̃` es la
que el aire recorrería en ese mismo tiempo:

```
    D̃ = Δt_c · c₀ = (D / v_p) · c₀ = D · c₀/(⅔c₀) = (3/2)·D

    D̃ = (3/2) · 5,55 m = 8,33 m
```

> El factor **3/2 es 1/VF**. Ahí está la trampa: el coaxil es *más lento* que
> el aire, así que 5,55 m de cable le parecen 8,33 m de aire al radar.

**3. El recorrido total que ve el mezclador**, sumando la ida y vuelta al
blanco:

```
    D_T = D̃ + 2R = 8,33 m + 2 m = 10,33 m

    Δt_T = D_T / c₀ = 10,33 / 3·10⁸ = 34,4 ns
```

**4. La frecuencia de batido**

```
    f_beat = μ · Δt_T = 50·10⁹ · 34,4·10⁻⁹ = 1721 Hz     ← con los coaxiles
    f_beat = μ · 2R/c₀ = 50·10⁹ · 6,67·10⁻⁹ = 333 Hz     ← sin ellos
                                              ────────
                        los coaxiles agregan    1388 Hz
```

**Los 5,55 m de coaxil pesan 4,2 veces más que el blanco.**

## Lo importante: es un OFFSET, no una escala

Lo que el software informa como distancia es `R_est = c₀·Δt/2`, así que:

```
    R_est  =  R  +  D̃/2  =  R  +  D / (2·VF)
              ↑     ↑
        lo real   constante: no depende del blanco
```

De ahí las tres consecuencias que se vieron en el banco:

- **La pendiente es 1.** Mover el blanco 1 m mueve la lectura 1 m. Por eso
  "se acerca y baja, se aleja y sube" funcionaba perfecto.
- **El error es constante**, y se saca con una resta.
- **La resolución no se toca.** Sigue valiendo `c/(2·BW)` = 14,4 cm.

Cada metro de coaxil aporta `1/(2·VF)` metros de offset — **0,75 m por metro**
con VF = 2/3. Ojo con esto: **el cable se recorre una sola vez**, así que va
`c·Δt/2` sin el factor 2 del ida y vuelta. Por eso 5 ns de cable son 0,75 m de
offset y no 1,5.

| tipo de cable | VF | ns/m | offset por metro |
|---|---|---|---|
| RG-58 / RG-174 | 0,66 | 5,05 | **0,76 m** |
| semirrígido PTFE | 0,70 | 4,76 | 0,71 m |
| RG-8X espuma | 0,78 | 4,27 | 0,64 m |

## Tablas

**Offset según el cableado** (no depende del `T_PRF`):

Las dos primeras filas son los juegos reales; el resto es qué pasaría si se
le agregara cable al LO para emparejar.

| L_TX | L_RX | L_LO | neto `D` | `D̃` | **offset `D̃/2`** |
|---|---|---|---|---|---|
| **3 m** | **2,6 m** | **0,05 m** ← hoy | 5,55 m | 8,33 m | **4,20 m** |
| **1 m** | **1 m** | **0,05 m** ← RG-213 | 1,95 m | 2,93 m | **1,48 m** |
| 1 m | 1 m | 0,5 m | 1,5 m | 2,25 m | 1,14 m |
| 1 m | 1 m | 1,0 m | 1,0 m | 1,50 m | 0,76 m |
| 1 m | 1 m | 2,0 m | 0 | 0 | **0** (emparejado) |

**En frecuencia, para un blanco a 1 m** (BW = 1 GHz, cables de 3 y 2,6 m, LO
directo):

| `T_PRF` | `T_rampa` | `μ` | Hz/m | sin cables | con cables | agregan |
|---|---|---|---|---|---|---|
| **40 ms** | 20 ms | 50 GHz/s | 334 | 334 Hz | **1736 Hz** | 1402 Hz |
| **80 ms** | 40 ms | 25 GHz/s | 167 | 167 Hz | **868 Hz** | 701 Hz |
| 160 ms | 80 ms | 12,5 GHz/s | 83 | 83 Hz | 434 Hz | 351 Hz |

La fila de 80 ms es la que cierra con lo observado en el banco: **"a 1 m era
más de 800 Hz"**.

## Lo que sí cuesta

El offset no arruina la medición, pero **se come parte del alcance no
ambiguo**: consume presupuesto de Nyquist antes de que empiece el blanco.

Con `SPS_SALIDA` = 6000 (Nyquist 3000 Hz) y el offset de 4,20 m:

| `T_PRF` | Hz/m | alcance aparente | menos el offset | **útil** |
|---|---|---|---|---|
| 40 ms | 334 | 9,0 m | −4,20 m | **4,8 m** |
| 80 ms | 167 | 18,0 m | −4,20 m | **13,8 m** |
| 160 ms | 83 | 36,0 m | −4,20 m | **31,8 m** |

**Con estos cables conviene el `T_PRF` largo.** A 40 ms quedan menos de 5 m
útiles.

Con los RG-213 de 1 m el offset baja a 1,48 m y a 40 ms quedan **7,5 m
útiles**, o sea que acortar los cables recupera alcance además de precisión.

El otro costo, más sutil: el acoplamiento directo TX→RX (las antenas a
~0,15 m) también se corre al offset, así que aparece justo donde caen los
blancos cercanos, en vez de quedar pegado al cero donde es fácil ignorarlo.
Para eso está la resta de fondo de `vivo.py`.

## Cómo sacarlo

**1. Medirlo directo, sin blanco** — es lo más limpio y no depende de saber
dónde está nada. Unir el cable de TX con el de RX por un barrel, salteando
las antenas y el aire:

```
   splitter ──[ L_TX ]──┐
                        ├── barrel + atenuador
   LNA ◄────[ L_RX ]────┘
```

El batido que quede **es** el offset, con `R = 0`. Poner un atenuador para no
saturar el LNA ni el mezclador.

**2. Un punto de calibración.** En `vivo.py`: poner un blanco a distancia
conocida, tipearla en `dist. real [m]`, `tomar punto`, `calibrar`. Con un
solo punto ajusta nada más el offset y deja la pendiente en 1, que es lo
físicamente correcto. Al calibrar imprime el offset traducido a nanosegundos
y a metros de coaxil, para ver si el número cierra con el cableado real.

**3. Con dos o más puntos**, además ajusta la pendiente — y eso es la
**verificación**: tiene que dar ~1. Si da lejos de 1 no son los cables, y lo
primero a revisar es el período de la triangular.

**4. Emparejar los caminos**: agregarle al LO tanto cable como `L_TX + L_RX`.
Como hoy el LO es una conexión directa, serían los 5,55 m enteros: deja el
offset en cero de raíz, pero agrega ~3,5 dB de pérdida en el LO, que el
mezclador puede necesitar para conmutar bien. Con los RG-213 de 1 m serían
2 m y ~0,7 dB, bastante más razonable. No hace falta para medir bien; sí
ayuda al presupuesto de alcance.

## Verificación sobre datos reales

Reprocesando la captura del 2026-09-04 con el período correcto (80 ms, ver
`GPRv2/CLAUDE.md`), el pico dominante cae en **5,31 m**. Restando el offset
queda la placa en **1,11 m** (con los 4,20 m calculados) o **1,48 m** (con
los 3,83 m que midió el VNA), contra ~1 m real.

⚠️ Este párrafo decía antes "1,14 m", restando un offset de 4,17 m que salía
de suponer dos cables de 3 m y 0,5 m al LO. Los dos errores casi se
cancelaban. El orden de magnitud siempre estuvo bien, pero **el ajuste fino
era casualidad**: para validar de verdad hay que medir el offset directo con
el barrel (opción 1).
