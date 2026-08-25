# Estudio de hardware — PCM1808 + ESP32-C3 SuperMini como digitalizador para GPR FMCW

Documento previo al firmware. Objetivo: definir circuito, arquitectura de reloj y
arquitectura de datos antes de escribir código.

Fecha: 2026-08-05

---

## 0. Resumen ejecutivo (leer esto sí o sí)

Analicé tus capturas reales (`MEDI/SDS0000{1,2,3}.CSV`) y el datasheet del PCM1808.
Hay **una incompatibilidad de fondo entre el PCM1808 y tu radar tal como está hoy**:

| | Tu señal IF hoy | Lo que el PCM1808 puede ver |
|---|---|---|
| Banda útil de CH1 | **0.06 Hz – 50 Hz** (98 % de la energía < 50 Hz) | > ~3 Hz, y en la práctica > 20 Hz |
| fs mínima | ~1 kHz alcanza y sobra | **8 kHz** (mínimo absoluto del chip) |
| Acople | DC | **AC obligatorio** (HPF interno + capacitor de entrada) |

El PCM1808 es un ADC **de audio**: tiene un filtro pasa-altos digital interno
(fc = 1.9·10⁻⁵ · fs → **0.91 Hz @ 48 kHz**, 1.82 Hz @ 96 kHz) *más* el capacitor
de acople del módulo contra los 60 kΩ de impedancia de entrada. El de este módulo
está rotulado `CS 10`, o sea **10 µF → polo en 0.27 Hz**. Los dos en cascada dan
un corte combinado de **~1.2 Hz a 48 kHz**, ya corroborado en el banco: la caída
del techo de una cuadrada dio τ ≈ 125 ms → 1.27 Hz medidos (el detalle está en
[`validacion_banco.md`](validacion_banco.md) §5).
No hay forma de puentear el HPF digital: no tiene puerto de control.

Con tu `T_sweep ≈ 1.46 s` y `BW = 1000 MHz`, la frecuencia de beat es:

```
f_beat = 2·R·BW / (c·T_sweep) = 6.67 / T_sweep  [Hz por metro]
       = 4.57 Hz/m   con T_sweep = 1.46 s
```

O sea que **toda la zona de interés de un GPR (0.2 m – 2 m) cae entre 0.9 Hz y
9 Hz**, es decir sobre el faldón del pasa-altos. Con los dos polos reales en
cascada (0.91 Hz del filtro interno + 0.27 Hz del capacitor de 10 µF):

| Profundidad (aire) | f_beat | Atenuación HPF | Error de fase |
|---|---|---|---|
| 0.2 m | 0.91 Hz | **−3.4 dB** | **+61°** |
| 0.5 m | 2.28 Hz | −0.7 dB | +28° |
| 1.0 m | 4.57 Hz | −0.2 dB | +15° |
| 5.0 m | 17.1 Hz | −0.0 dB | +4° |

La atenuación se puede compensar; **el error de fase que varía rápido con el rango
no**, y es lo que rompe la FFT (te ensancha y corre los picos cercanos).

**Mirá la columna de fase, no la de atenuación.** Entre 0.2 m y 0.5 m la amplitud
casi no se mueve (−3.4 → −0.7 dB) pero la fase se corre 33°. Ese es el daño real,
y es el que no se compensa con una ganancia.

### La solución es acelerar el sweep, no cambiar el ADC

Si bajás `T_sweep` a **5–10 ms**, todo se acomoda solo:

| T_sweep | f_beat/m | @0.2 m | @2 m | @5 m | fs recomendada | ¿Sirve PCM1808? |
|---|---|---|---|---|---|---|
| 1.46 s (hoy) | 4.6 Hz/m | 0.9 Hz | 9.1 Hz | 23 Hz | — | ✗ |
| 100 ms | 67 Hz/m | 13 Hz | 133 Hz | 333 Hz | 8 kHz | ⚠ justo |
| **10 ms** | **667 Hz/m** | **133 Hz** | **1.3 kHz** | **3.3 kHz** | **48 kHz** | ✓✓ |
| **5 ms** | **1.3 kHz/m** | **267 Hz** | **2.7 kHz** | **6.7 kHz** | **48 kHz** | ✓✓ |
| 1 ms | 6.7 kHz/m | 1.3 kHz | 13 kHz | 33 kHz | 96 kHz | ✓ |

Beneficios adicionales de acelerar el sweep, todos gratis:

1. **La rampa de sincronismo (tu CH2) también pasa a ser audible.** A 10 ms el
   diente de sierra tiene fundamental en 100 Hz → pasa el acople AC sin problema
   → podés meterla en el canal derecho del PCM1808 y sincronizar por software,
   exactamente como hacés hoy con el osciloscopio. Con 1.46 s eso es imposible.
2. **Promediación masiva.** A 10 ms tenés 100 sweeps/s. En 10 s de medición
   promediás 1000 sweeps → +30 dB de SNR. Hoy, en 4 s de captura, tenés ~2 sweeps.
3. **Inmunidad a movimiento y a deriva térmica del VCO** (el sweep termina antes
   de que nada se mueva).
4. La resolución en distancia **no cambia**: sigue siendo `c/(2·BW) = 0.15 m` en
   aire, `≈ 5 cm` en suelo con εr ≈ 9. La resolución la fija el ancho de banda,
   no el tiempo de sweep.

### El número que justifica todo el cambio

Tu osciloscopio (SDS1072CML+, 8 bits) está digitalizando CH1 con **LSB = 4 mV**
sobre 0.6 Vpp → ~7.6 bits efectivos.
El PCM1808 a fondo de escala 3.0 Vpp da **LSB = 179 nV** y ~99 dB de rango
dinámico (16 bits efectivos reales). Son **~22 000× más resolución**. *Ese* es el
motivo real por el que vale la pena el módulo.

### Si NO podés acelerar el sweep

Entonces el PCM1808 es el componente equivocado y te lo digo ahora y no después.
El reemplazo correcto para señales de 0.05–50 Hz acopladas en DC es un
delta-sigma de instrumentación: **MCP3564** (24 bit, SPI, 4 canales) o **ADS1256**
(24 bit, 30 kSPS) o, más barato, **ADS1115** (16 bit, I²C, 860 SPS — alcanza
holgado para 50 Hz de banda). Todos son DC-coupled y muestrean tan lento como
quieras.

**Igual voy a escribir el firmware del PCM1808 completo y funcionando**, porque el
módulo ya lo tenés y sirve perfecto para la versión rápida del radar. Solo quiero
que la decisión de arriba la tomes con los números a la vista.

---

## 1. El módulo: identificación de pines

Tu serigrafía dice `FMY, MDI, MDO, GND, 3.3, 5V, BCK, OUT, LRC, SCK, GND, 3.3`.
Traducido a los nombres del datasheet (SLES177B):

| Serigrafía | Pin real | Nº | Dir. | Función |
|---|---|---|---|---|
| `FMY` | **FMT** | 12 | IN | Formato: **LOW = I²S 24 bit**, HIGH = left-justified |
| `MDI` | **MD1** | 11 | IN | Selección de modo, bit 1 |
| `MDO` | **MD0** | 10 | IN | Selección de modo, bit 0 |
| `BCK` | **BCK** | 8 | IN/OUT | Bit clock (64·fs en modo esclavo) |
| `OUT` | **DOUT** | 9 | OUT | Datos serie, 24 bit MSB-first |
| `LRC` | **LRCK** | 7 | IN/OUT | Word select / frame clock = fs |
| `SCK` | **SCKI** | 6 | IN | ⚠ **System clock (MCLK), 256/384/512·fs** |
| `5V` | **VCC** | 3 | PWR | Alimentación **analógica, 5 V** (4.5–5.5) |
| `3.3` | **VDD** | 4 | PWR | Alimentación **digital, 3.3 V** |

> ⚠ **Trampa importante**: en casi todos los micrófonos y DAC I²S de hobby, `SCK`
> significa *bit clock*. **Acá no.** En el PCM1808, `SCK` = SCKI = master clock, y
> el bit clock es `BCK`. Si los cruzás no sale nada (o sale ruido). Es el error
> #1 con este chip.

### Tabla de modos (datasheet, Tabla 2)

| MD1 | MD0 | Modo |
|---|---|---|
| **LOW** | **LOW** | **Esclavo (autodetecta SCKI = 256/384/512·fs)** ← el que vamos a usar |
| LOW | HIGH | Maestro, 512 fs |
| HIGH | LOW | Maestro, 384 fs |
| HIGH | HIGH | Maestro, 256 fs |

`FMT`, `MD0` y `MD1` son entradas Schmitt con **pulldown interno de 50 kΩ**, o sea
que dejarlos al aire ya los pone en LOW = modo esclavo + I²S. Igual **atalos a GND
con cable**, porque en un ambiente con RF cerca no querés entradas flotando.

> **MD1/MD0 se leen una sola vez, al encender.** El datasheet lo dice explícito:
> *"It is necessary to set MD1 and MD0 prior to power on."* No podés cambiar de
> modo en caliente.

### Por qué modo ESCLAVO (esto es lo que te da fs variable)

Vos pediste que **la frecuencia de sampling sea una variable**. Eso decide la
arquitectura:

- En **modo maestro**, el PCM1808 divide un cristal externo fijo. `fs = f_xtal/512`
  (o /384, /256). Con un cristal de 12.288 MHz solo podés tener 24 / 32 / 48 kHz y
  nada más. **fs no es variable.**
- En **modo esclavo**, el ESP32-C3 genera SCKI, BCK y LRCK. `fs` es lo que el
  ESP32 quiera, continuo entre 8 kHz y 96 kHz. **fs es una variable de software.**

→ **Modo esclavo, sin discusión.**

⚠ Antes de conectar nada: **fijate si tu módulo tiene un oscilador/cristal
soldado** (un paquetito metálico rectangular de 4 patas, o un cristal cilíndrico).
Muchos clones del PCM1808 traen un oscilador de 12.288 MHz ya puesto y con MD1/MD0
cableados a modo maestro. Si es tu caso, **no podés inyectar SCKI desde el ESP32**
(chocarían dos salidas) y hay que desoldarlo. Mandame una foto del módulo por las
dos caras y te lo confirmo.

---

## 2. Alimentación

```
USB 5V ──┬─ 10 Ω ──┬──────────────── VCC (5V) del PCM1808  [analógico, ~8.6 mA]
(pin 5V  │         │
 del C3) │        ═╪═ 100 µF   ═╪═ 100 nF   (lo más cerca posible del chip)
         │         │            │
         └─────────┴────────────┴── GND

3V3 del C3 ──┬──────────────────── 3.3 del PCM1808  [digital VDD, ~5.9 mA]
             │
            ═╪═ 10 µF  ═╪═ 100 nF
             │          │
            GND        GND
```

Puntos:

- **VCC tiene que ser 5 V, no 3.3 V.** El fondo de escala analógico es
  `0.6 · VCC` = **3.0 Vpp** a 5 V. Si lo alimentás con 3.3 V, el chip queda fuera
  de rango de operación recomendado (4.5 V mín.) y perdés rango dinámico.
- El pin `5V` del SuperMini es **VBUS del USB directo** — es ruidoso, y ruido en
  VCC entra por VREF (= 0.5·VCC) directo a la señal. El RC de 10 Ω + 100 µF
  (fc ≈ 160 Hz) es el mínimo. Si querés los 99 dB de verdad, poné un LDO limpio
  (ej. **LP2985-5.0** alimentado desde una batería de 9 V, o **TPS7A4901**).
  Con la notebook conectada por USB vas a ver el switching de la fuente en el
  espectro; con batería, no.
- Los **dos pines `GND`** del módulo van conectados juntos a GND del ESP32.
- Los **dos pines `3.3`** son el mismo net (VDD); alcanza con conectar uno.
- El PCM1808 se resetea solo si le cortás SCKI (`t(CKR)` ≈ 50 µs) — útil para
  reiniciarlo por software sin tocar la alimentación.

---

## 3. Mapeo de pines propuesto (ESP32-C3 SuperMini)

El C3 tiene **un solo periférico I²S**, y a diferencia del ESP32 clásico puede
sacar **MCLK por cualquier GPIO** (va por la GPIO matrix). Eso nos da libertad.

Restricciones del SuperMini:
- GPIOs expuestos: `0,1,2,3,4,5,6,7,8,9,10,20,21`
- **Strapping (evitar): `GPIO2`, `GPIO8`, `GPIO9`.** `GPIO9` = botón BOOT,
  `GPIO8` = LED azul integrado (**activo en bajo**).
- ADC1 (por si querés seguir usando el ADC interno en paralelo): `GPIO0..GPIO4`
- `GPIO20/21` = UART0 (RX/TX). El SuperMini además tiene **USB nativo (CDC)**, que
  es mucho más rápido que la UART → vamos a usar USB CDC para los datos.

**Es especialmente importante que `OUT`/DOUT NO vaya a GPIO2, 8 ni 9**: el PCM1808
mantiene DOUT en 0 hasta que sale de reset, y un strapping pin en LOW durante el
arranque impide que el ESP32 bootee.

| ESP32-C3 | → | Módulo PCM1808 | Notas |
|---|---|---|---|
| `GPIO4` | → | `SCK` (SCKI/MCLK) | 256·fs. A 48 kHz = 12.288 MHz |
| `GPIO5` | → | `BCK` | 64·fs. A 48 kHz = 3.072 MHz |
| `GPIO6` | → | `LRC` (LRCK/WS) | = fs |
| `GPIO7` | ← | `OUT` (DOUT) | **entrada** al ESP32 |
| `GND` | ↔ | `GND` (los dos) | |
| `3V3` | → | `3.3` | VDD |
| `5V` | → | `5V` | VCC, con el filtro de la sección 2 |
| `GND` | → | `FMY` (FMT) | I²S 24 bit |
| `GND` | → | `MDI` (MD1) | esclavo |
| `GND` | → | `MDO` (MD0) | esclavo |
| `GPIO10` | ← | *(sync de sweep, opcional)* | ver sección 6 |
| `GPIO8` | | *(LED integrado, activo bajo)* | indicador de estado |

Niveles: VDD = 3.3 V → DOUT sale 0–3.3 V, compatible directo con el C3. Las
entradas digitales del PCM1808 son 5-V tolerantes y aceptan 3.3 V sin problema.
**No hace falta level shifter en ningún lado.**

Cableado: los cuatro clocks son señales de MHz. Mantené los cables **cortos
(< 10 cm)** y con un GND al lado. Si usás protoboard vas a tener crosstalk de BCK
sobre la entrada analógica — es la causa típica de un piso de ruido feo.
**Ideal: la parte analógica en una plaquita aparte, con el módulo lo más cerca
posible del ESP32 y la señal analógica entrando por cable blindado.**

---

## 4. Front-end analógico

### 4.1 Lo que hay que respetar (datasheet)

| Parámetro | Valor |
|---|---|
| Fondo de escala | **0.6 · VCC = 3.0 Vpp** (±1.5 V) con VCC = 5 V |
| Tensión de centro | **VREF = 0.5 · VCC = 2.5 V** |
| Impedancia de entrada | **60 kΩ** |
| Filtro antialias analógico interno | −3 dB en **1.3 MHz** |
| Sobremuestreo del modulador | 64× |
| Rango de fs | **8 kHz – 96 kHz** |
| Rango dinámico / SNR | 99 dB (A-weighted) @ 48 kHz |
| THD+N | −87 a −93 dB |

Tu módulo ya trae el capacitor de acople y la red de polarización a VREF, así que
**la entrada la podés atacar directamente con una señal centrada en 0 V** — el
capacitor la recentra en 2.5 V solo.

### 4.2 Ganancia necesaria — con tus números reales

Medí tus CSV:

| | SDS00001 (vacío) | SDS00003 (persona) |
|---|---|---|
| CH1 (IF) Vpp | 0.604 V | 0.848 V |
| CH1 σ | 97.7 mV | 239 mV |
| CH2 (rampa) Vpp | 2.16 V | 7.36 V (con clipping) |

Con 0.6–0.85 Vpp sobre un fondo de escala de 3.0 Vpp estás a **−14 dBFS**. Eso ya
es perfectamente usable con 24 bits (te quedan ~85 dB de rango dinámico). O sea:

> **La etapa de ganancia es OPCIONAL.** Podés arrancar conectando la IF directo y
> ver qué pasa. Si querés exprimir el ADC, una ganancia de **×3.5** te deja el
> pico en −1 dBFS.

Si la agregás, un no-inversor con rail-to-rail alimentado de los mismos 5 V:

```
                        5V
                         │
   IF ──┤├── R1 100k ────┼──> polarización a 2.5 V (divisor 100k/100k + 10µF)
     (1µF)               │
                    ┌────┴────┐
   ───────────────> │+ MCP6002│──┬──── R_aa 1k ──┬──> VINL del módulo
              ┌───> │−  (o    │  │               │
              │     │ OPA2340)│  │              ═╪═ C_aa 1.5 nF   → LPF 106 kHz
              │     └─────────┘  │               │
              ├── R3 3k3 ────────┘              GND
              │
              └── R2 1k3 ── 2.5V     G = 1 + R3/R2 = 3.5
```

Notas:
- **Rail-to-rail obligatorio** (MCP6002, OPA2340, TLV9062). Un LM358 no llega a
  los rieles y te clipea.
- El `R_aa/C_aa` es un antialias de cortesía. Como el modulador es delta-sigma con
  64× de sobremuestreo, el aliasing real solo puede entrar en bandas angostas
  alrededor de `k · 64 · fs` (a 48 kHz eso es 3.07 MHz, 6.14 MHz…). El filtro
  interno de 1.3 MHz ya ayuda; este RC lo termina de matar. **No hace falta un
  Sallen-Key**: esa es la gran ventaja de usar un delta-sigma.
- Si tu mixer ya tiene un LPF de video a la salida, este RC es redundante.

### 4.3 Lo que **no** hay que hacer

- ❌ No metas una señal con componente de DC esperando leerla. El DC se va, punto.
- ❌ No superes 3.0 Vpp: satura y el delta-sigma satura **feo** (no clipea
  suavemente como un SAR, se vuelve inestable y escupe basura). Tu CH2 de
  SDS00003 llegó a 7.36 Vpp → eso hay que atenuar antes de entrar.
- ❌ No dejes la entrada al aire si no la usás: atala a GND por un capacitor.

---

## 5. Arquitectura de reloj del ESP32-C3 y precisión real de fs

El C3 **no tiene APLL** (el ESP32 clásico sí). El I²S solo puede colgarse de
`PLL_160M` (160 MHz) o del `XTAL` (40 MHz), y llega a la frecuencia pedida con un
divisor **fraccionario** `N + b/a` (con `a,b ≤ 63`).

Consecuencia práctica: **fs no siempre es exacta.**

| fs pedida | MCLK = 256·fs | 160 MHz / MCLK | ¿Exacto? | Error |
|---|---|---|---|---|
| 48 000 Hz | 12.288 MHz | 13 + 1/48 | ✅ exacto | 0 |
| 32 000 Hz | 8.192 MHz | 19 + 17/32 | ✅ exacto | 0 |
| 44 100 Hz | 11.2896 MHz | 14 + 5/29 (aprox) | ⚠ | ~0.005 % |
| 96 000 Hz | 24.576 MHz | 6 + 25/49 (aprox) | ⚠ | ~0.04 % |
| 16 000 Hz | 4.096 MHz | 39 + 1/16 | ✅ exacto | 0 |

**Recomendación: usá 16 / 32 / 48 kHz**, que salen exactas del PLL de 160 MHz.
Igual el firmware va a **reportar la fs real calculada**, y para un FMCW un error
de 0.05 % en fs es un error de 0.05 % en la distancia (2.5 mm en 5 m) → irrelevante.
Lo que sí importa es que el **jitter** de un divisor fraccionario es peor que el
de un cristal.

⚠ El PCM1808 es **sensible al jitter entre LRCK y SCKI**: si la relación se corre
más de ±6 BCK en un período de muestra, el chip **se muta solo** (saca ceros) y
tarda `32/fs + 48/fs` en recuperarse. Como el ESP32 deriva MCLK, BCK y LRCK del
**mismo divisor**, están sincronizados por construcción y esto no debería pasar.
Si ves silencios digitales periódicos, es esto.

**Ancho de slot: 32 bits, no 24.** El PCM1808 en modo esclavo acepta 64 BCK/frame
o 48 BCK/frame, **pero no 32**. Configurando slots de 32 bits estéreo tenemos
64 BCK/frame exactos ✓. La muestra de 24 bits viene alineada al MSB dentro de la
palabra de 32 → en firmware se recupera con un **shift aritmético a la derecha de
8 bits** (`sample = raw >> 8`, con `int32_t`, que preserva el signo).
(De paso: el driver I²S del ESP-IDF tiene rarezas conocidas con `bit_width = 24`;
usar 32 las evita.)

---

## 6. Sincronismo con el sweep — el punto crítico del GPR

Para hacer FFT por sweep y promediar coherentemente, el firmware **tiene que saber
dónde empieza cada rampa**. Hoy lo resolvés con CH2 del osciloscopio. Opciones:

### Opción A — Muestrear la rampa en el canal derecho ★ recomendada (si acelerás el sweep)
El PCM1808 es **estéreo**: `VINL` = IF del mixer, `VINR` = rampa de sintonía.
Ambos se muestrean en el **mismo instante y con el mismo reloj** → sincronismo
perfecto, cero jitter relativo, y reutilizás tu `detectar_segmentos()` de
`analisis_gpr.py` casi sin tocarlo.

- ✅ Funciona **solo si el sweep es rápido** (T ≤ 100 ms → fundamental ≥ 10 Hz).
  Con 1.46 s la rampa queda diferenciada por el acople AC y no sirve.
- Hay que **atenuar**: tu rampa es 2.16 Vpp (y 7.36 Vpp en una de las capturas).
  Un divisor resistivo simple alcanza. Ojo: como se acopla en AC, del diente de
  sierra queda solo la parte variable — el flanco de retorno (flyback) sigue siendo
  clarísimo y es todo lo que necesitás para segmentar.

### Opción B — Pulso de sync digital a un GPIO
Si tu generador de rampa tiene salida de sync/trigger (los generadores de función
la tienen), va a `GPIO10` con una interrupción.

- ✅ Funciona a cualquier velocidad de sweep.
- ⚠ El timestamp de la interrupción está en el dominio de `esp_timer`, no en el
  dominio del reloj I²S. Hay que correlacionarlos (se puede: llevás la cuenta de
  frames I²S y anotás el contador en la ISR). Precisión ~1 muestra.
- ⚠ Si el pulso es de 5 V, divisor resistivo — el C3 **no** es 5-V tolerante.

### Opción C — Que el ESP32 genere la rampa ★★ la mejor de todas
El ESP32-C3 manda la tensión de sintonía del VCO y además muestrea. Sabe
exactamente en qué punto del sweep está cada muestra: **coherencia perfecta, sin
detección de flancos, sin jitter**. Además podés hacer sweeps arbitrarios
(triangular, escalonado, stepped-frequency, pre-distorsionado para linealizar el VCO).

- ⚠ El **ESP32-C3 no tiene DAC** (el ESP32 clásico sí). Dos caminos:
  - **PWM (LEDC) + RC**: gratis, pero 8 bits a 312 kHz de portadora → 256 escalones
    sobre la banda = 3.9 MHz por escalón, y el ripple del PWM te modula el VCO.
    Aceptable para empezar, mediocre para la tesis.
  - **DAC SPI externo `MCP4921`** (12 bit, ~USD 2, 3 pines): 4096 escalones =
    244 kHz por paso, salida limpia. **Es lo que recomiendo.** Se le manda una
    muestra nueva por cada N muestras del I²S → rampa perfectamente enganchada al
    reloj del ADC.
- ⚠ Requiere saber el rango de tensión de sintonía de tu VCO (¿0–2.2 V como en
  CH2? ¿o CH2 es una versión escalada?) y probablemente un amplificador de
  tensión si el VCO pide más que 3.3 V.

---

## 7. Presupuesto de datos: throughput y RAM

Esto define si el firmware puede **streamear** o tiene que **capturar en ráfaga**.

Datos crudos = `fs × 2 canales × 4 bytes`:

| fs | Caudal crudo |
|---|---|
| 16 kHz | 128 kB/s |
| 48 kHz | **384 kB/s** |
| 96 kHz | 768 kB/s |

Capacidades del C3 SuperMini:

- **UART a 921600 baudios ≈ 92 kB/s** → no alcanza ni a 16 kHz. Descartada para datos crudos.
- **USB CDC nativo (Full Speed 12 Mbps)**: en la práctica **200–500 kB/s** sostenidos.
  A 48 kHz estéreo crudo estás en el límite; a 96 kHz **no llega**.
- **RAM**: 400 kB de SRAM total, heap libre realista **~250–300 kB** (sin WiFi).
  Guardando estéreo `int32`: ~30 000 frames = **0.6 s a 48 kHz**. Poco.

### Solución: diezmado en el firmware

Tu señal útil, incluso con `T_sweep = 5 ms`, ocupa como mucho hasta 5–10 kHz. No
necesitás mandar 48 000 muestras/s a la PC. Diezmando por `D` con un filtro
promediador (CIC/boxcar) de largo `D`:

- El caudal cae `D` veces.
- Y de yapa **ganás resolución**: promediar `D` muestras da `+10·log10(D)` dB de
  SNR (D = 16 → **+12 dB**, o sea +2 bits efectivos).

| fs | D | fs efectiva | Caudal | ¿Streaming por USB? |
|---|---|---|---|---|
| 48 kHz | 1 | 48 kHz | 384 kB/s | ⚠ al límite |
| 48 kHz | 4 | 12 kHz | 96 kB/s | ✅ cómodo |
| 48 kHz | 16 | 3 kHz | 24 kB/s | ✅✅ hasta en CSV de texto |
| 96 kHz | 8 | 12 kHz | 96 kB/s | ✅ cómodo |

→ **El firmware va a tener dos parámetros independientes: `fs` (reloj del ADC,
8–96 kHz) y `D` (diezmado, 1–256).** Eso te da "frecuencia de sampling variable"
en los dos sentidos que importan.

Y además va a soportar **dos modos de salida**:
- **Streaming continuo** (CSV de texto para debug, o binario para producción).
- **Ráfaga a RAM** (`N` sweeps) + volcado posterior — para cuando quieras fs
  máxima sin diezmar y no te importe capturar de a tandas.

---

## 8. Riesgos y "gotchas" conocidos

| # | Riesgo | Mitigación |
|---|---|---|
| 1 | Confundir `SCK`(=MCLK) con `BCK` | Ver sección 1. Es el error #1. |
| 2 | Módulo con oscilador soldado + MD en modo maestro | Mandar foto; desoldar si aplica |
| 3 | Alimentar VCC con 3.3 V | Fondo de escala cae a 2 Vpp y el chip queda fuera de spec |
| 4 | Todo cero en DOUT | 99 % de las veces es SCKI ausente o mal conectado. El chip queda en reset si no ve SCKI |
| 5 | Silencios periódicos | Pérdida de sync LRCK↔SCKI (ver §5) |
| 6 | Ruido de conmutación del USB en el espectro | Alimentar con batería + LDO |
| 7 | Crosstalk de BCK (MHz) sobre la entrada analógica | Cables cortos, GND de guarda, analógico separado |
| 8 | Buscar el DC / los mHz | No existe en este chip. Es estructural |
| 9 | DOUT a un strapping pin (2/8/9) → no bootea | Usar GPIO7 |
| 10 | `bit_width = 24` en el driver I²S | Usar slots de 32 bits y `>> 8` |
| 11 | Los primeros ~80 ms de datos son basura | El chip hace fade-in tras el reset. El firmware descarta el arranque |

---

## 9. Diagrama completo propuesto (escenario recomendado)

```
     ┌──────────────────┐
     │  VCO 1.0–2.0 GHz │◄─── V_tune ──┬── (Opción C) MCP4921 ◄─SPI─┐
     └────────┬─────────┘              │                            │
              │                        └── (Opción A) divisor ──┐   │
        ┌─────┴─────┐                                           │   │
        │  Splitter │                                           │   │
        └──┬─────┬──┘                                           │   │
           │     │                                              │   │
        TX │     │ LO                                           │   │
      ┌────┴─┐ ┌─┴────┐                                         │   │
      │Ant TX│ │Mixer │◄── RX ◄── Ant RX                        │   │
      └──────┘ └──┬───┘                                         │   │
                  │ IF (0.6 Vpp)                                │   │
                  │                                             │   │
            ┌─────┴──────┐                                      │   │
            │ LPF + gain │ (opcional ×3.5)                      │   │
            │  MCP6002   │                                      │   │
            └─────┬──────┘                                      │   │
                  │                                             │   │
                  ▼                                             ▼   │
            ┌─────────────────────────────────────────────────────┐ │
            │              MÓDULO PCM1808                         │ │
            │  VINL ◄── IF          VINR ◄── rampa (sync)         │ │
            │  FMT─GND  MD1─GND  MD0─GND   (esclavo, I²S 24b)     │ │
            │  VCC=5V(filtrado)   VDD=3.3V                        │ │
            └──┬──────┬──────┬──────┬─────────────────────────────┘ │
            SCK│   BCK│   LRC│   OUT│                               │
            ◄──┘   ◄──┘   ◄──┘   ──►│                               │
               │      │      │      │                               │
            GPIO4  GPIO5  GPIO6  GPIO7                              │
            ┌──┴──────┴──────┴──────┴────────────────────┐          │
            │        ESP32-C3 SuperMini                  │──────────┘
            │  I²S maestro · fs 8–96 kHz variable        │  GPIO0/1/10
            │  diezmado D · sync por sweep · USB CDC     │
            └────────────────────┬───────────────────────┘
                                 │ USB (datos + alimentación)
                                 ▼
                              Notebook  →  analisis_gpr.py v3
```

---

## 10. Preguntas

### 🔴 Bloqueantes (necesito estas para escribir el firmware correcto)

1. **¿Podés acelerar el sweep FMCW?** ¿Qué genera hoy la rampa de 1.46 s —
   generador de funciones, un 555, un Arduino, un integrador analógico? ¿Cuál es
   el límite de velocidad de tu VCO / lazo de sintonía?
2. **¿Quién va a generar la rampa en la versión final** — sigue siendo externo, o
   te sirve que la genere el ESP32-C3 (Opción C, con MCP4921)?
3. **¿Qué querés en el canal derecho (VINR)?** ¿La rampa para sincronizar, una
   segunda antena RX, la componente Q de un mixer I/Q, o nada?
4. **¿Modo de salida?** ¿Streaming continuo a la PC mientras medís, o ráfaga
   (capturo N sweeps → vuelco → repito)?

### 🟡 Importantes

5. **Foto del módulo, ambas caras.** Necesito ver si tiene oscilador soldado,
   qué capacitores de acople trae (define el HPF exacto) y si hay regulador
   on-board.
6. ¿El mixer da una IF sola o I/Q (dos salidas en cuadratura)?
7. ¿Qué amplitud tiene la IF **realmente** en la entrada del sistema? (medí 0.6 Vpp
   en el osciloscopio, pero puede haber una etapa de por medio).
8. ¿El VCO es lineal en tensión→frecuencia, o hay que pre-distorsionar la rampa?
   ¿Tenés la curva V_tune vs f? (Impacta mucho la calidad de la FFT).
9. ¿Alimentación por USB desde la notebook, o batería? (define cuánto esfuerzo
   poner en la limpieza de VCC).
10. ¿La medición es estática (antenas quietas) o barrido en movimiento (B-scan)?
    Si es B-scan, ¿cómo se registra la posición — encoder, tiempo, manual?

### 🟢 De diseño / preferencias

11. **Toolchain**: ¿Arduino IDE (como tu `sketch_may29a.ino`) o PlatformIO?
    ¿Qué versión del core ESP32 de Arduino tenés? (La API de I²S cambió
    completamente entre la 2.x y la 3.x — necesito saberlo).
12. **Formato de salida**: ¿CSV de texto (cómodo, lento) o binario + script Python
    de decodificación (rápido, eficiente)? Puedo hacer los dos y que se elija por
    comando.
13. ¿Querés control interactivo por consola serie (comandos tipo `fs 48000`,
    `dec 16`, `start`, `stop`) o todo por `#define` y recompilar?
14. ¿Querés que el ESP32 haga la FFT a bordo (tiene DSP suficiente para 512–1024
    puntos por sweep) y mande solo el perfil de rango, o que mande crudo y todo el
    procesamiento quede en Python?
15. ¿Guardar en tarjeta SD? (Sería otra opción para no depender del USB, pero
    consume 4 GPIOs más — quedan justos).
16. ¿Necesitás WiFi (medir con la notebook lejos)? Ojo: **WiFi en el C3 come RAM y
    genera interferencia**; con un radar cerca no es gratis.

---

## 11. Fuentes

- [PCM1808 datasheet SLES177B — Texas Instruments](https://www.ti.com/lit/ds/symlink/pcm1808.pdf)
- [PCM1808 product folder — TI](https://www.ti.com/product/PCM1808)
- [Inter-IC Sound (I2S) — ESP-IDF Programming Guide, ESP32-C3](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-reference/peripherals/i2s.html)
- [I2S — Arduino-ESP32 documentation](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/i2s.html)
- [ESP32-C3 Super Mini Pinout Reference — Last Minute Engineers](https://lastminuteengineers.com/esp32-c3-super-mini-pinout-reference/)
- [Strapping Pins — ESP32-C3 Wireless Adventure](https://espressif.github.io/esp32-c3-book-en/chapter_5/5.2/5.2.6.html)
- Datos medidos de `MEDI/SDS00001.CSV` y `MEDI/SDS00003.CSV`
