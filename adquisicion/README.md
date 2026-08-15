# Adquisición

Software de captura y visualización en tiempo real contra el firmware
[`PCM1808_ESP32C3`](../firmware/PCM1808_ESP32C3/).

> **Estado: en construcción.** El firmware con protocolo binario ya está listo;
> el cliente Python todavía no.

---

## Entorno — tiene que ser Windows

**WSL 2 no ve los puertos COM.** El ESP32 aparece como un dispositivo serie de
Windows, y el kernel de WSL corre en una VM sin acceso al hardware serie del
host. Se puede resolver con `usbipd-win`, pero entonces el puerto **desaparece de
Windows** —adiós Arduino IDE y visores— y hay que re-attachar tras cada
desconexión. No vale la pena.

El `venv_gpr` de WSL sigue sirviendo para el **análisis posterior**, que no toca
hardware.

### El venv

```
C:\Users\tinch\venvs\gpr-win
```

Python 3.11.0. Desde PowerShell, sin activarlo:

```powershell
$py = "C:\Users\tinch\venvs\gpr-win\Scripts\python.exe"
```

Instalado: `pyserial 3.5`, `numpy 2.4.6`, `matplotlib 3.11.1`.
Falta para el cliente completo: `pyqtgraph` y `PyQt6`.

### ⚠️ Kaspersky rompe pip — y cómo se resolvió

Kaspersky intercepta el TLS de la máquina y **re-firma los certificados con su
propia CA raíz**, así que `pip` falla con `CERTIFICATE_VERIFY_FAILED`: el bundle
de `certifi` no conoce esa CA.

Se resolvió **sin desactivar la verificación** (que sería la solución peligrosa):

1. Se exportó la CA de Kaspersky
   (`CN=Kaspersky Anti-Virus Personal Root Certificate`,
   huella `1EAC5410D0C34B8F1D9F5B5BFB4DBA35853B1582`).
2. Se concatenó con el bundle de `certifi` en
   `C:\Users\tinch\venvs\gpr-win\ca-bundle.pem`.
3. Se dejó un `pip.ini` dentro del venv apuntando ahí:

```ini
[global]
cert = C:\Users\tinch\venvs\gpr-win\ca-bundle.pem
```

Si algún día `pip` vuelve a fallar así en otra máquina, este es el camino.
**No uses `--trusted-host`**: desactiva la verificación en vez de arreglarla.

### Versiones: divergencia conocida

El [`requirements.txt`](../requirements.txt) de la raíz fija las versiones del
entorno de análisis en WSL (numpy 2.4.4, pandas 3.0.2, scipy 1.17.1,
matplotlib 3.10.9). El venv de Windows tiene otras. **Está bien que difieran**:
son entornos con propósitos distintos y ninguno de los dos scripts cruza.
Cuando el cliente esté escrito, este directorio va a tener su propio
`requirements.txt`.

---

## La placa

| | |
|---|---|
| Puerto | `COM3` (verificá, cambia según el USB) |
| VID / PID | `0x303A` / `0x1001` (Espressif USB Serial/JTAG) |

El VID `0x303A` permite **autodetectar el puerto** sin pedírselo al usuario.

⚠️ **Cerrá el Monitor Serie del Arduino IDE** antes de correr cualquier script.
Un solo programa puede tener el puerto abierto.

---

## Protocolo binario

Modo `bin` del firmware. Trama:

```
[0xA5 0x5A] [idx:uint32] [n:uint16] [flags:uint8] [n × float32] [crc16]
     2           4           2          1            4·n           2
```

| Campo | Significado |
|---|---|
| `magic` | Preámbulo, para resincronizar si se pierden bytes |
| `idx` | Índice **absoluto** de la primera muestra, desde el inicio de la captura |
| `n` | Cantidad de muestras (256 normalmente; menos en el último de una ráfaga) |
| `flags` | bit 0 = primer paquete de una ráfaga |
| datos | `float32` little-endian, en **volts** |
| `crc16` | CCITT-FALSE (poly 0x1021, init 0xFFFF) sobre `idx`..datos |

**`idx` es la clave del diseño.** No es un contador de paquetes: avanza con el
tiempo real, también durante las pausas del modo ráfaga. Con eso el cliente
reconstruye el eje temporal con los huecos incluidos y **distingue una pausa
esperada de una pérdida del DMA** — que es el modo de falla que corrompería una
FFT sin avisar.

### Configuración antes de capturar

Los comandos siguen siendo texto. La secuencia es: configurar, leer `info` para
registrar en la metadata **lo que el firmware realmente tiene**, y recién
entonces mandar `bin`.

```
fs 32000
dec 4
ch l
raf 0 0        ← continuo; o "raf <on> <off>" para ráfagas
info
bin
```

Para volver a texto, mandar `stats` o `off` en cualquier momento: el firmware
sigue leyendo la consola mientras transmite binario.

---

## Compilar el firmware sin abrir el IDE

```powershell
& "C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe" compile --fqbn "esp32:esp32:nologo_esp32c3_super_mini:CDCOnBoot=cdc" ".\firmware\PCM1808_ESP32C3"
```

Core `esp32` 3.3.10.

⚠️ **El toolchain de Arduino no compila en rutas UNC** (`\\wsl.localhost\...`):
pasa por `cmd.exe`, que rechaza directorios UNC. Por eso el repo vive en `D:`.
