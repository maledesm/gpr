// ===========================================================================
//  GPRv3 - El nucleo del firmware corriendo en la PC
//
//  Compila nucleo.h tal cual lo usa la placa y repite el lazo de
//  adquisicion_sync.ino sobre un archivo de entrada. Lo usa
//  software/verificar.py para comprobar, sin hardware, que el diezmado, la
//  ubicacion de los flancos y los paquetes que arma el firmware son los que
//  espera el decodificador de Python.
//
//      gcc -O2 -o prueba_nucleo prueba_nucleo.c
//      prueba_nucleo entrada.bin salida.gpr3 [atraso_us]
//
//  entrada.bin (little endian):
//      u32 fs, u32 dec, u32 n_tramas, u32 n_flancos, i64 t0_us
//      i32 muestras[n_tramas]            (24 bits con signo)
//      { i64 t_us, u8 nivel }[n_flancos] (9 bytes cada uno)
//
//  La trama j termina en t0 + (j+1)*1e6/fs. `atraso_us` simula un lazo que
//  procesa cada bloque tarde: los flancos de ese rato ya estan en la cola. El
//  resultado tiene que ser el mismo con cualquier atraso.
// ===========================================================================

#include <stdio.h>
#include <stdlib.h>
#include "../adquisicion_sync/nucleo.h"

#define BLOQUE 256

static int leer(void *p, size_t n, FILE *f) { return fread(p, 1, n, f) == n; }

int main(int argc, char **argv) {
  if (argc < 3) {
    fprintf(stderr, "uso: prueba_nucleo entrada.bin salida.gpr3 [atraso_us]\n");
    return 2;
  }
  int64_t atraso = argc > 3 ? atoll(argv[3]) : 0;
  FILE *fe = fopen(argv[1], "rb");
  FILE *fs_ = fopen(argv[2], "wb");
  if (!fe || !fs_) { fprintf(stderr, "no pude abrir los archivos\n"); return 1; }

  uint32_t fs, dec, n_tramas, n_flancos;
  int64_t t0;
  if (!leer(&fs, 4, fe) || !leer(&dec, 4, fe) || !leer(&n_tramas, 4, fe) ||
      !leer(&n_flancos, 4, fe) || !leer(&t0, 8, fe)) return 1;

  int32_t *x = (int32_t *)malloc(sizeof(int32_t) * n_tramas);
  int64_t *tf = (int64_t *)malloc(sizeof(int64_t) * (n_flancos + 1));
  uint8_t *nv = (uint8_t *)malloc(n_flancos + 1);
  if (!leer(x, sizeof(int32_t) * n_tramas, fe)) return 1;
  for (uint32_t i = 0; i < n_flancos; i++) {
    if (!leer(&tf[i], 8, fe) || !leer(&nv[i], 1, fe)) return 1;
  }

  static uint8_t paq[PAQ_MAX];
  diezmador_t d;
  if (!diezmadorIniciar(&d, dec)) { fprintf(stderr, "dec invalido\n"); return 1; }

  fwrite(paq, 1, paqInfo(paq, fs, (uint16_t)dec, 10, BLOQUE), fs_);

  uint32_t n_out = 0, k = 0, flancos = 0;
  for (uint32_t b = 0; (b + 1) * BLOQUE <= n_tramas; b++) {
    int64_t n_in_ult = (int64_t)(b + 1) * BLOQUE - 1;
    int64_t t_bloque = t0 + ((n_in_ult + 1) * 1000000LL + fs / 2) / fs;

    while (k < n_flancos && tf[k] <= t_bloque + atraso) {
      int64_t idx256 = indiceFlanco256(n_in_ult, t_bloque, tf[k], fs, dec);
      if (idx256 >= 0) {
        fwrite(paq, 1, paqSync(paq, idx256, nv[k], (uint32_t)tf[k]), fs_);
      }
      k++;
      flancos++;
    }

    uint16_t n = 0;
    paqDatosAbrir(paq, n_out);
    for (uint32_t i = 0; i < BLOQUE; i++) {
      int32_t y;
      if (!diezmar(&d, x[b * BLOQUE + i], &y)) continue;
      paqDatosAgregar(paq, n++, y);
      n_out++;
    }
    if (n) fwrite(paq, 1, paqDatosCerrar(paq, n), fs_);
  }
  fwrite(paq, 1, paqEstado(paq, 0, 0, flancos, 0), fs_);
  fwrite(paq, 1, paqTexto(paq, "fin"), fs_);
  fclose(fe);
  fclose(fs_);
  return 0;
}
