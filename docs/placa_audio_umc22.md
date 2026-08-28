# Puesta en marcha de la placa de audio (U-Phoria UMC22)

Cómo dejar andando la captura por placa de sonido **en una máquina nueva**, de
cero. El diseño y el porqué están en
[`adquisicion_audio/README.md`](../adquisicion_audio/README.md); esto es el
procedimiento.

> **Estado: la cadena está verificada de punta a punta con la placa conectada**
> (48 kHz, 2 canales, 0,05 % de error de tasa, sin pérdidas). **Todavía no se
> midió con señal del radar.**

---

## 1. Qué hace falta

**Hardware**

- Behringer U-Phoria UMC22 y su cable USB.
- Un **plug TS mono** de 6,35 mm (mono: un solo aro negro; si tiene dos es TRS y
  no sirve) y cable.
- El **divisor de entrada**: 10 kΩ + 1,1 kΩ. Soldalo *adentro del plug* o en una
  plaquetita pegada a él, no del lado del circuito: así el cable largo va con
  impedancia baja y levanta menos zumbido.

**Software**

```powershell
pip install sounddevice numpy scipy pyqtgraph PyQt6
```

- `sounddevice` es lo único nuevo respecto del cliente serie. Trae PortAudio
  adentro del wheel: no hay que instalar nada más.
- `pyqtgraph` + `PyQt6` son para el gráfico en vivo. Sin ellos graba igual, pero
  no se abre la ventana.
- `pyserial` **no** hace falta para este camino.

Tiene que ser un venv de **Windows**. WSL 2 no ve la placa de sonido, igual que
no ve los puertos COM.

**Driver**

Instalá el **driver ASIO de Behringer** desde behringer.com. No es obligatorio
—con el driver genérico de clase USB anda— pero conviene: ASIO va derecho al
hardware y además evita el lío de canales del punto 3.

Para saber cuál tenés, mirá cómo aparece la placa en el paso 4:

| Cómo aparece | Qué driver es |
|---|---|
| `UMC ASIO Driver` | el de Behringer |
| `Microphone (USB Audio CODEC)` | el genérico de Windows |

---

## 2. Conectar

1. **GAIN de la entrada 2 al mínimo**, todo a la izquierda.
2. **+48 V apagado.** Verificá que el LED esté apagado *antes* de enchufar nada.
   El fantasma sale por el XLR y le entraría al circuito.
3. Plug TS en la **entrada 2, la de 1/4" INSTRUMENT** (Hi-Z, 1 MΩ):
   - **Tip** (la punta, después del aro negro) → salida del filtro, vía divisor.
   - **Sleeve** (el cuerpo largo) → GND del circuito.
4. Opcional pero recomendado: la rampa del DAC, atenuada, en la **entrada 1**.
   Se graba en el segundo canal del WAV y sirve de referencia de sincronismo.

**Nunca el beat en el combo XLR.** Esa entrada va al preamp de micrófono y tiene
el botón de +48 V al lado.

---

## 3. Configurar Windows

Panel de sonido → la UMC22 → Propiedades → **Avanzado**:

- Formato: **2 canales, 16 bit, 48000 Hz**.
- Pestaña **Mejoras**: desactivar todo.

**Los 2 canales importan más de lo que parece.** Windows suele dejar el formato
compartido en **mono**, y entonces la placa aparece con 1 solo canal por WASAPI
—no alcanza para grabar beat + sincronismo. Es exactamente lo que nos pasó la
primera vez (ver §7).

Y cerrá lo que pueda estar agarrando la placa: Audacity, Zoom, Discord, el
navegador. Vale la misma regla que con el puerto COM del ESP32: un solo programa
por vez.

---

## 4. Verificar que la placa aparece

```powershell
python adquisicion_audio\grabaraudio.py --listar
```

Sale el listado completo y, al final, cuál eligió `auto`. Lo que se vio en la
máquina de referencia, con el driver genérico:

```
[  1] Microphone (USB Audio CODEC )   MME                 2 ch   44100 Hz  <- placa de audio
[  7] Microphone (USB Audio CODEC )   Windows DirectSoun  2 ch   44100 Hz  <- placa de audio
[ 14] Microphone (USB Audio CODEC )   Windows WASAPI      1 ch   48000 Hz  <- placa de audio
[ 37] Microphone (USB Audio CODEC)    Windows WDM-KS      2 ch   44100 Hz  <- placa de audio
```

**El mismo dispositivo aparece una vez por API, y no todas ofrecen lo mismo.**
Acá WASAPI lo mostraba con 1 canal (formato en mono) y WDM-KS con 2. El programa
descarta las que no alcanzan antes de mirar la preferencia de API, así que con
`canal_sync` activo elige la de 2 canales.

Si `auto` no la encuentra, poné el índice a mano en `dispositivo` cuando el
grabador te lo pregunte.

---

## 5. Ajustar el GAIN

Antes de tocar el radar, conectá el **Arduino Uno con `generador_patron`** (la
cuadrada de 100 Hz, 1,52 Vpp). Es el mismo camino con el que se validó el
PCM1808.

```powershell
python adquisicion_audio\grabaraudio.py
```

Contestá las preguntas —Enter deja el valor entre corchetes— y poné
`duracion_s` en 10 para esta prueba.

**Mirá el arranque:**

```
Verificando la tasa de muestreo real...
Tasa real: 47976 S/s contra 48000 nominales (0.05 % de error). Bien.
```

Si en vez de eso sale el cartel de `!!!!`, **pará y arreglá la configuración de
Windows antes de seguir**. Un error de tasa corre el eje de distancias sin que se
note en ningún otro lado.

**Y la línea de estado:**

```
10.0 s | 480000 muestras | 48.00 kS/s | pico  -8.3 dBFS | clip 0 | overflow 0
```

Subí el **GAIN** hasta que el pico quede entre **−12 y −6 dBFS**: deja margen y
aprovecha la escala. Si aparece `clip` distinto de cero, bajá.

De referencia: con las entradas al aire el piso de ruido da **−78 dBFS**. Si ves
eso con la señal conectada, no está entrando nada.

---

## 6. Calibrar — con el GAIN ya donde va a quedar

Con la cuadrada de 1,52 Vpp todavía conectada y **sin tocar más la perilla**:

```powershell
python adquisicion_audio\grabaraudio.py --calibrar 1.52
```

Devuelve `escala_v_por_fs` y lo guarda en `config.json`. A partir de ahí el CSV
sale en volts y el encabezado dice `unidad = V`. Sin esto va en fracción de fondo
de escala (`unidad = FS`), que es lo honesto: entre el divisor y la perilla no
hay forma de saber a qué tensión corresponde el fondo de escala.

**Desde acá la perilla GAIN no se toca.** Si se mueve, la calibración deja de
valer y hay que repetir este paso.

`config.json` está en `.gitignore` porque es por máquina: **cada computadora
tiene su propia calibración**, y copiarla de una a otra da números mal.

---

## 7. Medir

Desconectá el generador de patrón, conectá la salida del filtro, y:

```
medir_audio.bat
```

Arranca el grabador y, cuando aparece el CSV, abre `graficarserial.py`
apuntándole: espectro, osciloscopio y B-scan en vivo, igual que con el ESP32.

Poné `t_sweep_ms` acorde a la rampa que esté corriendo el DAC. Fijate en el
resumen previo:

```
Beat a 0.2 m         : 133.3 Hz
```

Si sale el aviso de que el beat cae contra los 10 Hz de la placa, el sweep está
muy lento y no vas a ver nada útil cerca.

Al terminar, los tres renglones que tienen que estar limpios:

```
Tasa       : 48151.6 S/s medidos, 48000 nominales (0.32 % de error)
Clipeo     : ninguno
Overflow   : ninguno
```

Los archivos quedan en `datos/`: el **CSV** (canal de beat, para el graficador) y
el **WAV** (los dos canales crudos, para el análisis offline).

---

## 8. Si algo no anda

| Síntoma | Causa | Solución |
|---|---|---|
| `no encontre la placa` | No está enchufada, o el nombre no matchea las pistas | `--listar` y poner el índice a mano en `dispositivo` |
| `ofrece 1 canal/es y hacen falta 2` | El formato compartido de Windows está en mono | Propiedades → Avanzado → 2 canales. O instalar ASIO. O `canal_sync = 0` |
| Cartel de `!!!!` con la tasa | El driver declara una `fs` y entrega otra | Formato en 48000 Hz, desactivar Mejoras, probar ASIO |
| `[aviso] No pude abrir en modo exclusivo` | Otra aplicación tiene la placa | Cerrar Audacity, Zoom, Discord, el navegador |
| Pico en −78 dBFS con señal conectada | No entra nada | Revisar el cable, el divisor, y que el GAIN no esté al mínimo |
| `clip` distinto de cero | Satura en −3 dBu (≈1,55 Vpp) con GAIN al mínimo | Bajar el GAIN, o agrandar el divisor |
| `overflow` distinto de cero | Se perdieron muestras; el eje temporal quedó corrido | Cerrar lo que esté usando el disco y repetir |
| No se abre el gráfico | Falta `pyqtgraph` o `PyQt6` | `pip install pyqtgraph PyQt6` |

### Dos trampas que ya nos costaron tiempo

**1. WASAPI en modo exclusivo puede mentir la frecuencia de muestreo.** Contra la
placa interna de una de las máquinas, `stream.samplerate` declaraba 48000 y el
stream entregaba **63,2 kS/s**; el mismo dispositivo en modo compartido daba
47,7 kS/s. No se ve en ningún lado —el WAV suena raro y nada más— pero corre el
eje de frecuencias un 32 %, y como la distancia sale del beat, arruina todo en
silencio. Por eso el grabador **mide** la tasa antes de grabar y reintenta en
compartido si se va más del 2 %.

**2. La API más "directa" no siempre es la que sirve.** Ver §4: WASAPI aparecía
con 1 canal y WDM-KS con 2. La preferencia de API es una heurística, no una
garantía; lo que manda es si el dispositivo ofrece los canales que hacen falta.

---

## 9. Números medidos, para comparar

Máquina de referencia, UMC22 con el driver genérico de clase USB, entradas al
aire:

| | |
|---|---|
| API elegida por `auto` | Windows WDM-KS, 2 canales |
| Tasa real a 48 kHz | 47976 S/s (**0,05 %** de error) |
| Captura de 5 s | 238592 muestras, 0 clipeo, 0 overflow |
| Piso de ruido | −78 dBFS |
| CSV y WAV | consistentes muestra a muestra |

Si en la otra máquina los números se parecen, la cadena está bien. Si el error de
tasa pasa el 2 %, hay algo mal configurado y el programa lo va a decir.

---

## 10. Volver al PCM1808

Nada de este camino toca `adquisicion/`, `firmware/` ni `analisis/`. Se vuelve
corriendo `medir.py` (o `medir.bat`) en vez de `medir_audio.py`.
