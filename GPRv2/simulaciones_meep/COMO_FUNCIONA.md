# Cómo funciona la simulación MEEP del banco GPRv2

Este documento explica **qué hace el simulador, por qué está armado así y cómo
leer lo que produce**. Para correrlo alcanza con el [README](README.md); esto
es para entenderlo y poder explicarlo.

Números de referencia: corrida del 2026-09-22 con placa de 70 cm a 1 m, hueco
de 10 cm entre bocas, sonda adaptada, 2 m de RG-213 con el S21 medido y rampa
de 50 ms (Tprf 100 ms). Las medidas de la bocina y cómo se leen están en
[`../mediciones/README.md`](../mediciones/README.md).

---

## 0. En un minuto

> Simulamos con MEEP (FDTD 2D) **solo el aire**: las dos bocinas y la placa.
> Con un único pulso de banda ancha obtenemos la **función de transferencia
> H(f)** entre la sonda de la bocina TX y la de la RX. Como la escena es
> lineal e invariante (la placa está quieta), H(f) la describe entera. Después,
> en el Python del banco, le agregamos **lo que MEEP no simula**: los cables
> (con el S21 medido con el VNA) y el retardo interno. Con eso **sintetizamos
> el batido que vería el mezclador**, `½·Re{H(f(t))}`, recorriendo la curva
> real del VCO, y lo pasamos por **las mismas funciones** que procesan una
> captura real. Si el pico cae donde predice el modelo, queda probado el
> pipeline entero, no solo una fórmula.
>
> Resultado: moviendo la placa, el eco sube **138,2 Hz por metro contra 138,6
> del ideal** 4B/(c·Tprf) (a = 0,997), y los cables agregan un corrimiento fijo
> de **1,456 m, contra 1,455 m medidos con el VNA**. O sea: todo lo que no es
> aire es un offset puro, y alcanza con un punto de calibración.

---

## 1. Qué se simula y qué no

El banco real, de punta a punta:

```
            ┌──────────── camino del LO: 5 cm directos (0,25 ns) ─────────────┐
            │                                                                 ▼
 VCO ─► splitter                                                         mezclador ─► pasabajos ─► ADC ─► PC
            │                                                                 ▲
            └─► cable TX ─► bocina TX ─► aire ─► placa ─► aire ─► bocina RX ─► cable RX ─► LNA ─┘
                 (1 m)      └──────────────── lo que simula MEEP ───────────────┘       (1 m)
```

| pieza | quién la pone | cómo |
|---|---|---|
| bocinas, aire, placa | **MEEP** (`escena.py`) | FDTD 2D, de la sonda TX a la sonda RX |
| cables TX y RX | `radar.py` | el S21 **medido** con el VNA (módulo y fase), o un retardo ideal |
| camino del LO | `radar.py` | 0,25 ns que **restan** (es la otra entrada del mezclador) |
| splitter, mezclador, LNA, latiguillos | `radar.py` | un retardo `TAU_INTERNO` = **4 ns**, ajustado contra la captura del banco (sección 8) |
| curva del VCO, remuestreo, FFT | `analisis/` | las MISMAS funciones que usa `vivo_rapido.py` |

Un FMCW no mide la distancia al blanco: mide la **diferencia de retardo entre
las dos entradas del mezclador**. Por eso todo lo que está en el camino de RF y
no en el del LO (cables, bocinas, electrónica) aparece como distancia extra.

---

## 2. La idea central: H(f) en vez de un chirp

Las simulaciones viejas (`chirp_v7.py`) metían el chirp adentro de MEEP y
mezclaban en software. Eso no sirve acá: el chirp de MEEP dura nanosegundos,
el retardo a la placa más los cables es ~16 ns, y la aproximación de batido se
rompe. El chirp real dura 50 ms, siete órdenes de magnitud más; simularlo
directamente sería imposible.

La salida es que **la escena es lineal e invariante en el tiempo**: la placa
no se mueve (no hay Doppler). Una escena así queda totalmente descripta por su
función de transferencia H(f). Entonces:

1. MEEP mide H(f) **una sola vez**, con un pulso corto de banda ancha.
2. El batido para cualquier rampa se calcula después, sin volver a correr MEEP.

### Por qué el batido es `½·Re{H(f(t))}`

El TX emite `cos φ(t)`, con `φ'(t) = 2π f(t)`. Para una escena lineal con
respuesta al impulso h:

```
Rx(t) = Re{ ∫ h(τ) e^{j φ(t−τ)} dτ }
```

Como el retardo τ es chico frente a la rampa, `φ(t−τ) ≈ φ(t) − 2π f(t) τ`
(aproximación cuasi-estática, la del *stretch processing*):

```
Rx(t) ≈ Re{ e^{j φ(t)} · H(f(t)) }
```

El mezclador multiplica por el LO, `cos φ(t)`, y el pasabajos se queda con la
parte lenta:

```
IF(t) = ½·Re{H(f(t))}   +   ½·Re{H(f(t))·e^{j 2φ(t)}}
        └── batido ──┘       └── lo elimina el pasabajos ──┘
```

**El batido es literalmente la parte real de H leída a lo largo de la rampa de
frecuencia.** Los cables entran como `e^{−j2πfτ}`, así que corren el pico sin
deformarlo. El error de la aproximación va con `α·τ²`, con
α = 20,8 GHz/s y τ ≈ 16 ns: unos 5·10⁻⁹ rad. Despreciable.

Ventajas:

- El FDTD **no depende del Tprf**: cambiar la rampa no obliga a re-simular.
- Se usa la **rampa real** (300 muestras a 6000 sps, 50 ms) con la **no
  linealidad real** del VCO.
- Es barato: ~4 s de FDTD por escena.

---

## 3. El recorrido completo

```
simular.bat ──(variables GPR_SIM_*)──► parametros.py   valores de referencia + lo que pisa el .bat
    │                                                  arma NOMBRE → carpeta salidas/<NOMBRE>/
    │
    ├─[WSL, conda "meep"]──► escena.py      FDTD 2D: pulso en la sonda TX, se registra la sonda RX
    │                           └─► H_*.npz  H(f) = Rx(f)/Fuente(f)  (solo aire) + 3 fotos del campo
    │
    └─[Windows]────────────► radar.py       H · cables · e^{−j2πfτ_int}  →  ½·Re{H(f(t))}
                                 │            → remuestreo en θ (curva del VCO) → Hann → FFT ×8
                                 ├─► correr.py   placa a DIST_PLACA → escena.png, espectro.png
                                 └─► barrido.py  varias distancias  → barrido.png
```

Son dos intérpretes distintos: MEEP vive en WSL y no tiene pandas, así que
`escena.py` no puede importar `analisis/`. Por eso `parametros.py` no depende
de nada del barrido, y lo comparten los dos lados.

| archivo | corre en | qué hace |
|---|---|---|
| [`simular.bat`](../simular.bat) | Windows | la interfaz: el bloque de arriba se edita, lanza todo y abre las figuras |
| [`parametros.py`](parametros.py) | los dos | geometría, banda, retardos, valores del `.bat`, nombre de la carpeta |
| [`escena.py`](escena.py) | WSL / meep | arma la geometría, corre el FDTD y guarda H(f) |
| [`correr_meep.sh`](correr_meep.sh) | WSL | activa el env conda y llama a `escena.py` |
| [`radar.py`](radar.py) | Windows | cables, τ interno, síntesis del batido, perfil de distancia |
| [`correr.py`](correr.py) | Windows | placa a una distancia: picos contra modelo, figuras |
| [`barrido.py`](barrido.py) | Windows | varias distancias: recta de calibración, pendiente y offsets |

---

## 4. La escena en MEEP (`escena.py`)

### Unidades

MEEP trabaja sin dimensiones. Se eligió **a = 0,15 m** (λ en aire a 2 GHz):

- longitud: 1 u = 15 cm
- tiempo: 1 u = a/c = 0,5 ns
- frecuencia: `f_meep = f·a/c`, así que 1 GHz → 0,5 y 2 GHz → 1,0

### Geometría

2D, polarización **Ez** (el campo sale del plano). El plano simulado corta la
guía por su lado de 18 cm; el de 9 cm queda fuera. Medidas del croquis
[`mediciones/mediciones_antena.png`](../mediciones/mediciones_antena.png),
todas **por fuera** (lectura cota por cota en
[`mediciones/README.md`](../mediciones/README.md)):

```
                    placa: 70 cm de ancho, 1 cm de espesor
          ═══════════════════════════════════════════
                              ▲
                              │ DIST_PLACA (1,00 m)
                              │
   y = 0  ─ ─ ─\─ ─ ─ ─ ─ /─ ─ ┼ ─ \─ ─ ─ ─ ─ /─ ─ ─   boca de las bocinas: 30,5 × 30,5 cm
                \  flare  /    │    \         /          flare: 19 cm de largo
                 │       │ ◄──►│     │       │           hueco entre bocas: 10 cm
                 │ guía  │     │     │ guía  │           guía: 18 cm de ancho, 33,5 cm de largo
                 │   ●   │     │     │   ●   │           ● sonda: 5,9 cm (TX) y 5,4 cm (RX) del fondo
                 │   TX  │           │   RX  │
                 └───────┘           └───────┘           corto (solo con SONDA = corto)
```

- Largo total de la bocina: 52,5 cm, del fondo al plano de la boca.
- La bocina es de chapa (~1 mm). La onda ve la cara **interior**, así que se
  resta la chapa: guía de **17,8 cm** por dentro (corte del modo guiado en
  842 MHz), boca de 30,3 cm y largo de 52,4 cm.
- Las paredes se simulan de 1 cm, porque la grilla de 7,5 mm no resuelve
  1 mm, pero se engordan **hacia afuera** de la cara interior: lo que ve la
  onda queda en la medida real.
- Centros de las bocinas: boca (por fuera) + hueco = 40,5 cm.
- Todas estas medidas se cambian desde el bloque "La bocina" del `.bat`, en
  centímetros y por fuera, como el croquis.

### La celda y el PML

La celda rodea todo con 15 cm de aire (`MARGEN`) y 15 cm de **PML** (`DPML`),
la capa absorbente que simula espacio libre. Queda de 1,33 × 2,15 m con la
placa a 1 m: 178 × 286 celdas de 7,5 mm (`RESOLUCION` 20).

**La escena con placa y la vacía usan la MISMA grilla.** Así la resta
`H_placa − H_vacío` es exactamente el eco de la placa, y no además la
diferencia entre dos discretizaciones. En el barrido, todas las distancias
comparten la celda de la distancia mayor por el mismo motivo.

### El pulso y la medición de H(f)

- **Fuente:** una gaussiana modulada de Ez en la sonda TX, centrada en
  1,475 GHz, con σ = 530 MHz: los bordes de la banda quedan al 56 % del pico.
- **Medición:** se registra Ez en la sonda RX cada 0,05 u (25 ps), durante
  200 u = **100 ns**, tiempo suficiente para tres idas y vueltas a la placa.
- **H(f)** = DFT(traza RX) / DFT(pulso), calculadas con **el mismo código**
  en 401 frecuencias de 0,90 a 2,05 GHz. Cualquier sesgo del muestreo se
  cancela en el cociente, y la forma del pulso no importa mientras tenga
  energía en toda la banda.
- La banda cubre de sobra el barrido real del VCO (942 a 1982 MHz). Si
  quedara corta, `radar.py` avisa en vez de extrapolar.

Además se guardan tres **fotos del campo** para `escena.png`, en los instantes
en que el pulso sale, llega a la placa y vuelve. Los instantes se calculan de
la geometría.

Cada escena deja un `H_<escena>.npz` con `f_hz`, `H`, la traza cruda, las
fotos, el mapa de metal y los parámetros usados.

---

## 5. La carga de la sonda (`SONDA`)

### El problema

En el banco, cada sonda está conectada a **50 Ω**: la de RX al receptor, la de
TX a la salida del VCO/amplificador. Lo que vuelve a entrar a una bocina baja
por la guía, la sonda se lo entrega a esa carga, y **no vuelve a salir**.

MEEP no sabe nada de 50 Ω. La sonda RX solo *mide* el campo y la TX solo
*inyecta* corriente; ninguna absorbe nada. Con el corto del fondo, cada bocina
queda como una **cavidad metálica cerrada que devuelve todo**. Eso infla los
rebotes que entran a una bocina y hacen un segundo viaje a la placa.

### Los dos modelos

| `SONDA` | geometría | qué representa |
|---|---|---|
| **`adaptada`** (la de siempre) | sin corto: la guía sigue derecho detrás de la sonda hasta **atravesar el PML** del borde de la celda | una transición **perfectamente adaptada** en toda la banda: lo que llega a la sonda se absorbe |
| `corto` | la bocina del croquis tal cual, con el corto a 5,9 cm detrás de la sonda | la bocina **sin carga**: devuelve todo lo que le entra |

Que el PML absorba el modo guiado es la forma estándar de terminar una guía en
MEEP. Se verificó que no refleja: con el PML el doble de grueso, H(f) cambia
menos de −43 dB y el pico B no se mueve.

### El banco está entre los dos

La sonda a 5,9 cm del corto es **un cuarto de longitud de onda guiada a
~1,5 GHz**, el centro de la banda. La transición real adapta bien ahí y peor
hacia los bordes. Los dos modelos son los extremos que encierran al banco.

| placa a 1 m | `corto` | `adaptada` |
|---|---|---|
| rebote adentro D (respecto de B) | −4 dB | **−30 dB** |
| dos rebotes adentro E | −12 dB | **−37 dB** |
| energía de la traza RX después de 40 ns | −12 dB | −31 dB |
| eco B, sin cables | 1,662 m | 1,593 m |
| offset de las bocinas (`barrido.py`) | 0,660 m | 0,595 m |

Los **niveles** de los rebotes de adentro cambian muchísimo, que es lo que se
buscaba. Pero también **el eco se corre ~6 cm**. Con el corto, parte de la
señal va de la sonda al fondo y vuelve, y eso atrasa el centro de fase de la
bocina. **La captura real de la placa va a decir cuál de los dos offsets se
parece más al banco.**

---

## 6. Del H(f) al espectro (`radar.py`)

### 6.1 La cadena de RF

```
H_total(f) = H_aire(f) · S21_TX(f) · S21_RX(f) · e^{+j2πf·τ_LO} · e^{−j2πf·τ_interno}
```

- **`CABLE = medido`**: el S21 complejo de los dos RG-213 de 1 m
  (`docs/CABLES/RG213_A_1m.s2p` y `_B_`), leído con `cables_vna.leer_s2p()`.
  Incluye la atenuación que crece con la frecuencia. Se interpolan el módulo
  y la fase desenrollada por separado, porque con 10 ns de retardo la fase
  gira mucho entre puntos.
- `ideal`: retardo puro `e^{−j2πf(τ_TX+τ_RX)}` con 4,983 + 4,975 ns, sin
  pérdidas.
- `ninguno`: sin cables. Es el radar ideal de la tesis.
- **El LO resta** 0,25 ns, los 5 cm entre el splitter y el mezclador.
  Neto: 9,708 ns → `c·τ/2` = **1,455 m** de distancia aparente. Es `c·τ/2` y
  no `c·τ` porque el cable se recorre una vez, no ida y vuelta.

### 6.2 La síntesis del batido

1. Rampa de `T_SWEEP` = 50 ms a 6000 sps: **300 muestras**, igual que el banco.
2. La tensión sube lineal de 0 a 3 V y la frecuencia sale de la **curva medida
   del VCO** (`VCO/Caracteristica VCO.csv`), no de una recta. Así el batido
   sintético tiene la misma no linealidad que el real.
3. `beat(t) = ½·Re{H_total(f(t))}`.

### 6.3 El perfil de distancia (idéntico al del banco)

1. `eje_theta()`: arma el eje θ que linealiza el barrido del VCO.
2. `remuestrear()`: spline cúbico a una grilla θ uniforme.
3. Ventana de Hann y FFT con **relleno ×8**, igual que `vivo_rapido.py`. El
   relleno no agrega resolución, que sigue siendo `c/(2B)` = 14,4 cm; solo
   interpola la forma del pico.
4. Frecuencia → distancia aparente: `d = f·c/(2α₀)`.
5. `pico()`: parábola sobre los tres puntos del máximo en dB, para leer la
   posición sin quedar atado al bin.

---

## 7. La pendiente: 4B/(c·Tprf)

Con una triangular de período Tprf, la rampa de subida dura Tprf/2 y barre B:

```
α = B / (Tprf/2) = 2B/Tprf          f_b = α·τ = (2B/Tprf)·(2d/c) = 4B·d/(c·Tprf)
```

**T en la fórmula de la tesis es el Tprf completo** (subida más bajada), no
la rampa. Con los números del banco:

```
4B/(c·Tprf) = 4 × 1039,6 MHz / (3·10⁸ m/s × 100 ms) = 138,6 Hz por metro
```

Es lo mismo que `2B/(c·T_rampa)` con la rampa de 50 ms, y que `2α₀/c` en el
código.

**Simulado:** 138,2 Hz/m (a = 0,997). La pendiente no depende de los cables ni
de las bocinas: las rectas con y sin cables son paralelas. Tampoco depende del
Tprf: con `TPRF_MS = 80` da 172,8 contra 173,3 Hz/m, el mismo a.

**Si en el banco la pendiente no da ~1, no son los cables.** Lo primero a
revisar es que el Tprf del panel coincida con el del generador.

---

## 8. La distancia aparente: por qué el eco no cae en 1 m

```
d_aparente = d_real + d_bocinas + c·τ_cables/2 + c·τ_interno/2
             1,000  +  0,595    +    1,456     +   0,600
           = 3,651 m   →   × 138,6 Hz/m = 506 Hz
```

- **`d_bocinas`**: el camino dentro de las bocinas. Tiene dos partes:
  - el **largo físico** sonda→boca, promediando las dos sondas:
    52,4 − (5,8 + 5,3)/2 = **0,469 m**;
  - un **exceso** de 0,127 m (adaptada) o 0,192 m (corto). Cerca del corte
    del modo guiado la onda viaja más lenta que c (dispersión de la guía),
    y el flare y el centro de fase suman algo más. Con el corto se agrega la
    componente que va y vuelve al fondo.
- **Cables**: 1,456 m simulados contra 1,455 m del VNA. Es la validación más
  fuerte: el simulador y el VNA coinciden al milímetro.
- **Retardo interno**: **4 ns = 0,60 m**, ajustado contra el banco (ver
  abajo). No está medido directo.

Todo eso es un **offset**: no depende de la distancia. Por eso un solo punto
de calibración alcanza, y dos o más sirven para verificar la pendiente.

### Comparación con el banco (2026-09-22)

Captura `datos/capturas/captura_1m_cf.png`: cables RG-213 de 1 m, placa a
1 m, sin restar el fondo. Picos leídos del PNG (±3 Hz):

| | medido | simulado, τ_interno = 0 | simulado, τ_interno = 4 ns |
|---|---|---|---|
| **B**, eco de la placa | **~505 Hz**, 0 dB | 423 Hz | **506 Hz** |
| **A**, acoplamiento directo | zona elevada de 340 a 400 Hz, −8 a −10 dB | 289 Hz, −46 dB | 372 Hz, −46 dB |
| pico sin identificar | 433 Hz, −4 dB | — | — |
| pico sin identificar | 580 Hz, −14 dB | — | — |

- **De ahí salen los 4 ns.** Sin retardo interno el eco cae 82 Hz abajo:
  82 / 138,6 = 0,59 m aparentes = 3,95 ns. Con `SONDA = corto` serían 3,5 ns:
  el valor arrastra la incertidumbre del modelo de la bocina.
- **4 ns son ~80 cm de coaxil equivalentes**, más de lo que explican
  splitter, mezclador y LNA solos: probablemente hay latiguillos o
  adaptadores en el camino de RF. Para medirlo sin depender de la bocina:
  unir los cables de TX y RX con un barrel y un atenuador, sin antenas.
- **El acoplamiento cae donde lo pone la simulación**, pero ~35 dB más
  fuerte: en el banco se suma la fuga interna entre TX y RX.
- **El resto es la sala.** La captura del fondo, sin placa
  (`captura_1m_fondo.png`), tiene un pico en 547 Hz tan fuerte como el eco,
  y ecos a −5/−10 dB en toda la banda. Son fijos en el tiempo (franjas quietas
  en el radargrama): es clutter, no ruido. La simulación no lo tiene, porque
  la celda termina en PML (espacio libre).
- **Para confirmar que 505 Hz es la placa** y no un eco de la sala: medirla a
  otra distancia. A 1,5 m tendría que caer en ~574 Hz.

---

## 9. Cómo leer cada figura

### `escena.png`: el campo en tres instantes

Rojo y azul son el signo de Ez; negro es metal. El origen de y es la boca de
las bocinas y la placa está en y = distancia.

1. **El pulso sale de TX**: frente de onda casi plano saliendo de la bocina
   izquierda.
2. **Llega a la placa**.
3. **Vuelve el eco**: frente reflejado bajando hacia las bocinas.

Con la sonda adaptada, la guía no tiene fondo: la flecha "a la carga 50 Ω"
marca que sigue hasta el borde absorbente. No es un error de dibujo.

### `espectro.png`: lo que vería el radar

Tres curvas, todas en dB **respecto del pico de la placa**, así que la
diferencia de altura entre curvas es real:

| curva | qué es |
|---|---|
| **placa** (azul) | la escena completa: **lo que mide el radar** |
| **vacío** (naranja) | sin la placa: solo el acoplamiento directo. Es lo que guarda "medir fondo" en `vivo_rapido.py` |
| **solo la placa** (verde, rayada) | placa − vacío, restado en complejo. Separa los picos; no se mide |

El eje de abajo está en Hz, como `vivo_rapido.py`, y el de arriba es la
distancia aparente sin calibrar.

#### Qué es cada pico

Se identificaron **moviendo la placa** (`barrido.py`). La regla es simple:
**un camino que va N veces a la placa se corre N veces lo que se mueve la
placa.**

| pico | camino | se corre | adaptada | corto |
|---|---|---|---|---|
| **A** | TX → aire → RX, sin tocar la placa | 0× | 289 Hz, −46 dB | 299 Hz, −47 dB |
| **B** | TX → placa → RX: **el eco, el que se calibra** | 1× | 423 Hz, 0 dB | 432 Hz, 0 dB |
| **C** | un rebote en la **boca** (el metal alrededor de la apertura): TX → placa → boca → placa → RX | 2× | 566 Hz, −14 dB | 576 Hz, −14 dB |
| **D** | un rebote **adentro** de una bocina: entra, vuelve a salir, otro viaje | 2× | 619 Hz, −30 dB | 660 Hz, −4 dB |
| **C2** | dos rebotes en la boca: cae en B + 2·(C − B) | 3× | 714 Hz, −26 dB | 729 Hz, −20 dB |
| **CD** | uno en la boca y uno adentro: cae en C + D − B | 3× | (< −40 dB) | 804 Hz, −12 dB |
| **E** | dos rebotes adentro (tercer viaje completo): 3 veces B | 3× | 854 Hz, −37 dB | 884 Hz, −12 dB |

- Los rebotes **de adentro** (D, CD, E) son los que dependen de la carga de la
  sonda, porque es la sonda la que se los lleva. Con el corto, D sale casi tan
  alto como el eco.
- C y C2 rebotan en el metal de afuera, así que la sonda no los toca: son
  **reales** y van a aparecer en el banco.
- Con la sonda adaptada, D cae ~15 cm antes de "2 veces B": lo que queda es lo
  que reflejan las paredes de la bocina **antes** de llegar a la sonda.
- **A sale 46 dB abajo del eco, y en el banco es lo más fuerte de la
  pantalla.** MEEP solo ve el acoplamiento por el aire; en el banco domina la
  fuga interna (splitter, mezclador, cables juntos). Es lo que trata
  `docs/refs/park2018_leakage_internal_delay.pdf`.

Solo se rotulan máximos locales de verdad y más fuertes que −40 dB, para no
ponerle nombre al piso. En cada ventana se toma el máximo local más alto, no
el máximo a secas: al lado de D con el corto (−4 dB), la falda de D es más
alta que C2.

### `barrido.png`: la recta de calibración

Frecuencia del eco B contra la distancia real, para cada distancia de
`BARRIDO`:

- **rojo, con cables**: lo que mediría el banco;
- **azul, sin cables**: solo aire y bocinas;
- **punteada**: el radar ideal `4B·d/(c·Tprf)`, sin cables ni bocinas.

Las tres son paralelas: **misma pendiente, distinto origen**. La distancia
vertical entre roja y azul es el offset de los cables, y entre azul y punteada
el de las bocinas. El título compara la pendiente simulada con la ideal.

---

## 10. Los parámetros del `.bat`

Los valores de referencia viven en `parametros.py`. El `.bat` los pisa **solo
para esa corrida**, exportando variables `GPR_SIM_*`, que llegan a WSL porque
se agregan a `WSLENV`. Dejar un valor vacío usa el de `parametros.py`. Se
acepta coma o punto decimal.

| variable | qué es | por defecto | ¿cambia el FDTD? |
|---|---|---|---|
| `NOMBRE` | carpeta de la corrida (vacío = automático) | vacío | — |
| `QUE` | `placa`, `barrido` o `todo` | `todo` | — |
| `DIST_PLACA` | boca de las bocinas → placa [m] | 1,00 | sí |
| `BARRIDO` | distancias del barrido [m] | 0,75 1,00 1,25 1,50 | sí |
| `SEPARACION_BOCAS` | hueco entre bocas, borde a borde [m] | 0,10 | sí |
| `PLACA_ANCHO` | ancho de la placa [m] | 0,70 | sí |
| `SONDA` | `adaptada` o `corto` (sección 5) | `adaptada` | sí |
| `BOC_GUIA_ANCHO`, `BOC_BOCA`, `BOC_LARGO`, `BOC_GUIA_LARGO` | la bocina, **en cm y por fuera**: ancho de la guía, boca, largo total, tramo recto | 18, 30,5, 52,5, 33,5 | sí |
| `BOC_CONECTOR_TX`, `BOC_CONECTOR_RX` | conector (sonda) de cada bocina al fondo [cm] | 5,9, 5,4 | sí |
| `BOC_CHAPA` | espesor de la chapa [cm] | 0,1 | sí |
| `CABLE` | `medido`, `ideal` o `ninguno` | `medido` | no |
| `TAU_INTERNO_NS` | retardo de la electrónica [ns], ajustado contra el banco | 4 | no |
| `RESOLUCION` | celdas por 15 cm (20 = 7,5 mm; 30 tarda ~3×) | 20 | sí |
| `TPRF_MS` | Tprf del generador [ms] (vacío = el de `analisis/`, 100) | vacío | no |

Hoy el `.bat` corre MEEP siempre. "No" quiere decir que ese parámetro solo
cambia el procesamiento de Windows: el H(f) de MEEP sale igual.

---

## 11. Dónde queda cada cosa

Cada corrida va a `simulaciones_meep/salidas/<NOMBRE>/`:

| archivo | qué es |
|---|---|
| `escena.png` | el campo en tres instantes |
| `espectro.png` | la FFT con los picos explicados |
| `barrido.png` | frecuencia contra distancia, con la recta ideal |
| `resumen_placa.txt`, `resumen_barrido.txt` | lo mismo que la consola, **encabezado con los parámetros usados**: sirven para saber de dónde sale cada número |
| `H_placa.npz`, `H_vacio.npz` | MEEP, placa a `DIST_PLACA` |
| `H_placa_0p75.npz`… `H_vacio_barrido.npz` | MEEP, barrido |

**`NOMBRE` vacío** arma el nombre con `nombre_auto()`: siempre la geometría, y
el resto solo si se aparta de la referencia.

- `placa1.00m_hueco10cm_ancho70cm`: el caso normal.
- `placa1.00m_hueco10cm_ancho70cm_sonda-corto`
- `barrido0.75-1.50m_hueco10cm_ancho70cm_cable-ideal_tau1.5ns`

Con el mismo nombre, la corrida nueva pisa a la anterior. Los `.npz`, `.png`
y `.txt` de `salidas/` no entran a git: se regeneran corriendo el `.bat`.

---

## 12. Limitaciones

- **Es 2D.** Se pierde el 1/r² y el recorte de la placa en la otra dimensión.
  **Las posiciones valen; los niveles no se comparan directo con el banco.**
- **El acoplamiento directo (A) sale muy chico.** En el banco domina la fuga
  interna, que no es un camino por el aire.
- **`TAU_INTERNO = 4 ns` está ajustado, no medido**: sale de hacer coincidir
  el eco con una captura, y depende del modelo de la sonda (3,5 a 4 ns).
- **La sonda es un extremo o el otro** (sección 5); el banco está en el medio.
  El offset de las bocinas queda entre 0,595 y 0,660 m según el modelo.
- **Paredes de 1 cm en vez de chapa de 1 mm.** La cara interior está en la
  medida real, pero el borde de la boca es 1 cm de metal en vez de 1 mm, y
  eso puede pesar algo en el rebote C, que es justamente en la boca.
- **Falta confirmar:** el espesor de la chapa, cuál conector es el de TX, y
  si las bocinas están paralelas. Ver
  [`mediciones/README.md`](../mediciones/README.md#falta-medir-o-confirmar).

---

## 13. Para tocar el código

| quiero… | dónde |
|---|---|
| cambiar un valor para una corrida | el bloque de arriba de `simular.bat` |
| cambiar un valor de referencia (croquis, VNA) | `parametros.py` |
| agregar un parámetro al `.bat` | leerlo con `_env()` en `parametros.py`, exportarlo en el `.bat` como `GPR_SIM_X` y sumarlo a `VARS` (si no, no llega a WSL) |
| cambiar la geometría (otro blanco, arena, etc.) | `construir()` en `escena.py`. La escena con y sin blanco tienen que compartir la celda |
| cambiar cómo entra un cable o la electrónica | `respuesta_cables()` / `aplicar_cadena()` en `radar.py` |
| agregar un pico con nombre | `buscar_picos()` y `EXPLICACION` en `correr.py` |
| cambiar el procesamiento | **no**: tiene que ser el de `analisis/`, que es lo que se está validando |

---

## Glosario

- **FDTD**: diferencias finitas en el dominio del tiempo. MEEP resuelve las
  ecuaciones de Maxwell paso a paso sobre una grilla.
- **PML**: capa absorbente en el borde de la celda. Simula espacio libre, y
  con la sonda adaptada también hace de carga.
- **H(f)**: función de transferencia de sonda TX a sonda RX.
- **Tprf**: período de la triangular del generador (subida + bajada).
  `T_SWEEP` es solo la subida.
- **θ**: eje de tiempo deformado que corrige la no linealidad del VCO.
- **Distancia aparente**: `f_batido·c/(2α₀)`, lo que el radar lee antes de
  calibrar.
- **Offset**: la parte de la distancia aparente que no depende de la
  distancia real (cables, bocinas, electrónica).
- **Centro de fase**: el punto desde donde la bocina "parece" irradiar. No
  coincide con la boca, y por eso las bocinas agregan más que su largo físico.
