// ===========================================================================
//  GPRv3 - Adquisicion con sincronismo
//
//  Muestrea el PCM1808 por I2S, diezma y manda el batido por USB en paquetes
//  binarios. La cuadrada de sincronismo del generador de triangular entra por
//  PIN_SYNC: cada flanco se ubica sobre el eje de muestras y sale como un
//  paquete aparte. La PC corta las rampas con eso. Ver GPRv3/README.md.
//
//  Comandos (una linea de texto, terminada en Enter):
//      run          emite en binario (lo que usa la PC)
//      texto        emite "batido,sync" en texto, para el Serial Plotter
//      stop         corta la emision
//      sps 12000    muestras/s de salida: 3000, 6000, 12000 o 24000
//      info         informa la configuracion
//
//  COMPILAR con la placa "Nologo ESP32C3 Super Mini" (USB CDC On Boot
//  habilitado). compilar.bat lo hace con arduino-cli.
//
//  Pines:
//      GPIO4 -> SCK  del modulo = master clock, 256*fs
//      GPIO5 -> BCK  bit clock, 64*fs
//      GPIO6 -> LRC  word select, = fs
//      GPIO7 <- OUT  datos
//      PIN_SYNC <- cuadrada de sincronismo (maximo 3,3 V)
// ===========================================================================

#include <Arduino.h>
#include "driver/i2s_std.h"
#include "driver/gpio.h"
#include "esp_timer.h"
#include "nucleo.h"

#define PIN_MCLK  4
#define PIN_BCLK  5
#define PIN_LRCK  6
#define PIN_DIN   7
#define PIN_SYNC 10       // <- cambiar aca si el sync esta en otro GPIO

#define FS             48000   // fija: sale exacta del PLL
#define SPS_DEF        12000
#define BLOQUE           256   // tramas por bloque de DMA
#define WARMUP_MS        150
#define ANTIRREBOTE_US  2000   // la rampa mas corta dura 10 ms
#define TX_BUFFER       8192
#define ESTADO_MS       1000
#define NIVEL_TEXTO  2000000   // altura del sync en el modo texto

enum { PARADO, BINARIO, TEXTO };

static i2s_chan_handle_t rx = nullptr;
static int32_t  buf[BLOQUE * 2];            // L,R intercalados
static uint8_t  paq[PAQ_MAX];
static diezmador_t g_diez;

static uint32_t g_dec  = FS / SPS_DEF;
static uint8_t  g_modo = PARADO;
static uint32_t g_n_out = 0;                // indice de la proxima muestra de salida
static uint32_t g_seq0 = 0;                 // bloque donde arranco el diezmador
static uint32_t g_seq_ant = 0;

static uint32_t g_descartados = 0;          // paquetes que no entraron al USB
static uint32_t g_errores = 0;              // lecturas de I2S fallidas
static uint32_t g_flancos = 0;

// --- Instante de cada bloque de DMA ----------------------------------------
//
// El instante se toma en la interrupcion de fin de bloque y no al volver de
// i2s_channel_read(): si el lazo viene atrasado, la lectura devuelve un
// bloque viejo y el reloj de "ahora" no es el suyo. Los bloques se leen en
// el mismo orden en que terminan, asi que el k-esimo leido es el k-esimo de
// la interrupcion, mas los que el driver haya descartado por desborde.

#define N_TS 16
static volatile int64_t  g_ts[N_TS];
static volatile uint32_t g_rx_seq = 0;
static volatile uint32_t g_desbordes = 0;
static uint32_t g_leidos = 0;

static bool IRAM_ATTR alRecibir(i2s_chan_handle_t, i2s_event_data_t *, void *) {
  g_ts[g_rx_seq & (N_TS - 1)] = esp_timer_get_time();
  g_rx_seq = g_rx_seq + 1;
  return false;
}

static bool IRAM_ATTR alDesbordar(i2s_chan_handle_t, i2s_event_data_t *, void *) {
  g_desbordes = g_desbordes + 1;
  return false;
}

// --- Flancos del sync -------------------------------------------------------

#define N_FLANCOS 16
typedef struct { int64_t t; uint8_t nivel; } flanco_t;
static volatile flanco_t g_fl[N_FLANCOS];
static volatile uint8_t  g_fl_w = 0;
static uint8_t           g_fl_r = 0;
static volatile int64_t  g_t_ult = 0;

static void IRAM_ATTR isrSync() {
  int64_t t = esp_timer_get_time();
  if (t - g_t_ult < ANTIRREBOTE_US) return;
  g_t_ult = t;
  uint8_t i = g_fl_w & (N_FLANCOS - 1);
  g_fl[i].t = t;
  g_fl[i].nivel = (uint8_t)gpio_get_level((gpio_num_t)PIN_SYNC);
  g_fl_w = g_fl_w + 1;
}

// Flancos ya ubicados, para dibujar el nivel en el modo texto.
#define N_PEND 8
static struct { uint32_t idx; uint8_t nivel; } g_pend[N_PEND];
static uint8_t g_pend_w = 0, g_pend_r = 0;
static uint8_t g_nivel = 0;

// --- Salida -----------------------------------------------------------------

// El paquete entra entero o no entra: nunca se bloquea el lazo esperando al
// USB ni se manda un paquete por la mitad. La PC ve el hueco por el indice.
static bool enviar(size_t n) {
  if ((size_t)Serial.availableForWrite() < n) {
    g_descartados++;
    return false;
  }
  Serial.write(paq, n);
  return true;
}

static void decir(const char *s) {
  if (g_modo == BINARIO) {
    enviar(paqTexto(paq, s));
  } else {
    Serial.print("# ");
    Serial.println(s);
  }
}

static void informar() {
  if (g_modo == BINARIO) {
    enviar(paqInfo(paq, FS, (uint16_t)g_dec, PIN_SYNC, BLOQUE));
    return;
  }
  Serial.printf("# GPRv3 protocolo %d: fs %d Hz, dec %lu, salida %lu sps, "
                "sync en GPIO%d\n", PROTO_VERSION, FS, (unsigned long)g_dec,
                (unsigned long)(FS / g_dec), PIN_SYNC);
}

// --- I2S ---------------------------------------------------------------------

static bool leerBloque(int64_t *t_bloque, uint32_t *seq) {
  size_t bytes = 0;
  if (i2s_channel_read(rx, buf, sizeof(buf), &bytes, 100) != ESP_OK ||
      bytes != sizeof(buf)) {
    return false;
  }
  uint32_t s = g_leidos + g_desbordes;
  g_leidos++;
  *t_bloque = g_ts[s & (N_TS - 1)];
  *seq = s;
  return true;
}

static bool i2sArrancar() {
  if (rx) {
    i2s_channel_disable(rx);
    i2s_del_channel(rx);
    rx = nullptr;
  }

  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
  cc.dma_desc_num  = 6;
  cc.dma_frame_num = BLOQUE;
  cc.auto_clear    = false;
  if (i2s_new_channel(&cc, nullptr, &rx) != ESP_OK) return false;

  i2s_std_config_t sc = {};
  sc.clk_cfg.sample_rate_hz = FS;
  sc.clk_cfg.clk_src        = I2S_CLK_SRC_DEFAULT;
  sc.clk_cfg.mclk_multiple  = I2S_MCLK_MULTIPLE_256;
  // Slots de 32 bits: el PCM1808 esclavo acepta 64 o 48 BCK por trama, nunca
  // 32. La muestra de 24 bits llega alineada al MSB (>>8 en el lazo).
  sc.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,
                                                    I2S_SLOT_MODE_STEREO);
  sc.gpio_cfg.mclk = (gpio_num_t)PIN_MCLK;
  sc.gpio_cfg.bclk = (gpio_num_t)PIN_BCLK;
  sc.gpio_cfg.ws   = (gpio_num_t)PIN_LRCK;
  sc.gpio_cfg.dout = I2S_GPIO_UNUSED;
  sc.gpio_cfg.din  = (gpio_num_t)PIN_DIN;
  if (i2s_channel_init_std_mode(rx, &sc) != ESP_OK) return false;

  i2s_event_callbacks_t cb = {};
  cb.on_recv       = alRecibir;
  cb.on_recv_q_ovf = alDesbordar;
  if (i2s_channel_register_event_callback(rx, &cb, nullptr) != ESP_OK) return false;

  g_rx_seq = 0;
  g_desbordes = 0;
  g_leidos = 0;
  if (i2s_channel_enable(rx) != ESP_OK) return false;

  // El PCM1808 arranca en mute y hace fade-in: los primeros ms son basura.
  uint32_t t = millis();
  int64_t tb;
  uint32_t seq = 0;
  while (millis() - t < WARMUP_MS) leerBloque(&tb, &seq);

  diezmadorIniciar(&g_diez, g_dec);
  g_seq0 = seq + 1;
  g_seq_ant = seq;
  g_n_out = 0;
  g_fl_r = g_fl_w;
  g_pend_r = g_pend_w;
  return true;
}

// --- Consola -----------------------------------------------------------------

static void comando(const char *s) {
  if (!strcmp(s, "run")) {
    g_modo = BINARIO;
    informar();
  } else if (!strcmp(s, "texto")) {
    g_modo = TEXTO;
    informar();
    if (FS / g_dec > 6000) {
      Serial.println("# aviso: en texto conviene 'sps 6000' o menos");
    }
  } else if (!strcmp(s, "stop")) {
    g_modo = PARADO;
    Serial.println("# stop");
  } else if (!strcmp(s, "info")) {
    informar();
  } else if (!strncmp(s, "sps ", 4)) {
    uint32_t sps = strtoul(s + 4, nullptr, 10);
    if (sps != 3000 && sps != 6000 && sps != 12000 && sps != 24000) {
      decir("sps tiene que ser 3000, 6000, 12000 o 24000");
      return;
    }
    // Reiniciar el I2S se come el warm-up del PCM1808: se corta la emision
    // en vez de dejar un agujero en el medio de una captura.
    g_modo = PARADO;
    g_dec = FS / sps;
    if (!i2sArrancar()) Serial.println("# ERROR: no arranco el I2S");
    informar();
  } else {
    decir("comandos: run | texto | stop | sps N | info");
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
  Serial.setTxBufferSize(TX_BUFFER);
  Serial.begin(115200);
  delay(300);
  Serial.println("# GPRv3 adquisicion con sincronismo");
  // PULLDOWN: con el pin al aire, el ruido del USB dispara la interrupcion.
  pinMode(PIN_SYNC, INPUT_PULLDOWN);
  attachInterrupt(PIN_SYNC, isrSync, CHANGE);
  if (!i2sArrancar()) Serial.println("# ERROR: no arranco el I2S");
  informar();
  Serial.println("# comandos: run | texto | stop | sps N | info");
}

void loop() {
  leerConsola();

  // Se lee siempre, aunque no se emita, para que el DMA no desborde.
  int64_t  t_bloque;
  uint32_t seq;
  if (!leerBloque(&t_bloque, &seq)) {
    g_errores++;
    i2sArrancar();
    return;
  }
  // Bloques que el driver descarto: el indice de salida avanza igual, asi el
  // eje de muestras sigue siendo el del reloj y la PC ve el hueco.
  g_n_out += (seq - g_seq_ant - 1) * (BLOQUE / g_dec);
  g_seq_ant = seq;
  int64_t n_in_ult = (int64_t)(seq - g_seq0 + 1) * BLOQUE - 1;

  // Los flancos van ANTES que las muestras del bloque: por el retardo del
  // filtro caen ~12 muestras de salida mas adelante que el momento en que
  // llegaron, o sea que algunos tocan muestras de este mismo bloque.
  while (g_fl_r != g_fl_w) {
    uint8_t i = g_fl_r & (N_FLANCOS - 1);
    int64_t tf = g_fl[i].t;
    uint8_t nivel = g_fl[i].nivel;
    g_fl_r++;
    g_flancos++;
    int64_t idx256 = indiceFlanco256(n_in_ult, t_bloque, tf, FS, g_dec);
    if (idx256 < 0) continue;
    if (g_modo == BINARIO) {
      enviar(paqSync(paq, idx256, nivel, (uint32_t)tf));
    }
    g_pend[g_pend_w & (N_PEND - 1)].idx = (uint32_t)(idx256 >> 8);
    g_pend[g_pend_w & (N_PEND - 1)].nivel = nivel;
    g_pend_w++;
  }

  uint32_t idx0 = g_n_out;
  uint16_t n = 0;
  if (g_modo == BINARIO) paqDatosAbrir(paq, idx0);
  for (uint32_t i = 0; i < BLOQUE; i++) {
    int32_t muestra;
    if (!diezmar(&g_diez, buf[2 * i] >> 8, &muestra)) continue;
    while (g_pend_r != g_pend_w &&
           (int32_t)(g_n_out - g_pend[g_pend_r & (N_PEND - 1)].idx) >= 0) {
      g_nivel = g_pend[g_pend_r & (N_PEND - 1)].nivel;
      g_pend_r++;
    }
    if (g_modo == BINARIO) {
      paqDatosAgregar(paq, n++, muestra);
    } else if (g_modo == TEXTO && Serial.availableForWrite() >= 32) {
      Serial.printf("%ld,%ld\n", (long)muestra,
                    (long)(g_nivel ? NIVEL_TEXTO : 0));
    }
    g_n_out++;
  }
  if (g_modo == BINARIO && n) enviar(paqDatosCerrar(paq, n));

  static uint32_t t_estado = 0;
  if (g_modo == BINARIO && millis() - t_estado >= ESTADO_MS) {
    t_estado = millis();
    enviar(paqEstado(paq, g_desbordes, g_descartados, g_flancos, g_errores));
  }
}
