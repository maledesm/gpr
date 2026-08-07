# GPR FMCW — Tesis

Radar de penetración terrestre (GPR) de onda continua modulada en frecuencia.
Firmware de adquisición sobre ESP32-C3 + PCM1808, y procesamiento en Python.

**Facultad de Ingeniería, UBA.**

---

## Parámetros del radar

| | |
|---|---|
| Banda | 1.00 – 1.75 GHz |
| Ancho de banda | 750 MHz |
| Resolución en distancia | 20 cm en aire · ~6.7 cm en suelo (εr ≈ 9) |
| Digitalización | PCM1808, 24 bit, 8–96 kHz, estéreo |
| Controlador | ESP32-C3 SuperMini |

La frecuencia de beat en función de la distancia:

```
f_beat = 2·R·BW / (c·T_sweep) = (5 / T_sweep) Hz por metro
```

---

## Estructura

```
firmware/
  PCM1808_ESP32C3/   Digitalizador I2S. fs variable 8-96 kHz, diezmado
                     configurable, modo osciloscopio para Serial Plotter,
                     medición automática (Vpp, Vrms, dBFS, frecuencia) y
                     diagnóstico de conexión del PCM1808.
  gpr_sampler/       Versión previa del muestreador.
  sketch_may29a/     Prueba inicial con el ADC interno del ESP32-C3.

docs/
  PCM1808_hardware.md   Estudio de hardware: circuito, alimentación,
                        front-end analógico, arquitectura de reloj,
                        presupuesto de datos, riesgos conocidos.
  PCM1808_uso.md        Manual de uso del firmware: cableado, configuración
                        del IDE, comandos, resolución de problemas.

analisis/
  v1/  Espectros y señales crudas por medición.
  v2/  Segmentación por sweeps + espectro promediado vs. distancia.

simulacion/
  lpda_meep.py   Antena log-periódica en MEEP, campo lejano 1–1.75 GHz.

datos/
  SDS0000*.CSV   Capturas del osciloscopio (Siglent SDS1072CML+).
                 CH1 = IF del mixer · CH2 = rampa de sintonía del VCO.
```

---

## Puesta en marcha

### Firmware

Arduino IDE con el core **ESP32 3.x**. Placa **"Nologo ESP32C3 Super Mini"**
(o "ESP32C3 Dev Module" con *USB CDC On Boot: Enabled*).

El cableado y los comandos están en [`docs/PCM1808_uso.md`](docs/PCM1808_uso.md).
Vale la pena leer las tres advertencias del principio antes de conectar nada —
sobre todo la de que el pin `SCK` del módulo es el master clock y **no** el bit
clock.

### Análisis

```
python -m venv venv_gpr
pip install -r requirements.txt
cd analisis/v2 && python analisis_gpr.py
```

Los scripts leen los CSV de `datos/` con rutas relativas, así que hay que
correrlos parados en su propia carpeta.

---

## Estado y pendientes

Funcionando:

- [x] Digitalización con PCM1808 verificada contra generador de funciones
- [x] Frecuencia de muestreo variable en caliente (8–96 kHz)
- [x] Procesamiento FMCW de las capturas de osciloscopio

Pendiente:

- [ ] **Acelerar el sweep FMCW.** Es lo más importante. Con el `T_sweep ≈ 1.46 s`
      actual, las frecuencias de beat de la zona útil (0.2–2 m) caen entre
      0.7 y 7 Hz, o sea adentro del pasa-altos del PCM1808, que no se puede
      desactivar. Bajando a 5–10 ms el beat pasa a 100 Hz – 5 kHz y el problema
      desaparece. El análisis con los números está en
      [`docs/PCM1808_hardware.md`](docs/PCM1808_hardware.md), sección 0.
- [ ] Sincronismo con el sweep (tres arquitecturas evaluadas, sección 6 del mismo
      documento)
- [ ] Segundo canal para I/Q
- [ ] Captura desde el ESP32 hacia Python, reemplazando al osciloscopio
