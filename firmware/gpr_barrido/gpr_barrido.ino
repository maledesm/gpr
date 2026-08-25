/* ===========================================================================
 *  GPR FMCW -- barrido y adquisicion sincronizados
 *  ESP32-C3 SuperMini + MCP4725 (rampa del VCO) + PCM1808 (beat)
 * ===========================================================================
 *
 *  Junta las dos mitades que hasta ahora vivian en sketches separados:
 *
 *      prueba_mcp4725      -> generaba la triangular, sin tocar el I2S
 *      PCM1808_ESP32C3     -> digitalizaba, sin tocar el DAC
 *
 *  Los dos originales quedan intactos como referencia. Este es el que va a la
 *  placa para medir con el radar.
 *
 *  ---------------------------------------------------------------------------
 *  POR QUE NO ALCANZA CON PEGAR LOS DOS LAZOS
 *  ---------------------------------------------------------------------------
 *
 *  El sketch del PCM lee el I2S con i2s_channel_read BLOQUEANTE de 256 frames:
 *  a 48 kHz son 5.33 ms en los que el loop() no ejecuta nada mas. El sketch del
 *  DAC pacea la rampa haciendo polling de micros() en loop(). Juntados tal
 *  cual, cada lectura de I2S congelaria la rampa 5.33 ms, y una rampa entera
 *  dura 2.5 ms.
 *
 *  La solucion es hacer las dos cosas en el MISMO lazo, pero leyendo el I2S de
 *  a bloques chicos: se lee un bloque, se empujan las muestras a un buffer
 *  circular, y se mira si toca escalon del DAC. Como el bloque dura menos que
 *  el escalon, la rampa nunca se queda esperando.
 *
 *  Ese lazo vive en una tarea de FreeRTOS de prioridad alta. El loop() de
 *  Arduino, que corre por debajo, solo vacia el buffer circular hacia el
 *  puerto serie. Asi la transmision no puede demorar la rampa, que es la
 *  prioridad que elegimos: rampa uniforme ante todo.
 *
 *  ---------------------------------------------------------------------------
 *  LOS DOS MODOS DE SINCRONISMO
 *  ---------------------------------------------------------------------------
 *
 *  MARCA  El DAC se pacea solo, con micros(). El firmware anota en que numero
 *         de muestra cayo cada vertice de la triangular y lo manda en la trama.
 *         La duracion de cada rampa varia un poco segun cuanto tarde cada
 *         escritura I2C. Es el modo simple.
 *
 *  ATADO  El reloj de muestreo manda: el DAC avanza exactamente cada N
 *         muestras contadas del propio stream de I2S. Todas las rampas duran
 *         lo mismo, muestra por muestra, y los escalones quedan parejos por
 *         construccion. Obliga a que fs, duracion y pasos den numeros enteros.
 *
 *  Los dos anotan el vertice, asi que se pueden comparar en el banco con la
 *  misma cadena de procesamiento. El comando 'jit' reporta la dispersion real
 *  de la duracion de rampa, que es el numero que decide si hace falta ATADO.
 *
 *  ---------------------------------------------------------------------------
 *  CONEXIONADO
 *  ---------------------------------------------------------------------------
 *
 *      ESP32-C3            PCM1808              (I2S, GPIO4..7)
 *      GPIO4    ------>    SCK    (SCKI / master clock = 256*fs)
 *      GPIO5    ------>    BCK    (bit clock)
 *      GPIO6    ------>    LRC    (word select = fs)
 *      GPIO7    <------    OUT    (DOUT)
 *      5V       ------>    5V     (VCC analogico: 5 V, NO 3.3)
 *      3V3      ------>    3.3
 *      GND      ------>    GND, FMY, MDI, MDO
 *
 *      ESP32-C3            MCP4725              (I2C, GPIO0..1)
 *      GPIO0    <----->    SDA
 *      GPIO1    ------>    SCL
 *      3V3      ------>    VCC    (define la escala completa de salida)
 *      GND      ------>    GND
 *
 *  Ojo: 'SCK' en el modulo del PCM1808 es el MASTER CLOCK, no el bit clock.
 *  Cruzarlo con BCK da "todo cero".
 *
 *  Requiere Arduino-ESP32 core 3.x (API i2s_std de ESP-IDF 5).
 * ===========================================================================
 */

#include <Wire.h>
#include <Preferences.h>
#include "driver/i2s_std.h"
#include "tabla_vco.h"

// ---------------------------------------------------------------------------
//  Consola dual
// ---------------------------------------------------------------------------
//
//  En el core 3.x `Serial` es un macro que apunta a hardware distinto segun la
//  opcion "USB CDC On Boot":
//
//      Enabled  ->  HWCDCSerial  = USB nativo
//      Disabled ->  Serial0      = UART0, pines GPIO20/21
//
//  La placa "ESP32C3 Dev Module" viene con cdc_on_boot = 0 de fabrica, o sea
//  que por defecto imprime por unos pines a los que no hay nada conectado y el
//  Monitor Serie queda mudo aunque el programa corra perfecto. En vez de
//  depender de que el menu este bien puesto, escribimos por los dos lados.
//
#if ARDUINO_USB_MODE && !ARDUINO_USB_CDC_ON_BOOT
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
    UsbCdc.setTxTimeoutMs(0);   // no esperar a un host que puede no existir
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

  // El buffer de transmision del CDC son 256 bytes por defecto
  // (HWCDC.cpp:422). Una trama binaria son ~1 kB: sin ampliarlo, write()
  // devuelve una cuenta corta y la trama sale mutilada.
  void ampliarBufferTx(size_t n) {
#if CONSOLA_DUAL
    UsbCdc.setTxBufferSize(n);
#else
    Serial.setTxBufferSize(n);
#endif
  }

  bool usbConectado() {
#if CONSOLA_DUAL || ARDUINO_USB_MODE
    return HWCDC::isConnected();
#else
    return true;
#endif
  }

  operator bool() { return true; }
};

static Consola Con;
#undef Serial
#define Serial Con

// ---------------------------------------------------------------------------
//  Pines
// ---------------------------------------------------------------------------
// Se evitan GPIO2, GPIO8 y GPIO9: son strapping pins del C3.
#define PIN_MCLK   4      // -> SCK del modulo (SCKI)
#define PIN_BCLK   5      // -> BCK
#define PIN_LRCK   6      // -> LRC
#define PIN_DIN    7      // <- OUT (DOUT)
#define PIN_LED    8      // LED azul integrado, ACTIVO EN BAJO
#define PIN_SDA    0
#define PIN_SCL    1

// ---------------------------------------------------------------------------
//  Parametros
// ---------------------------------------------------------------------------
#define FS_MIN         8000
#define FS_MAX        96000
#define PASOS_MIN          4
#define PASOS_MAX       1024      // tope de la tabla de predistorsion
// Muestras por escalon. El tope no es arbitrario: dma_frame_num se iguala a
// este valor, y el IDF exige que un descriptor no pase de 4092 bytes. Con dos
// slots de 32 bits son 8 bytes por frame, o sea 511 frames como maximo. 256
// deja margen y alcanza de sobra: a 48 kHz son 5.3 ms por escalon, una rampa
// lentisima. Si hace falta ir mas lento, se sube 'pasos', no esto.
#define NMUE_MIN           8
#define NMUE_MAX         256

// La escritura I2C medida son ~125 us. Si el escalon dura menos que eso el bus
// no llega y la rampa se deforma. Se avisa por consola.
#define ESCRITURA_TIPICA_US  125

#define RING_N          4096      // muestras en vuelo entre la tarea y el loop
#define EV_N              32      // vertices en vuelo
#define WARMUP_MS        150      // el PCM1808 arranca en mute y hace fade-in

// Trama binaria v2. Magic distinto del v1 (0xA5 0x5A) a proposito: un
// decodificador viejo no sincroniza con esto y falla limpio en vez de
// interpretar mal los campos nuevos.
#define BIN_MAGIC0     0xA5
#define BIN_MAGIC1     0x5B
#define BIN_MUESTRAS    256
#define BIN_CAB          13       // magic(2)+idx(4)+n(2)+flags(1)+rampa(4)
#define BIN_MAX         (BIN_CAB + BIN_MUESTRAS * 4 + 2)

#define FLAG_INICIO    0x01       // primera trama de la adquisicion
#define FLAG_OVF_DMA   0x02       // hubo desborde del DMA desde la trama anterior
#define FLAG_BAJADA    0x04       // la rampa en curso es descendente
#define FLAG_VERTICE   0x08       // esta trama arranca una rampa nueva
#define FLAG_OVF_RING  0x10       // el loop no vacio el ring a tiempo

#define SINC_MARCA   0
#define SINC_ATADO   1

// Fondo de escala del PCM1808 = 0.6 * VCC, con VCC = 5 V -> 3.0 Vpp.
#define PCM_VCC        5.0f
#define PCM_FS_V      (0.6f * PCM_VCC / 2.0f)   // pico, en volts

// ---------------------------------------------------------------------------
//  Estado
// ---------------------------------------------------------------------------
static Preferences prefs;

static uint32_t g_fs      = 48000;   // Hz
static uint16_t g_pasos   = 75;      // escalones por rampa
static uint16_t g_nmue    = 16;      // muestras por escalon
static bool     g_predist = true;
static uint8_t  g_sinc    = SINC_MARCA;
static uint8_t  g_canal   = 0;       // 0 = L, 1 = R
static bool     g_bin     = true;    // salida binaria (si no, solo texto)

static uint8_t  g_addr    = 0x60;
static uint32_t g_clk     = 400000;

// Si no hay MCP4725 conectado el firmware NO se planta: sigue funcionando con
// la rampa en seco. La cuenta de escalones y los vertices se generan igual,
// asi que se puede probar toda la cadena -- segmentacion, tramas, CRC y el
// software de la PC -- teniendo solo el ESP32 sobre la mesa. Lo unico que no
// pasa es la escritura al bus.
static bool     g_dacOk   = false;

static i2s_chan_handle_t rx_chan = nullptr;
static TaskHandle_t      h_adq   = nullptr;
static volatile bool     g_corriendo = false;

// Ring de muestras. Un solo productor (la tarea) y un solo consumidor (loop),
// asi que alcanza con indices volatiles: no hace falta seccion critica.
static volatile float    ring[RING_N];
static volatile uint32_t ringHead = 0, ringTail = 0;

// Ring de vertices: (indice de muestra donde arranca la rampa, numero, sentido)
struct Vertice { uint32_t idx; uint32_t rampa; uint8_t bajada; };
static volatile Vertice  evs[EV_N];
static volatile uint32_t evHead = 0, evTail = 0;

// Contadores compartidos. Solo los escribe la tarea.
static volatile uint32_t g_muestras   = 0;   // muestras empujadas al ring
static volatile uint32_t g_rampa      = 0;   // rampas desde que arranco
static volatile uint32_t g_ovfDma     = 0;
static volatile uint32_t g_ovfRing    = 0;
static volatile uint32_t g_atrasos    = 0;
static volatile uint32_t g_peorUs     = 0;
static volatile uint32_t g_rampaMinUs = 0xFFFFFFFF;
static volatile uint32_t g_rampaMaxUs = 0;
static volatile uint32_t g_rampaUltUs = 0;
static volatile uint32_t g_errI2C     = 0;

// Estado de la rampa, solo lo toca la tarea
static int32_t  idxPaso = 0;
static int8_t   sentido = +1;
static uint32_t proximoUs = 0;
static uint32_t acumMue = 0;
static uint32_t tVerticeUs = 0;

// Buffers
static int32_t  rawBuf[NMUE_MAX * 2];
static uint8_t  binBuf[BIN_MAX];
static uint16_t binN = 0;
static uint32_t binIdxPkt = 0, binRampaPkt = 0;
static uint8_t  binFlags = 0;
static uint32_t binTruncados = 0;

// Estado del consumidor (loop)
static uint32_t consumidas = 0;
static uint32_t rampaAct = 0;
static bool     bajadaAct = false;

// ===========================================================================
//  MCP4725
// ===========================================================================

// Solo el comando rapido de 2 bytes. NUNCA el de EEPROM: aguanta ~1e6 ciclos
// y tarda 25-50 ms por escritura, o sea que en una rampa se quemaria en
// minutos.
static inline bool escribirDAC(uint16_t valor) {
  // Sin DAC no se toca el bus: una transaccion contra una direccion que nadie
  // contesta igual consume tiempo esperando el NACK, y en la rampa eso se
  // pagaria en cada escalon.
  if (!g_dacOk) return true;
  if (valor > 4095) valor = 4095;
  Wire.beginTransmission(g_addr);
  Wire.write((uint8_t)(valor >> 8));
  Wire.write((uint8_t)(valor & 0xFF));
  return Wire.endTransmission() == 0;
}

static bool buscarDAC() {
  for (uint8_t a = 0x60; a <= 0x67; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) { g_addr = a; g_dacOk = true; return true; }
  }
  g_dacOk = false;
  return false;
}

// Codigo del DAC para el escalon k.
//
// Con predistorsion se indexa la tabla generada de la curva medida del VCO:
// recorriendola a paso constante, la FRECUENCIA avanza lineal en el tiempo, la
// tension no. Sin predistorsion es la rampa lineal en tension de siempre, para
// poder comparar las dos.
static inline uint16_t codigoPaso(int32_t k) {
  if (g_predist) {
    uint32_t i = (uint32_t)k * (TABLA_VCO_N - 1) / (g_pasos - 1);
    return TABLA_VCO[i];
  }
  return (uint16_t)((uint32_t)TABLA_VCO[TABLA_VCO_N - 1] * k / (g_pasos - 1));
}

// ===========================================================================
//  Rings
// ===========================================================================

// Devuelve false si el ring estaba lleno y la muestra se perdio.
//
// Que devuelva el resultado no es cosmetico: g_muestras solo se incrementa con
// los push que ENTRARON. Asi el indice que llevan los vertices y el que lleva
// el consumidor cuentan lo mismo y siguen alineados aunque se pierdan
// muestras. Contando los intentos, despues de una sola perdida el consumidor
// quedaria permanentemente atras del indice de los vertices y no volveria a
// reconocer ni un solo comienzo de rampa.
static inline bool ringPush(float v) {
  uint32_t h = ringHead;
  uint32_t n = (h + 1) & (RING_N - 1);
  if (n == ringTail) { g_ovfRing = g_ovfRing + 1; return false; }   // el loop no da abasto
  ring[h] = v;
  ringHead = n;
  return true;
}

static inline bool ringPop(float *v) {
  uint32_t t = ringTail;
  if (t == ringHead) return false;
  *v = ring[t];
  ringTail = (t + 1) & (RING_N - 1);
  return true;
}

static inline void evPush(uint32_t idx, uint32_t rampa, bool bajada) {
  uint32_t h = evHead;
  uint32_t n = (h + 1) & (EV_N - 1);
  if (n == evTail) return;             // se pierde el vertice, no la muestra
  evs[h].idx    = idx;
  evs[h].rampa  = rampa;
  evs[h].bajada = bajada ? 1 : 0;
  evHead = n;
}

static inline bool evPeek(Vertice *v) {
  if (evTail == evHead) return false;
  v->idx    = evs[evTail].idx;
  v->rampa  = evs[evTail].rampa;
  v->bajada = evs[evTail].bajada;
  return true;
}

static inline void evPop() { evTail = (evTail + 1) & (EV_N - 1); }

// ===========================================================================
//  I2S
// ===========================================================================

// dma_frame_num se iguala al bloque de lectura a proposito. El driver del IDF
// entrega los datos de a descriptor completo, asi que si el descriptor fuera
// grande las lecturas volverian en rafagas: una espera larga y despues varias
// instantaneas. Con el descriptor del tamano del bloque, cada lectura vuelve
// justo cuando llegan esas muestras, que es lo que hace fina la marca del
// vertice y deterministico el paso del DAC.
static bool i2sStart() {
  if (rx_chan) {
    i2s_channel_disable(rx_chan);
    i2s_del_channel(rx_chan);
    rx_chan = nullptr;
  }

  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  cc.dma_desc_num  = 16;              // elasticidad ante hipos del loop
  cc.dma_frame_num = g_nmue;
  cc.auto_clear    = false;
  if (i2s_new_channel(&cc, nullptr, &rx_chan) != ESP_OK) {
    Serial.println("[ERROR] i2s_new_channel fallo");
    return false;
  }

  i2s_std_config_t sc = {};
  sc.clk_cfg.sample_rate_hz = g_fs;
  sc.clk_cfg.clk_src        = I2S_CLK_SRC_DEFAULT;
  sc.clk_cfg.mclk_multiple  = I2S_MCLK_MULTIPLE_256;

  // Slots de 32 bits y no de 24: el PCM1808 esclavo acepta 64 o 48 BCK por
  // trama pero NO 32, y estereo x 32 bits da 64 exactos. La muestra de 24 bits
  // llega alineada al MSB y se recupera con un shift aritmetico de 8.
  sc.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,
                                                    I2S_SLOT_MODE_STEREO);
  sc.gpio_cfg.mclk = (gpio_num_t)PIN_MCLK;
  sc.gpio_cfg.bclk = (gpio_num_t)PIN_BCLK;
  sc.gpio_cfg.ws   = (gpio_num_t)PIN_LRCK;
  sc.gpio_cfg.dout = I2S_GPIO_UNUSED;
  sc.gpio_cfg.din  = (gpio_num_t)PIN_DIN;

  if (i2s_channel_init_std_mode(rx_chan, &sc) != ESP_OK) {
    Serial.println("[ERROR] i2s_channel_init_std_mode fallo");
    return false;
  }

  i2s_event_callbacks_t cbs = {};
  cbs.on_recv_q_ovf = [](i2s_chan_handle_t, i2s_event_data_t *, void *) -> bool {
    // Corre en contexto de interrupcion: solo incrementa. El ++ sobre volatile
    // esta deprecado en C++20, por eso la forma larga.
    g_ovfDma = g_ovfDma + 1;
    return false;
  };
  i2s_channel_register_event_callback(rx_chan, &cbs, nullptr);
  g_ovfDma = 0;

  if (i2s_channel_enable(rx_chan) != ESP_OK) {
    Serial.println("[ERROR] i2s_channel_enable fallo");
    return false;
  }

  uint32_t t = millis();
  size_t   n;
  while (millis() - t < WARMUP_MS) {
    i2s_channel_read(rx_chan, rawBuf, (size_t)g_nmue * 8, &n, 100);
  }
  return true;
}

// ===========================================================================
//  Tarea de adquisicion
// ===========================================================================

// Un escalon del DAC. Al llegar a un extremo invierte el sentido y anota el
// vertice con el indice de muestra en curso, que es lo que despues permite
// segmentar el stream en barridos.
static inline void pasoDac() {
  if (!escribirDAC(codigoPaso(idxPaso))) g_errI2C = g_errI2C + 1;

  idxPaso += sentido;
  bool vertice = false;
  if (idxPaso >= (int32_t)g_pasos - 1) { idxPaso = g_pasos - 1; sentido = -1; vertice = true; }
  else if (idxPaso <= 0)               { idxPaso = 0;           sentido = +1; vertice = true; }

  if (vertice) {
    uint32_t ahora = micros();
    if (tVerticeUs) {
      uint32_t dur = ahora - tVerticeUs;
      g_rampaUltUs = dur;
      if (dur < g_rampaMinUs) g_rampaMinUs = dur;
      if (dur > g_rampaMaxUs) g_rampaMaxUs = dur;
    }
    tVerticeUs = ahora;
    g_rampa    = g_rampa + 1;
    evPush(g_muestras, g_rampa, sentido < 0);
  }
}

static void tareaAdq(void *) {
  const size_t bytesBloque = (size_t)g_nmue * 2 * sizeof(int32_t);
  const uint32_t pasoUs    = (uint32_t)((uint64_t)g_nmue * 1000000ULL / g_fs);

  idxPaso   = 0;
  sentido   = +1;
  acumMue   = 0;
  tVerticeUs = 0;
  proximoUs = micros();

  while (g_corriendo) {
    size_t bytes = 0;
    if (i2s_channel_read(rx_chan, rawBuf, bytesBloque, &bytes, pdMS_TO_TICKS(200))
        != ESP_OK || bytes == 0) {
      continue;
    }
    uint32_t frames = bytes / (2 * sizeof(int32_t));

    uint32_t entraron = 0;
    for (uint32_t i = 0; i < frames; i++) {
      // 24 bits alineados al MSB dentro de 32: shift aritmetico preserva signo
      int32_t m = rawBuf[i * 2 + g_canal] >> 8;
      if (ringPush((float)m / 8388608.0f * PCM_FS_V)) entraron++;
    }
    g_muestras = g_muestras + entraron;

    if (g_sinc == SINC_ATADO) {
      // El reloj de muestreo manda: el escalon cae siempre en la misma cuenta
      // de muestras, sin importar cuanto tardo la escritura anterior.
      acumMue += frames;
      while (acumMue >= g_nmue) { acumMue -= g_nmue; pasoDac(); }
    } else {
      // El DAC se pacea solo. 'proximo' es un instante absoluto, asi que el
      // error no se acumula aunque un escalon salga tarde.
      uint32_t ahora = micros();
      if ((int32_t)(ahora - proximoUs) >= 0) {
        uint32_t retraso = ahora - proximoUs;
        if (retraso > g_peorUs) g_peorUs = retraso;
        if (retraso > pasoUs / 2) g_atrasos = g_atrasos + 1;
        pasoDac();
        proximoUs += pasoUs;
        if ((int32_t)(micros() - proximoUs) > (int32_t)(pasoUs * 4)) {
          proximoUs = micros();      // quedamos muy atras: resincronizar
        }
      }
    }
  }

  h_adq = nullptr;
  vTaskDelete(nullptr);
}

// ===========================================================================
//  Trama binaria
// ===========================================================================

// CRC-16/CCITT-FALSE, bit a bit. Son ~64 operaciones por byte, menos del 2 %
// de CPU al caudal maximo: no justifica una tabla de 512 bytes.
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

static void binEnviar() {
  if (binN == 0) return;

  if (g_ovfDma)  { binFlags |= FLAG_OVF_DMA;  g_ovfDma  = 0; }
  if (g_ovfRing) { binFlags |= FLAG_OVF_RING; g_ovfRing = 0; }

  binBuf[0] = BIN_MAGIC0;
  binBuf[1] = BIN_MAGIC1;
  memcpy(&binBuf[2],  &binIdxPkt,   4);
  memcpy(&binBuf[6],  &binN,        2);
  binBuf[8] = binFlags;
  memcpy(&binBuf[9],  &binRampaPkt, 4);

  // El CRC cubre desde idx hasta el ultimo dato: todo menos el preambulo, que
  // es solo marca de sincronismo y no lleva informacion.
  size_t   largo = BIN_CAB + (size_t)binN * 4;
  uint16_t c     = crc16(&binBuf[2], largo - 2);
  memcpy(&binBuf[largo], &c, 2);

  // write() puede escribir MENOS de lo pedido: ante contrapresion del host el
  // CDC devuelve una cuenta corta. Ignorar ese retorno mutilaba cada trama.
  size_t   total = largo + 2, enviados = 0;
  uint32_t t0 = millis();
  while (enviados < total) {
    size_t w = Serial.write(binBuf + enviados, total - enviados);
    enviados += w;
    if (enviados >= total) break;
    if (millis() - t0 > 250) { binTruncados++; break; }   // el host no lee
    if (w == 0) delay(1);
  }

  binN     = 0;
  binFlags = 0;
}

static inline void binAgregar(float v) {
  if (binN == 0) {
    binIdxPkt   = consumidas;
    binRampaPkt = rampaAct;
    if (bajadaAct) binFlags |= FLAG_BAJADA;
  }
  memcpy(&binBuf[BIN_CAB + (size_t)binN * 4], &v, 4);
  if (++binN >= BIN_MUESTRAS) binEnviar();
}

// ===========================================================================
//  Configuracion
// ===========================================================================

// Ajusta g_nmue para que la rampa dure lo mas parecido posible al PRF pedido
// manteniendo un numero ENTERO de muestras por escalon. Devuelve el PRF real.
static float snapPrf(float prf_ms) {
  uint32_t muestrasRampa = (uint32_t)(prf_ms / 2.0f * g_fs / 1000.0f + 0.5f);
  uint32_t n = muestrasRampa / g_pasos;
  if (n < NMUE_MIN) n = NMUE_MIN;
  if (n > NMUE_MAX) n = NMUE_MAX;
  g_nmue = (uint16_t)n;
  return 2.0f * g_pasos * g_nmue * 1000.0f / g_fs;
}

static float prfActual() { return 2.0f * g_pasos * g_nmue * 1000.0f / g_fs; }
static float pasoUsActual() { return g_nmue * 1000000.0f / g_fs; }

static void guardar() {
  prefs.begin("gpr", false);
  prefs.putUInt("fs", g_fs);
  prefs.putUShort("pasos", g_pasos);
  prefs.putUShort("nmue", g_nmue);
  prefs.putBool("pre", g_predist);
  prefs.putUChar("sinc", g_sinc);
  prefs.putUChar("canal", g_canal);
  prefs.end();
}

static void cargar() {
  prefs.begin("gpr", true);
  g_fs      = prefs.getUInt("fs", g_fs);
  g_pasos   = prefs.getUShort("pasos", g_pasos);
  g_nmue    = prefs.getUShort("nmue", g_nmue);
  g_predist = prefs.getBool("pre", g_predist);
  g_sinc    = prefs.getUChar("sinc", g_sinc);
  g_canal   = prefs.getUChar("canal", g_canal);
  prefs.end();
}

static void mostrarInfo() {
  float paso = pasoUsActual();
  Serial.println();
  Serial.println("------------------- ESTADO -------------------");
  Serial.printf("  fs                : %lu Hz\n", (unsigned long)g_fs);
  Serial.printf("  Canal             : %c\n", g_canal ? 'R' : 'L');
  Serial.printf("  Sincronismo       : %s\n", g_sinc == SINC_ATADO ? "ATADO" : "MARCA");
  Serial.printf("  Predistorsion     : %s\n", g_predist ? "ON" : "OFF");
  Serial.println();
  Serial.printf("  Escalones/rampa   : %u\n", g_pasos);
  Serial.printf("  Muestras/escalon  : %u  (%.1f us)\n", g_nmue, paso);
  Serial.printf("  Muestras/rampa    : %lu\n", (unsigned long)((uint32_t)g_pasos * g_nmue));
  Serial.printf("  Rampa             : %.3f ms\n", prfActual() / 2.0f);
  Serial.printf("  PRF (periodo)     : %.3f ms  (%.1f Hz)\n",
                prfActual(), 1000.0f / prfActual());
  Serial.println();
  Serial.printf("  Barrido           : %.0f a %.0f MHz  (BW %.0f MHz)\n",
                TABLA_VCO_F0_MHZ, TABLA_VCO_F1_MHZ, TABLA_VCO_BW_MHZ);
  Serial.printf("  Escalon frecuencia: %.2f MHz\n", TABLA_VCO_BW_MHZ / g_pasos);
  Serial.printf("  Resolucion        : %.1f cm\n", 15000.0f / TABLA_VCO_BW_MHZ);
  Serial.printf("  Alcance no ambiguo: %.2f m en aire\n",
                g_pasos * 15000.0f / TABLA_VCO_BW_MHZ / 100.0f);
  Serial.printf("  f_beat por metro  : %.0f Hz/m\n",
                2.0f * TABLA_VCO_BW_MHZ * 1e6f / (3e8f * (prfActual() / 2000.0f)));
  Serial.println();
  if (g_dacOk) {
    Serial.printf("  DAC               : 0x%02X, bus %lu Hz\n",
                  g_addr, (unsigned long)g_clk);
  } else {
    Serial.println("  DAC               : NO CONECTADO -- rampa en seco");
    Serial.println("                      (se cuentan escalones y vertices, no sale tension)");
  }
  if (paso < ESCRITURA_TIPICA_US * 1.2f) {
    Serial.printf("  [AVISO] el escalon dura %.0f us y una escritura I2C ~%d us:\n",
                  paso, ESCRITURA_TIPICA_US);
    Serial.println("          no hay margen. Subi 'prf' o bajá 'pasos'.");
  }
  Serial.println("----------------------------------------------");
}

static void mostrarJitter() {
  float nominal = prfActual() / 2.0f * 1000.0f;    // us
  Serial.println();
  Serial.println("---------------- SINCRONISMO -----------------");
  Serial.printf("  Modo              : %s\n", g_sinc == SINC_ATADO ? "ATADO" : "MARCA");
  Serial.printf("  Rampa nominal     : %.1f us\n", nominal);
  if (g_rampaMaxUs) {
    uint32_t mn = g_rampaMinUs, mx = g_rampaMaxUs;
    Serial.printf("  Rampa medida      : %lu a %lu us  (ultima %lu)\n",
                  (unsigned long)mn, (unsigned long)mx,
                  (unsigned long)g_rampaUltUs);
    Serial.printf("  Dispersion        : %lu us  =  %.0f ppm  =  %.2f %% \n",
                  (unsigned long)(mx - mn), (mx - mn) / nominal * 1e6f,
                  (mx - mn) / nominal * 100.0f);
    // Lo que importa no es el jitter en si sino cuanto corre la distancia:
    // un error relativo en T_sweep se traslada igual a la distancia.
    Serial.printf("  Error de rango    : %.1f %% de la distancia medida\n",
                  (mx - mn) / nominal * 100.0f);
  } else {
    Serial.println("  Rampa medida      : (todavia sin datos, corre 'run')");
  }
  Serial.printf("  Escalones tarde   : %lu  (peor %lu us)\n",
                (unsigned long)g_atrasos, (unsigned long)g_peorUs);
  Serial.printf("  Overflow DMA      : %lu\n", (unsigned long)g_ovfDma);
  Serial.printf("  Overflow ring     : %lu\n", (unsigned long)g_ovfRing);
  Serial.printf("  Errores I2C       : %lu\n", (unsigned long)g_errI2C);
  Serial.printf("  Tramas truncadas  : %lu\n", (unsigned long)binTruncados);
  Serial.println("----------------------------------------------");
}

// Una asignacion por linea y no encadenadas: sobre variables volatile, usar el
// valor de una asignacion esta deprecado en C++20 y el compilador avisa.
static void resetCuentas() {
  g_atrasos    = 0;
  g_peorUs     = 0;
  g_rampaMinUs = 0xFFFFFFFF;
  g_rampaMaxUs = 0;
  g_rampaUltUs = 0;
  g_ovfDma     = 0;
  g_ovfRing    = 0;
  g_errI2C     = 0;
  binTruncados = 0;
}

static void arrancar() {
  if (g_corriendo) return;
  if (!i2sStart()) return;

  ringHead   = 0;
  ringTail   = 0;
  evHead     = 0;
  evTail     = 0;
  g_muestras = 0;
  g_rampa    = 0;
  consumidas = 0;
  rampaAct   = 0;
  bajadaAct  = false;
  binN = 0;
  binFlags = FLAG_INICIO;
  resetCuentas();

  g_corriendo = true;
  // Prioridad 5, por encima del loopTask de Arduino (1): la rampa nunca se
  // demora por la transmision serie. Es la prioridad que elegimos.
  xTaskCreate(tareaAdq, "adq", 4096, nullptr, 5, &h_adq);
  digitalWrite(PIN_LED, LOW);
}

static void parar() {
  if (!g_corriendo) return;
  g_corriendo = false;
  while (h_adq) delay(5);
  binEnviar();
  if (rx_chan) {
    i2s_channel_disable(rx_chan);
    i2s_del_channel(rx_chan);
    rx_chan = nullptr;
  }
  escribirDAC(0);
  digitalWrite(PIN_LED, HIGH);
}

// ===========================================================================
//  Consola
// ===========================================================================

static void ayuda() {
  Serial.println();
  Serial.println("  run | stop            arrancar / detener la adquisicion");
  Serial.println("  fs <hz>               frecuencia de muestreo, 8000 a 96000");
  Serial.println("  prf <ms>              periodo de la triangular (se ajusta a entero)");
  Serial.println("  pasos <n>             escalones por rampa, 4 a 1024");
  Serial.println("  nmue <n>              muestras por escalon (alternativa a prf)");
  Serial.println("  sinc marca|atado      como se ata la rampa al muestreo");
  Serial.println("  pre on|off            predistorsion del VCO");
  Serial.println("  ch l|r                canal del PCM1808");
  Serial.println("  bin on|off            salida binaria por serie");
  Serial.println("  dac                   volver a buscar el MCP4725 en el bus");
  Serial.println("  dc <codigo>           tension fija en el DAC (con la adq parada)");
  Serial.println("  jit                   dispersion de la duracion de rampa");
  Serial.println("  info | reset | help");
}

static void procesar(String s) {
  s.trim();
  if (!s.length()) return;
  int e = s.indexOf(' ');
  String cmd = (e < 0) ? s : s.substring(0, e);
  String arg = (e < 0) ? "" : s.substring(e + 1);
  arg.trim();
  cmd.toLowerCase();
  long   ai = arg.toInt();
  float  af = arg.toFloat();
  bool   corria = g_corriendo;

  if (cmd == "run")        { arrancar(); if (!g_bin) Serial.println("[ok] corriendo"); return; }
  if (cmd == "stop")       { parar(); Serial.println("[ok] detenido"); return; }
  if (cmd == "help")       { ayuda(); return; }
  if (cmd == "info")       { mostrarInfo(); return; }
  if (cmd == "jit")        { mostrarJitter(); return; }
  if (cmd == "reset")      { resetCuentas(); Serial.println("[ok] cuentas en cero"); return; }

  if (cmd == "dac") {
    if (g_corriendo) { Serial.println("[error] pará la adquisicion primero"); return; }
    if (buscarDAC()) { Serial.printf("[ok] MCP4725 en 0x%02X\n", g_addr); escribirDAC(0); }
    else             Serial.println("[aviso] sigo sin encontrarlo; rampa en seco");
    return;
  }

  if (cmd == "dc") {
    if (g_corriendo) { Serial.println("[error] pará la adquisicion primero"); return; }
    if (!g_dacOk) { Serial.println("[error] no hay DAC conectado ('dac' para buscarlo)"); return; }
    escribirDAC((uint16_t)ai);
    Serial.printf("[ok] DAC = %ld  (%.3f V con VDD 3.3)\n", ai, 3.3f * ai / 4095.0f);
    return;
  }

  // Los que cambian la configuracion: se para, se aplica y se vuelve a arrancar
  if (cmd == "fs" || cmd == "prf" || cmd == "pasos" || cmd == "nmue" ||
      cmd == "sinc" || cmd == "pre" || cmd == "ch" || cmd == "bin") {
    if (cmd == "bin") { g_bin = (arg != "off" && arg != "0"); Serial.printf("[ok] bin %s\n", g_bin ? "on" : "off"); return; }
    parar();

    if (cmd == "fs") {
      if (ai < FS_MIN || ai > FS_MAX) { Serial.printf("[error] fs entre %d y %d\n", FS_MIN, FS_MAX); return; }
      g_fs = (uint32_t)ai;
      Serial.printf("[ok] fs = %lu Hz  ->  PRF %.3f ms\n", (unsigned long)g_fs, prfActual());
    } else if (cmd == "prf") {
      if (af <= 0) { Serial.println("[error] prf debe ser > 0"); return; }
      float real = snapPrf(af);
      Serial.printf("[ok] PRF pedido %.3f ms  ->  real %.3f ms  (%u muestras/escalon)\n",
                    af, real, g_nmue);
    } else if (cmd == "pasos") {
      if (ai < PASOS_MIN || ai > PASOS_MAX) { Serial.printf("[error] pasos entre %d y %d\n", PASOS_MIN, PASOS_MAX); return; }
      g_pasos = (uint16_t)ai;
      Serial.printf("[ok] pasos = %u  ->  PRF %.3f ms\n", g_pasos, prfActual());
    } else if (cmd == "nmue") {
      if (ai < NMUE_MIN || ai > NMUE_MAX) { Serial.printf("[error] nmue entre %d y %d\n", NMUE_MIN, NMUE_MAX); return; }
      g_nmue = (uint16_t)ai;
      Serial.printf("[ok] nmue = %u  ->  PRF %.3f ms\n", g_nmue, prfActual());
    } else if (cmd == "sinc") {
      g_sinc = (arg == "atado") ? SINC_ATADO : SINC_MARCA;
      Serial.printf("[ok] sincronismo %s\n", g_sinc == SINC_ATADO ? "ATADO" : "MARCA");
    } else if (cmd == "pre") {
      g_predist = (arg != "off" && arg != "0");
      Serial.printf("[ok] predistorsion %s\n", g_predist ? "ON" : "OFF");
    } else if (cmd == "ch") {
      g_canal = (arg == "r" || arg == "R") ? 1 : 0;
      Serial.printf("[ok] canal %c\n", g_canal ? 'R' : 'L');
    }

    guardar();
    if (corria) arrancar();
    return;
  }

  Serial.printf("[?] '%s' no existe. 'help' para la lista.\n", cmd.c_str());
}

// ===========================================================================
//  setup / loop
// ===========================================================================

void setup() {
  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, HIGH);          // activo en bajo: apagado

  Serial.begin(115200);
  Serial.ampliarBufferTx(4096);
  uint32_t t = millis();
  while (!Serial.usbConectado() && millis() - t < 2500) delay(10);
  delay(300);

  Serial.println();
  Serial.println("==============================================");
  Serial.println(" GPR FMCW - barrido y adquisicion sincronizados");
  Serial.println("==============================================");

  cargar();

  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(g_clk);
  if (buscarDAC()) {
    Serial.printf("  MCP4725 en 0x%02X\n", g_addr);
    escribirDAC(0);
  } else {
    Serial.println();
    Serial.println("  [AVISO] No encuentro el MCP4725 en 0x60..0x67.");
    Serial.println("          Sigo igual, con la RAMPA EN SECO: se cuentan los");
    Serial.println("          escalones y se marcan los vertices, pero no sale");
    Serial.println("          tension. Sirve para probar la cadena completa");
    Serial.println("          teniendo solo el ESP32.");
    Serial.println("          Cuando lo conectes, 'dac' vuelve a buscarlo sin");
    Serial.println("          tener que reiniciar.");
    Serial.printf("          Revisa: SDA en GPIO%d, SCL en GPIO%d, VCC 3.3 V,\n",
                  PIN_SDA, PIN_SCL);
    Serial.println("          GND comun y pull-ups de 4k7 si el modulo no trae.");
  }

  mostrarInfo();
  Serial.println("\n'run' para arrancar, 'help' para la lista de comandos.");
}

void loop() {
  static String buf;
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (buf.length()) { procesar(buf); buf = ""; }
    } else if (buf.length() < 48) {
      buf += c;
    }
  }

  if (!g_corriendo) { delay(2); return; }

  // Vaciar el ring hacia la trama binaria. El paquete se corta en cada
  // vertice, asi que cada trama pertenece a UNA sola rampa y la PC no tiene
  // que buscar el corte: le llega hecho.
  float v;
  uint32_t movidas = 0;
  while (movidas < 2048) {
    // Se comparan con resta con signo y no con == : si por lo que sea un
    // vertice quedo atras, se descarta en vez de trabar la cola para siempre.
    Vertice ev;
    while (evPeek(&ev) && (int32_t)(consumidas - ev.idx) >= 0) {
      if (ev.idx == consumidas) {
        binEnviar();                     // cerrar el paquete de la rampa anterior
        rampaAct  = ev.rampa;
        bajadaAct = ev.bajada != 0;
        binFlags |= FLAG_VERTICE;
      }
      evPop();
    }
    if (!ringPop(&v)) break;
    consumidas++;
    movidas++;
    if (g_bin) binAgregar(v);
  }

  if (!g_bin) {
    static uint32_t t_rep = 0;
    if (millis() - t_rep >= 2000) {
      Serial.printf("muestras %lu | rampas %lu | rampa %lu us | ovfDMA %lu | ovfRing %lu\n",
                    (unsigned long)g_muestras, (unsigned long)g_rampa,
                    (unsigned long)g_rampaUltUs, (unsigned long)g_ovfDma,
                    (unsigned long)g_ovfRing);
      t_rep = millis();
    }
  }
}
