# Adquisición con placa de audio (U-Phoria UMC22)

Reemplazo **temporal** de la etapa de digitalización: en vez de PCM1808 + ESP32
por I²S, el beat entra por una placa de sonido USB.

> **¿Venís a dejarlo andando en una máquina nueva?** El procedimiento paso a
> paso está en [`docs/placa_audio_umc22.md`](../docs/placa_audio_umc22.md).
> Este README explica el diseño y el porqué.

> **Estado: cadena verificada con la placa conectada, sin señal de radar
> todavía.** Los dos módulos pasan su autoprueba y la captura se probó contra la
> UMC22 real: WDM-KS, 48 kHz, 2 canales, 0,05 % de error de tasa, 238592 muestras
> en 5,1 s sin clipeo ni overflow, CSV y WAV consistentes muestra a muestra.
> **Falta medir con la cadena de RF conectada.**

La cadena de RF no cambia. Cambia solamente quién digitaliza:

```
... mezclador ──> filtro ──> [divisor] ──> UMC22 ──USB──> PC
```

---

## Por qué es temporal, y qué se pierde

| | PCM1808 + ESP32 | UMC22 |
|---|---|---|
| Resolución | 24 bits | **16 bits** |
| `fs` | 8–96 kHz, variable en caliente | 44,1 / 48 kHz |
| Corte inferior | 0,91 Hz a 48 kHz | **10 Hz** (−3 dB) |
| Sincronismo con la rampa | atable a la cuenta de muestras | **no hay** |
| Canales | 1 (el segundo está pendiente) | 2 |

**El corte inferior es el punto que importa.** La UMC22 corta *más arriba* que
el PCM1808, así que el pendiente número 1 de la tesis —acelerar el sweep— no se
relaja al cambiar de ADC: se endurece. Con `T_sweep = 10 ms` el beat a 0,2 m son
133 Hz y sobra margen; con el sweep original de 1,46 s no se ve nada. El
grabador lo calcula y avisa antes de empezar.

Los 16 bits no son el límite real: el piso de ruido medido de la cadena da unos
62 dB de SNR (≈10 bits efectivos).

**Lo que se gana** es el segundo canal: se puede grabar la rampa del DAC como
referencia de sincronismo y recuperar los bordes de cada barrido en el análisis
offline, que es lo que reemplaza al atado por cuenta de muestras.

---

## Conexionado

**Entrada 2, la de 1/4" INSTRUMENT (Hi-Z, 1 MΩ)**, con un plug **TS mono**:

| Plug | Va a |
|---|---|
| **Tip** (la punta, después del aro negro) | salida del filtro, a través del divisor |
| **Sleeve** (el cuerpo largo) | GND del circuito |

**No uses la entrada 1 (combo XLR) para el beat.** Esa va al preamp de micrófono
y tiene el botón **+48 V**: si se aprieta con el circuito conectado, le entra
fantasma por el XLR.

### Divisor de entrada — hace falta

El instrument input satura en **−3 dBu = 0,55 Vrms ≈ 1,55 Vpp** con la perilla
GAIN al mínimo, y el peor caso de la cadena es 3 Vpp.

```
señal ──[ 10 kΩ ]──┬── tip
                   │
                 [ 1,1 kΩ ]
                   │
GND ───────────────┴── sleeve
```

÷10,1 → 3 Vpp quedan en 297 mVpp, unos 14 dB abajo del clipeo, y se sube con la
perilla. Carga de 11,1 kΩ sobre el filtro (un opamp la maneja) e impedancia de
Thevenin de ~1 kΩ, baja para no levantar zumbido en el cable.

El grabador cuenta las muestras pegadas al tope de escala y lo informa: si
aparece "CLIPEO" en el resumen, el divisor o la perilla están mal.

### Canal de sincronismo (opcional pero recomendado)

La rampa del DAC, atenuada, en la **entrada 1**. Se graba en el segundo canal
del WAV. La entrada también es AC-acoplada, así que el nivel de continua se
pierde, pero para encontrar los vértices de la triangular sólo hacen falta los
flancos. Para eso: prominencia, no distancia — igual que en el análisis del
osciloscopio.

Si no se usa, poner `canal_sync = 0`.

---

## Qué escribe

Dos archivos por captura, en `datos/`:

| Archivo | Qué tiene |
|---|---|
| `AAAA-MM-DD_HHMMSS.csv` | sólo el canal de beat, **mismo formato exacto** que `grabarserial.py` |
| `AAAA-MM-DD_HHMMSS.wav` | los dos canales crudos, 16 bits. El master para el análisis offline |

El CSV usa el mismo formato a propósito: **`graficarserial.py` lo abre sin
tocarle una línea**. Espectro, osciloscopio y B-scan en vivo funcionan igual.

Los dos se escriben incrementalmente con `flush` + `fsync` cada 0,25 s: si el
programa se corta, lo grabado hasta ese momento es válido y está en disco.

> El WAV necesita el flush explícito. `wave.writeframes()` parcha el tamaño en
> la cabecera en cada llamada, pero el buffer de Python se interpone: sin
> `sincronizar()`, un corte dejaba un archivo de cero bytes. Está en la
> autoprueba.

---

## Uso

```powershell
python grabaraudio.py --listar          # qué entradas ve el sistema
python grabaraudio.py --calibrar 1.52   # fija la escala vertical
python medir_audio.py                   # graba + gráfico en vivo
python grabaraudio.py                   # graba solamente
```

### La verificación de tasa de muestreo

Antes de grabar, el programa **mide** cuántas muestras por segundo entrega
realmente el stream y las compara con las que pidió. No es paranoia: probando
esto contra la placa interna de la máquina, **WASAPI en modo exclusivo declaraba
`samplerate = 48000` y entregaba 63,2 kS/s**; el mismo dispositivo en modo
compartido daba 47,7 kS/s, que es lo correcto.

Un error así no se ve en ningún lado —el WAV suena raro y nada más— pero corre
el eje de frecuencias un 32 %, y como la distancia sale de la frecuencia de
beat, arruina todas las mediciones en silencio.

Si la desviación pasa el 2 %, el programa reintenta solo en modo compartido; si
sigue mal, avisa a los gritos y no se hace el tonto. La tasa medida queda
guardada en el encabezado del CSV (`fs_medida`), al lado de la nominal.

`fs_eff` —la clave que usa el graficador— se deja en la **nominal** a propósito:
si las dos difieren hay un problema de configuración que se arregla, no se
compensa por software metiendo un número raro en el eje.

### La calibración vertical

Sin calibrar, el CSV va en **fracción de fondo de escala** (`# unidad = FS`), no
en volts. Es lo honesto: entre el divisor y la perilla GAIN no hay forma de
saber a qué tensión corresponde el fondo de escala.

`--calibrar <Vpp>` lo resuelve inyectando una amplitud conocida —por ejemplo la
cuadrada de 1,52 Vpp de `firmware/generador_patron/`— y midiendo el pico. El
número que sale absorbe todo: divisor, perilla y fondo de escala de la placa.

**Vale mientras no se toque la perilla GAIN.** Si se mueve, hay que repetirla.

---

## Configuración de Windows

- Instalar el **driver ASIO de Behringer**. El genérico de clase USB anda, pero
  ASIO va derecho al hardware. El programa prefiere solo la API más directa que
  encuentre: ASIO → WASAPI → WDM-KS → DirectSound → MME.
- Panel de sonido → Propiedades del dispositivo → Avanzado: **48000 Hz, 2 canales,
  16 bit**.
- Pestaña **Mejoras**: desactivar todo. Cualquier AGC o supresión de ruido
  destruye la medición sin avisar.
- Un solo programa por vez con el dispositivo abierto en modo exclusivo. Es la
  misma regla que con el puerto COM del ESP32.

---

## Entorno

Igual que `adquisicion/`: venv de **Windows**, Python 3.11. Además de lo que ya
pedía el cliente serie, hace falta:

```powershell
pip install sounddevice
```

`sounddevice` trae PortAudio adentro del wheel, así que no hay nada más que
instalar. El WAV se escribe con el módulo `wave` de la biblioteca estándar: no
hace falta `soundfile`.

`grabarserial.py` necesitaba `pyserial`; éste no. El gráfico en vivo sigue
necesitando `pyqtgraph` + `PyQt6`.

---

## Archivos

| | |
|---|---|
| `audio.py` | Dispositivos, selección de API, WAV incremental. Autoprueba: `--test` |
| `grabaraudio.py` | Grabador. Autopruebas: `--test`. Utilidades: `--listar`, `--calibrar` |
| `medir_audio.py` | Lanzador: grabador + `graficarserial.py` |
| `config.json` | Se genera solo. Es por máquina, está en `.gitignore` |

Las dos autopruebas corren **sin hardware** —`audio.py` importa `sounddevice`
dentro de las funciones a propósito— así que también pasan en la máquina de
análisis en WSL.

---

## Para volver al PCM1808

Nada de esta carpeta toca `adquisicion/`, `firmware/` ni `analisis/`. Se vuelve
corriendo `medir.py` en vez de `medir_audio.py`.
