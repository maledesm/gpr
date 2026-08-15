"""
Graficador en tiempo real.

    python graficarserial.py [archivo.csv]

Sin argumento toma el CSV mas reciente de datos/.

Lee el archivo que grabarserial.py esta escribiendo, siguiendolo a medida que
crece (como un 'tail'). Ese desacople es a proposito: el graficador puede
colgarse, cerrarse o abrirse tarde sin afectar la grabacion, que es lo que no
se puede perder. Tambien sirve para revisar mediciones viejas.

Todo el procesamiento vive en dsp.py; aca solo hay interfaz.
"""

import os
import sys

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets

import dsp

AQUI = os.path.dirname(os.path.abspath(__file__))
DATOS = os.path.normpath(os.path.join(AQUI, "..", "datos"))

MAX_MUESTRAS = 1 << 21          # ~2 M muestras en memoria (4.4 min a 8 kHz)


# ---------------------------------------------------------------------------
# Lectura incremental del CSV
# ---------------------------------------------------------------------------

class LectorCSV:
    """Sigue un CSV que se esta escribiendo.

    La sutileza: el grabador puede estar a mitad de una linea cuando leemos.
    Por eso solo se procesan lineas terminadas en '\\n' y el resto se guarda
    para la vuelta siguiente. Sin eso aparecen valores basura esporadicos,
    imposibles de rastrear despues.
    """

    def __init__(self, ruta):
        self.ruta = ruta
        self.meta = {}
        self._f = open(ruta, "r", encoding="utf-8", errors="replace")
        self._resto = ""
        self.idx = np.zeros(MAX_MUESTRAS, dtype=np.int64)
        self.val = np.zeros(MAX_MUESTRAS, dtype=np.float64)
        self.n = 0
        self.total = 0

    def _guardar(self, idxs, vals):
        k = len(vals)
        if k >= MAX_MUESTRAS:
            self.idx[:] = idxs[-MAX_MUESTRAS:]
            self.val[:] = vals[-MAX_MUESTRAS:]
            self.n = MAX_MUESTRAS
        elif self.n + k <= MAX_MUESTRAS:
            self.idx[self.n:self.n + k] = idxs
            self.val[self.n:self.n + k] = vals
            self.n += k
        else:
            sobra = self.n + k - MAX_MUESTRAS
            self.idx[:self.n - sobra] = self.idx[sobra:self.n]
            self.val[:self.n - sobra] = self.val[sobra:self.n]
            self.n -= sobra
            self.idx[self.n:self.n + k] = idxs
            self.val[self.n:self.n + k] = vals
            self.n += k
        self.total += k

    def leer(self):
        trozo = self._f.read()
        if not trozo:
            return 0
        datos = self._resto + trozo
        corte = datos.rfind("\n")
        if corte < 0:
            self._resto = datos
            return 0
        self._resto = datos[corte + 1:]

        idxs, vals = [], []
        for linea in datos[:corte].split("\n"):
            if not linea:
                continue
            if linea[0] == "#":
                if "=" in linea:
                    k, v = linea[1:].split("=", 1)
                    self.meta[k.strip()] = v.strip()
                continue
            if linea[0] == "i":            # cabecera de columnas
                continue
            try:
                a, b = linea.split(",")
                idxs.append(int(a))
                vals.append(float(b))
            except ValueError:
                continue
        if vals:
            self._guardar(np.array(idxs, dtype=np.int64),
                          np.array(vals, dtype=np.float64))
        return len(vals)

    def num(self, clave, defecto):
        try:
            return float(self.meta[clave])
        except (KeyError, ValueError):
            return defecto

    def cerrar(self):
        try:
            self._f.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Ventana
# ---------------------------------------------------------------------------

class Ventana(QtWidgets.QMainWindow):

    def __init__(self, ruta):
        super().__init__()
        self.lector = LectorCSV(ruta)
        self.lector.leer()

        self.fs = self.lector.num("fs_eff", 8000.0)
        self.bw = self.lector.num("bw_mhz", 750.0) * 1e6
        self.tsweep = self.lector.num("t_sweep_ms", 10.0) / 1000.0
        self.prom = dsp.Promediador(1)
        self.referencia = None
        self.congelado = False
        self.cascada = None

        self.setWindowTitle(f"GPR - {os.path.basename(ruta)}")
        self.resize(1400, 900)
        self._construir()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.actualizar)
        self.timer.start(50)                       # 20 Hz

    # -- interfaz ----------------------------------------------------------

    def _construir(self):
        pg.setConfigOptions(antialias=True)
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        raiz = QtWidgets.QHBoxLayout(central)

        # ---- columna de controles
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(270)
        col = QtWidgets.QVBoxLayout(panel)
        form = QtWidgets.QFormLayout()
        col.addLayout(form)

        def combo(items, actual=0):
            c = QtWidgets.QComboBox()
            c.addItems(items)
            c.setCurrentIndex(actual)
            return c

        def spin(lo, hi, val, paso=1):
            s = QtWidgets.QSpinBox()
            s.setRange(lo, hi)
            s.setValue(val)
            s.setSingleStep(paso)
            return s

        form.addRow(QtWidgets.QLabel("<b>Espectro</b>"))
        self.c_ventana = combo(dsp.VENTANAS, 0)
        form.addRow("Ventana", self.c_ventana)

        self.c_nfft = combo(["512", "1024", "2048", "4096", "8192", "16384"], 3)
        form.addRow("Puntos FFT", self.c_nfft)

        self.c_zp = combo(["x1", "x2", "x4", "x8"], 1)
        form.addRow("Zero padding", self.c_zp)

        self.s_prom = spin(1, 256, 8)
        form.addRow("Promediar", self.s_prom)

        self.c_ejex = combo(["Frecuencia (Hz)", "Distancia (m)"], 1)
        form.addRow("Eje X", self.c_ejex)

        self.s_dmax = spin(1, 200, 10)
        form.addRow("Distancia max (m)", self.s_dmax)

        form.addRow(QtWidgets.QLabel("<b>Filtros</b>"))
        self.k_hpf = QtWidgets.QCheckBox("Pasa-altos (acople directo)")
        form.addRow(self.k_hpf)
        self.s_hpf = spin(1, 5000, 100, 10)
        form.addRow("  Corte (Hz)", self.s_hpf)

        self.k_notch = QtWidgets.QCheckBox("Notch de red")
        form.addRow(self.k_notch)
        self.s_notch = spin(10, 500, 50)
        form.addRow("  Frecuencia (Hz)", self.s_notch)

        form.addRow(QtWidgets.QLabel("<b>Osciloscopio</b>"))
        self.s_puntos = spin(64, 65536, 2048, 64)
        form.addRow("Puntos a mostrar", self.s_puntos)

        self.s_dec = spin(1, 256, 1)
        form.addRow("Decimacion visual", self.s_dec)

        self.k_interp = QtWidgets.QCheckBox("Interpolar (curva suave)")
        self.k_interp.setChecked(True)
        form.addRow(self.k_interp)

        form.addRow(QtWidgets.QLabel("<b>Referencia</b>"))
        b_guardar = QtWidgets.QPushButton("Guardar traza actual")
        b_guardar.clicked.connect(self._guardar_ref)
        form.addRow(b_guardar)
        b_borrar = QtWidgets.QPushButton("Borrar referencia")
        b_borrar.clicked.connect(self._borrar_ref)
        form.addRow(b_borrar)
        self.k_dif = QtWidgets.QCheckBox("Mostrar diferencia")
        form.addRow(self.k_dif)

        self.k_cascada = QtWidgets.QCheckBox("Cascada (B-scan)")
        form.addRow(QtWidgets.QLabel("<b>Vista</b>"))
        form.addRow(self.k_cascada)
        self.k_cascada.stateChanged.connect(self._toggle_cascada)

        self.b_congelar = QtWidgets.QPushButton("Congelar")
        self.b_congelar.setCheckable(True)
        self.b_congelar.toggled.connect(self._congelar)
        form.addRow(self.b_congelar)

        col.addStretch(1)
        self.lbl = QtWidgets.QLabel("...")
        self.lbl.setWordWrap(True)
        self.lbl.setStyleSheet("font-family: Consolas; font-size: 11px;")
        col.addWidget(self.lbl)
        raiz.addWidget(panel)

        # ---- graficos: 70 % espectro, 30 % osciloscopio
        graf = QtWidgets.QVBoxLayout()
        raiz.addLayout(graf, 1)

        self.p_esp = pg.PlotWidget()
        self.p_esp.setLabel("left", "Amplitud", units="dB")
        self.p_esp.showGrid(x=True, y=True, alpha=0.3)
        self.p_esp.addLegend()
        self.cur_esp = self.p_esp.plot(pen=pg.mkPen("#4ea3ff", width=1.5), name="actual")
        self.cur_ref = self.p_esp.plot(pen=pg.mkPen("#ff9f4e", width=1.2,
                                                    style=QtCore.Qt.PenStyle.DashLine),
                                       name="referencia")
        graf.addWidget(self.p_esp, 70)

        self.p_cascada = pg.PlotWidget()
        self.p_cascada.setLabel("left", "Tiempo")
        self.img = pg.ImageItem()
        self.p_cascada.addItem(self.img)
        self.p_cascada.hide()
        graf.addWidget(self.p_cascada, 40)

        self.p_osc = pg.PlotWidget()
        self.p_osc.setLabel("left", "Senal", units="V")
        self.p_osc.setLabel("bottom", "Tiempo", units="s")
        self.p_osc.showGrid(x=True, y=True, alpha=0.3)
        self.cur_osc = self.p_osc.plot(pen=pg.mkPen("#7ee081", width=1.2))
        graf.addWidget(self.p_osc, 30)

    def _guardar_ref(self):
        self.referencia = getattr(self, "_ultima", None)

    def _borrar_ref(self):
        self.referencia = None
        self.cur_ref.setData([], [])

    def _congelar(self, on):
        self.congelado = on
        self.b_congelar.setText("Reanudar" if on else "Congelar")

    def _toggle_cascada(self):
        if self.k_cascada.isChecked():
            self.p_cascada.show()
            self.cascada = None
        else:
            self.p_cascada.hide()

    # -- actualizacion -----------------------------------------------------

    def actualizar(self):
        nuevos = self.lector.leer()
        if self.congelado or self.lector.n < 64:
            return

        n_osc = min(self.s_puntos.value(), self.lector.n)
        x = self.lector.val[self.lector.n - n_osc:self.lector.n].copy()

        # Los filtros se aplican antes de todo lo demas
        if self.k_hpf.isChecked():
            x = dsp.pasaaltos(x, self.fs, float(self.s_hpf.value()))
        if self.k_notch.isChecked():
            x = dsp.notch(x, self.fs, float(self.s_notch.value()))

        # ---- osciloscopio
        xv = dsp.decimar(x, self.s_dec.value())
        fs_v = self.fs / self.s_dec.value()
        t = np.arange(len(xv)) / fs_v
        self.cur_osc.setData(t, xv,
                             connect="all" if self.k_interp.isChecked() else "pairs")

        # ---- espectro
        nfft = int(self.c_nfft.currentText())
        n_fft = min(nfft, self.lector.n)
        xf = self.lector.val[self.lector.n - n_fft:self.lector.n].copy()
        if self.k_hpf.isChecked():
            xf = dsp.pasaaltos(xf, self.fs, float(self.s_hpf.value()))
        if self.k_notch.isChecked():
            xf = dsp.notch(xf, self.fs, float(self.s_notch.value()))

        zp = int(self.c_zp.currentText()[1:])
        frec, pot = dsp.espectro(xf, self.fs, self.c_ventana.currentText(), zp)
        if len(frec) == 0:
            return

        self.prom.configurar(self.s_prom.value())
        pot = self.prom.agregar(pot)
        db = dsp.a_db(pot)
        self._ultima = (frec.copy(), db.copy())

        if self.c_ejex.currentIndex() == 1:
            eje = dsp.frec_a_distancia(frec, self.bw, self.tsweep)
            self.p_esp.setLabel("bottom", "Distancia", units="m")
            self.p_esp.setXRange(0, self.s_dmax.value(), padding=0)
        else:
            eje = frec
            self.p_esp.setLabel("bottom", "Frecuencia", units="Hz")
            self.p_esp.setXRange(0, self.fs / 2, padding=0)

        if self.k_dif.isChecked() and self.referencia is not None \
                and len(self.referencia[1]) == len(db):
            self.cur_esp.setData(eje, db - self.referencia[1])
            self.cur_ref.setData([], [])
        else:
            self.cur_esp.setData(eje, db)
            if self.referencia is not None and len(self.referencia[0]) == len(eje):
                self.cur_ref.setData(eje, self.referencia[1])

        if self.k_cascada.isChecked():
            self._actualizar_cascada(db, eje)

        pico = int(np.argmax(db))
        self.lbl.setText(
            f"fs_eff  {self.fs:.1f} Hz\n"
            f"BW      {self.bw / 1e6:.0f} MHz\n"
            f"T_sweep {self.tsweep * 1e3:.2f} ms\n"
            f"Resol.  {dsp.resolucion_distancia(self.bw) * 100:.1f} cm\n"
            f"------------------------\n"
            f"Muestras {self.lector.total}\n"
            f"Promedios {self.prom.cargados}/{self.prom.k}\n"
            f"------------------------\n"
            f"Pico  {db[pico]:.1f} dB\n"
            f"      {frec[pico]:.1f} Hz\n"
            f"      {dsp.frec_a_distancia(frec[pico], self.bw, self.tsweep):.3f} m"
        )

    def _actualizar_cascada(self, db, eje):
        """B-scan: cada fila es un espectro, el eje vertical es el tiempo.
        Es la imagen clasica de un GPR barriendo el terreno."""
        n = min(len(db), 1024)
        fila = db[:n]
        if self.cascada is None or self.cascada.shape[1] != n:
            self.cascada = np.full((300, n), fila.min())
        self.cascada = np.roll(self.cascada, -1, axis=0)
        self.cascada[-1] = fila
        self.img.setImage(self.cascada.T, autoLevels=True)
        self.img.setRect(QtCore.QRectF(0, 0, eje[n - 1], self.cascada.shape[0]))

    def closeEvent(self, e):
        self.timer.stop()
        self.lector.cerrar()
        super().closeEvent(e)


def main():
    if len(sys.argv) > 1:
        ruta = sys.argv[1]
    else:
        archivos = [os.path.join(DATOS, f) for f in os.listdir(DATOS)
                    if f.endswith(".csv")] if os.path.isdir(DATOS) else []
        if not archivos:
            print(f"No hay CSV en {DATOS}. Corré primero grabarserial.py.")
            sys.exit(1)
        ruta = max(archivos, key=os.path.getmtime)
        print(f"Abriendo el mas reciente: {os.path.basename(ruta)}")

    app = QtWidgets.QApplication(sys.argv)
    v = Ventana(ruta)
    v.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
