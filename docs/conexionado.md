# Conexionado del banco de prueba

ESP32-C3 SuperMini + módulo PCM1808 + Arduino Uno como generador de patrón.
Hoja de referencia para armar en protoboard.

---

## 1. ESP32-C3 → módulo PCM1808 (señales digitales)

| ESP32-C3 | | Módulo | Qué es |
|---|---|---|---|
| `GPIO4` | → | `SCK` | **SCKI / master clock** = 256·fs |
| `GPIO5` | → | `BCK` | bit clock = 64·fs |
| `GPIO6` | → | `LRC` | LRCK / word select = fs |
| `GPIO7` | ← | `OUT` | DOUT, datos (**entrada** al ESP32) |

> ⚠ **`SCK` de este módulo es el MASTER CLOCK, no el bit clock.** El bit clock
> es `BCK`. En casi todos los micrófonos I²S de hobby `SCK` significa bit clock;
> acá no. Cruzarlos da "todo cero" y es el error más común con este chip.

> ⚠ **`OUT` tiene que ir a `GPIO7`.** No lo pases a GPIO2, GPIO8 ni GPIO9: son
> strapping pins, y el PCM1808 mantiene DOUT en bajo hasta salir de reset, con
> lo cual el ESP32 no bootea.

## 2. Pines de configuración → todos a GND

| Módulo | A | Efecto |
|---|---|---|
| `FMY` (FMT) | GND | Formato I²S de 24 bits |
| `MDI` (MD1) | GND | ┐ modo **esclavo** |
| `MDO` (MD0) | GND | ┘ (autodetecta SCKI 256/384/512·fs) |

Tienen pulldown interno de 50 kΩ, así que al aire ya quedan en bajo — pero
atalos con cable igual: con RF cerca no querés entradas flotando.

**MD1 y MD0 se leen una sola vez, al encender.** No se pueden cambiar en caliente.

## 3. Alimentación — acá va el RC

```
              10 Ω
ESP32 5V ────/\/\/\────┬──────────────────┬────► 5V (VCC) del módulo
                       │                  │
                     100 µF             100 nF     ← lo más cerca del módulo
                    (electrolítico)     (cerámico)
                       │                  │
GND ───────────────────┴──────────────────┴────► GND
```

```
ESP32 3V3 ─────────────┬──────────────────┬────► 3.3 (VDD) del módulo
                       │                  │
                     10 µF              100 nF
                       │                  │
GND ───────────────────┴──────────────────┴────► GND
```

Por qué el RC: el pin `5V` del SuperMini es VBUS del USB directo, y es ruidoso.
Ese ruido entra por VREF (= 0.5·VCC) derecho a la señal medida. El RC de
10 Ω + 100 µF corta en **159 Hz** y limpia todo lo que esté por encima.

- **Respetá la polaridad del electrolítico**: la pata larga (+) al lado del
  resistor y de VCC, la corta (−) a masa.
- El de 100 nF va **lo más pegado posible** al módulo. Es el que se ocupa de
  los transitorios rápidos, que el electrolítico no alcanza a seguir.
- La caída sobre los 10 Ω es de unos 145 mV con los ~14.5 mA que consume el
  módulo. Irrelevante.

**`VCC` va a 5 V, no a 3.3 V.** El fondo de escala es `0.6·VCC` = 3.0 Vpp; con
3.3 V el chip queda fuera del rango de operación recomendado (4.5 V mínimo).

Los **dos pines `GND`** del módulo van a masa. Los **dos pines `3.3`** son el
mismo nodo interno: alcanza con conectar uno.

## 4. Arduino Uno → entrada analógica

```
Uno D9 ──── 10 kΩ ───┬───────────► VINL (entrada izquierda del módulo)
                     │
                    4k7
                     │
Uno GND ─────────────┴───────────► GND común
```

```
divisor sin carga  = 4.7 / 14.7          = 0.320
impedancia salida  = 10k ‖ 4k7           = 3.2 kΩ
carga del módulo   = 60 / (60 + 3.2)     = 0.949
amplitud en el ADC = 5 × 0.320 × 0.949   = 1.52 Vpp   (−5.9 dBFS)
```

> ⚠ **El divisor no es opcional.** El Uno saca 5 Vpp y el fondo de escala son
> 3.0 Vpp. Un delta-sigma saturado no recorta suave como un SAR: se vuelve
> inestable y escupe basura.

> ⚠ **Dónde está `VINL`**: los 12 pines de la tira que veníamos usando son
> todos digitales y de alimentación. Las entradas analógicas están en **otro
> conector del módulo**, casi siempre un header aparte rotulado `L / G / R` o
> `IN L / IN R`, o directamente unos pads. Fijate en tu placa antes de conectar.
> Si no encontrás el rótulo, seguí la pista que llega a los capacitores de
> acople: esa es la entrada.

## 4 bis. ESP32-C3 → MCP4725 (la rampa de sintonía del VCO)

Es el DAC que genera la triangular que barre el VCO. Va por I²C, en un bus
aparte de todo lo demás.

| ESP32-C3 | | MCP4725 | Qué es |
|---|---|---|---|
| `GPIO0` | ↔ | `SDA` | datos I²C |
| `GPIO1` | → | `SCL` | reloj I²C |
| `3V3` | → | `VCC` | **3.3 V** |
| `GND` | ↔ | `GND` | |
| | | `OUT` | → entrada del amplificador que ataca al VCO |

**`VCC` define la escala completa**: la salida del DAC va de 0 a VDD. Si el riel
real no es 3.300 V, todas las tensiones se escalan y el barrido se corre entero.
Medilo con el tester y, si difiere, regenerá la tabla cambiando `VDD` en
[`../VCO/analisis_vco.py`](../VCO/analisis_vco.py).

La mayoría de los módulos ya traen las resistencias de pull-up del bus. Si el
tuyo no las tiene, van **2 × 4k7 a 3.3 V**, una en SDA y otra en SCL.

El sketch [`prueba_mcp4725`](../firmware/prueba_mcp4725/) **escanea las
direcciones 0x60 a 0x67** al arrancar y te dice cuál encontró, así que no hace
falta saberla de antemano.

> ⚠ **Falta la protección del VCO.** Todavía no hay clamp ni Zener entre el
> amplificador y la entrada de sintonía. Está pendiente de saber la tensión de
> alimentación del amplificador para dimensionarlo.

## 5. Masa común — no es negociable

**Uno, ESP32 y módulo tienen que compartir masa.** Sin retorno común, las
tensiones no tienen referencia y no medís nada coherente. Un solo cable de GND
entre el Uno y la protoboard alcanza.

## 6. Recomendaciones de armado

- Los cuatro relojes son señales de **MHz** (SCKI llega a 12.288 MHz a 48 kHz
  de fs). Cables **cortos, menos de 10 cm**, y si podés con un GND al lado.
- Mantené la entrada analógica **lejos de BCK y SCKI**. El acoplamiento de esos
  relojes sobre la entrada es la causa típica de un piso de ruido feo.
- Si el piso de ruido no baja, alimentá con batería en vez de USB: la fuente
  conmutada de la notebook se ve en el espectro.

---

## 7. Verificación al encender

1. **LED azul del ESP32**: 6 destellos rápidos y después ~1 Hz. Si no parpadea,
   el sketch no está corriendo.
2. En el Monitor Serie, comando `diag`. Tiene que decir **"Enlace I2S OK y hay
   señal"**.
3. Comando `stats`. Con el generador conectado:

| | Esperado |
|---|---|
| `Vpp` | **1400–1600 mV** |
| `DC` | ≈ 0 mV (el pasa-altos lo elimina) |
| `captura` | 100 % |

4. Para ver la forma de onda: `n 50` → `win 10` → `plot`.

## 8. Diagnóstico rápido de fallas

| Síntoma | Causa más probable |
|---|---|
| Todo cero en los dos canales | Falta SCKI (`GPIO4 → SCK`), o lo cruzaste con BCK. Sin SCKI el chip queda en reset. |
| Hay datos pero sin señal | Entrada al aire, generador apagado, o el divisor mal conectado |
| Los 8 bits bajos no son cero | Desalineación de trama: revisá FMT, MD1 y MD0 a GND |
| `Vpp` cerca de 3000 mV o `CLIP!` | Falta el divisor, o quedó mal armado |
| DC muy grande | Saturación (el HPF debería eliminar la continua) |
| Ruido a frecuencias altas | Crosstalk de BCK/SCKI sobre la entrada analógica |
| El ESP32 no bootea | `OUT` conectado a un strapping pin (GPIO2/8/9) |
