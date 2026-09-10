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
                        ┌──────────┐        L_LO (corto)
             VCO ──────►│ splitter ├──────────────────────────┐
                        └────┬─────┘                          │
                             │ L_TX ≈ 3 m                     ▼
                        ┌────▼────┐                    ┌─────────────┐
                        │antena TX│                    │  mezclador  │──► IF
                        └────┬────┘                    └──────▲──────┘
                             │                                │
                             │  2R por el aire            ┌───┴───┐
                             │  (R = 1 m → 2 m)           │  LNA  │
                             │                            └───▲───┘
                        ┌────▼────┐      L_RX ≈ 3 m           │
                        │antena RX├───────────────────────────┘
                        └─────────┘
```

## La cuenta

Definiciones, con la notación del cuaderno:

| símbolo | qué es | valor del banco |
|---|---|---|
| `BW` | ancho de barrido | 1 GHz (943 → 1982 MHz medidos) |
| `T_PRF` | período de la triangular | 40 ms |
| `T_rampa` | **medio** período: la rampa de subida | 20 ms |
| `μ` | pendiente del chirp, `BW / T_rampa` | **50 GHz/s** |
| `v_p` | velocidad en el coaxil, `VF·c₀` | 2/3·c₀ ≈ 200 000 km/s |
| `D` | coaxil neto, `L_TX + L_RX − L_LO` | 6 m |
| `R` | distancia real al blanco | 1 m |

**1. Cuánto tarda la señal en los cables**

```
    Δt_c = D / v_p = 6 m / 200 000 km/s = 30 ns
```

**2. Cuánto "aire" le parece eso al radar** — la distancia aparente `D̃` es la
que el aire recorrería en ese mismo tiempo:

```
    D̃ = Δt_c · c₀ = (D / v_p) · c₀ = D · c₀/(⅔c₀) = (3/2)·D

    D̃ = (3/2) · 6 m = 9 m
```

> El factor **3/2 es 1/VF**. Ahí está la trampa: el coaxil es *más lento* que
> el aire, así que 6 m de cable le parecen 9 m de aire al radar.

**3. El recorrido total que ve el mezclador**, sumando la ida y vuelta al
blanco:

```
    D_T = D̃ + 2R = 9 m + 2 m = 11 m

    Δt_T = D_T / c₀ = 11 / 3·10⁸ = 36,7 ns
```

**4. La frecuencia de batido**

```
    f_beat = μ · Δt_T = 50·10⁹ · 36,7·10⁻⁹ = 1833 Hz     ← con los coaxiles
    f_beat = μ · 2R/c₀ = 50·10⁹ · 6,67·10⁻⁹ = 333 Hz     ← sin ellos
                                              ────────
                        los coaxiles agregan    1500 Hz
```

**Los 6 m de coaxil pesan 4,5 veces más que el blanco.**

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

| L_TX | L_RX | L_LO | neto `D` | `D̃` | **offset `D̃/2`** |
|---|---|---|---|---|---|
| 3 m | 3 m | 0 | 6,0 m | 9,00 m | **4,50 m** |
| 3 m | 3 m | 0,5 m | 5,5 m | 8,25 m | **4,12 m** |
| 3 m | 3 m | 1,0 m | 5,0 m | 7,50 m | **3,75 m** |
| 2 m | 2 m | 0,5 m | 3,5 m | 5,25 m | **2,62 m** |
| 1 m | 1 m | 0,5 m | 1,5 m | 2,25 m | **1,12 m** |
| 0,5 m | 0,5 m | 0,5 m | 0,5 m | 0,75 m | **0,38 m** |

**En frecuencia, para un blanco a 1 m** (BW = 1 GHz, cables 2×3 m + 0,5 m al LO):

| `T_PRF` | `T_rampa` | `μ` | Hz/m | sin cables | con cables | agregan |
|---|---|---|---|---|---|---|
| **40 ms** | 20 ms | 50 GHz/s | 333 | 333 Hz | **1708 Hz** | 1375 Hz |
| **80 ms** | 40 ms | 25 GHz/s | 167 | 167 Hz | **854 Hz** | 688 Hz |
| 160 ms | 80 ms | 12,5 GHz/s | 83 | 83 Hz | 427 Hz | 344 Hz |

La fila de 80 ms es la que cierra con lo observado en el banco: **"a 1 m era
más de 800 Hz"**.

## Lo que sí cuesta

El offset no arruina la medición, pero **se come parte del alcance no
ambiguo**: consume presupuesto de Nyquist antes de que empiece el blanco.

Con `SPS_SALIDA` = 6000 (Nyquist 3000 Hz) y un offset de 4,17 m:

| `T_PRF` | Hz/m | alcance aparente | menos el offset | **útil** |
|---|---|---|---|---|
| 40 ms | 333 | 9,0 m | −4,17 m | **4,8 m** |
| 80 ms | 167 | 18,0 m | −4,17 m | **13,8 m** |
| 160 ms | 83 | 36,0 m | −4,17 m | **31,8 m** |

**Con estos cables conviene el `T_PRF` largo.** A 40 ms quedan menos de 5 m
útiles.

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
Deja el offset en cero de raíz, pero son ~6 m más de coaxil y 4-5 dB de
pérdida en el LO, que el mezclador puede necesitar para conmutar bien. No
hace falta para medir bien; sí ayuda al presupuesto de alcance.

## Verificación sobre datos reales

Reprocesando la captura del 2026-09-04 con el período correcto (80 ms, ver
`GPRv2/CLAUDE.md`), el pico dominante cae en **5,31 m**. Restando el offset de
~4,17 m quedan **1,14 m**: la placa, que estaba a ~1 m.
