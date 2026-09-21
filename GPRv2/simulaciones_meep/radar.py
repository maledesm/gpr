"""
GPRv2 - De H(f) al radargrama, con el pipeline real del banco
==============================================================

Corre en el Python de Windows, el mismo que corre `vivo_rapido.py`, y usa
`analisis/` de verdad: la curva medida del VCO, `eje_theta()`,
`remuestrear()` y `perfil_distancia()`. O sea que lo que sale de aca pasa
por EXACTAMENTE las mismas cuentas que una captura del banco, y si el pico
cae donde tiene que caer, es el pipeline entero el que queda probado, no
solo la formula.

`escena.py` (en WSL, env meep) deja H(f) del aire en `salidas/H_*.npz`.
Aca se le agrega todo lo que MEEP no simula y se sintetiza el batido.


Por que el batido es Re{H(f(t))}
--------------------------------

El transmitido es cos(phi(t)), con phi'(t) = 2*pi*f(t). Para una escena
lineal e invariante con respuesta al impulso h, el recibido es

    Rx(t) = Re{ integral h(tau) e^{j phi(t-tau)} dtau }

y como phi(t-tau) ~= phi(t) - 2*pi*f(t)*tau para tau chico (aproximacion
cuasi-estatica, la misma del "stretch processing"),

    Rx(t) ~= Re{ e^{j phi(t)} H(f(t)) }

El mezclador multiplica por el LO, cos(phi(t)):

    IF = Rx * LO = 1/2 Re{H(f(t))} + 1/2 Re{H(f(t)) e^{j 2 phi(t)}}
                   \_____________/   \___________________________/
                    lo que queda        se lo come el pasabajos

    ==>  s_IF(t) = 1/2 Re{ H(f(t)) }

O sea: el batido es, literalmente, la parte real de la funcion de
transferencia leida a lo largo de la rampa de frecuencia. Los cables entran
como e^{-j 2 pi f tau} y por eso corren el pico sin deformarlo.

El error de la aproximacion va con alpha*tau^2. Con la rampa real
(alpha = 20,8 GHz/s) y el retardo total de ~16 ns, eso es 5e-9 de fase: es
lo que hace que este metodo sea MUCHO mas exacto que meter el chirp adentro
de MEEP, donde el barrido dura nanosegundos y esa correccion es enorme.
"""

import os
import sys

import numpy as np
from scipy.interpolate import interp1d

AQUI = os.path.dirname(os.path.abspath(__file__))
ANALISIS = os.path.join(AQUI, "..", "analisis")
sys.path.insert(0, AQUI)
sys.path.insert(0, ANALISIS)

import parametros as P                                            # noqa: E402

# `correccion_no_linealidad` resuelve VCO_CSV relativo al DIRECTORIO ACTUAL,
# no al archivo (ver "waterfall.py solo corre parado en analisis/" en
# GPRv2/CLAUDE.md). Por eso se entra a analisis/ para importarlo y se vuelve.
_cwd0 = os.getcwd()
os.chdir(ANALISIS)
try:
    from correccion_no_linealidad import (                        # noqa: E402
        T_SWEEP, C, cargar_curva_vco, eje_theta, remuestrear, fs_theta,
        perfil_distancia)
    from cables_vna import leer_s2p                               # noqa: E402
finally:
    os.chdir(_cwd0)

FS = 6000.0          # sps de la salida diezmada del firmware (SPS_SALIDA)


# --- Lo que MEEP no simula -------------------------------------------------

def _interp_complejo(f_tabla, y, f):
    """Interpola una respuesta compleja: modulo y fase DESENROLLADA aparte.

    Interpolar re e im por separado es lo mismo solo si la fase gira poco
    entre puntos. Con 5 ns de retardo y 2,9 MHz de paso la fase gira 5,2
    grados por punto, asi que todavia daria, pero con el cable medido (paso
    de 2,5 MHz y 10 ns) se acerca al limite. Sobre modulo y fase no hay
    limite: el retardo es una recta en fase y se interpola exacto.
    """
    mag = interp1d(f_tabla, np.abs(y), kind="cubic",
                   bounds_error=False, fill_value="extrapolate")(f)
    fase = interp1d(f_tabla, np.unwrap(np.angle(y)), kind="cubic",
                    bounds_error=False, fill_value="extrapolate")(f)
    return mag * np.exp(1j * fase)


def respuesta_cables(f_hz, modo="medido"):
    """Respuesta del cableado que ve el mezclador, como factor sobre H(f).

    modo:
      "ninguno"  sin cables. El radar ideal de la ecuacion del capitulo de
                 la tesis, util para ver el offset como diferencia.
      "ideal"    retardo puro e^{-j 2 pi f tau}, con el tau de la tabla de
                 la tesis (fase de S21) y sin perdidas.
      "medido"   el S21 COMPLETO medido con el VNA de los dos RG-213, o sea
                 modulo y fase reales, incluida la atenuacion que crece con
                 la frecuencia. Es lo mas parecido al banco.

    En los tres casos se resta el camino del LO (los 5 cm de union directa
    entre el splitter y el mezclador), que es el unico termino que resta en
    D = L_TX + L_RX - L_LO.
    """
    if modo == "ninguno":
        return np.ones_like(f_hz, dtype=complex)

    lo = np.exp(+2j * np.pi * f_hz * P.TAU_LO)      # el LO RESTA retardo

    if modo == "ideal":
        return np.exp(-2j * np.pi * f_hz * (P.TAU_TX + P.TAU_RX)) * lo

    if modo == "medido":
        h = np.ones_like(f_hz, dtype=complex)
        for ruta in (P.S2P_TX, P.S2P_RX):
            f_v, s = leer_s2p(ruta)
            h = h * _interp_complejo(f_v, s["S21"], f_hz)
        return h * lo

    raise ValueError(f"modo de cable desconocido: {modo}")


def aplicar_cadena(f_hz, H, modo_cable="medido", tau_interno=None):
    """H del aire -> H que ve el mezclador: + cables + retardo interno."""
    if tau_interno is None:
        tau_interno = P.TAU_INTERNO
    return (H * respuesta_cables(f_hz, modo_cable)
            * np.exp(-2j * np.pi * f_hz * tau_interno))


# --- Sintesis del batido y perfil de distancia -----------------------------

def sintetizar(f_hz, H_total, t_rampa=None, fs=FS, curva=None):
    """Devuelve (t, beat, theta, alpha0) de UNA rampa de subida.

    El eje de frecuencia instantanea sale de la curva MEDIDA del VCO, no de
    una rampa lineal: asi el batido que se sintetiza tiene la misma no
    linealidad que el del banco, y el remuestreo de `remuestrear()` tiene
    algo real que corregir.
    """
    if t_rampa is None:
        t_rampa = T_SWEEP
    if curva is None:
        curva = cargar_curva_vco(P.VCO_CSV)

    n = int(round(t_rampa * fs))
    t = np.linspace(0, t_rampa, n, endpoint=False)
    f_t, theta, alpha0 = eje_theta(curva, t)

    if f_t.min() < f_hz.min() - 1e6 or f_t.max() > f_hz.max() + 1e6:
        raise SystemExit(
            f"el barrido del VCO ({f_t.min()/1e6:.0f}-{f_t.max()/1e6:.0f} MHz) "
            f"se sale de la banda de H(f) ({f_hz.min()/1e6:.0f}-"
            f"{f_hz.max()/1e6:.0f} MHz). Ampliar F_MIN/F_MAX en parametros.py "
            f"y volver a correr escena.py.")

    beat = 0.5 * _interp_complejo(f_hz, H_total, f_t).real
    return t, beat, theta, alpha0


def perfil(f_hz, H_total, relleno=1, **kw):
    """(rango [m], espectro) con el MISMO camino que una captura del banco.

    Remuestreo cubico sobre la grilla theta que linealiza el VCO, y despues
    FFT con ventana de Hann. Identico a lo que hacen `vivo_rapido.py` y
    `graficar_captura.py`, salvo que la rampa viene de H(f) en vez del
    puerto serie.

    `relleno` es el zero-padding de la FFT, el mismo que `vivo_rapido.py`
    tiene en RELLENO = 8. NO agrega resolucion —el ancho de bin real sigue
    valiendo c/(2*BW) = 14,4 cm y eso solo lo cambia la BW del VCO— pero
    interpola el pico y deja leer su posicion sin quedar atado al bin.
    Con relleno = 1 la cuenta es exactamente `perfil_distancia()`.
    """
    _t, beat, theta, alpha0 = sintetizar(f_hz, H_total, **kw)
    n = len(beat)
    _th_u, beat_u = remuestrear(theta, beat, n)
    fs = fs_theta(theta, n)
    if relleno == 1:
        return perfil_distancia(beat_u, fs, alpha0)
    espectro = np.abs(np.fft.rfft(beat_u * np.hanning(n), n=n * relleno))
    freqs = np.fft.rfftfreq(n * relleno, d=1.0 / fs)
    return freqs * C / (2.0 * alpha0), espectro


def guardar_figura(fig, destino, dpi=130):
    """Guarda la figura aunque la version anterior este abierta en un visor.

    El visor de Fotos de Windows traba el archivo que muestra, y savefig()
    falla con "Invalid argument". Se escribe a un temporal y se reemplaza; si
    ni eso se puede, se guarda con la hora en el nombre en vez de romper la
    corrida entera. Devuelve la ruta con la que quedo.
    """
    import time
    tmp = destino + ".tmp.png"
    fig.savefig(tmp, dpi=dpi)
    try:
        os.replace(tmp, destino)
        return destino
    except OSError:
        base, ext = os.path.splitext(destino)
        alt = f"{base}_{time.strftime('%H-%M-%S')}{ext}"
        os.replace(tmp, alt)
        print(f"  [!] {os.path.basename(destino)} esta abierto en otro programa "
              f"(cerrar el visor); se guardo como {os.path.basename(alt)}")
        return alt


def anotar_para_abrir(destino):
    """simular.bat abre al terminar las figuras que se anotan aca."""
    if os.environ.get("GPR_SIM_ABRIR") == "1":
        with open(os.path.join(P.SALIDAS, "_abrir.txt"), "a",
                  encoding="utf-8") as fh:
            fh.write(destino + "\n")


def cargar(etiqueta):
    """Lee salidas/H_<etiqueta>.npz -> (f_hz, H)."""
    ruta = os.path.join(P.SALIDAS, f"H_{etiqueta}.npz")
    if not os.path.exists(ruta):
        raise SystemExit(
            f"falta {ruta}. Corre primero la simulacion:\n"
            f"    wsl -d Ubuntu -- bash "
            f"/mnt/c/Users/mogic/Tesis/gpr/GPRv2/simulaciones_meep/correr_meep.sh")
    d = np.load(ruta)
    return d["f_hz"], d["H"]


def pico(rango, espectro, desde=0.0, hasta=np.inf):
    """(distancia, nivel dB relativo al maximo) del pico en una ventana."""
    m = (rango >= desde) & (rango <= hasta)
    if not m.any():
        return np.nan, np.nan
    idx = np.flatnonzero(m)
    i = idx[np.argmax(espectro[m])]
    d = rango[i]
    # Interpolacion parabolica sobre el log del espectro (tres bins). Sin
    # esto la posicion queda cuantizada al paso del eje (18 mm con relleno 8)
    # y un ajuste de recta sobre varios picos puede dar un residuo "cero"
    # que es solo que todos cayeron justo en bins.
    if 0 < i < len(espectro) - 1:
        y0, y1, y2 = np.log(espectro[i - 1:i + 2] + 1e-300)
        den = y0 - 2 * y1 + y2
        if den < 0:
            d = d + 0.5 * (y0 - y2) / den * (rango[1] - rango[0])
    return float(d), float(20 * np.log10(espectro[i] / espectro.max()))
