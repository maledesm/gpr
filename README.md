# GPR FMCW — Tesis

Radar de penetración terrestre de onda continua modulada en frecuencia.
Firmware de adquisición sobre ESP32-C3 + PCM1808, y procesamiento en Python.

**Facultad de Ingeniería, UBA.**

---

## Empezar por acá

| Quiero… | Voy a |
|---|---|
| **Medir ahora** | doble click en **`medir.bat`** → graba a CSV y abre el gráfico en vivo |
| **Ver una captura vieja** | doble click en **`graficar.bat`** (o arrastrarle un `.csv` encima) |
| **Ver si el software está sano** | doble click en **`pruebas.bat`** — corre sin hardware |
| **Cargar el firmware** | `firmware/PCM1808_ESP32C3/` ← **el único vigente** |
| **Cablear la placa** | [`docs/conexionado.md`](docs/conexionado.md) |
| **Caracterizar el sampler** | [`docs/validacion_banco.md`](docs/validacion_banco.md) |
| **Entender el circuito** | [`docs/PCM1808_hardware.md`](docs/PCM1808_hardware.md) |
| **Usar los comandos del firmware** | [`docs/PCM1808_uso.md`](docs/PCM1808_uso.md) |

Los `.bat` no llevan rutas fijas: se ubican solos con `%~dp0`, así que el repo
se puede mover, renombrar o clonar en otra máquina y siguen andando.

Si preferís la consola, es lo mismo:

```powershell
& "$env:USERPROFILE\venvs\gpr-win\Scripts\python.exe" .\adquisicion\medir.py
```

> **Antes de medir**: el ESP32 enchufado y el **Monitor Serie del Arduino IDE
> cerrado**. Un solo programa puede tener el puerto abierto.

---

## Parámetros del radar

| | |
|---|---|
| Banda de diseño | **1,0 – 2,0 GHz** |
| Ancho de banda | 1000 MHz |
| Resolución en distancia | 15 cm en aire · 5 cm en suelo (εr ≈ 9) |
| Digitalización | PCM1808, 24 bit, 8–96 kHz |
| Controlador | ESP32-C3 SuperMini |

```
f_beat = 2·R·BW / (c·T_sweep) = (6,67 / T_sweep) Hz por metro
```

**Lo que entrega el VCO hoy**, con la tabla de predistorsión actual (rango del
DAC de 0 a 3,00 V): **943 – 1982 MHz**, o sea BW 1039 MHz y 14,4 cm de
resolución. Cubre prácticamente la banda de diseño y con algo más de ancho.

Para llegar a **2,000 GHz exactos harían falta 3,091 V**, por encima del tope de
3,00 V que tiene hoy la tabla. Es alcanzable —el DAC llega hasta VDD = 3,3 V—
pero implica regenerar `tabla_vco.h` con otro `V_MAX_USO`. Los 3,00 V son un
margen elegido, no un límite del hardware. Medición y análisis en
[`VCO/analisis_vco.py`](VCO/analisis_vco.py).

---

## Estructura

```
firmware/
  PCM1808_ESP32C3/      ★ EL FIRMWARE ACTUAL. Es el que va en la placa.
                          Salida en texto (Serial Plotter, Telemetry Viewer)
                          y en binario con CRC para el software de Python.
  prueba_mcp4725/         Rampa de sintonía del VCO por I²C. Sketch AISLADO:
                          no toca el I²S ni el PCM1808, para probar el DAC sin
                          arriesgar la cadena de adquisición.
    tabla_vco.h           GENERADO por VCO/analisis_vco.py — no editar a mano.
  generador_patron/       Arduino Uno: cuadrada de 100 Hz como señal de
                          referencia, para validar sin el radar.
  historico/              Etapas viejas. NO cargar: ver su README.

adquisicion/            Software de captura y visualización (corre en WINDOWS)
  medir.py                Lanzador: arranca los dos de abajo.
  grabarserial.py         Graba el flujo binario a CSV, con metadata completa.
  graficarserial.py       Espectro + osciloscopio + B-scan en tiempo real.
  protocolo.py            Decodificador de tramas.   Autoprueba: --test
  dsp.py                  Ventanas, FFT, filtros, distancia.  Autoprueba: --test

docs/
  conexionado.md          Cableado, alimentación, divisores. Empezar por acá.
  validacion_banco.md     Caracterización con generador de funciones.
  PCM1808_hardware.md     Estudio de circuito: relojes, pasa-altos, ruido.
  PCM1808_uso.md          Comandos del firmware y resolución de problemas.

analisis/               Procesamiento offline (corre en WSL o en Windows)
  v1/  Espectros y señales crudas por medición.
  v2/  Segmentación por sweeps + espectro promediado vs. distancia.

VCO/                    Caracterización y linealización del barrido
  Caracteristica VCO.csv  34 puntos medidos cada 100 mV. Decimales con COMA.
  analisis_vco.py         Genera firmware/prueba_mcp4725/tabla_vco.h + curva_vco.png
                          ⚠ tabla_vco.h está DUPLICADA (prueba_mcp4725 y
                          gpr_barrido) y el script escribe solo la primera. Si la
                          regenerás, copiala a mano a la otra. Pendiente:
                          que el script escriba las dos.
  grafico_vco.py          Figura F vs V con la sensibilidad dF/dV.
  grafico_capturas_dac.py Figura de las 4 capturas de osciloscopio de la rampa.
  Osciloscopio DAC/       Capturas SDS00001..4 (.CSV y .BMP).

Filtro Pasabajos/       Caracterización de un filtro activo. Trabajo aparte del
                        radar, se dejó acá para no perderlo.

simulacion/
  beat_simulado.py        Genera un WAV con la señal de beat de varios blancos,
                          para reproducir por la placa de sonido y validar todo
                          el procesamiento sin tener el radar.
  lpda_meep.py            Antena log-periódica en MEEP.

datos/                  Capturas. Las del ESP32 se llaman AAAA-MM-DD_HHMMSS.csv;
                        las SDS*.CSV son del osciloscopio Siglent.
```

> **Nota**: los CSV de `datos/` están en `.gitignore` porque se generan en cada
> medición. Para conservar una: `git add -f datos/2026-08-15_143000.csv`

---

## Los dos entornos de Python

Son distintos a propósito y no comparten scripts:

| | Dónde | Para qué |
|---|---|---|
| `C:\Users\tinch\venvs\gpr-win` | **Windows** | Adquisición. Obligatorio: el ESP32 es un puerto COM y **WSL 2 no lo ve** |
| `~/MEDI/venv_gpr` | WSL | Análisis offline. No toca hardware |

Detalles del entorno de Windows —incluido el workaround del certificado de
Kaspersky que rompe `pip`— en [`adquisicion/README.md`](adquisicion/README.md).

---

## Estado

Funcionando y verificado sobre hardware:

- [x] Digitalización con PCM1808, validada contra generador de funciones
- [x] Frecuencia de muestreo variable en caliente (8–96 kHz)
- [x] Enlace binario con CRC: 8001,6 S/s medidos contra 8000 nominales, cero pérdidas
- [x] Grabación a CSV con metadata y verificación de continuidad
- [x] Visualización en vivo: espectro, osciloscopio y B-scan
- [x] Procesamiento FMCW de las capturas de osciloscopio

Pendiente, en orden de importancia:

- [ ] **Acelerar el sweep FMCW.** Es el bloqueante principal. Con el
      `T_sweep ≈ 1,46 s` actual, las frecuencias de beat de la zona útil
      (0,2–2 m) caen entre 0,9 y 9 Hz, o sea **adentro del pasa-altos del
      PCM1808**, que no se puede desactivar. Bajando a 5–10 ms el beat pasa a
      130 Hz – 2,7 kHz y el problema desaparece. Números en
      [`docs/PCM1808_hardware.md`](docs/PCM1808_hardware.md) §0.
- [ ] **Sincronismo con el sweep.** Sin él no se puede promediar
      coherentemente. Tres arquitecturas evaluadas en §6 del mismo documento.
- [ ] Caracterizar el piso de ruido con batería. Una captura preliminar dio
      ~62 dB de SNR (≈10 bits efectivos) con un pico de red en 50 Hz, bastante
      por debajo de los 99 dB del chip.
- [ ] Atenuador de entrada, dimensionado para 3 Vpp (el peor caso).
- [ ] Segundo canal para I/Q.
