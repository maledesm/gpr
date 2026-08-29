# Pruebas

Sketches de **medición**, no del sistema. Cada uno prueba **una sola cosa**, sin
depender de nada más del repo: si algo no cierra, el problema está adentro de
ese archivo y en ningún otro lado.

Están separados de `firmware/` a propósito. En `firmware/` vive lo que va en la
placa cuando el radar funciona; acá vive lo que se carga para contestar una
pregunta concreta y después se borra de la placa.

---

## `velocidad_dac/`

**Pregunta que contesta:** ¿cuánto tarda de verdad una escritura al MCP4725, y
qué relación impone eso entre el PRF y la cantidad de escalones?

Esa es la restricción que gobierna todo el diseño de la rampa. Con `N` niveles
hay `N−1` intervalos, y una triangular completa los recorre dos veces:

```
PRF_min = 2 · (N − 1) · t_escritura
N_max   = 1 + PRF / (2 · t_escritura)
```

Y de `N` cuelga la física:

```
Δf     = BW / (N − 1)          salto de frecuencia por escalón
R_amb  = c / (4·Δf)            alcance no ambiguo (UN canal real)
ΔR     = c / (2·BW)            resolución — NO depende de N
```

### Cableado

| ESP32-C3 | | |
|---|---|---|
| `GPIO0` | → | `SDA` |
| `GPIO1` | → | `SCL` |
| `3V3` | → | `VCC` |
| `GND` | ↔ | `GND` |
| `GPIO3` | → | **canal 2** del osciloscopio (sube durante la escritura) |
| `OUT` del DAC | → | **canal 1** del osciloscopio |

`GPIO3` no es strapping y no lo usa nada más, así que se puede sacrificar como
pin de marca.

### Las tres mediciones

**1. `barrido`** — mide a 100k, 200k, 400k, 800k y 1M de reloj I²C y desglosa
cuánto es bus y cuánto es la librería `Wire`. Si el overhead no baja al subir
el reloj, el techo lo pone el driver y acelerar más no sirve.

**2. `sq`** — cuadrada entre dos códigos a máxima velocidad. **Es la medición
más confiable**, porque el número sale del osciloscopio y no del reloj del
propio ESP32:

```
t_escritura = 1 / (2 · f_medida)
```

Y de paso se ve si el DAC **alcanza a establecerse**: si en vez de cuadrada
aparece un trapecio, no llega.

**3. `rampa <pasos>`** — triangular con esa cantidad de escalones, corriendo a
fondo. No se le pide un PRF: se mide el que sale. Es la respuesta directa a la
pregunta, y el osciloscopio lo confirma midiendo el período.

Después, `tabla` arma la grilla PRF vs escalones con el `t_escritura` medido,
agregando `Δf` y el alcance no ambiguo de cada fila.

### Comandos

| | |
|---|---|
| `sq [bajo alto]` | cuadrada a máxima velocidad |
| `rampa <pasos>` | triangular a máxima velocidad |
| `mide [n]` | `t_escritura` por software |
| `barrido` | mide a los cinco relojes |
| `tabla` | PRF vs pasos, con Δf y alcance |
| `clk <hz>` | reloj del I²C |
| `dc <codigo>` | tensión fija, para el tester |
| `dac` | re-escanea 0x60..0x67 |
| `info` · `help` | |

`sq` y `rampa` corren hasta que mandes cualquier tecla.

### Compilar

```bash
arduino-cli compile --fqbn "esp32:esp32:esp32c3:CDCOnBoot=cdc" pruebas/velocidad_dac
```

En el IDE: placa **Nologo ESP32C3 Super Mini**, o **ESP32C3 Dev Module** con
*USB CDC On Boot = Enabled*. Con CDC deshabilitado el monitor queda mudo — el
sketch tira un `#warning` al compilar para avisarlo.

### Lo que este sketch NO hace

- No usa la tabla de predistorsión: los códigos van lineales. Acá se mide
  velocidad, no linealidad.
- No toca el I²S ni el PCM1808.
- No guarda nada en flash.
