// ===========================================================================
//  GPRv2 - Adquisicion
//
//  Muestrea el PCM1808 por I2S y manda las muestras diezmadas por USB serie,
//  en texto, para mirarlas con el Serial Plotter o Telemetry Viewer.
//
//  Comandos (una linea, terminada en Enter):
//      run          empieza a emitir
//      stop         corta la emision
//      fs           informa la fs actual
//      fs 48000     la cambia (8000 a 96000)
//
//  Salida: "L,sync" por linea (CSV). L en cuentas del ADC (+-8388607);
//  sync = muestras transcurridas desde el ultimo flanco de subida en GPIO10,
//  o -1 si todavia no llego ninguno. Se ve como diente de sierra en el
//  plotter y da la fase dentro de la rampa en cada muestra.
//
//  El canal derecho se lee (el PCM1808 obliga a tramas estereo) pero no se
//  emite: VINR esta al aire y esos bytes son caudal tirado.
//  Las respuestas a los comandos van con '#' adelante.
//
//  COMPILAR con la placa "Nologo ESP32C3 Super Mini", o con "ESP32C3 Dev
//  Module" y USB CDC On Boot = Enabled. Si no, Serial apunta a UART0
//  (GPIO20/21) y no sale nada por USB aunque el programa corra bien.
//
//  Pines (ver docs/conexionado.md):
//      GPIO4 -> SCK  del modulo = SCKI / master clock, 256*fs
//      GPIO5 -> BCK  bit clock, 64*fs
//      GPIO6 -> LRC  word select, = fs
//      GPIO7 <- OUT  datos (DOUT)
// ===========================================================================

#include <Arduino.h>
#include "driver/i2s_std.h"
#include "esp_timer.h"

#define PIN_MCLK  4
#define PIN_BCLK  5
#define PIN_LRCK  6
#define PIN_DIN   7
#define PIN_SYNC 10   // <- sync del generador, por divisor 10k/15k (3.00 V)

#define FS_DEF        16000
#define FS_MIN         8000   // minimo absoluto del PCM1808
#define FS_MAX        96000   // maximo absoluto del PCM1808
// Muestras/s que salen por serie, con cualquier fs. 4000 da Nyquist en
// 2000 Hz, contra los 1096 Hz del blanco lejano a 10 ms de rampa, y unos
// 52 kB/s con dos columnas: comodo frente al techo del CDC.
#define SPS_SALIDA     4000
#define BLOCK_FRAMES    256
#define WARMUP_MS       150

static i2s_chan_handle_t rx = nullptr;
static int32_t  buf[BLOCK_FRAMES * 2];      // L,R intercalados

static uint32_t g_fs  = FS_DEF;
static uint32_t g_dec = FS_DEF / SPS_SALIDA;
static bool     g_run = false;

static int32_t  accL = 0;
static uint32_t accN = 0;

// Microsegundos del ultimo flanco de subida del sync. Se guarda el instante
// y no un contador de muestras porque el DMA entrega 256 tramas de golpe y
// el lazo las procesa en rafaga: dentro de esa rafaga no hay tiempo real, y
// leer el pin ahi ubicaria el flanco en cualquier lado del bloque (16 ms a
// 16 kHz). Con el timestamp, cada muestra sabe su distancia real al flanco.
// Se guarda un anillo de los ultimos flancos, no uno solo ni dos. Un bloque
// de DMA trae BLOCK_FRAMES/fs segundos de muestras (16 ms a 16 kHz) y en ese
// rato pueden entrar VARIOS flancos: con rampas de 10 ms entran dos. A cada
// muestra emitida le corresponde el ultimo flanco ANTERIOR a ella, que no
// tiene por que ser el mas nuevo del anillo. Con dos slots esto fallaba y
// salian cuentas negativas y rampas de largo cambiante.
// 8 slots cubren rampas de hasta BLOCK_FRAMES/(8*fs), o sea 2 ms a 16 kHz.
#define N_FLANCOS 8
static volatile int64_t t_flancos[N_FLANCOS] = {0};
static volatile uint8_t i_flanco = 0;

static void IRAM_ATTR isrSync() {
  uint8_t i = (i_flanco + 1) & (N_FLANCOS - 1);
  t_flancos[i] = esp_timer_get_time();
  i_flanco = i;
}

// ---------------------------------------------------------------------------

static bool i2sArrancar(uint32_t fs) {
  if (rx) {
    i2s_channel_disable(rx);
    i2s_del_channel(rx);
    rx = nullptr;
  }

  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  cc.dma_desc_num  = 6;
  cc.dma_frame_num = BLOCK_FRAMES;
  cc.auto_clear    = false;
  if (i2s_new_channel(&cc, nullptr, &rx) != ESP_OK) {
    Serial.println("# ERROR: i2s_new_channel");
    return false;
  }

  i2s_std_config_t sc = {};
  sc.clk_cfg.sample_rate_hz = fs;
  sc.clk_cfg.clk_src        = I2S_CLK_SRC_DEFAULT;
  sc.clk_cfg.mclk_multiple  = I2S_MCLK_MULTIPLE_256;

  // Slots de 32 bits, no de 24: el PCM1808 en modo esclavo acepta 64 o 48 BCK
  // por trama, nunca 32. Estereo x 32 bits da 64 BCK exactos. La muestra de
  // 24 bits llega alineada al MSB y se recupera con el >>8 del lazo.
  sc.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,
                                                    I2S_SLOT_MODE_STEREO);

  sc.gpio_cfg.mclk = (gpio_num_t)PIN_MCLK;
  sc.gpio_cfg.bclk = (gpio_num_t)PIN_BCLK;
  sc.gpio_cfg.ws   = (gpio_num_t)PIN_LRCK;
  sc.gpio_cfg.dout = I2S_GPIO_UNUSED;
  sc.gpio_cfg.din  = (gpio_num_t)PIN_DIN;

  if (i2s_channel_init_std_mode(rx, &sc) != ESP_OK) {
    Serial.println("# ERROR: i2s_channel_init_std_mode");
    return false;
  }
  if (i2s_channel_enable(rx) != ESP_OK) {
    Serial.println("# ERROR: i2s_channel_enable");
    return false;
  }

  // El PCM1808 arranca en mute y hace fade-in: los primeros ms son basura.
  uint32_t t = millis();
  size_t   n;
  while (millis() - t < WARMUP_MS) {
    i2s_channel_read(rx, buf, sizeof(buf), &n, 100);
  }

  g_fs  = fs;
  g_dec = fs / SPS_SALIDA;
  accL  = 0;
  accN  = 0;
  return true;
}

// ---------------------------------------------------------------------------

static void informar() {
  Serial.printf("# fs = %lu Hz, dec = %lu, salida = %lu sps\n",
                (unsigned long)g_fs, (unsigned long)g_dec,
                (unsigned long)(g_fs / g_dec));
  // 16/32/48 kHz salen exactas del divisor fraccionario del PLL de 160 MHz;
  // el resto tiene error, chico pero no nulo.
  if (g_fs != 16000 && g_fs != 32000 && g_fs != 48000) {
    Serial.println("# aviso: fs no exacta, solo 16000/32000/48000 lo son");
  }
}

static void comando(const char *s) {
  if (!strcmp(s, "run")) {
    g_run = true;
  } else if (!strcmp(s, "stop")) {
    g_run = false;
    Serial.println("# stop");
  } else if (!strcmp(s, "fs")) {
    informar();
  } else if (!strncmp(s, "fs ", 3)) {
    uint32_t f = strtoul(s + 3, nullptr, 10);
    if (f < FS_MIN || f > FS_MAX) {
      Serial.printf("# fs fuera de rango (%d a %d)\n", FS_MIN, FS_MAX);
      return;
    }
    // Reiniciar el I2S se come el warm-up del PCM1808, asi que cortamos la
    // emision en vez de dejar un agujero en el medio de una captura.
    g_run = false;
    if (i2sArrancar(f)) informar();
  } else {
    Serial.println("# comandos: run | stop | fs [Hz]");
  }
}

static void leerConsola() {
  static char linea[32];
  static uint8_t n = 0;

  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (n) {
        linea[n] = 0;
        n = 0;
        comando(linea);
      }
    } else if (n < sizeof(linea) - 1) {
      linea[n++] = c;
    }
  }
}

// ---------------------------------------------------------------------------

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("# GPRv2 adquisicion");
  pinMode(PIN_SYNC, INPUT);   // el 15k del divisor ya lo mantiene abajo
  attachInterrupt(PIN_SYNC, isrSync, RISING);
  if (i2sArrancar(FS_DEF)) informar();
  Serial.println("# comandos: run | stop | fs [Hz]");
}

void loop() {
  leerConsola();

  // Se lee siempre, aunque no se emita, para que el ring del DMA no desborde
  // y para que 'run' arranque con muestras frescas.
  size_t bytes = 0;
  if (i2s_channel_read(rx, buf, sizeof(buf), &bytes, 100) != ESP_OK) return;
  int64_t t_bloque = esp_timer_get_time();
  uint32_t frames = bytes / (2 * sizeof(int32_t));

  // Copia del anillo. Si el indice no cambio entre antes y despues, no entro
  // ningun flanco mientras copiabamos y la foto es consistente. Hace falta
  // porque son 64 bits sobre un micro de 32 y la ISR puede partir una lectura.
  int64_t fl[N_FLANCOS];
  uint8_t iv, iv2;
  do {
    iv = i_flanco;
    for (uint8_t k = 0; k < N_FLANCOS; k++) fl[k] = t_flancos[k];
    iv2 = i_flanco;
  } while (iv != iv2);

  for (uint32_t i = 0; i < frames; i++) {
    // 24 bits alineados al MSB dentro de 32 -> el shift aritmetico da el
    // valor con signo. El acumulador no desborda: dec llega como mucho a 48
    // (fs 96k), y 48 * 2^23 entra holgado en int32.
    accL += buf[2 * i] >> 8;
    if (++accN < g_dec) continue;

    if (g_run) {
      int64_t t_m = t_bloque - (int64_t)(frames - 1 - i) * 1000000 / g_fs;
      // El anillo esta ordenado en el tiempo: se camina del mas nuevo hacia
      // atras y el primero que no sea posterior a esta muestra es el suyo.
      int64_t ref = 0;
      for (uint8_t k = 0; k < N_FLANCOS; k++) {
        int64_t c = fl[(iv - k) & (N_FLANCOS - 1)];
        if (c != 0 && c <= t_m) { ref = c; break; }
      }
      long desde = (ref == 0) ? -1 : (long)(((t_m - ref) * g_fs) / 1000000);
      Serial.printf("%ld,%ld\n", (long)(accL / (int32_t)g_dec), desde);
    }
    accL = 0;
    accN = 0;
  }
}
