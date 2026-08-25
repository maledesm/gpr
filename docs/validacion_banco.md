# Validación del sampler en el banco

Objetivo: dejar el PCM1808 **caracterizado y confiable antes** de conectarle el
radar. Todo se hace con generador de funciones, sin GPR.

Al terminar tenés medido el fondo de escala real, el corte real del pasa-altos,
el piso de ruido y el ENOB, la exactitud del `fs`, y la cadena de procesamiento
FMCW validada punta a punta. Son números que van directo a la tesis.

Tiempo estimado: 1,5 – 2 horas la primera vez.

---

## ⚠️ Lo primero: la trampa del generador

**Casi todos los generadores asumen carga de 50 Ω.** La entrada del PCM1808 son
**60 kΩ**, prácticamente circuito abierto: si el generador está en modo 50 Ω y le
pedís 1 Vpp, te va a entregar **2 Vpp**.

Buscá en el menú *Output → Load* o *Utility → Output Setup* y ponelo en
**High-Z**. Si no tiene la opción, asumí que todo lo que muestra vale el doble.
Verificalo con el osciloscopio antes de conectar el ADC.

Con un fondo de escala de 3,0 Vpp, ese factor 2 es la diferencia entre medir bien
y recortar todo. Y un ΔΣ sobrecargado no recorta prolijamente: se desestabiliza.

---

## Materiales

- ESP32-C3 + PCM1808 cableados según [`conexionado.md`](conexionado.md)
- Generador que llegue a **0,1 Hz** por abajo (para el paso 6)
- Osciloscopio, para verificar el nivel en paralelo
- Firmware [`PCM1808_ESP32C3`](../firmware/PCM1808_ESP32C3/)
- Python en **Windows** — ver [`../adquisicion/README.md`](../adquisicion/README.md)

> La adquisición corre en Windows: el ESP32 es un puerto COM y **WSL 2 no lo ve**
> sin `usbipd-win`. El `venv_gpr` de Linux sirve solo para el análisis posterior.

> ⚠️ **Cerrá el Monitor Serie del IDE** antes de correr cualquier script, o vas a
> ver "el puerto está ocupado".

---

## Paso 0 — Identificar VINL y VINR

Los 12 pines de la tira son digitales y de alimentación. Las **entradas
analógicas están en otro conector**, normalmente rotulado `L / G / R`. Si no lo
encontrás, seguí la pista que llega a los capacitores de acople.

- **VINL** ← señal del generador
- **VINR** ← a GND con cable corto. Sirve como referencia del piso de ruido del
  propio ADC: lo que midas ahí es el ruido del chip, sin contribución externa.
- Masa del generador → al **AGND del módulo**, no al GND del ESP32

---

## Paso 1 — Encendido sin señal

Con el generador desconectado y VINL a masa:

```
diag
```

Tiene que decir **"Enlace I2S OK"**. Si dice "todo cero", el sospechoso número
uno es SCKI: `GPIO4 → SCK`, y acordate de que en este módulo `SCK` es el master
clock, no el bit clock.

**No sigas hasta que esto salga bien.**

---

## Paso 2 — Primera señal, a nivel bajo a propósito

Generador: **senoidal, 1 kHz, 200 mVpp, offset 0, High-Z.**

Son ~7 % del fondo de escala: si algo está mal (el factor 2 de los 50 Ω, por
ejemplo) no rompés nada.

```
fs 16000
```
```
dec 1
```
```
stats
```

| Campo | Esperado | Si no da |
|---|---|---|
| `f(Hz)` | **1000,0** | Los relojes están mal |
| `Vpp` | **~200 mV** | Si da ~400 mV, el generador está en modo 50 Ω |
| `DC` | ≈ 0 | — |

---

## Paso 3 — Medir el fondo de escala REAL

El datasheet dice `0.6·VCC` pico a pico, pero eso depende de tu rail. Medilo:

1. Generador a **1,000 Vpp** exactos, verificado con el osciloscopio.
2. `stats` → anotá `Vpp` y `dBFS`.
3. `FS_pp = Vpp_medido / 10^(dBFS/20) ` … o más simple: subí la amplitud de a
   poco (1,5 → 2,0 → 2,5 → 2,8 → 3,0 Vpp) mirando el `CLIP!` de `stats`. **El Vpp
   donde aparece el recorte ES el fondo de escala.**

Anotá también a partir de qué nivel se degrada el `Vrms` respecto de lo esperado:
un ΔΣ se degrada *antes* de recortar formalmente.

> **Este número decide la atenuación del front-end.** Con la IF real medida en
> tus capturas (0,6–0,85 Vpp) tenés ~11 dB de margen y no hace falta atenuar.
> Si tu IF llega a 3 Vpp, la atenuación es obligatoria.

Volvé a 1 Vpp antes de seguir.

---

## Paso 4 — Exactitud del `fs`

Con el generador en **1000 Hz exactos**, corré `stats` a cada tasa:

```
fs 8000
```
```
fs 16000
```
```
fs 32000
```
```
fs 48000
```
```
fs 96000
```

El ESP32-C3 **no tiene APLL**: el I²S cuelga del PLL de 160 MHz con un divisor
fraccionario, y no toda `fs` sale exacta. 16/32/48 kHz sí; 44,1 y 96 kHz tienen
error.

El error relativo debería ser **el mismo en todas** (es el cristal del ESP32 y el
del generador). **Si alguna tasa se desvía del resto, ahí el divisor fraccionario
no está dando exacto** — y para eso está el comando `fsmed`, que mide la `fs`
real contando frames contra `esp_timer`.

Anotá la tabla: es una figura de la tesis.

> **Matiz importante:** en el FMCW la distancia sale de
> `R = f_beat · c · T_sweep / (2·BW)`, y `f_beat = bin · fs / N`. Si además medís
> `T_sweep` **contando muestras** (que es lo que vas a hacer con el canal de
> sincronismo), entonces `T_sweep = N_sweep / fs` y **la `fs` se cancela**:
> `R = bin · N_sweep · c / (2·BW·N)`. La exactitud de `fs` solo importa si
> `T_sweep` viene de un reloj externo o se asume del valor nominal.

---

## Paso 5 — Respuesta en frecuencia: separar los dos pasa-altos

Hay dos polos en cascada:

| Polo | ¿Depende de fs? |
|---|---|
| HPF interno del PCM1808 (`0.019·fs/1000`) | **Sí**, escala con fs |
| Capacitor de acople del módulo (R·C) | **No**, es fijo |

Midiendo a **dos fs distintas** los separás sin ambigüedad.

### Predicción a falsear

Con el capacitor rotulado `CS 10` (10 µF) contra los 60 kΩ de entrada:

| fs | HPF interno | Polo del cap | **Corte combinado esperado** |
|---|---|---|---|
| **8 kHz** | 0,152 Hz | 0,27 Hz | **0,42 Hz** |
| **48 kHz** | 0,912 Hz | 0,27 Hz | **1,18 Hz** |

Esto ya está parcialmente corroborado: la caída del techo de la cuadrada medida
en el plotter dio τ ≈ 125 ms → **1,27 Hz a 48 kHz**, contra 1,18 Hz predicho.

### Medición

Generador a **1 Vpp fijo** (no cambies la amplitud, solo la frecuencia), y barré
**0,1 · 0,2 · 0,3 · 0,5 · 0,8 · 1 · 2 · 5 · 10 · 20 Hz** anotando `Vpp` de
`stats` en cada punto, con `fs 8000` y después con `fs 48000`.

⚠️ A 0,1 Hz el período es de 10 s: dejá que `stats` promedie varios ciclos antes
de anotar. Usá `dec` alto para que la ventana de análisis cubra varios períodos.

### Interpretación

| Resultado | Conclusión |
|---|---|
| Los cortes escalan ~6× entre 8 k y 48 k | Manda el **HPF interno**, el capacitor es grande. No hay que tocar el módulo ✔ |
| Los dos cortes dan casi iguales | Manda el **capacitor**. Reemplazarlo por uno más grande |
| Escalan, pero menos de 6× | Los dos polos están cerca. El capacitor aporta |

El corte medido fija el **`T_sweep` máximo utilizable**: la frecuencia de beat del
blanco más cercano que querés ver tiene que quedar bien por encima de él.

---

## Paso 6 — Piso de ruido y ENOB

Generador desconectado, **VINL a GND** con cable corto.

```
fs 16000
```
```
dec 1
```
```
stats
```

El `Vrms` del canal L es el piso de ruido. Con el fondo de escala medido:

```
SNR_dB = 20·log10( FS_pico / (Vrms·√2) )      ENOB = (SNR_dB − 1.76) / 6.02
```

Referencia: el PCM1808 da 99 dB de rango dinámico. **El canal R, que dejaste a
masa, es tu control**: si L y R dan parecido, el ruido es del chip; si L da mucho
peor, entra por el cableado.

Si medís bastante menos de lo esperado:

1. Alimentá el módulo con **batería o power bank** en vez del USB de la
   notebook, y volvé a medir. La diferencia entre las dos lecturas es lo que
   aportaba la fuente conmutada.
2. Alejá los cables de MCLK/BCK/LRCK de la entrada analógica. A 16 kHz el MCLK
   son 4,1 MHz corriendo al lado de tu señal.
3. Acortá los cables de reloj.

Repetí a 8 kHz y 96 kHz: el ruido integrado sube con el ancho de banda, y esa
dependencia también es una figura de la tesis.

---

## Paso 7 — Demostrar el plegado alrededor de 64·fs

Opcional, pero es de los experimentos más valiosos que podés mostrar.

El filtro de decimación del ΔΣ protege alrededor de `fs/2`, **no** alrededor de
`64·fs`. Con `fs 16000`, el modulador corre a **1,024 MHz**, y el antialias
analógico del chip recién corta en 1,3 MHz.

1. Generador a **1,024 MHz**, 500 mVpp → `stats`
2. Generador a **1,0243 MHz** (= 64·fs + 300 Hz) → `stats`

Si aparece un tono en ~300 Hz en banda base, **ahí tenés el plegado en vivo**:
energía a 1 MHz cayendo directo sobre tus frecuencias de beat.

Compará con **8,3 kHz** (apenas arriba de Nyquist a fs=16 k): ahí el filtro de
decimación sí atenúa fuerte. Las dos medidas juntas explican exactamente qué
protege el ΔΣ y qué no — y justifican el RC de entrada.

---

## Paso 8 — Validar la cadena FMCW completa

Se puede validar todo el procesamiento **antes de tener el radar**.

Con `T_sweep = 10 ms` y `BW = 1000 MHz`, la relación es **666,7 Hz por metro**.
Poné el generador en un tono conocido y verificá que el pico caiga donde
corresponde:

| Generador | Distancia esperada |
|---|---|
| 250 Hz | 0,375 m |
| 500 Hz | 0,750 m |
| 1000 Hz | 1,500 m |

Y con el simulador multi-blanco de
[`../simulacion/beat_simulado.py`](../simulacion/beat_simulado.py) reproducido por
la placa de sonido, verificá que aparezcan los cuatro picos en sus distancias.

**Esta es la validación que conviene mostrar en la defensa: el sistema mide bien
una distancia conocida antes de que exista el radar.**

---

## Paso 9 — Prueba de resistencia

```
fs 48000
```
```
dec 1
```

Y una captura larga en modo binario desde Python (5 minutos). Al final, `stats`
tiene que reportar **`captura 100 %`** y el cliente **cero tramas perdidas**. Si
hay pérdidas, el USB no da abasto: subí `dec`.

---

## Planilla de resultados

```
Fecha:                          VCC medida:            V

Fondo de escala medido:            Vpp   (teórico 0.6·VCC =        Vpp)
Recorte aparece a:                 Vpp
Atenuación necesaria para la IF:  ×

fs nominal | fs medido (fsmed) | error % | f_gen 1 kHz medida | error %
   8000    |                   |         |                    |
  16000    |                   |         |                    |
  32000    |                   |         |                    |
  48000    |                   |         |                    |
  96000    |                   |         |                    |

Corte -3 dB @ fs= 8000:        Hz   (esperado 0.42 Hz con cap de 10 µF)
Corte -3 dB @ fs=48000:        Hz   (esperado 1.18 Hz)
Conclusión sobre el capacitor de acople:
T_sweep máximo utilizable:          ms

Piso de ruido L @ 16 kHz:      µVrms    ENOB:        bits
Piso de ruido R (a masa):      µVrms
SNR con tono a -20 dBFS:       dB

Plegado 64·fs: tono de 1.0243 MHz aparece en          Hz  (esperado ~300)
Validación FMCW: 500 Hz -> pico en          m  (esperado 0.750, con T_sweep=10 ms)
```
