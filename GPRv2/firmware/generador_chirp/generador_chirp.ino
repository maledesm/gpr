// ===========================================================================
//  GPRv2 - Generador de banco (Arduino Uno)
//
//  Sustituye a toda la cadena de RF para probar en casa. Emite:
//
//    D3  senal de batido de un blanco a 1.20 m, con la no linealidad REAL
//        del VCO, mas ruido blanco. PWM de 62.5 kHz que el RC del divisor
//        convierte en analogica.
//    D2  sync: cuadrada de 20 Hz, flanco de SUBIDA justo al principio de
//        cada rampa.
//
//  Los dos salen del mismo timer, o sea que son coherentes: el flanco cae
//  exactamente en la muestra 0 del chirp. Eso es lo que no da un generador
//  de mano, y es lo que hace falta para verificar el alineamiento.
//
//  La tabla la calcula GPRv2/analisis/generar_tabla_chirp.py desde
//  VCO/Caracteristica VCO.csv. Se precalcula porque el ATmega no llega a
//  hacer un coseno en los 125 us que tiene por muestra.
//
//  Cableado (ver GPRv2/CONTEXTO.md):
//
//    D3 ──10k──┬────────────────► VINL del modulo PCM1808
//              │
//             4k7 ∥ 43.5nF        (dos de 87nF en serie)
//              │                   fc = 1.2 kHz: pasa el beat (112-220 Hz)
//    GND ──────┴──── GND comun     y borra la portadora de PWM
//
//    D2 ──10k──┬────────────────► GPIO10 del ESP32-C3
//              │
//             15k                 3.00 V. El Uno saca 5 V y el C3 no los
//              │                  tolera: el divisor NO es opcional.
//    GND ──────┴──── GND comun
//
//  Masa comun entre Uno, ESP32 y modulo, si o si.
// ===========================================================================

#include "tabla_chirp.h"

#define PIN_SYNC   2      // PORTD bit 2
#define RUIDO     25      // amplitud del ruido, en cuentas de PWM. 0 lo apaga.

static volatile uint16_t idx = 0;
static uint16_t lfsr = 0xACE1;

ISR(TIMER1_COMPA_vect) {
  if (idx == 0)             PORTD |=  _BV(PIN_SYNC);
  else if (idx == CHIRP_N / 2) PORTD &= ~_BV(PIN_SYNC);

  lfsr = (lfsr >> 1) ^ (uint16_t)(-(int16_t)(lfsr & 1) & 0xB400);
  int16_t v = (int16_t)pgm_read_byte(&chirp[idx]) +
              (((int16_t)(lfsr & 0x3F) - 32) * RUIDO) / 32;
  if (v < 0)        v = 0;
  else if (v > 255) v = 255;
  OCR2B = (uint8_t)v;

  if (++idx >= CHIRP_N) idx = 0;
}

void setup() {
  pinMode(2, OUTPUT);
  pinMode(3, OUTPUT);

  // Timer2: PWM rapido de 62.5 kHz (16 MHz / 256) en OC2B = D3, sin
  // prescaler. Cuanto mas alta la portadora, mas facil se la filtra.
  TCCR2A = _BV(COM2B1) | _BV(WGM21) | _BV(WGM20);
  TCCR2B = _BV(CS20);
  OCR2B  = 128;

  // Timer1: CTC a CHIRP_FS exactos. 16 MHz / 8000 = 2000, sin resto.
  TCCR1A = 0;
  TCCR1B = _BV(WGM12) | _BV(CS10);
  OCR1A  = (F_CPU / CHIRP_FS) - 1;
  TIMSK1 = _BV(OCIE1A);
}

void loop() {
}
