/*
 * ============================================================================
 *  PCM1808 + ESP32-C3 SuperMini  --  version con salida BINARIA
 * ============================================================================
 *
 *  Fork de PCM1808_ESP32C3, que queda intacto como version validada y red de
 *  seguridad. Esta agrega dos cosas para el software de captura en Python:
 *
 *    - Modo 'bin': tramas binarias con indice absoluto y CRC. 2.5x mas
 *      eficiente que el texto, y permite detectar muestras perdidas.
 *    - Comando 'raf': captura por rafagas (capturar N, pausar M), con la
 *      captura continua como caso particular (M = 0).
 *
 *  Todos los modos de texto siguen funcionando igual. Cuando algo no anda,
 *  poder abrir un monitor serie y ver numeros legibles vale oro.
 *
 *  Objetivo original: verificar que el PCM1808 mide bien. Se inyecta una
 *  senoidal con un generador de funciones y se comprueba amplitud,
 *  frecuencia, offset y piso de ruido. La salida de texto es compatible
 *  con el Serial Plotter del Arduino IDE.
 *
 *  Arquitectura:
 *    - El ESP32-C3 es MAESTRO de I2S: genera SCKI (MCLK), BCK y LRCK.
 *    - El PCM1808 va en modo ESCLAVO (MD1=MD0=GND) y formato I2S (FMT=GND).
 *    - Eso es lo unico que permite que fs sea una VARIABLE (8 kHz .. 96 kHz).
 *      En modo maestro el PCM1808 divide un cristal fijo y fs queda clavada.
 *
 *  Cadena de datos:
 *      PCM1808 --I2S 24bit--> slots de 32 bits --> >>8 --> int24 con signo
 *          --> diezmado por promedio (factor D) --> volts --> Serial
 *
 *      fs      = reloj real del ADC        (8000 .. 96000 Hz)
 *      D       = factor de diezmado        (1 .. 4096)
 *      fs_eff  = fs / D                    = muestras/s que salen por USB
 *
 *  El diezmado por promedio no es solo para bajar el caudal: promediar D
 *  muestras da +10*log10(D) dB de SNR. Con D=48 son +17 dB gratis.
 *
 *  ---------------------------------------------------------------------------
 *  CABLEADO  (ver README.md para el detalle y las advertencias)
 *  ---------------------------------------------------------------------------
 *      ESP32-C3          Modulo PCM1808
 *      --------          --------------
 *      GPIO4    ------>  SCK   (SCKI / master clock = 256*fs)   <-- NO es el bit clock
 *      GPIO5    ------>  BCK   (bit clock = 64*fs)
 *      GPIO6    ------>  LRC   (LRCK / word select = fs)
 *      GPIO7    <------  OUT   (DOUT, datos)
 *      5V       ------>  5V    (VCC analogico, con filtro RC)
 *      3V3      ------>  3.3   (VDD digital)
 *      GND      ------>  GND   (los dos pines)
 *      GND      ------>  FMY   (FMT = LOW  -> formato I2S)
 *      GND      ------>  MDI   (MD1 = LOW) -+
 *      GND      ------>  MDO   (MD0 = LOW) -+-> modo esclavo
 *
 *  ---------------------------------------------------------------------------
 *  REQUISITOS DE COMPILACION
 *  ---------------------------------------------------------------------------
 *      - Arduino-ESP32 core 3.x o superior (usa la API i2s_std de ESP-IDF 5).
 *      - Placa: "ESP32C3 Dev Module"
 *      - "USB CDC On Boot: Enabled"   <-- IMPRESCINDIBLE para ver la consola
 *                                         por el mismo USB que programa.
 *
 *  ---------------------------------------------------------------------------
 *  COMANDOS (escribir en el Monitor Serie y dar Enter)
 *  ---------------------------------------------------------------------------
 *      fs <hz>      cambia la frecuencia de muestreo del ADC (8000..96000)
 *      dec <n>      cambia el factor de diezmado (1..4096)
 *      eff <hz>     elige D automaticamente para acercarse a esa fs efectiva
 *      ch l|r|both  canal a mostrar
 *      plot         modo grafico (Serial Plotter)
 *      stats        modo medicion (Vpp, Vrms, DC, dBFS, frecuencia)
 *      raw          volcado CSV con timestamp
 *      off          detiene la salida
 *      diag         diagnostico de conexion del PCM1808
 *      info         estado actual
 *      help         esta ayuda
 * ============================================================================
 */

#include <Arduino.h>
#include <Preferences.h>
#include "driver/i2s_std.h"

#if ESP_IDF_VERSION_MAJOR < 5
#error "Este sketch requiere Arduino-ESP32 core 3.x (ESP-IDF 5.x). En el core 2.x la API de I2S es otra."
#endif

// ===========================================================================
//  Consola dual: escribe y lee por los DOS puertos serie posibles
// ===========================================================================
//
//  En el core 3.x, `Serial` es un MACRO que apunta a hardware distinto segun
//  la opcion "USB CDC On Boot" del IDE (ver HardwareSerial.h:439):
//
//     Enabled  ->  Serial = HWCDCSerial  = USB nativo (el mismo cable que
//                                          usas para programar)
//     Disabled ->  Serial = Serial0      = UART0, pines fisicos GPIO20/21
//
//  El problema: la placa "ESP32C3 Dev Module" viene con cdc_on_boot = 0 de
//  fabrica (boards.txt:1445). O sea que por defecto el sketch imprime por unos
//  pines a los que no tenes nada conectado, y en el Monitor Serie no aparece
//  NADA -- aunque el programa este corriendo perfecto. La subida funciona igual
//  porque el flasheo lo hace el ROM por el USB-Serial-JTAG, que es otro camino.
//
//  En vez de depender de que el menu este bien puesto, la consola escribe por
//  los dos lados a la vez y acepta comandos desde cualquiera de los dos.
//
#if ARDUINO_USB_MODE && !ARDUINO_USB_CDC_ON_BOOT
// El core solo instancia HWCDCSerial cuando CDC_ON_BOOT esta activo
// (HWCDC.h:109), asi que en este caso nos creamos el nuestro.
static HWCDC UsbCdc;
#define CONSOLA_DUAL 1
#else
#define CONSOLA_DUAL 0
#endif

class Consola : public Print {
public:
  void begin(unsigned long baud) {
    Serial.begin(baud);
#if CONSOLA_DUAL
    UsbCdc.begin();
    // Sin esto, cada write se queda esperando a un host que puede no existir.
    UsbCdc.setTxTimeoutMs(0);
#endif
  }

  size_t write(uint8_t c) override {
    size_t n = Serial.write(c);
#if CONSOLA_DUAL
    n = max(n, UsbCdc.write(c));
#endif
    return n;
  }

  size_t write(const uint8_t *b, size_t len) override {
    size_t n = Serial.write(b, len);
#if CONSOLA_DUAL
    n = max(n, UsbCdc.write(b, len));
#endif
    return n;
  }

  int available() {
    int n = Serial.available();
#if CONSOLA_DUAL
    n += UsbCdc.available();
#endif
    return n;
  }

  int read() {
    if (Serial.available()) return Serial.read();
#if CONSOLA_DUAL
    if (UsbCdc.available()) return UsbCdc.read();
#endif
    return -1;
  }

  // true cuando hay una PC del otro lado del USB
  bool usbConectado() {
#if CONSOLA_DUAL
    return HWCDC::isConnected();
#elif ARDUINO_USB_MODE
    return HWCDC::isConnected();
#else
    return true;
#endif
  }

  operator bool() { return true; }
};

static Consola Con;

// De aca en adelante, `Serial` en el resto del sketch es la consola dual.
#undef Serial
#define Serial Con

// ---------------------------------------------------------------------------
// Pines
// ---------------------------------------------------------------------------
// Evitamos GPIO2, GPIO8 y GPIO9: son strapping pins del C3. En particular DOUT
// NO puede ir a ninguno de esos: el PCM1808 lo mantiene en LOW hasta salir de
// reset, y un strapping en LOW durante el arranque impide que el ESP32 bootee.
#define PIN_MCLK   4   // -> SCK  del modulo (SCKI)
#define PIN_BCLK   5   // -> BCK
#define PIN_LRCK   6   // -> LRC
#define PIN_DIN    7   // <- OUT  (DOUT)
#define PIN_LED    8   // LED azul integrado, ACTIVO EN BAJO

// ---------------------------------------------------------------------------
// Escala analogica
// ---------------------------------------------------------------------------
// Datasheet SLES177B: fondo de escala = 0.6 * VCC pico-a-pico, centrado en
// VREF = 0.5 * VCC. Con VCC = 5 V son 3.0 Vpp, es decir +-1.5 V de pico.
// Si alimentas el modulo con otra tension, cambia PCM_VCC y las medidas siguen
// siendo correctas.
#define PCM_VCC          5.0f
static const float FS_PEAK_V = 0.3f * PCM_VCC;          // 1.5 V con VCC=5V
static const float LSB_V     = FS_PEAK_V / 8388608.0f;  // 179 nV con VCC=5V

// ---------------------------------------------------------------------------
// Parametros por defecto
// ---------------------------------------------------------------------------
#define DEF_FS        48000   // exacta desde el PLL de 160 MHz del C3
// D=8 -> fs_eff = 6000 Hz: Nyquist en 3 kHz, o sea que 'stats' mide bien
// cualquier tono de prueba tipico sin aliasing, y ya da +9 dB de SNR.
// Para graficar conviene fijarlo con el comando 'sig <frecuencia>'.
#define DEF_DEC           8
#define FS_MIN         8000   // minimo absoluto del PCM1808
#define FS_MAX        96000   // maximo absoluto del PCM1808
#define DEC_MAX        4096

// Bloque que se lee del DMA por vuelta (en frames estereo)
#define BLOCK_FRAMES    256
// Ventana de analisis para el modo stats (en muestras ya diezmadas)
#define ANA_N          2048
// Descarte al arrancar: el PCM1808 hace fade-in despues del reset
#define WARMUP_MS       150

// ---------------------------------------------------------------------------
// Estado global
// ---------------------------------------------------------------------------
enum Mode { MODE_OFF, MODE_PLOT, MODE_STREAM, MODE_STATS, MODE_RAW, MODE_BIN };
enum Chan { CH_L = 0, CH_R = 1, CH_BOTH = 2 };
enum Fmt  { FMT_LABEL, FMT_PLAIN };

// Resultado de una ventana de medicion. Va aca arriba, antes de cualquier
// definicion de funcion, porque el preprocesador del .ino inserta los
// prototipos automaticos justo antes de la primera funcion del archivo: si la
// struct estuviera mas abajo, los prototipos que la mencionan no compilarian.
struct Medicion {
  float dc;        // V
  float vpp;       // V
  float vrms;      // V, sin DC
  float dbfs;      // dBFS del pico
  float freq;      // Hz, 0 si no se pudo estimar
  uint32_t ciclos; // ciclos usados en la estimacion
};

static uint32_t g_fs   = DEF_FS;
static uint32_t g_dec  = DEF_DEC;
static Mode     g_mode = MODE_STATS;
static Chan     g_ch   = CH_L;
static Fmt      g_fmt  = FMT_LABEL;
static bool     g_mV   = true;    // milivolts: el autoescalado del plotter se
                                  // porta mucho mejor que con volts (1e-4)

// --- Modo osciloscopio (MODE_PLOT) ---------------------------------------
// El Serial Plotter del IDE 2.x no aguanta mas de unos cientos de puntos por
// segundo, pero para ver una senoidal de 100 Hz o 1 kHz hacen falta miles.
// La salida es: capturar un bloque CONTIGUO de muestras a la fs real, y
// despues reproducirlo despacio. La forma de onda queda intacta -- el plotter
// no sabe que le estan pasando una grabacion. Es exactamente lo que hace un
// osciloscopio: barrido rapido, tiempo muerto, barrido rapido.
static uint32_t g_plotN    = 400;   // puntos por barrido
static uint32_t g_plotRate = 200;   // puntos/s que se le entregan al plotter
static bool     plotCapturando = true;
static uint32_t plotIdx     = 0;
static uint32_t plotLast_us = 0;

// ===========================================================================
//  Modo binario (MODE_BIN) y captura por rafagas
// ===========================================================================
//
//  Trama:
//     [0xA5 0x5A] [idx:uint32] [n:uint16] [flags:uint8] [n x float32] [crc16]
//         2           4           2          1            4*n           2
//
//  idx   = indice ABSOLUTO de la primera muestra del paquete, contado desde
//          que arranco la captura. No es un contador de paquetes: avanza con
//          el tiempo real, tambien durante las pausas de rafaga. Gracias a eso
//          los huecos son explicitos y medibles, y la PC puede distinguir una
//          pausa esperada de una perdida del DMA.
//  flags = bit0: primer paquete de una rafaga.
//  crc16 = CCITT-FALSE (poly 0x1021, init 0xFFFF) sobre idx..datos.
//
//  Rafagas: se capturan g_rafOn muestras, se pausan g_rafOff, y se repite.
//  Con g_rafOff = 0 la captura es continua (es el mismo camino de codigo, la
//  continuidad es el caso degenerado). Durante la pausa se sigue vaciando el
//  DMA para que no desborde, y el indice sigue avanzando: representa tiempo
//  real, no cantidad de muestras enviadas.
//
#define BIN_MAGIC0     0xA5
#define BIN_MAGIC1     0x5A
#define BIN_MUESTRAS   256          // muestras por paquete
#define BIN_CAB        9            // magic(2) + idx(4) + n(2) + flags(1)
#define BIN_MAX        (BIN_CAB + BIN_MUESTRAS * 4 + 2)

static uint8_t  binBuf[BIN_MAX];
static uint16_t binN       = 0;     // muestras acumuladas en el paquete
static uint64_t binIdx     = 0;     // indice absoluto de muestra
static uint32_t binIdxPkt  = 0;     // indice de la primera muestra del paquete
static uint8_t  binFlags   = 0;

static uint32_t g_rafOn  = 0;       // muestras a capturar (0 = continuo)
static uint32_t g_rafOff = 0;       // muestras a pausar
static bool     rafCapturando = true;
static uint32_t rafRestan     = 0;

// Configuracion persistente en NVS.
//
// Hace falta porque la ventana del Serial Plotter del IDE 2.x NO tiene campo
// para escribir comandos, y al abrirla se resetea la placa. Sin persistencia
// quedas trabado: para poner 'plot' necesitas el Monitor Serie, pero al pasar
// al plotter la placa arranca de nuevo en el modo por defecto. Guardando la
// configuracion, la ajustas una vez desde el monitor y queda.
static Preferences prefs;

static i2s_chan_handle_t rx_chan = nullptr;

static int32_t  rawBuf[BLOCK_FRAMES * 2];   // L,R intercalados, 2 kB

// Acumuladores del diezmador
static int64_t  accL = 0, accR = 0;
static uint32_t accN = 0;

// Ventana de analisis (modo stats) y contadores
static float    anaL[ANA_N];
static float    anaR[ANA_N];
static uint32_t anaN = 0;

// Contadores de salud
static uint64_t framesTotal = 0;   // frames leidos desde el ultimo reset de cuentas
static uint32_t clipCount   = 0;
static uint32_t clipLast_ms = 0;   // ultimo instante con saturacion, para el LED
static uint32_t t0_ms       = 0;
static uint64_t sampleIndex = 0;   // indice de muestra diezmada, para el modo raw

// ===========================================================================
//  I2S
// ===========================================================================

// Devuelve la fs que el hardware realmente puede generar.
// El ESP32-C3 no tiene APLL: el I2S cuelga del PLL de 160 MHz y llega a la
// frecuencia pedida con un divisor fraccionario, asi que no toda fs es exacta.
// 16000 / 32000 / 48000 salen exactas; 44100 y 96000 tienen ~0.005% y ~0.04%
// de error. Para reportarlo hay que preguntarselo al driver, cosa que la API
// publica no expone, asi que aca solo informamos la nominal.
static bool i2sStart(uint32_t fs) {
  if (rx_chan) {
    i2s_channel_disable(rx_chan);
    i2s_del_channel(rx_chan);
    rx_chan = nullptr;
  }

  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  cc.dma_desc_num  = 6;
  cc.dma_frame_num = BLOCK_FRAMES;
  cc.auto_clear    = false;
  if (i2s_new_channel(&cc, nullptr, &rx_chan) != ESP_OK) {
    Serial.println("[ERROR] i2s_new_channel fallo");
    return false;
  }

  i2s_std_config_t sc = {};
  sc.clk_cfg.sample_rate_hz = fs;
  sc.clk_cfg.clk_src        = I2S_CLK_SRC_DEFAULT;
  // SCKI = 256*fs. El PCM1808 en modo esclavo autodetecta 256/384/512 fs.
  sc.clk_cfg.mclk_multiple  = I2S_MCLK_MULTIPLE_256;

  // Slots de 32 bits, no de 24. Dos motivos:
  //   1) El PCM1808 en modo esclavo acepta 64 o 48 BCK/frame, pero NO 32.
  //      Estereo x 32 bits = 64 BCK/frame exactos.
  //   2) El driver I2S del IDF tiene rarezas conocidas con bit_width = 24.
  // La muestra de 24 bits llega alineada al MSB dentro de la palabra de 32,
  // se recupera con un shift aritmetico de 8 bits (ver leerBloque).
  sc.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,
                                                    I2S_SLOT_MODE_STEREO);

  sc.gpio_cfg.mclk = (gpio_num_t)PIN_MCLK;
  sc.gpio_cfg.bclk = (gpio_num_t)PIN_BCLK;
  sc.gpio_cfg.ws   = (gpio_num_t)PIN_LRCK;
  sc.gpio_cfg.dout = I2S_GPIO_UNUSED;          // solo recibimos
  sc.gpio_cfg.din  = (gpio_num_t)PIN_DIN;
  sc.gpio_cfg.invert_flags.mclk_inv = false;
  sc.gpio_cfg.invert_flags.bclk_inv = false;
  sc.gpio_cfg.invert_flags.ws_inv   = false;

  if (i2s_channel_init_std_mode(rx_chan, &sc) != ESP_OK) {
    Serial.println("[ERROR] i2s_channel_init_std_mode fallo");
    return false;
  }
  if (i2s_channel_enable(rx_chan) != ESP_OK) {
    Serial.println("[ERROR] i2s_channel_enable fallo");
    return false;
  }

  // El PCM1808 arranca en mute y hace fade-in. Tiramos lo primero.
  uint32_t t = millis();
  size_t   n;
  while (millis() - t < WARMUP_MS) {
    i2s_channel_read(rx_chan, rawBuf, sizeof(rawBuf), &n, 100);
  }

  accL = accR = 0;
  accN = anaN = 0;
  framesTotal = 0;
  clipCount   = 0;
  sampleIndex = 0;
  t0_ms       = millis();
  return true;
}

// Lee un bloque del DMA y devuelve cuantos frames trajo.
// Deja en rawBuf los valores ya convertidos a int24 con signo.
static uint32_t leerBloque() {
  size_t bytes = 0;
  esp_err_t e  = i2s_channel_read(rx_chan, rawBuf, sizeof(rawBuf), &bytes, 1000);
  if (e != ESP_OK || bytes == 0) return 0;

  uint32_t frames = bytes / (2 * sizeof(int32_t));
  for (uint32_t i = 0; i < frames * 2; i++) {
    // 24 bits alineados al MSB dentro de 32 -> shift aritmetico preserva signo
    rawBuf[i] >>= 8;
  }
  framesTotal += frames;
  return frames;
}

// ===========================================================================
//  Diezmado
// ===========================================================================

// Alimenta el diezmador con un frame. Si completo un grupo de D, deja el
// promedio en *outL / *outR (en volts) y devuelve true.
static inline bool diezmar(int32_t l, int32_t r, float *outL, float *outR) {
  if (l >= 8388600 || l <= -8388600 || r >= 8388600 || r <= -8388600) {
    clipCount++;
    clipLast_ms = millis();
  }
  accL += l;
  accR += r;
  if (++accN < g_dec) return false;
  *outL = (float)((double)accL / (double)accN) * LSB_V;
  *outR = (float)((double)accR / (double)accN) * LSB_V;
  accL = accR = 0;
  accN = 0;
  return true;
}

// ===========================================================================
//  Analisis (modo stats)
// ===========================================================================

// Estimacion de frecuencia por cruces por cero ascendentes con interpolacion
// lineal e histeresis. Para una senoidal limpia da mejor que 0.1% con 2048
// muestras. Mucho mas barato que una FFT y mas preciso para un tono unico.
static float estimarFrecuencia(const float *x, uint32_t n, float mean,
                               float amp, float fs_eff, uint32_t *ciclos) {
  *ciclos = 0;
  if (n < 8 || amp <= 0.0f) return 0.0f;

  const float hys = amp * 0.10f;
  bool   armado   = true;
  double primero = -1.0, ultimo = -1.0;
  uint32_t c = 0;

  for (uint32_t i = 1; i < n; i++) {
    float prev = x[i - 1] - mean;
    float cur  = x[i]     - mean;
    if (cur < -hys) armado = true;
    if (armado && prev < 0.0f && cur >= 0.0f) {
      double frac = (double)(-prev) / (double)(cur - prev);
      double pos  = (double)(i - 1) + frac;
      if (primero < 0.0) {
        primero = pos;
      } else {
        ultimo = pos;
        c++;
      }
      armado = false;
    }
  }
  if (c == 0 || ultimo <= primero) return 0.0f;
  *ciclos = c;
  return (float)((double)c * (double)fs_eff / (ultimo - primero));
}

static Medicion analizar(const float *x, uint32_t n, float fs_eff) {
  Medicion m = {};
  if (n == 0) return m;

  double sum = 0.0;
  float  mn = x[0], mx = x[0];
  for (uint32_t i = 0; i < n; i++) {
    sum += x[i];
    if (x[i] < mn) mn = x[i];
    if (x[i] > mx) mx = x[i];
  }
  m.dc  = (float)(sum / n);
  m.vpp = mx - mn;

  double sq = 0.0;
  for (uint32_t i = 0; i < n; i++) {
    double d = x[i] - m.dc;
    sq += d * d;
  }
  m.vrms = (float)sqrt(sq / n);

  float pico = fmaxf(fabsf(mx - m.dc), fabsf(mn - m.dc));
  m.dbfs = (pico > 0.0f) ? 20.0f * log10f(pico / FS_PEAK_V) : -999.0f;
  m.freq = estimarFrecuencia(x, n, m.dc, m.vpp * 0.5f, fs_eff, &m.ciclos);
  return m;
}

// ===========================================================================
//  Diagnostico de conexion
// ===========================================================================

static void diagnostico() {
  Serial.println();
  Serial.println("=== DIAGNOSTICO PCM1808 ===");
  Serial.printf("fs nominal    : %lu Hz\n", (unsigned long)g_fs);
  Serial.printf("SCKI (GPIO%d) : %.3f MHz\n", PIN_MCLK, g_fs * 256.0 / 1e6);
  Serial.printf("BCK  (GPIO%d) : %.3f MHz\n", PIN_BCLK, g_fs * 64.0 / 1e6);
  Serial.printf("LRCK (GPIO%d) : %lu Hz\n",   PIN_LRCK, (unsigned long)g_fs);

  // Juntamos unos cuantos frames y miramos que pinta tienen los bits
  const uint32_t OBJETIVO = 4096;
  uint32_t vistos = 0;
  int32_t  minL = INT32_MAX, maxL = INT32_MIN;
  int32_t  minR = INT32_MAX, maxR = INT32_MIN;
  uint32_t cerosL = 0, cerosR = 0;
  uint32_t colaNoCero = 0;   // muestras con basura en los 8 bits bajos
  double   sumL = 0, sumR = 0, sqL = 0, sqR = 0;

  // Releemos crudo (sin el shift) para poder mirar los bits bajos
  while (vistos < OBJETIVO) {
    size_t bytes = 0;
    if (i2s_channel_read(rx_chan, rawBuf, sizeof(rawBuf), &bytes, 1000) != ESP_OK) break;
    uint32_t frames = bytes / (2 * sizeof(int32_t));
    for (uint32_t i = 0; i < frames; i++) {
      int32_t r0 = rawBuf[2 * i];
      int32_t r1 = rawBuf[2 * i + 1];
      if ((r0 & 0xFF) || (r1 & 0xFF)) colaNoCero++;
      int32_t l = r0 >> 8;
      int32_t r = r1 >> 8;
      if (l == 0) cerosL++;
      if (r == 0) cerosR++;
      if (l < minL) minL = l;  if (l > maxL) maxL = l;
      if (r < minR) minR = r;  if (r > maxR) maxR = r;
      sumL += l; sumR += r;
      sqL  += (double)l * l;
      sqR  += (double)r * r;
      vistos++;
    }
  }

  if (vistos == 0) {
    Serial.println();
    Serial.println(">> NO LLEGA NINGUN DATO del periferico I2S.");
    Serial.println("   El driver no esta entregando frames. Revisa la");
    Serial.println("   configuracion de pines y que el core sea 3.x.");
    Serial.println("===========================");
    return;
  }

  double mL = sumL / vistos, mR = sumR / vistos;
  double rL = sqrt(sqL / vistos - mL * mL);
  double rR = sqrt(sqR / vistos - mR * mR);

  Serial.printf("\nFrames analizados: %lu\n", (unsigned long)vistos);
  Serial.printf("  L: min=%-9ld max=%-9ld media=%-10.1f rms(ac)=%-10.1f  (%.3f mVrms)\n",
                (long)minL, (long)maxL, mL, rL, rL * LSB_V * 1000.0);
  Serial.printf("  R: min=%-9ld max=%-9ld media=%-10.1f rms(ac)=%-10.1f  (%.3f mVrms)\n",
                (long)minR, (long)maxR, mR, rR, rR * LSB_V * 1000.0);
  Serial.printf("  Muestras exactamente en cero: L=%lu/%lu  R=%lu/%lu\n",
                (unsigned long)cerosL, (unsigned long)vistos,
                (unsigned long)cerosR, (unsigned long)vistos);
  Serial.printf("  Frames con bits 7..0 distintos de cero: %lu\n",
                (unsigned long)colaNoCero);

  Serial.println();
  bool ok = true;

  if (cerosL == vistos && cerosR == vistos) {
    ok = false;
    Serial.println(">> TODO CERO en los dos canales. Causas, por probabilidad:");
    Serial.printf("   1. SCKI no llega. Verifica GPIO%d -> pin 'SCK' del modulo.\n", PIN_MCLK);
    Serial.println("      OJO: 'SCK' en el PCM1808 es el MASTER CLOCK, no el bit");
    Serial.println("      clock. El bit clock es 'BCK'. Si los cruzaste, es esto.");
    Serial.println("      Sin SCKI el chip se queda en reset y saca ceros.");
    Serial.println("   2. El modulo no tiene alimentacion (VCC=5V y VDD=3.3V).");
    Serial.printf("   3. DOUT ('OUT') no llega a GPIO%d.\n", PIN_DIN);
    Serial.println("   4. El modulo trae un oscilador soldado y esta en modo");
    Serial.println("      MAESTRO: entonces el choca con nuestros BCK/LRCK.");
    Serial.println("      Verifica que MD1 y MD0 esten a GND.");
  } else if (rL < 2.0 && rR < 2.0) {
    Serial.println(">> Hay datos, pero sin actividad (ruido < 2 LSB).");
    Serial.println("   El enlace I2S funciona. Falta senal en la entrada,");
    Serial.println("   o la entrada esta al aire / a masa.");
  }

  if (colaNoCero > vistos / 100) {
    ok = false;
    Serial.println(">> Los 8 bits bajos no son cero. La alineacion de la trama");
    Serial.println("   no es la esperada. Revisa que FMT este a GND (formato");
    Serial.println("   I2S) y que MD1/MD0 esten a GND (modo esclavo).");
  }

  if (fabs(mL) > 50000 || fabs(mR) > 50000) {
    Serial.println(">> Continua muy grande. Raro: el PCM1808 tiene un pasa-altos");
    Serial.println("   interno que deberia quitar el DC. Puede ser saturacion.");
  }

  if (ok && (rL >= 2.0 || rR >= 2.0)) {
    Serial.println(">> Enlace I2S OK y hay senal.");
  }
  Serial.println("===========================");
  Serial.println();

  // Reset de acumuladores: el diagnostico consumio frames
  accL = accR = 0;
  accN = anaN = 0;
  framesTotal = 0;
  t0_ms = millis();
}

// ===========================================================================
//  Consola
// ===========================================================================

static const char* nombreModo(Mode m) {
  switch (m) {
    case MODE_PLOT:   return "plot (osciloscopio)";
    case MODE_STREAM: return "stream (tiempo real)";
    case MODE_BIN:    return "bin (binario para Python)";
    case MODE_STATS:  return "stats";
    case MODE_RAW:    return "raw";
    default:          return "off";
  }
}

// --- Configuracion persistente ---------------------------------------------

static void guardarConfig() {
  prefs.begin("pcm1808", false);
  prefs.putUInt ("fs",    g_fs);
  prefs.putUInt ("dec",   g_dec);
  prefs.putUChar("mode",  (uint8_t)g_mode);
  prefs.putUChar("ch",    (uint8_t)g_ch);
  prefs.putUChar("fmt",   (uint8_t)g_fmt);
  prefs.putBool ("mV",    g_mV);
  prefs.putUInt ("plotN", g_plotN);
  prefs.putUInt ("rate",  g_plotRate);
  prefs.putUInt ("rafOn",  g_rafOn);
  prefs.putUInt ("rafOff", g_rafOff);
  prefs.end();
}

static void cargarConfig() {
  prefs.begin("pcm1808", true);
  g_fs       = prefs.getUInt ("fs",    DEF_FS);
  g_dec      = prefs.getUInt ("dec",   DEF_DEC);
  g_mode     = (Mode)prefs.getUChar("mode", (uint8_t)MODE_STATS);
  g_ch       = (Chan)prefs.getUChar("ch",   (uint8_t)CH_L);
  g_fmt      = (Fmt) prefs.getUChar("fmt",  (uint8_t)FMT_LABEL);
  g_mV       = prefs.getBool ("mV",    true);
  g_plotN    = prefs.getUInt ("plotN", 400);
  g_plotRate = prefs.getUInt ("rate",  200);
  g_rafOn    = prefs.getUInt ("rafOn",  0);
  g_rafOff   = prefs.getUInt ("rafOff", 0);
  prefs.end();

  // Sanidad: si la NVS tiene basura de una version anterior, no arrancamos roto
  if (g_fs < FS_MIN || g_fs > FS_MAX)          g_fs   = DEF_FS;
  if (g_dec < 1 || g_dec > DEC_MAX)            g_dec  = DEF_DEC;
  if (g_mode > MODE_BIN)                       g_mode = MODE_STATS;
  // Si la rafaga quedo mal guardada, volvemos a continuo: con rafOn = 0 y
  // rafOff > 0 el contador se desbordaria en el primer decremento.
  if (g_rafOff > 0 && g_rafOn == 0)            g_rafOff = 0;
  if (g_ch > CH_BOTH)                          g_ch   = CH_L;
  if (g_fmt > FMT_PLAIN)                       g_fmt  = FMT_LABEL;
  if (g_plotN < 16 || g_plotN > ANA_N)         g_plotN = 400;
  if (g_plotRate < 10 || g_plotRate > 2000)    g_plotRate = 200;
}

static void borrarConfig() {
  prefs.begin("pcm1808", false);
  prefs.clear();
  prefs.end();
}

static const char* nombreCanal(Chan c) {
  switch (c) {
    case CH_L:    return "L";
    case CH_R:    return "R";
    default:      return "L+R";
  }
}

static void mostrarInfo() {
  float eff = (float)g_fs / (float)g_dec;
  Serial.println();
  Serial.println("---------------- ESTADO ----------------");
  Serial.printf("  fs (reloj ADC)   : %lu Hz\n", (unsigned long)g_fs);
  Serial.printf("  D  (diezmado)    : %lu\n", (unsigned long)g_dec);
  Serial.printf("  fs_eff (salida)  : %.2f Hz\n", eff);
  Serial.printf("  Banda util       : DC..%.1f Hz (Nyquist de fs_eff)\n", eff / 2.0f);
  Serial.printf("  Ganancia por prom: +%.1f dB de SNR\n", 10.0f * log10f((float)g_dec));
  Serial.printf("  Modo             : %s\n", nombreModo(g_mode));
  Serial.printf("  Canal            : %s\n", nombreCanal(g_ch));
  Serial.printf("  Unidad / formato : %s / %s\n",
                g_mV ? "mV" : "V", g_fmt == FMT_LABEL ? "L:valor" : "solo numero");
  if (g_rafOff == 0) {
    Serial.println("  Captura          : continua");
  } else {
    Serial.printf("  Captura          : rafaga %lu on / %lu off  (%.1f %% util)\n",
                  (unsigned long)g_rafOn, (unsigned long)g_rafOff,
                  100.0f * g_rafOn / (g_rafOn + g_rafOff));
  }
  Serial.printf("  Caudal binario   : %.1f kB/s\n", eff * 4.0f / 1000.0f *
                (g_rafOff == 0 ? 1.0f : (float)g_rafOn / (g_rafOn + g_rafOff)));
  Serial.printf("  Fondo de escala  : %.2f Vpp (+-%.3f V), VCC=%.1f V\n",
                2.0f * FS_PEAK_V, FS_PEAK_V, PCM_VCC);
  Serial.printf("  1 LSB            : %.1f nV\n", LSB_V * 1e9f);
  Serial.println();
  Serial.println("  Modo osciloscopio (comando 'plot'):");
  Serial.printf("    Puntos por barrido : %lu  (comando 'n')\n",
                (unsigned long)g_plotN);
  Serial.printf("    Cadencia al plotter: %lu pts/s  (comando 'rate')\n",
                (unsigned long)g_plotRate);
  Serial.printf("    Ventana capturada  : %.2f ms de senal real\n",
                1000.0f * g_plotN / eff);
  Serial.printf("    Se dibuja en       : %.2f s\n",
                (float)g_plotN / g_plotRate);
  Serial.printf("    Senal maxima visible: %.0f Hz (Nyquist de fs_eff)\n",
                eff / 2.0f);
  Serial.println();
  Serial.println("  Recordatorio del pasa-altos del PCM1808:");
  Serial.printf("    HPF digital interno = 1.9e-5 * fs = %.2f Hz\n", 1.9e-5f * g_fs);
  Serial.println("    + el capacitor de acople del modulo contra 60 kohm.");
  Serial.println("    Por debajo de ~5 Hz la medida NO es confiable.");
  Serial.println("----------------------------------------");
  Serial.println();
}

static void mostrarAyuda() {
  Serial.println();
  Serial.println("---------------- COMANDOS ----------------");
  Serial.println(" Muestreo:");
  Serial.println("  fs <hz>      frecuencia de muestreo del ADC (8000..96000)");
  Serial.println("  dec <n>      factor de diezmado (1..4096)");
  Serial.println("  eff <hz>     elige D para acercarse a esa fs efectiva");
  Serial.println("  ch l|r|both  canal a mostrar");
  Serial.println(" Base de tiempo (como el TIME/DIV de un osciloscopio).");
  Serial.println(" No cambian NADA de la senal: solo cuanto tiempo entra en la");
  Serial.println(" pantalla. Cada punto dibujado es una muestra real del ADC.");
  Serial.println("  win <ms>     cuantos ms de senal entran en un barrido");
  Serial.println("  sig <hz>     lo mismo, pero se lo pedis en frecuencia:");
  Serial.println("               encuadra ~8 ciclos de una senal de esa f");
  Serial.println(" Modos:");
  Serial.println("  plot         OSCILOSCOPIO: captura un barrido a fs real y");
  Serial.println("               lo dibuja despacio. Es el que sirve para ver");
  Serial.println("               una senoidal en el Serial Plotter del IDE.");
  Serial.println("  stream       tiempo real, una linea por muestra. Solo si");
  Serial.println("               fs_eff < ~200 Hz o si lees con otro programa.");
  Serial.println("  bin          BINARIO para el software de Python: tramas");
  Serial.println("               con indice absoluto y CRC. 2.5x mas eficiente");
  Serial.println("               que el texto y detecta muestras perdidas.");
  Serial.println("  raf <on> <off>  captura <on> muestras y pausa <off>.");
  Serial.println("               Con off = 0 la captura es continua.");
  Serial.println("  stats        medicion (Vpp, Vrms, DC, dBFS, frecuencia)");
  Serial.println("  raw          volcado CSV con timestamp");
  Serial.println("  off          detiene la salida");
  Serial.println(" Ajustes del osciloscopio:");
  Serial.println("  n <puntos>   puntos por barrido (16..2048)");
  Serial.println("  rate <pts/s> cadencia hacia el plotter (10..2000)");
  Serial.println(" Formato de salida:");
  Serial.println("  unit v|mv    unidad de los valores");
  Serial.println("  fmt label    'L:valor'  (Serial Plotter del IDE 2.x)");
  Serial.println("  fmt plain    solo el numero (IDE 1.8, Serial Studio, scripts)");
  Serial.println(" Otros:");
  Serial.println("  diag         diagnostico de conexion");
  Serial.println("  info         estado actual");
  Serial.println("  reset        vuelve a los valores de fabrica y reinicia");
  Serial.println("  help         esta ayuda");
  Serial.println();
  Serial.println(" La configuracion se guarda sola en la flash: la ajustas una");
  Serial.println(" vez desde aca y sobrevive al reset que provoca abrir el");
  Serial.println(" Serial Plotter (que no tiene donde escribir comandos).");
  Serial.println("------------------------------------------");
  Serial.println();
}

static void reiniciarVentana() {
  accL = accR = 0;
  accN = anaN = 0;
  framesTotal = 0;
  clipCount   = 0;
  sampleIndex = 0;
  t0_ms       = millis();
}

static void procesarComando(String s) {
  s.trim();
  s.toLowerCase();
  if (s.length() == 0) return;

  int esp = s.indexOf(' ');
  String cmd = (esp < 0) ? s : s.substring(0, esp);
  String arg = (esp < 0) ? "" : s.substring(esp + 1);
  arg.trim();

  if (cmd == "fs") {
    long v = arg.toInt();
    if (v < FS_MIN || v > FS_MAX) {
      ack("[ERROR] fs fuera de rango. El PCM1808 admite %d..%d Hz.\n",
          FS_MIN, FS_MAX);
      return;
    }
    g_fs = (uint32_t)v;
    ack("[OK] Reconfigurando I2S a fs = %lu Hz...\n", (unsigned long)g_fs);
    if (i2sStart(g_fs)) {
      ack("[OK] fs = %lu Hz, fs_eff = %.2f Hz\n",
          (unsigned long)g_fs, (float)g_fs / g_dec);
    }
    plotCapturando = true;
    plotIdx = 0;
  }
  else if (cmd == "dec") {
    long v = arg.toInt();
    if (v < 1 || v > DEC_MAX) {
      ack("[ERROR] dec fuera de rango (1..%d).\n", DEC_MAX);
      return;
    }
    g_dec = (uint32_t)v;
    reiniciarVentana();
    ack("[OK] D = %lu, fs_eff = %.2f Hz (+%.1f dB de SNR)\n",
        (unsigned long)g_dec, (float)g_fs / g_dec,
        10.0f * log10f((float)g_dec));
  }
  else if (cmd == "eff") {
    float v = arg.toFloat();
    if (v <= 0.0f) { ack("[ERROR] fs efectiva invalida.\n"); return; }
    long d = lroundf((float)g_fs / v);
    if (d < 1) d = 1;
    if (d > DEC_MAX) d = DEC_MAX;
    g_dec = (uint32_t)d;
    reiniciarVentana();
    ack("[OK] D = %lu -> fs_eff = %.2f Hz (pediste %.2f Hz)\n",
        (unsigned long)g_dec, (float)g_fs / g_dec, v);
  }
  else if (cmd == "ch") {
    if      (arg == "l")    g_ch = CH_L;
    else if (arg == "r")    g_ch = CH_R;
    else if (arg == "both") g_ch = CH_BOTH;
    else { ack("[ERROR] usa: ch l | ch r | ch both\n"); return; }
    ack("[OK] canal = %s\n", nombreCanal(g_ch));
  }
  else if (cmd == "n") {
    long v = arg.toInt();
    if (v < 16 || v > (long)ANA_N) {
      ack("[ERROR] puntos por barrido fuera de rango (16..%d).\n", ANA_N);
      return;
    }
    g_plotN = (uint32_t)v;
    plotCapturando = true;
    plotIdx = 0;
    ack("[OK] %lu puntos por barrido (%.1f ms de senal, se dibuja en %.2f s)\n",
        (unsigned long)g_plotN, 1000.0f * g_plotN * g_dec / g_fs,
        (float)g_plotN / g_plotRate);
  }
  else if (cmd == "rate") {
    long v = arg.toInt();
    if (v < 10 || v > 2000) {
      ack("[ERROR] cadencia fuera de rango (10..2000 pts/s).\n");
      return;
    }
    g_plotRate = (uint32_t)v;
    ack("[OK] %lu pts/s hacia el plotter (barrido de %.2f s)\n",
        (unsigned long)g_plotRate, (float)g_plotN / g_plotRate);
  }
  else if (cmd == "win") {
    // Base de tiempo, como el TIME/DIV de un osciloscopio: cuantos ms de senal
    // real entran en un barrido.  ventana = plotN * D / fs  ->  D = ms*fs/(1000*plotN)
    float ms = arg.toFloat();
    if (ms <= 0.0f) { ack("[ERROR] usa: win <milisegundos>\n"); return; }
    long d = lroundf(ms * (float)g_fs / (1000.0f * (float)g_plotN));
    if (d < 1) d = 1;
    if (d > DEC_MAX) d = DEC_MAX;
    g_dec = (uint32_t)d;
    reiniciarVentana();
    plotCapturando = true;
    plotIdx = 0;
    float eff  = (float)g_fs / g_dec;
    float real = 1000.0f * g_plotN / eff;
    ack("[OK] Ventana = %.2f ms (pediste %.2f), D = %lu, fs_eff = %.0f Hz\n",
        real, ms, (unsigned long)g_dec, eff);
    ack("     Cada punto = promedio de %lu muestras del ADC. Con 'dec 1'\n",
        (unsigned long)g_dec);
    ack("     cada punto es una muestra cruda, sin promediar.\n");
  }
  else if (cmd == "sig") {
    // Ajusta el diezmado para que en un barrido entren ~8 ciclos de una senal
    // de la frecuencia indicada. Es la forma comoda de encuadrar la senoidal
    // sin pensar:  ventana = plotN*D/fs  y queremos  ventana = 8/f.
    float f = arg.toFloat();
    if (f <= 0.0f) { ack("[ERROR] usa: sig <frecuencia_en_Hz>\n"); return; }
    long d = lroundf(8.0f * (float)g_fs / (f * (float)g_plotN));
    if (d < 1) d = 1;
    if (d > DEC_MAX) d = DEC_MAX;
    g_dec = (uint32_t)d;
    reiniciarVentana();
    plotCapturando = true;
    plotIdx = 0;
    float eff = (float)g_fs / g_dec;
    ack("[OK] Para %.1f Hz: D = %lu, fs_eff = %.0f Hz\n",
        f, (unsigned long)g_dec, eff);
    ack("     %.0f puntos por ciclo, %.1f ciclos por barrido\n",
        eff / f, (float)g_plotN * f / eff);
    if (f > eff / 2.0f) {
      ack("     [AVISO] %.1f Hz supera Nyquist de fs_eff. Bajá 'dec' o subí 'n'.\n", f);
    }
  }
  else if (cmd == "unit") {
    if      (arg == "v")  g_mV = false;
    else if (arg == "mv") g_mV = true;
    else { ack("[ERROR] usa: unit v | unit mv\n"); return; }
    ack("[OK] unidad = %s\n", g_mV ? "mV" : "V");
  }
  else if (cmd == "fmt") {
    if      (arg == "label") g_fmt = FMT_LABEL;
    else if (arg == "plain") g_fmt = FMT_PLAIN;
    else { ack("[ERROR] usa: fmt label | fmt plain\n"); return; }
    ack("[OK] formato = %s\n", g_fmt == FMT_LABEL ? "L:valor" : "solo numero");
  }
  else if (cmd == "plot")  { reiniciarVentana(); vaciarDMA();
                             plotCapturando = true; plotIdx = 0;
                             g_mode = MODE_PLOT; }
  else if (cmd == "stream"){ reiniciarVentana(); g_mode = MODE_STREAM; }
  else if (cmd == "bin")   { reiniciarVentana(); vaciarDMA();
                             binReiniciar(); g_mode = MODE_BIN; }
  else if (cmd == "raf") {
    // raf <on> <off>, en muestras diezmadas. off = 0 -> captura continua.
    int esp2 = arg.indexOf(' ');
    long on  = (esp2 < 0) ? arg.toInt() : arg.substring(0, esp2).toInt();
    long off = (esp2 < 0) ? 0           : arg.substring(esp2 + 1).toInt();
    if (on < 0 || off < 0 || on > 1000000L || off > 1000000L) {
      ack("[ERROR] usa: raf <muestras_on> <muestras_off>  (0..1000000)\n");
      return;
    }
    if (off > 0 && on == 0) {
      ack("[ERROR] con pausa > 0, las muestras a capturar no pueden ser 0.\n");
      return;
    }
    g_rafOn  = (uint32_t)on;
    g_rafOff = (uint32_t)off;
    binReiniciar();
    if (g_rafOff == 0) {
      ack("[OK] Captura continua (sin pausas)\n");
    } else {
      float eff = (float)g_fs / g_dec;
      ack("[OK] Rafaga: %lu muestras (%.2f ms) + pausa %lu (%.2f ms)\n",
          (unsigned long)g_rafOn,  1000.0f * g_rafOn  / eff,
          (unsigned long)g_rafOff, 1000.0f * g_rafOff / eff);
      ack("     Ciclo util: %.1f %% de las muestras llegan a la PC\n",
          100.0f * g_rafOn / (g_rafOn + g_rafOff));
    }
  }
  else if (cmd == "stats") { g_mode = MODE_STATS; reiniciarVentana();
                             Serial.println("[OK] modo stats"); }
  else if (cmd == "raw")   { g_mode = MODE_RAW;   reiniciarVentana();
                             Serial.println("# t_s,L_V,R_V"); }
  else if (cmd == "off")   { g_mode = MODE_OFF;
                             Serial.println("[OK] salida detenida"); }
  else if (cmd == "diag")  { Mode prev = g_mode; g_mode = MODE_OFF;
                             diagnostico(); g_mode = prev; }
  else if (cmd == "info")  { mostrarInfo(); return; }
  else if (cmd == "help" || cmd == "?") { mostrarAyuda(); return; }
  else if (cmd == "reset") {
    borrarConfig();
    Serial.println("[OK] Configuracion borrada. Reiniciando...");
    delay(200);
    ESP.restart();
  }
  else {
    ack("[ERROR] comando desconocido: '%s'. Escribi 'help'.\n", cmd.c_str());
    return;
  }

  // Todo cambio se persiste en NVS, asi sobrevive al reset que provoca abrir
  // el Serial Plotter. La NVS no reescribe si el valor no cambio, o sea que
  // esto no desgasta la flash.
  guardarConfig();
}

static void leerConsola() {
  static String buf;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (buf.length()) { procesarComando(buf); buf = ""; }
    } else if (buf.length() < 64) {
      buf += c;
    }
  }
}

// ===========================================================================
//  Salidas
// ===========================================================================

// En modo grafico no puede salir NADA que no sea un dato: cualquier linea de
// texto suelta le desordena las series al plotter.
// En modo grafico no puede salir NADA que no sea un dato. En texto una linea
// suelta le desordena las series al plotter; en binario es peor, porque le
// mete bytes al medio de una trama y le rompe el sincronismo a la PC.
static inline bool modoGrafico() {
  return g_mode == MODE_PLOT || g_mode == MODE_STREAM || g_mode == MODE_BIN;
}

// Acuse de recibo de un comando, silenciado mientras se esta graficando.
static void ack(const char *fmt, ...) {
  if (modoGrafico()) return;
  char buf[192];
  va_list ap;
  va_start(ap, fmt);
  vsnprintf(buf, sizeof(buf), fmt, ap);
  va_end(ap);
  Serial.print(buf);
}

static void emitirPlot(float l, float r) {
  // Formato del Serial Plotter del Arduino IDE 2.x: una linea por punto, con
  // "etiqueta:valor" separados por coma. Terminador CRLF, que es lo que emite
  // Serial.println() del core y lo que el plotter espera.
  const float a = g_mV ? l * 1000.0f : l;
  const float b = g_mV ? r * 1000.0f : r;
  const int   d = g_mV ? 4 : 7;   // cifras decimales

  if (g_fmt == FMT_LABEL) {
    switch (g_ch) {
      case CH_L: Serial.printf("L:%.*f\r\n", d, a); break;
      case CH_R: Serial.printf("R:%.*f\r\n", d, b); break;
      default:   Serial.printf("L:%.*f,R:%.*f\r\n", d, a, d, b); break;
    }
  } else {
    // Sin etiquetas, separado por coma: CSV puro. Es lo que esperan
    // Telemetry Viewer, Serial Studio, el plotter viejo del IDE 1.8 y
    // cualquier script propio. El plotter del IDE 2.x tambien acepta coma.
    switch (g_ch) {
      case CH_L: Serial.printf("%.*f\r\n", d, a); break;
      case CH_R: Serial.printf("%.*f\r\n", d, b); break;
      default:   Serial.printf("%.*f,%.*f\r\n", d, a, d, b); break;
    }
  }
}

// ---------------------------------------------------------------------------
//  Modo binario
// ---------------------------------------------------------------------------

// CRC-16/CCITT-FALSE. Version bit a bit: son ~64 operaciones por byte, o sea
// menos del 2% de CPU al caudal maximo. No justifica una tabla de 512 bytes.
static uint16_t crc16(const uint8_t *d, size_t n) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < n; i++) {
    crc ^= (uint16_t)d[i] << 8;
    for (uint8_t b = 0; b < 8; b++) {
      crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
  }
  return crc;
}

static void binEnviarPaquete() {
  if (binN == 0) return;

  binBuf[0] = BIN_MAGIC0;
  binBuf[1] = BIN_MAGIC1;
  memcpy(&binBuf[2], &binIdxPkt, 4);
  memcpy(&binBuf[6], &binN,      2);
  binBuf[8] = binFlags;

  // El CRC cubre desde idx hasta el ultimo dato: todo menos el preambulo,
  // que es solo marca de sincronismo y no lleva informacion.
  size_t   largo = BIN_CAB + (size_t)binN * 4;
  uint16_t c     = crc16(&binBuf[2], largo - 2);
  memcpy(&binBuf[largo], &c, 2);

  Serial.write(binBuf, largo + 2);

  binN     = 0;
  binFlags = 0;
}

// Agrega una muestra al paquete en curso; lo despacha cuando se llena.
static inline void binAgregar(float v) {
  if (binN == 0) binIdxPkt = (uint32_t)binIdx;
  memcpy(&binBuf[BIN_CAB + (size_t)binN * 4], &v, 4);
  if (++binN >= BIN_MUESTRAS) binEnviarPaquete();
}

static void binReiniciar() {
  binN      = 0;
  binIdx    = 0;
  binFlags  = 0x01;              // el primer paquete abre rafaga
  rafCapturando = true;
  rafRestan = g_rafOn;
}

// Tira lo que haya quedado en el ring del DMA, para que el proximo barrido
// arranque con muestras frescas y contiguas entre si.
static void vaciarDMA() {
  size_t n;
  for (int i = 0; i < 64; i++) {
    if (i2s_channel_read(rx_chan, rawBuf, sizeof(rawBuf), &n, 0) != ESP_OK) break;
    if (n == 0) break;
  }
  accL = accR = 0;
  accN = 0;
}

static void emitirRaw(float l, float r) {
  double t = (double)sampleIndex * (double)g_dec / (double)g_fs;
  switch (g_ch) {
    case CH_L:    Serial.printf("%.6f,%.7f\n", t, l); break;
    case CH_R:    Serial.printf("%.6f,%.7f\n", t, r); break;
    default:      Serial.printf("%.6f,%.7f,%.7f\n", t, l, r); break;
  }
}

static void emitirStats() {
  float eff = (float)g_fs / (float)g_dec;
  Medicion mL = analizar(anaL, anaN, eff);
  Medicion mR = analizar(anaR, anaN, eff);

  // Frames realmente capturados vs. los que deberian haber entrado.
  // Si el porcentaje baja de 100 es que la salida serie no da abasto y el DMA
  // esta pisando datos.
  uint32_t dt = millis() - t0_ms;
  double esperados = (double)g_fs * (double)dt / 1000.0;
  double captura = (esperados > 0) ? 100.0 * (double)framesTotal / esperados : 0.0;

  Serial.println();
  Serial.printf("--- ventana %.3f s  |  fs=%lu Hz  D=%lu  fs_eff=%.1f Hz  |  captura %.1f%%",
                (float)anaN / eff, (unsigned long)g_fs, (unsigned long)g_dec,
                eff, captura);
  if (clipCount) Serial.printf("  |  CLIP! %lu", (unsigned long)clipCount);
  Serial.println();
  Serial.println("      DC(mV)    Vpp(mV)   Vrms(mV)   dBFS     f(Hz)   ciclos");
  Serial.printf("  L  %9.3f  %9.3f  %9.3f  %7.1f  %8.3f   %lu\n",
                mL.dc * 1e3f, mL.vpp * 1e3f, mL.vrms * 1e3f, mL.dbfs, mL.freq,
                (unsigned long)mL.ciclos);
  Serial.printf("  R  %9.3f  %9.3f  %9.3f  %7.1f  %8.3f   %lu\n",
                mR.dc * 1e3f, mR.vpp * 1e3f, mR.vrms * 1e3f, mR.dbfs, mR.freq,
                (unsigned long)mR.ciclos);

  clipCount   = 0;
  framesTotal = 0;
  t0_ms       = millis();
}

// ===========================================================================
//  setup / loop
// ===========================================================================

static void banner() {
  Serial.println();
  Serial.println("============================================================");
  Serial.println(" PCM1808 + ESP32-C3 SuperMini  --  banco de prueba");
  Serial.println("============================================================");
#if CONSOLA_DUAL
  Serial.println(" Aviso: compilaste con 'USB CDC On Boot: Disabled'.");
  Serial.println(" La consola igual sale por USB porque el sketch levanta el");
  Serial.println(" CDC nativo a mano, pero conviene poner la opcion en Enabled");
  Serial.println(" (o elegir la placa 'Nologo ESP32C3 Super Mini').");
#endif
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, HIGH);   // activo en bajo -> HIGH = apagado

  // Recuperamos la configuracion de la sesion anterior ANTES de imprimir nada:
  // si quedo guardado un modo grafico, el arranque tiene que ser mudo.
  cargarConfig();

  // Esperamos a que la PC abra el puerto, si es que hay una. Sin esto el
  // banner se imprime antes de que el Monitor Serie enumere y se pierde.
  uint32_t t = millis();
  while (!Serial.usbConectado() && (millis() - t) < 2500) { delay(10); }
  delay(300);

  // Parpadeo de arranque: si ves esto, el sketch esta corriendo. Si ademas no
  // ves nada en el Monitor Serie, el problema es del puerto, no del firmware.
  for (int i = 0; i < 6; i++) {
    digitalWrite(PIN_LED, i & 1);
    delay(80);
  }
  digitalWrite(PIN_LED, HIGH);

  if (!modoGrafico()) banner();

  if (!i2sStart(g_fs)) {
    // Esto si se dice siempre: sin I2S no hay nada que graficar.
    Serial.println("[FATAL] No se pudo inicializar el I2S. Se detiene.");
    while (true) { digitalWrite(PIN_LED, !digitalRead(PIN_LED)); delay(150); }
  }

  if (!modoGrafico()) {
    mostrarInfo();
    diagnostico();
    mostrarAyuda();
    Serial.printf("Modo actual: %s.\n", nombreModo(g_mode));
    Serial.println("Se guarda solo: al reabrir el puerto arranca asi de nuevo.");
    Serial.println();
  } else {
    // Arranque limpio para el plotter: ni una linea de texto.
    plotCapturando = true;
    plotIdx = 0;
    vaciarDMA();
  }
}

void loop() {
  // LED primero, siempre: es el unico indicador que sirve cuando la consola no
  // se ve. Fijo mientras haya saturacion reciente, si no parpadeo de "vivo".
  if (clipLast_ms && (millis() - clipLast_ms) < 500) {
    digitalWrite(PIN_LED, LOW);
  } else {
    digitalWrite(PIN_LED, ((millis() / 500) & 1) ? LOW : HIGH);
  }

  // Si abris el Monitor Serie despues de que arranco, repetimos la cabecera
  // para no obligarte a resetear la placa. En modo grafico no, que ensucia.
  static bool usbPrev = false;
  bool usbAhora = Serial.usbConectado();
  if (usbAhora && !usbPrev && !modoGrafico()) {
    delay(200);
    banner();
    mostrarInfo();
    Serial.println("Escribi 'help' para la lista de comandos, 'diag' para");
    Serial.println("repetir el diagnostico de conexion.");
    Serial.println();
  }
  usbPrev = usbAhora;

  leerConsola();

  if (g_mode == MODE_OFF) {
    // Igual vaciamos el DMA para que no se acumule basura vieja
    size_t n;
    i2s_channel_read(rx_chan, rawBuf, sizeof(rawBuf), &n, 10);
    delay(1);
    return;
  }

  // ---- Modo osciloscopio: capturar rapido, reproducir despacio ----
  if (g_mode == MODE_PLOT) {
    if (plotCapturando) {
      uint32_t frames = leerBloque();
      for (uint32_t i = 0; i < frames && plotIdx < g_plotN; i++) {
        float l, r;
        if (!diezmar(rawBuf[2 * i], rawBuf[2 * i + 1], &l, &r)) continue;
        anaL[plotIdx] = l;
        anaR[plotIdx] = r;
        plotIdx++;
      }
      if (plotIdx >= g_plotN) {   // barrido completo
        plotCapturando = false;
        plotIdx = 0;
        plotLast_us = micros();
      }
    } else {
      // Reproduccion pausada, un punto cada 1/g_plotRate segundos
      uint32_t intervalo = 1000000UL / g_plotRate;
      if ((uint32_t)(micros() - plotLast_us) >= intervalo) {
        plotLast_us += intervalo;
        emitirPlot(anaL[plotIdx], anaR[plotIdx]);
        if (++plotIdx >= g_plotN) {   // fin del barrido, a capturar de nuevo
          plotIdx = 0;
          plotCapturando = true;
          vaciarDMA();
        }
      }
    }
    return;
  }

  uint32_t frames = leerBloque();
  if (frames == 0) return;

  for (uint32_t i = 0; i < frames; i++) {
    float l, r;
    if (!diezmar(rawBuf[2 * i], rawBuf[2 * i + 1], &l, &r)) continue;

    switch (g_mode) {
      case MODE_STREAM:
        emitirPlot(l, r);
        break;

      case MODE_BIN:
        if (g_rafOff == 0) {
          binAgregar(l);                  // continuo
        } else if (rafCapturando) {
          binAgregar(l);
          if (--rafRestan == 0) {
            binEnviarPaquete();           // despachar el paquete a medio llenar
            rafCapturando = false;
            rafRestan     = g_rafOff;
          }
        } else {
          if (--rafRestan == 0) {         // fin de la pausa
            rafCapturando = true;
            rafRestan     = g_rafOn;
            binFlags     |= 0x01;         // el proximo paquete abre rafaga
          }
        }
        // El indice avanza SIEMPRE, tambien durante la pausa: representa
        // tiempo real, no cantidad de muestras enviadas. Es lo que le permite
        // a la PC reconstruir el eje temporal con los huecos incluidos.
        binIdx++;
        break;

      case MODE_RAW:
        emitirRaw(l, r);
        break;

      case MODE_STATS:
        if (anaN < ANA_N) {
          anaL[anaN] = l;
          anaR[anaN] = r;
          anaN++;
        }
        if (anaN >= ANA_N) {
          emitirStats();
          anaN = 0;
        }
        break;

      default:
        break;
    }
    sampleIndex++;
  }
}
