// ===========================================================================
//  GPRv3 - Nucleo del firmware: diezmado, ubicacion de flancos y paquetes.
//
//  C puro, sin nada de Arduino ni del ESP32, para poder compilarlo tambien en
//  la PC (firmware/prueba_pc/) y probarlo contra el decodificador de Python.
//  El formato de los paquetes esta descripto en GPRv3/README.md.
// ===========================================================================
#ifndef GPR_NUCLEO_H
#define GPR_NUCLEO_H

#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>

// --- Diezmado: cascada de filtros de semibanda (el mismo de GPRv2) ----------

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
  uint8_t fase;    // sale una muestra cada dos entradas
} etapa_t;

#define MAX_ETAPAS 4

typedef struct {
  etapa_t etapa[MAX_ETAPAS];
  uint8_t n_etapas;
} diezmador_t;

static inline bool hbEmpujar(etapa_t *e, int32_t x, int32_t *y) {
  e->z[e->idx] = x;
  if (++e->idx == HB_TAPS) e->idx = 0;
  e->fase ^= 1;
  if (e->fase) return false;

  int64_t acc = 0;
  uint8_t k = e->idx;
  for (int8_t j = HB_TAPS - 1; j >= 0; j--) {
    if (HB[j]) acc += (int64_t)e->z[k] * HB[j];
    if (++k == HB_TAPS) k = 0;
  }
  *y = (int32_t)(acc >> HB_Q);
  return true;
}

// dec tiene que ser potencia de 2 entre 2 y 16. Devuelve false si no lo es.
static inline bool diezmadorIniciar(diezmador_t *d, uint32_t dec) {
  memset(d, 0, sizeof(*d));
  uint8_t n = 0;
  while (dec > 1 && (dec & 1) == 0 && n < MAX_ETAPAS) { dec >>= 1; n++; }
  if (dec != 1 || n == 0) return false;
  d->n_etapas = n;
  return true;
}

static inline bool diezmar(diezmador_t *d, int32_t x, int32_t *y) {
  int32_t v = x;
  for (uint8_t e = 0; e < d->n_etapas; e++) {
    if (!hbEmpujar(&d->etapa[e], v, &v)) return false;
  }
  *y = v;
  return true;
}

// --- Donde cae un flanco del sync, en muestras de SALIDA --------------------
//
// n_in_ult: indice de la ultima trama de entrada del bloque (la primera
//           despues de iniciar el diezmador es la 0).
// t_bloque: instante en que termino ese bloque [us].
// t_flanco: instante del flanco [us].
//
// La salida m de la cascada sale al entrar la trama dec*m + dec-1 y, por el
// retardo de grupo de las etapas (15 muestras de su propia entrada cada una),
// corresponde al instante de la trama dec*m - 14*(dec-1). De ahi el termino
// que se suma. Devuelve el indice de salida multiplicado por 256.
static inline int64_t indiceFlanco256(int64_t n_in_ult, int64_t t_bloque,
                                      int64_t t_flanco, uint32_t fs,
                                      uint32_t dec) {
  int64_t j = n_in_ult * 1000000LL - (t_bloque - t_flanco) * (int64_t)fs;
  j += 14LL * (int64_t)(dec - 1) * 1000000LL;
  if (j < 0) return -1;
  return (j / (int64_t)dec) * 256 / 1000000LL;
}

// --- Paquetes ---------------------------------------------------------------
//
//   A5 5A | tipo (1) | largo (2, LE) | carga (largo) | crc16 (2, LE)
//
// El CRC es CRC-16/CCITT-FALSE (polinomio 0x1021, inicial 0xFFFF) sobre
// tipo + largo + carga. En Python: binascii.crc_hqx(datos, 0xFFFF).

#define PROTO_VERSION 1
#define MAGIA0 0xA5
#define MAGIA1 0x5A
#define TIPO_DATOS  'D'   // idx0 (u32) + n muestras de 24 bits con signo
#define TIPO_SYNC   'S'   // idx (u32) + fraccion/256 (u8) + nivel (u8) + t_us (u32)
#define TIPO_INFO   'I'   // version (u8) + fs (u32) + dec (u16) + pin (u8) + bloque (u16)
#define TIPO_ESTADO 'E'   // desbordes, descartados, flancos, errores (u32 c/u)
#define TIPO_TEXTO  'T'   // mensaje ASCII

#define PAQ_CABECERA 5
#define PAQ_COLA     2
#define PAQ_CARGA_MAX 480
#define PAQ_MAX (PAQ_CABECERA + PAQ_CARGA_MAX + PAQ_COLA)

static inline uint16_t crc16(const uint8_t *p, size_t n) {
  uint16_t c = 0xFFFF;
  while (n--) {
    c ^= (uint16_t)(*p++) << 8;
    for (uint8_t i = 0; i < 8; i++) {
      c = (c & 0x8000) ? (uint16_t)((c << 1) ^ 0x1021) : (uint16_t)(c << 1);
    }
  }
  return c;
}

static inline void pon16(uint8_t *p, uint16_t v) {
  p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);
}

static inline void pon32(uint8_t *p, uint32_t v) {
  p[0] = (uint8_t)v;         p[1] = (uint8_t)(v >> 8);
  p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

// Cierra un paquete cuya carga ya esta escrita en dst + PAQ_CABECERA.
// Devuelve el largo total a transmitir.
static inline size_t paqCerrar(uint8_t *dst, uint8_t tipo, uint16_t largo) {
  dst[0] = MAGIA0;
  dst[1] = MAGIA1;
  dst[2] = tipo;
  pon16(dst + 3, largo);
  pon16(dst + PAQ_CABECERA + largo, crc16(dst + 2, (size_t)largo + 3));
  return (size_t)PAQ_CABECERA + largo + PAQ_COLA;
}

// Datos: se abre con el indice de la primera muestra, se agregan muestras
// y se cierra con paqDatosCerrar().
static inline void paqDatosAbrir(uint8_t *dst, uint32_t idx0) {
  pon32(dst + PAQ_CABECERA, idx0);
}

static inline void paqDatosAgregar(uint8_t *dst, uint16_t n, int32_t muestra) {
  if (muestra >  8388607) muestra =  8388607;
  if (muestra < -8388608) muestra = -8388608;
  uint8_t *p = dst + PAQ_CABECERA + 4 + 3 * (size_t)n;
  p[0] = (uint8_t)muestra;
  p[1] = (uint8_t)(muestra >> 8);
  p[2] = (uint8_t)(muestra >> 16);
}

static inline size_t paqDatosCerrar(uint8_t *dst, uint16_t n) {
  return paqCerrar(dst, TIPO_DATOS, (uint16_t)(4 + 3 * n));
}

static inline size_t paqSync(uint8_t *dst, int64_t idx256, uint8_t nivel,
                             uint32_t t_us) {
  uint8_t *p = dst + PAQ_CABECERA;
  pon32(p, (uint32_t)(idx256 >> 8));
  p[4] = (uint8_t)(idx256 & 0xFF);
  p[5] = nivel;
  pon32(p + 6, t_us);
  return paqCerrar(dst, TIPO_SYNC, 10);
}

static inline size_t paqInfo(uint8_t *dst, uint32_t fs, uint16_t dec,
                             uint8_t pin_sync, uint16_t bloque) {
  uint8_t *p = dst + PAQ_CABECERA;
  p[0] = PROTO_VERSION;
  pon32(p + 1, fs);
  pon16(p + 5, dec);
  p[7] = pin_sync;
  pon16(p + 8, bloque);
  return paqCerrar(dst, TIPO_INFO, 10);
}

static inline size_t paqEstado(uint8_t *dst, uint32_t desbordes,
                               uint32_t descartados, uint32_t flancos,
                               uint32_t errores) {
  uint8_t *p = dst + PAQ_CABECERA;
  pon32(p, desbordes);
  pon32(p + 4, descartados);
  pon32(p + 8, flancos);
  pon32(p + 12, errores);
  return paqCerrar(dst, TIPO_ESTADO, 16);
}

static inline size_t paqTexto(uint8_t *dst, const char *s) {
  size_t n = strlen(s);
  if (n > PAQ_CARGA_MAX) n = PAQ_CARGA_MAX;
  memcpy(dst + PAQ_CABECERA, s, n);
  return paqCerrar(dst, TIPO_TEXTO, (uint16_t)n);
}

#endif
