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
//  Ademas, una vez por bloque de DMA sale una linea "#v,<adc>,<indice>" con
//  una lectura del ADC de la triangular que ataca al VCO (GPIO3, por divisor
//  4k7/4k7). El indice es la muestra de batido a la que corresponde, para
//  poder alinearlas. Sirve para recuperar los limites de rampa cuando el
//  generador no da sync; con sync conectado es redundante pero no molesta.
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
#include <string.h>   // memset, para reiniciar el filtro de diezmado
#include "driver/i2s_std.h"
#include "esp_timer.h"

#define PIN_MCLK  4
#define PIN_BCLK  5
#define PIN_LRCK  6
#define PIN_DIN   7
#define PIN_SYNC 10   // <- sync del generador, por divisor 10k/15k (3.00 V)
// <- triangular del generador, por divisor 4k7/4k7. Los 3 V se dividen a 1,5,
// que cae en el medio del rango util del ADC del C3 (~0 a 2,5 V con la
// atenuacion por defecto); a 3 V pelados el ADC se vuelve no lineal cerca del
// riel. El divisor tambien baja la impedancia de fuente a 2,35 kohm, que es
// lo que el ADC necesita ver para muestrear bien.
#define PIN_TRI   3

#define FS_DEF        48000   // uno de los "exactos" del PLL (16/32/48 kHz)
#define FS_MIN         8000   // minimo absoluto del PCM1808
#define FS_MAX        96000   // maximo absoluto del PCM1808
// Muestras/s que salen por serie, con cualquier fs. Elegido para las
// mediciones reales de laboratorio con rampa de 20 ms (ver GPRv2/CLAUDE.md):
// 6000 da Nyquist en 3000 Hz (el blanco a 5 m da 1732 Hz, con margen), 120
// muestras por rampa, y ~78 kB/s con dos columnas - comodo frente al techo
// de ~100 kB/s del CDC y lejos de los ~128 kB/s donde ya empieza a desbordar.
// Tiene que dividir a FS_DEF exacto (48000/6000=8) o "dec" trunca y la
// salida real no coincide con este numero.
#define SPS_SALIDA     6000
#define BLOCK_FRAMES    256
#define WARMUP_MS       150

static i2s_chan_handle_t rx = nullptr;
static int32_t  buf[BLOCK_FRAMES * 2];      // L,R intercalados

static uint32_t g_fs  = FS_DEF;
static uint32_t g_dec = FS_DEF / SPS_SALIDA;
static bool     g_run = false;

static int32_t  accL = 0;
static uint32_t accN = 0;
static uint32_t n_emitidas = 0;   // indice absoluto de muestra emitida

// ---------------------------------------------------------------------------
//  Diezmado con filtro antialias
//
//  Antes se diezmaba promediando 'dec' muestras. Como filtro antialias eso es
//  muy pobre: a 48 kHz y dec 8, un tono de 5 kHz se pliega sobre 1 kHz de la
//  salida atenuado apenas 14 dB, y uno de 4,5 kHz sobre 1,5 kHz atenuado 10.
//  Todo lo que haya entre 3 y 24 kHz entra casi sin tocarse. Medido sobre el
//  banco (2026-09-04) hay energia hasta el Nyquist mismo, que es la firma de
//  que algo se esta plegando.
//
//  En su lugar va una cascada de filtros de SEMIBANDA, uno por cada division
//  por dos: 48k -> 24k -> 12k -> 6k. Semibanda quiere decir que corta justo en
//  la mitad de su Nyquist y que la mitad de los coeficientes son cero exactos
//  (14 de 31 aca), asi que sale barato. Y como cada etapa solo calcula la
//  mitad de las salidas, el costo total es ~1,3 M multiplicaciones por segundo
//  a 48 kHz: alrededor del 7 % del micro.
//
//  Rechazo de alias medido (simulando esta misma aritmetica entera):
//
//      f de salida    promedio de 8    esta cascada
//         500 Hz         -20,7 dB        -90,5 dB
//        1000 Hz         -14,2 dB        -87,4 dB
//        2000 Hz          -7,6 dB        -71,1 dB
//
//  Arriba de 2400 Hz el rechazo se degrada (es la transicion de la ultima
//  etapa, simetrica alrededor de 3000): la banda limpia es 0 a 2400 Hz, que
//  con 347 Hz por metro son 6,9 m. El rizado en la banda util es 0,004 dB.
//
//  Coeficientes en Q30 (x 2^30). La suma da 2^30 EXACTO para que la ganancia
//  en continua sea 1 y el nivel no cambie.
// ---------------------------------------------------------------------------

#define HB_TAPS 31
#define HB_Q    30
static const int32_t HB[HB_TAPS] = {
    -135143,         0,   1143002,         0,  -4050661,         0,
   10527053,         0, -23184129,         0,  47232807,         0,
  -99955210,         0, 336873039, 536840308, 336873039,         0,
  -99955210,         0,  47232807,         0, -23184129,         0,
   10527053,         0,  -4050661,         0,   1143002,         0,
    -135143
};

typedef struct {
  int32_t z[HB_TAPS];
  uint8_t idx;     // proxima posicion a escribir = la mas vieja
  uint8_t fase;    // se emite una salida cada dos entradas
} etapa_t;

#define MAX_ETAPAS 5
static etapa_t  g_etapa[MAX_ETAPAS];
static uint8_t  g_n_etapas = 0;   // 0 = sin FIR, se usa el promedio de antes
static uint32_t g_retardo  = 0;   // retardo del filtro, en muestras de salida

// Empuja una muestra en una etapa. Devuelve true (y deja el resultado en *y)
// una vez cada dos.
static inline bool hbEmpujar(etapa_t *e, int32_t x, int32_t *y) {
  e->z[e->idx] = x;
  if (++e->idx == HB_TAPS) e->idx = 0;
  e->fase ^= 1;
  if (e->fase) return false;

  // La muestra mas vieja es la que esta en idx (la que se va a pisar), y le
  // toca el ultimo coeficiente. De ahi se camina hacia adelante en el tiempo.
  int64_t acc = 0;
  uint8_t k = e->idx;
  for (int8_t j = HB_TAPS - 1; j >= 0; j--) {
    if (HB[j]) acc += (int64_t)e->z[k] * HB[j];   // la mitad son cero
    if (++k == HB_TAPS) k = 0;
  }
  // No desborda: la muestra es de 24 bits (2^23) y la suma de |coef| ronda
  // 2^30, o sea el acumulador queda cerca de 2^53 contra los 2^63 del int64.
  *y = (int32_t)(acc >> HB_Q);
  return true;
}

static void filtroReiniciar(uint32_t dec) {
  memset(g_etapa, 0, sizeof(g_etapa));
  accL = 0;
  accN = 0;

  // Una etapa por cada division por dos. Si dec no es potencia de dos no hay
  // cascada posible y se cae al promedio de antes, avisando.
  uint32_t d = dec;
  g_n_etapas = 0;
  while ((d & 1) == 0 && d > 1 && g_n_etapas < MAX_ETAPAS) {
    d >>= 1;
    g_n_etapas++;
  }
  if (d != 1) g_n_etapas = 0;

  // Retardo de grupo. Cada etapa retrasa HB_TAPS/2 muestras DE SU PROPIA
  // entrada, o sea 15, 30, 60... referidas a la entrada de 48 kHz: en total
  // 15*(dec-1). En muestras de salida son 15*(dec-1)/dec, 13 para dec 8.
  // Hay que informarlo porque la lectura de la triangular se toma en tiempo
  // real y la de batido sale retrasada: sin corregirlo, los limites de rampa
  // quedan corridos 2,2 ms, que es el 11 % de una rampa de 20 ms.
  g_retardo = g_n_etapas
            ? ((HB_TAPS / 2) * (dec - 1) + dec / 2) / dec
            : 0;
}

// Mete una muestra cruda y devuelve true cuando sale una diezmada.
static inline bool diezmar(int32_t x, int32_t *y) {
  if (g_n_etapas == 0) {
    accL += x;
    if (++accN < g_dec) return false;
    *y = accL / (int32_t)g_dec;
    accL = 0;
    accN = 0;
    return true;
  }
  int32_t v = x;
  for (uint8_t e = 0; e < g_n_etapas; e++) {
    if (!hbEmpujar(&g_etapa[e], v, &v)) return false;
  }
  *y = v;
  return true;
}

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
  filtroReiniciar(g_dec);
  n_emitidas = 0;
  return true;
}

// ---------------------------------------------------------------------------

static void informar() {
  Serial.printf("# fs = %lu Hz, dec = %lu, salida = %lu sps\n",
                (unsigned long)g_fs, (unsigned long)g_dec,
                (unsigned long)(g_fs / g_dec));
  // El retardo lo tiene que saber la PC: vivo.py lleva su propio contador de
  // filas y le suma esto para ubicar la triangular. Se emite siempre, y en
  // 0 cuando no hay filtro, asi el que lo lee no necesita saber cual es cual.
  Serial.printf("# retardo = %lu muestras\n", (unsigned long)g_retardo);
  if (g_n_etapas) {
    Serial.printf("# antialias: %u etapas de semibanda, banda limpia 0 a "
                  "%lu Hz\n", g_n_etapas,
                  (unsigned long)(g_fs / g_dec * 2 / 5));
  } else {
    Serial.printf("# aviso: dec = %lu no es potencia de 2, se diezma "
                  "promediando y el alias entra casi sin atenuar\n",
                  (unsigned long)g_dec);
  }
  // 16/32/48 kHz salen exactas del divisor fraccionario del PLL de 160 MHz;
  // el resto tiene error, chico pero no nulo.
  if (g_fs != 16000 && g_fs != 32000 && g_fs != 48000) {
    Serial.println("# aviso: fs no exacta, solo 16000/32000/48000 lo son");
  }
}

static void comando(const char *s) {
  if (!strcmp(s, "run")) {
    g_run = true;
    n_emitidas = 0;
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
  // PULLDOWN, no INPUT a secas: con el pin al aire la rafaga de USB de cada
  // bloque de DMA se acopla y dispara la ISR. Se ve clarisimo porque las
  // distancias entre "flancos" salen todas multiplos de 32, que son las
  // muestras que emite un bloque. Con el divisor conectado el pulldown
  // interno (~45k) queda en paralelo con la pata de abajo: con 10k/15k la
  // tension baja de 3,00 a 2,65 V, todavia sobre el umbral de 2,48 pero
  // justo. Si el sync aparece, mejor 10k/22k, que con el pulldown da 2,98 V.
  pinMode(PIN_SYNC, INPUT_PULLDOWN);
  attachInterrupt(PIN_SYNC, isrSync, RISING);
  analogReadResolution(12);   // la atenuacion queda en la maxima por defecto
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

  // La triangular se lee ACA, pegada al timestamp del bloque, y se emite
  // recien al final: asi el instante de la lectura coincide con el de la
  // ultima muestra del bloque, que es la que se le adjudica. Emitirla antes
  // de leerla costaria el tiempo de escribir el bloque entero por USB, que
  // son ~1 ms, o sea un 3% del periodo de la triangular.
  int tri = analogRead(PIN_TRI);

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
    // valor con signo.
    int32_t muestra;
    if (!diezmar(buf[2 * i] >> 8, &muestra)) continue;

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
      Serial.printf("%ld,%ld\n", (long)muestra, desde);
      n_emitidas++;
    }
  }

  // La lectura de la triangular se emite recien aca. Se tomo pegada a
  // t_bloque, o sea AHORA, pero la muestra de batido que sale ahora
  // corresponde a un instante g_retardo muestras anterior, por el filtro de
  // diezmado. La que de verdad coincide con esta lectura todavia no salio:
  // es la n_emitidas-1+g_retardo, y ese es el indice que se informa.
  if (g_run && n_emitidas) {
    Serial.printf("#v,%d,%lu\n", tri,
                  (unsigned long)(n_emitidas - 1 + g_retardo));
  }
}
