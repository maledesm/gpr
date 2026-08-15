# GPR FMCW — Tesis

Radar de penetración terrestre de onda continua modulada en frecuencia.
Firmware de adquisición sobre ESP32-C3 + PCM1808, y procesamiento en Python.

**Facultad de Ingeniería, UBA.**

---

## Empezar por acá

| Quiero… | Voy a |
|---|---|
| **Medir ahora** | `adquisicion/medir.py` → graba a CSV y abre el gráfico en vivo |
| **Cargar el firmware** | `firmware/PCM1808_ESP32C3/` ← **el único vigente** |
| **Cablear la placa** | [`docs/conexionado.md`](docs/conexionado.md) |
| **Caracterizar el sampler** | [`docs/validacion_banco.md`](docs/validacion_banco.md) |
| **Entender el circuito** | [`docs/PCM1808_hardware.md`](docs/PCM1808_hardware.md) |
| **Usar los comandos del firmware** | [`docs/PCM1808_uso.md`](docs/PCM1808_uso.md) |

```powershell
& "C:\Users\tinch\venvs\gpr-win\Scripts\python.exe" .\adquisicion\medir.py
```

---

## Parámetros del radar

| | |
|---|---|
| Banda | 1,00 – 1,75 GHz |
| Ancho de banda | 750 MHz |
| Resolución en distancia | 20 cm en aire · ~6,7 cm en suelo (εr ≈ 9) |
| Digitalización | PCM1808, 24 bit, 8–96 kHz |
| Controlador | ESP32-C3 SuperMini |

```
f_beat = 2·R·BW / (c·T_sweep) = (5 / T_sweep) Hz por metro
```

---

## Estructura

```
firmware/
  PCM1808_ESP32C3/      ★ EL FIRMWARE ACTUAL. Es el que va en la placa.
                          Salida en texto (Serial Plotter, Telemetry Viewer)
                          y en binario con CRC para el software de Python.
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
      (0,2–2 m) caen entre 0,7 y 7 Hz, o sea **adentro del pasa-altos del
      PCM1808**, que no se puede desactivar. Bajando a 5–10 ms el beat pasa a
      100 Hz – 5 kHz y el problema desaparece. Números en
      [`docs/PCM1808_hardware.md`](docs/PCM1808_hardware.md) §0.
- [ ] **Sincronismo con el sweep.** Sin él no se puede promediar
      coherentemente. Tres arquitecturas evaluadas en §6 del mismo documento.
- [ ] Caracterizar el piso de ruido con batería. Una captura preliminar dio
      ~62 dB de SNR (≈10 bits efectivos) con un pico de red en 50 Hz, bastante
      por debajo de los 99 dB del chip.
- [ ] Atenuador de entrada, dimensionado para 3 Vpp (el peor caso).
- [ ] Segundo canal para I/Q.
