# Firmware histórico — no usar

Etapas anteriores del proyecto. Se conservan como registro, **no** para cargar
en la placa.

El firmware vigente es [`../PCM1808_ESP32C3/`](../PCM1808_ESP32C3/).

| Carpeta | Qué era | Por qué no se usa |
|---|---|---|
| `sketch_may29a/` | Primera prueba con el **ADC interno** del ESP32-C3 (12 bit, GPIO0) | Reemplazado por el PCM1808, que da 24 bit y ~99 dB de rango dinámico |
| `gpr_sampler/` | Muestreador para **ESP32 clásico** | Usa `GPIO34`, que **no existe en el ESP32-C3** (solo tiene GPIO0–21). Si lo cargás en la placa actual, arranca y escupe `adc_io_to_channel: invalid gpio number` una vez por milisegundo |

Ese último error ya nos costó una sesión de depuración: se había cargado
`gpr_sampler` por error creyendo que era el firmware del PCM1808. De ahí que
estos dos estén apartados en su propia carpeta.
