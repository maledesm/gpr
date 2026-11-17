"""
GPRv3 - Radargrama en tiempo real
=================================

    python vivo.py                     con la placa
    python vivo.py --sintetico         sin banco, con blancos simulados
    python vivo.py --archivo x.gpr3    reproduce una grabacion

A la izquierda los controles (Enter aplica), en el centro el radargrama
(distancia en x, tiempo en y, lo mas nuevo abajo) con la FFT de la ultima
fila debajo, y a la derecha el estado del barrido, la triangular dibujada,
la ultima rampa y los deslizadores: valle, cima y retardo.

Los perfiles son de potencia (se promedia |FFT|^2). Cada fila del radargrama
se calcula una vez, al cerrarse: lo que se cambie despues vale de ahi en mas.

Cada vez que se cambia un ajuste que altera lo que se mide o como se
procesa, queda una linea roja en ese instante del radargrama.

Teclas: e eje m/Hz, a autoescala el color, f fondo automatico, s captura,
q salir.
"""

import argparse
import json
import os
import sys
import threading
import time

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

import captura
import config as cfg
from fuentes import FuenteArchivo, FuenteSerie, FuenteSintetica, Grabador
from grabar import metadatos
from modelo import SENTIDOS, AjusteRetardo, Calibracion, Radar
from proceso import VENTANAS, cargar_curva

# Un solo color de fondo para todo: ventana, controles y graficos.
FONDO, PANEL, TEXTO, ACENTO = "#16181d", "#22252c", "#d6d8dc", "#3d7eff"
pg.setConfigOptions(imageAxisOrder="row-major", background=FONDO,
                    foreground=TEXTO)
# Los ajustes que solo cambian como se mira: no dejan marca.
SOLO_VISTA = ("ventana", "alcance", "piso", "techo", "dist_real", "espera",
              "d_ref")
CURVAS = ("estática", "medida")
RETARDO_MAX_US = int(cfg.RETARDO_MAX_S * 1e6)
AZUL, NARANJA, ROJO, CELESTE = (90, 170, 255), (255, 127, 14), "#ff3030", "#40e0ff"

# nombre -> (rotulo, minimo, maximo, paso, decimales)
CAJAS = {
    "n_rampas": ("rampas/fila", 1, cfg.N_MAX, 1, 0),
    "ventana": ("ventana [s]", 1.0, cfg.VENTANA_MAX, 5.0, 1),
    "alcance": ("alcance [m]", 0.5, cfg.D_MAX_M, 0.5, 2),
    "piso": ("piso [dB]", -160.0, 100.0, 5.0, 1),
    "techo": ("techo [dB]", -160.0, 100.0, 5.0, 1),
    "ignorar": ("ignorar < [m]", 0.0, cfg.D_MAX_M, 0.1, 2),
    "margen": ("margen [dB]", -80.0, 80.0, 1.0, 1),
    "dist_real": ("dist. real [m]", 0.0, 100.0, 0.1, 3),
    "espera": ("esperar [s]", 0.0, cfg.ESPERA_MAX, 1.0, 0),
    "d_ref": ("retardo de referencia", 0.3, 30.0, 0.1, 2),
}
GRIS = pg.mkBrush(150, 150, 150, 70)
NEGRITA = {"font-weight": "600"}

ESTILO = f"""
QWidget {{ font-size: 9pt; font-weight: 600; }}
QGroupBox {{ border: 1px solid #2f333c; border-radius: 10px; margin-top: 8px;
             padding-top: 6px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 4px;
                    color: #8fb4ff; }}
QPushButton {{ background: #2b2f38; border: none; border-radius: 9px;
               padding: 2px 10px; }}
QPushButton:hover {{ background: #363b47; }}
QPushButton:pressed {{ background: {ACENTO}; color: white; }}
QDoubleSpinBox, QLineEdit, QComboBox {{ background: {PANEL}; border: 1px solid
    #2f333c; border-radius: 7px; padding: 1px 6px; }}
QDoubleSpinBox:focus, QLineEdit:focus, QComboBox:focus {{ border-color: {ACENTO}; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {PANEL}; selection-background-color: {ACENTO}; }}
QSlider::groove:horizontal {{ height: 4px; background: #2f333c; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACENTO}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {TEXTO}; width: 14px; margin: -5px 0;
                              border-radius: 7px; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border-radius: 4px;
                        border: 1px solid #4a4f5a; background: {PANEL}; }}
QCheckBox::indicator:checked {{ background: {ACENTO}; border-color: {ACENTO}; }}
QStatusBar {{ color: #8d919b; font-size: 8pt; }}
"""


def letra_negrita(puntos=9):
    f = QtGui.QFont()
    f.setPointSize(puntos)
    f.setWeight(QtGui.QFont.Weight.DemiBold)
    return f


def tema_oscuro(app):
    app.setStyle("Fusion")
    p = QtGui.QPalette()
    R, G = QtGui.QPalette.ColorRole, QtGui.QPalette.ColorGroup
    for rol, color in ((R.Window, FONDO), (R.Base, PANEL), (R.Button, PANEL),
                       (R.AlternateBase, PANEL), (R.ToolTipBase, PANEL),
                       (R.WindowText, TEXTO), (R.Text, TEXTO),
                       (R.ButtonText, TEXTO), (R.ToolTipText, TEXTO),
                       (R.PlaceholderText, "#7a7d85"), (R.Highlight, ACENTO),
                       (R.HighlightedText, "#ffffff")):
        p.setColor(rol, QtGui.QColor(color))
    for rol in (R.WindowText, R.Text, R.ButtonText):
        p.setColor(G.Disabled, rol, QtGui.QColor("#6b6e76"))
    app.setPalette(p)
    app.setStyleSheet(ESTILO)


def cargar_config(ruta=cfg.CONFIG_JSON):
    try:
        with open(ruta, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


class Ventana(QtWidgets.QMainWindow):

    def __init__(self, fuente, radar, config=None):
        super().__init__()
        self.fuente = fuente
        self.radar = radar
        self.dist_real = 1.0
        self.espera = 0.0
        self.d_ref = cfg.D_REF_DEF
        self.aviso = ""
        self.t_disparo = None
        self.t_inicio = time.monotonic()
        self.cuadro = 0
        self.ms_cuadro = 0.0
        self._rango = None
        self.ajuste = None                # AjusteRetardo en curso

        self.setWindowTitle(f"GPRv3 - en vivo ({fuente.nombre})")
        self.resize(1900, 1000)
        centro = QtWidgets.QWidget()
        self.setCentralWidget(centro)
        fila = QtWidgets.QHBoxLayout(centro)
        fila.addWidget(self._armar_controles())
        fila.addWidget(self._armar_graficos(), 1)
        fila.addWidget(self._armar_derecha())

        self.aplicar_config(config or {})
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refrescar)
        self.timer.start(cfg.REFRESCO_MS)

    # --- armado ---

    def _armar_controles(self):
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(250)
        col = QtWidgets.QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        self.cajas = {}

        def grupo(titulo, nombres):
            g = QtWidgets.QGroupBox(titulo)
            forma = QtWidgets.QFormLayout(g)
            forma.setContentsMargins(6, 4, 6, 4)
            forma.setVerticalSpacing(2)
            for nombre in nombres:
                rotulo, lo, hi, paso, dec = CAJAS[nombre]
                c = QtWidgets.QDoubleSpinBox()
                c.setRange(lo, hi)
                c.setSingleStep(paso)
                c.setDecimals(dec)
                # Aplica con Enter o al salir del cuadro, no en cada tecla.
                c.setKeyboardTracking(False)
                c.valueChanged.connect(lambda v, n=nombre: self._escribir(n, v))
                self.cajas[nombre] = c
                forma.addRow(rotulo, c)
            col.addWidget(g)
            return forma

        def botones(forma, *pares):
            """Una fila de botones parejos. Devuelve los botones."""
            fila = QtWidgets.QHBoxLayout()
            fila.setSpacing(4)
            hechos = []
            for texto, accion in pares:
                b = QtWidgets.QPushButton(texto)
                b.clicked.connect(accion)
                b.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
                fila.addWidget(b)
                hechos.append(b)
            forma.addRow(fila)
            return hechos

        f = grupo("Pantalla", ("ventana", "alcance", "piso", "techo"))
        self.combo_color = QtWidgets.QComboBox()
        self.combo_color.addItems(cfg.MAPAS_COLOR)
        self.combo_color.setCurrentText(self.radar.mapa_color)
        self.combo_color.currentTextChanged.connect(self._cambiar_color)
        f.addRow("colores", self.combo_color)
        botones(f, ("eje m/Hz (e)", self.cambiar_eje),
                ("autoescala (a)", self.autoescala))

        f = grupo("Procesamiento", ("n_rampas",))
        self.combo_sentido = QtWidgets.QComboBox()
        self.combo_sentido.addItems(SENTIDOS)
        self.combo_sentido.currentTextChanged.connect(self._cambiar_sentido)
        f.addRow("rampas", self.combo_sentido)
        self.combo_fft = QtWidgets.QComboBox()
        self.combo_fft.addItems(list(VENTANAS))
        self.combo_fft.setCurrentText(self.radar.ventana_fft)
        self.combo_fft.currentTextChanged.connect(self._cambiar_fft)
        f.addRow("ventana FFT", self.combo_fft)

        self.combo_sps = QtWidgets.QComboBox()
        self.combo_sps.addItems([str(x) for x in cfg.SPS_OPCIONES])
        self.combo_sps.setCurrentText(str(cfg.SPS_DEF))
        self.combo_sps.setEnabled(not isinstance(self.fuente, FuenteArchivo))
        self.combo_sps.textActivated.connect(self._cambiar_sps)
        f.addRow("muestras/s", self.combo_sps)
        # Curva del barrido: la estatica del VCO o la medida con un retardo
        # conocido (cables unidos por un barrel, sin antenas). Al lado del
        # boton, el retardo de referencia en metros aparentes.
        self.combo_curva = QtWidgets.QComboBox()
        self.combo_curva.addItems(CURVAS)
        self.combo_curva.currentTextChanged.connect(self._cambiar_curva)
        f.addRow("curva VCO", self.combo_curva)
        rotulo, lo, hi, paso, dec = CAJAS["d_ref"]
        c = self.cajas["d_ref"] = QtWidgets.QDoubleSpinBox()
        c.setRange(lo, hi)
        c.setSingleStep(paso)
        c.setDecimals(dec)
        c.setKeyboardTracking(False)
        c.setSuffix(" m")
        c.setToolTip("retardo de referencia, en metros aparentes (c·τ/2)")
        c.valueChanged.connect(lambda v: self._escribir("d_ref", v))
        self.boton_barrido = QtWidgets.QPushButton("medir curva")
        self.boton_barrido.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.boton_barrido.clicked.connect(self.calibrar_barrido)
        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(4)
        fila.addWidget(c)
        fila.addWidget(self.boton_barrido, 1)
        f.addRow(fila)

        f = grupo("Fondo y detección", ("ignorar", "margen"))
        _, self.boton_mti, _ = botones(f, ("medir", self.medir_fondo),
                                       ("auto (f)", self.alternar_mti),
                                       ("borrar", self.borrar_fondo))

        f = grupo("Calibración de distancia", ("dist_real",))
        botones(f, ("punto", self.tomar_punto), ("calibrar", self.calibrar),
                ("borrar", self.borrar_cal))

        f = grupo("Captura", ("espera",))
        self.caja_nombre = QtWidgets.QLineEdit(cfg.NOMBRE_CAPTURA_DEF)
        f.insertRow(0, "nombre", self.caja_nombre)
        botones(f, ("guardar captura  (s)", self.boton_captura))
        self.casilla_crudo = QtWidgets.QCheckBox("grabar crudo (.gpr3)")
        self.casilla_crudo.toggled.connect(self._grabar_crudo)
        f.addRow(self.casilla_crudo)

        self.estado = QtWidgets.QLabel()
        self.estado.setWordWrap(True)
        self.estado.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        col.addWidget(self.estado, 1)
        return panel

    def _armar_graficos(self):
        self.gl = pg.GraphicsLayoutWidget()
        self.pr = self.gl.addPlot(row=0, col=0)
        self.pr.setLabel("left", "Tiempo atrás [s]  (0 = ahora; en rojo, los "
                                 "cambios de ajuste)", **NEGRITA)
        self.pr.setMouseEnabled(False, False)
        self.pr.hideButtons()
        self.pr.setMenuEnabled(False)
        self.img = pg.ImageItem()
        self.pr.addItem(self.img)
        self.barra = pg.ColorBarItem(
            values=(cfg.PISO_DEF, cfg.TECHO_DEF), label="dB", width=16,
            colorMap=pg.colormap.getFromMatplotlib(self.radar.mapa_color))
        self.barra.setImageItem(self.img, insert_in=self.pr)
        self.barra.sigLevelsChangeFinished.connect(self._barra_movida)
        self.linea_traza = self.pr.plot(pen=pg.mkPen(CELESTE, width=1.2),
                                        connect="finite")
        # Las marcas de cambio: tramos a tiempo constante, de a pares de
        # puntos. Rojas con borde blanco, para que se vean sobre cualquier
        # mapa de colores.
        self.borde_marca = self.pr.plot(pen=pg.mkPen("w", width=4),
                                        connect="pairs")
        self.lineas_marca = self.pr.plot(pen=pg.mkPen(ROJO, width=2),
                                         connect="pairs")

        self.pf = self.gl.addPlot(row=1, col=0)
        self.pf.setXLink(self.pr)
        self.pf.setLabel("left", "dB", **NEGRITA)
        self.pf.setMouseEnabled(False, False)
        self.pf.hideButtons()
        self.pf.setMenuEnabled(False)
        self.pf.showGrid(x=True, y=True, alpha=0.25)
        self.curva_fft = self.pf.plot(pen=pg.mkPen(AZUL, width=1.5))
        self.marca = pg.InfiniteLine(angle=90, pen=pg.mkPen(
            ROJO, style=QtCore.Qt.PenStyle.DashLine))
        self.pf.addItem(self.marca)
        self.gl.ci.layout.setRowStretchFactor(0, 3)
        self.gl.ci.layout.setRowStretchFactor(1, 1)
        # La barra de color le saca ancho al radargrama: la FFT deja el mismo
        # hueco a la derecha, asi las distancias de los dos quedan a plomo.
        self.pf.layout.setColumnFixedWidth(5, 62)
        for eje in (self.pr.getAxis("left"), self.pr.getAxis("bottom"),
                    self.pf.getAxis("left"), self.pf.getAxis("bottom")):
            eje.setTickFont(letra_negrita())
        self.pr.getAxis("left").setWidth(62)
        self.pf.getAxis("left").setWidth(62)

        # Cartel grande sobre el radargrama (cuenta regresiva, falta de sync).
        self.cartel = QtWidgets.QLabel(self.gl)
        self.cartel.setStyleSheet("background: #c00000; color: white; "
                                  "font-size: 26px; font-weight: bold; "
                                  "padding: 10px 18px;")
        self.cartel.hide()
        return self.gl

    def _armar_derecha(self):
        panel = QtWidgets.QWidget()
        panel.setFixedWidth(440)
        col = QtWidgets.QVBoxLayout(panel)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(3)
        # El cuadro de informacion va en dos columnas, para que entre de alto.
        mono = QtGui.QFontDatabase.systemFont(
            QtGui.QFontDatabase.SystemFont.FixedFont)
        mono.setPointSize(8)
        mono.setWeight(QtGui.QFont.Weight.DemiBold)
        dos = QtWidgets.QHBoxLayout()
        self.info, self.info2 = QtWidgets.QLabel(), QtWidgets.QLabel()
        for rotulo in (self.info, self.info2):
            rotulo.setFont(mono)
            rotulo.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
            dos.addWidget(rotulo, 1)
        col.addLayout(dos, 1)

        # La triangular, DIBUJADA con lo que se sabe de ella: cuanto duran la
        # subida y la bajada (del sync) y los vertices de config.py.
        self.ptri = pg.PlotWidget()
        self.ptri.setFixedHeight(125)
        self.ptri.setTitle("Triangular (dibujada): en color, lo que se usa",
                           size="8pt")
        self.ptri.setLabel("bottom", "tiempo [ms]", **NEGRITA)
        self.ptri.setLabel("left", "V", **NEGRITA)
        self.ptri.setMouseEnabled(False, False)
        self.ptri.hideButtons()
        self.ptri.setMenuEnabled(False)
        self.tri_toda = self.ptri.plot(pen=pg.mkPen((110, 114, 124), width=1.5))
        self.tri_sub = self.ptri.plot(pen=pg.mkPen(AZUL, width=3))
        self.tri_baj = self.ptri.plot(pen=pg.mkPen(NARANJA, width=3))
        col.addWidget(self.ptri)

        self.prampa = pg.PlotWidget()
        self.prampa.setFixedHeight(135)
        self.prampa.setTitle("Última rampa (en gris, lo que no se usa)", size="8pt")
        self.prampa.setLabel("bottom", "posición en la rampa [%]  (0 valle, "
                                       "100 cima)", **NEGRITA)
        self.prampa.setMouseEnabled(False, False)
        self.prampa.hideButtons()
        self.prampa.setMenuEnabled(False)
        self.prampa.setXRange(0, 100, padding=0)
        self.curva_sub = self.prampa.plot(pen=pg.mkPen(AZUL))
        self.curva_baj = self.prampa.plot(pen=pg.mkPen(NARANJA))
        self.zona_valle = pg.LinearRegionItem((0, 0), movable=False, brush=GRIS,
                                              pen=pg.mkPen(None))
        self.zona_cima = pg.LinearRegionItem((100, 100), movable=False,
                                             brush=GRIS, pen=pg.mkPen(None))
        self.prampa.addItem(self.zona_valle)
        self.prampa.addItem(self.zona_cima)
        col.addWidget(self.prampa)

        # Los dos deslizadores: el de abajo, al subir, saca muestras del
        # valle; el de arriba, al bajar, saca muestras de la cima.
        self.rot_valle = QtWidgets.QLabel()
        self.des_valle = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.des_valle.setRange(0, cfg.VALLE_MAX)
        self.rot_cima = QtWidgets.QLabel()
        self.des_cima = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.des_cima.setRange(cfg.CIMA_MIN, 100)
        self.des_cima.setValue(100)
        # El tercero corre los limites de las rampas: atraso del batido
        # respecto del sync, en pasos de 10 us.
        self.rot_retardo = QtWidgets.QLabel()
        self.des_retardo = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.des_retardo.setRange(-RETARDO_MAX_US // 10, RETARDO_MAX_US // 10)
        self.des_retardo.setValue(int(round(self.radar.retardo * 1e5)))
        self.des_retardo.setPageStep(10)
        for d in (self.des_valle, self.des_cima):
            d.valueChanged.connect(self._mover_ventana)
        self.des_retardo.valueChanged.connect(self._mover_retardo)
        for d in (self.des_valle, self.des_cima, self.des_retardo):
            # La marca va donde EMPIEZA el cambio: al agarrar el deslizador,
            # o en cada paso si se lo mueve con el teclado o la rueda.
            d.sliderPressed.connect(self.radar.marcar)
            d.valueChanged.connect(
                lambda _, d=d: d.isSliderDown() or self.radar.marcar())
            d.sliderReleased.connect(self.guardar_config)
        for w in (self.rot_valle, self.des_valle, self.rot_cima, self.des_cima,
                  self.rot_retardo, self.des_retardo):
            col.addWidget(w)
        self.boton_auto = QtWidgets.QPushButton("ajustar el retardo solo")
        self.boton_auto.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        self.boton_auto.clicked.connect(self.auto_retardo)
        col.addWidget(self.boton_auto)
        self._mover_ventana()
        self._mover_retardo()
        return panel

    # --- controles ---

    def _poner(self, nombre, valor):
        """Escribe un cuadro sin disparar su callback."""
        c = self.cajas[nombre]
        c.blockSignals(True)
        c.setValue(valor)
        c.blockSignals(False)

    def _refrescar_cajas(self):
        r = self.radar
        for n in ("n_rampas", "ventana", "alcance", "piso", "techo", "ignorar",
                  "margen"):
            self._poner(n, getattr(r, n))
        self._poner("dist_real", self.dist_real)
        self._poner("espera", self.espera)
        self._poner("d_ref", self.d_ref)
        self.barra.blockSignals(True)
        self.barra.setLevels((r.piso, r.techo))
        self.barra.blockSignals(False)
        self.boton_mti.setText("auto: SI (f)" if r.mti else "auto (f)")

    def _escribir(self, nombre, v):
        r = self.radar
        if nombre == "n_rampas":
            r.n_rampas = int(v)
        elif nombre == "piso":
            r.piso = min(v, r.techo - 1.0)
        elif nombre == "techo":
            r.techo = max(v, r.piso + 1.0)
        elif nombre in ("dist_real", "espera", "d_ref"):
            setattr(self, nombre, float(v))
        else:
            setattr(r, nombre, float(v))
        if nombre == "ignorar" and r.proc is not None:
            r.recalcular_fondo()
        if nombre not in SOLO_VISTA:
            r.marcar()
        self._rango = None
        self._refrescar_cajas()
        self.guardar_config()

    def _barra_movida(self, barra):
        self.radar.piso, self.radar.techo = barra.levels()
        self._refrescar_cajas()
        self.guardar_config()

    def _cambiar_sentido(self, texto):
        self.radar.sentido = texto
        self.radar.marcar()
        self.guardar_config()

    def _cambiar_fft(self, texto):
        self.radar.fijar_fft(texto)
        self.radar.marcar()
        self.guardar_config()

    def _poner_curva(self, medida):
        self.combo_curva.blockSignals(True)
        self.combo_curva.setCurrentText(CURVAS[1 if medida else 0])
        self.combo_curva.blockSignals(False)

    def _cambiar_curva(self, texto):
        r = self.radar
        if texto == CURVAS[1] and r.barrido_medido is None:
            self.aviso = "todavia no hay una curva medida: usar 'medir curva'"
            self._poner_curva(False)
            return
        r.usar_barrido(r.barrido_medido if texto == CURVAS[1] else None)
        r.marcar()
        self.guardar_config()

    def calibrar_barrido(self):
        """Mide f(t) con un retardo conocido, o cancela si ya esta midiendo."""
        r = self.radar
        if r._cal is not None:
            r.cancelar_calibracion()
            self.aviso = "medicion del barrido cancelada"
        elif r.proc is None or not r.hay_sync():
            self.aviso = "barrido: no hay rampas para medir"
        else:
            if self.ajuste is not None:
                self._terminar_auto("ajuste del retardo cancelado")
            r.calibrar_barrido(self.d_ref)
            self._seguir_retardo()
            self.aviso = (f"midiendo el barrido {cfg.CAL_BARRIDO_S:.0f} s: tiene "
                          "que estar el barrel puesto, sin antenas")

    def _atender_barrido(self):
        r = self.radar
        self.boton_barrido.setText("cancelar" if r._cal is not None
                                   else "medir curva")
        if r.cal_mensaje is None:
            return
        self.aviso, r.cal_mensaje = r.cal_mensaje, None
        if r.barrido is not None and r.barrido is r.barrido_medido:
            try:
                r.guardar_barrido()
            except OSError as e:
                self.aviso += f" (no se pudo guardar: {e})"
            self._poner_curva(True)
            self.guardar_config()

    def _cambiar_color(self, texto):
        self.radar.mapa_color = texto
        self.barra.setColorMap(pg.colormap.getFromMatplotlib(texto))
        self.guardar_config()

    def _cambiar_sps(self, texto):
        self.aviso = f"reiniciando la placa a {texto} sps"
        threading.Thread(target=self.fuente.arrancar, args=(int(texto),),
                         daemon=True).start()
        self.guardar_config()

    def _mover_ventana(self, _=None):
        lo, hi = self.des_valle.value(), self.des_cima.value()
        self.radar.fijar_ventana(lo / 100.0, hi / 100.0)
        self.zona_valle.setRegion((0, lo))
        self.zona_cima.setRegion((hi, 100))
        mapa = self.radar.proc.mapa if self.radar.proc else None

        def detalle(u):
            if mapa is None:
                return ""
            f = float(np.interp(u, mapa.u, mapa.f))
            return f"  ({mapa.v_de_u(u):.2f} V, {f / 1e6:.0f} MHz)"
        self.rot_valle.setText(f"valle: se descarta hasta {lo} %{detalle(lo / 100)}")
        self.rot_cima.setText(f"cima: se usa hasta {hi} %{detalle(hi / 100)}")

    def _mover_retardo(self, _=None):
        us = self.des_retardo.value() * 10
        self.radar.retardo = us * 1e-6
        self.rot_retardo.setText(f"retardo del batido: {us / 1000:+.2f} ms")
        if self.ajuste is not None:        # lo movieron a mano: se suelta
            self._terminar_auto("ajuste del retardo cancelado")

    def auto_retardo(self):
        """Arranca (o cancela) el ajuste automatico del retardo."""
        if self.ajuste is not None:
            self.radar.retardo = self.ajuste.inicial
            self._terminar_auto("ajuste del retardo cancelado")
        elif self.radar.picos_por_sentido() is None:
            self.aviso = "retardo: hace falta un pico claro y la escena quieta"
        else:
            self.radar.marcar()
            self.ajuste = AjusteRetardo(self.radar)
            self.boton_auto.setText("ajustando... (cancelar)")
            self.aviso = "ajustando el retardo: dejar la escena quieta"

    def _terminar_auto(self, mensaje):
        self.ajuste = None
        self.aviso = mensaje
        self.boton_auto.setText("ajustar el retardo solo")
        self._seguir_retardo()
        self.guardar_config()

    def _seguir_retardo(self):
        """Lleva el deslizador a donde esta el retardo del radar."""
        self.des_retardo.blockSignals(True)
        self.des_retardo.setValue(int(round(self.radar.retardo * 1e5)))
        self.des_retardo.blockSignals(False)
        self.rot_retardo.setText(
            f"retardo del batido: {self.radar.retardo * 1e3:+.2f} ms")

    def _dibujar_triangular(self):
        r = self.radar.resumen()
        if not r or not r["tprf"]:
            return
        ts, tb = r["t_subida"] * 1e3, r["t_bajada"] * 1e3
        v0, v1 = cfg.V_MIN, cfg.V_MAX
        v = lambda u: v0 + (v1 - v0) * u
        lo, hi = r["u_lo"], r["u_hi"]
        self.tri_toda.setData([0, ts, ts + tb, 2 * ts + tb],
                              [v0, v1, v0, v1])
        self.tri_sub.setData([ts * lo, ts * hi, np.nan,
                              ts + tb + ts * lo, ts + tb + ts * hi],
                             [v(lo), v(hi), np.nan, v(lo), v(hi)],
                             connect="finite")
        self.tri_baj.setData([ts + tb * (1 - hi), ts + tb * (1 - lo)],
                             [v(hi), v(lo)])
        self.ptri.setXRange(0, 2 * ts + tb, padding=0.02)
        self.ptri.setYRange(0, max(v1, 3.3), padding=0.02)

    def cambiar_eje(self):
        self.radar.en_metros = not self.radar.en_metros
        self._rango = None
        self.guardar_config()

    def autoescala(self):
        m = self.radar.matriz()
        if m is None:
            return
        db = m["db"]
        self.radar.techo = float(np.ceil(np.nanmax(db)))
        self.radar.piso = float(min(np.floor(np.nanpercentile(db, 10)),
                                    self.radar.techo - 10))
        self._refrescar_cajas()
        self.guardar_config()

    def medir_fondo(self):
        self.aviso = self.radar.medir_fondo()
        self.radar.marcar()
        self._refrescar_cajas()

    def alternar_mti(self):
        self.aviso = self.radar.alternar_mti()
        self.radar.marcar()
        self._refrescar_cajas()

    def borrar_fondo(self):
        r = self.radar
        r.borrar_fondo()
        r.piso, r.techo, r.margen = cfg.PISO_DEF, cfg.TECHO_DEF, cfg.MARGEN_DEF
        self.aviso = "fondo borrado"
        r.marcar()
        self._refrescar_cajas()

    def tomar_punto(self):
        pico = self.radar.pico_crudo()
        if pico is None:
            self.aviso = "no hay pico para tomar"
            return
        self.radar.cal.puntos.append((pico, self.dist_real))
        self.aviso = (f"punto {len(self.radar.cal.puntos)}: crudo {pico:.3f} m "
                      f"-> real {self.dist_real:.3f} m")

    def calibrar(self):
        self.aviso = self.radar.cal.ajustar()
        if self.radar.cal.puntos:
            try:
                self.radar.cal.guardar()
            except OSError as e:
                self.aviso = f"no pude guardar la calibracion: {e}"
        self.radar.marcar()
        self._rango = None

    def borrar_cal(self):
        self.radar.cal.borrar()
        try:
            os.remove(cfg.CAL_JSON)
        except OSError:
            pass
        self.aviso = "calibracion borrada"
        self.radar.marcar()
        self._rango = None

    def _grabar_crudo(self, prender):
        f = self.fuente
        if not prender:
            g, f.grabador = f.grabador, None
            if g:
                g.cerrar()
                self.aviso = f"crudo guardado en {os.path.basename(g.ruta)}"
            return
        if f.info_carga is None:
            self.aviso = "todavia no hay datos para grabar"
            self.casilla_crudo.setChecked(False)
            return
        try:
            f.grabador = Grabador(metadatos(f), f.info_carga)
            self.aviso = f"grabando {os.path.basename(f.grabador.ruta)}"
        except OSError as e:
            self.aviso = f"no pude grabar: {e}"
            self.casilla_crudo.setChecked(False)

    # --- captura ---

    def boton_captura(self):
        if self.t_disparo is not None:        # apretar de nuevo cancela
            self.t_disparo = None
            self.aviso = "captura cancelada"
        elif self.espera > 0:
            self.t_disparo = time.monotonic() + self.espera
        else:
            self.guardar_captura()

    def guardar_captura(self):
        g = self.fuente.grabador
        self.aviso, _ = captura.guardar(self.radar, self.caja_nombre.text(),
                                        os.path.basename(g.ruta) if g else None)
        self.guardar_config()

    def _atender_cuenta(self):
        if self.t_disparo is None:
            return None
        falta = self.t_disparo - time.monotonic()
        if falta > 0:
            return f"CAPTURA EN {int(np.ceil(falta))} s"
        self.t_disparo = None
        self.guardar_captura()
        return None

    # --- configuracion ---

    def aplicar_config(self, d):
        r = self.radar
        for n in ("n_rampas", "ventana", "alcance", "ignorar", "piso", "techo",
                  "margen"):
            if n in d:
                setattr(r, n, type(getattr(r, n))(d[n]))
        self.dist_real = float(d.get("dist_real", self.dist_real))
        self.espera = float(d.get("espera", self.espera))
        r.en_metros = bool(d.get("en_metros", r.en_metros))
        if d.get("sentido") in SENTIDOS:
            self.combo_sentido.setCurrentText(d["sentido"])
        if str(d.get("sps")) in [str(x) for x in cfg.SPS_OPCIONES]:
            self.combo_sps.setCurrentText(str(d["sps"]))
        if d.get("ventana_fft") in VENTANAS:
            self.combo_fft.setCurrentText(d["ventana_fft"])
        if d.get("colores") in cfg.MAPAS_COLOR:
            self.combo_color.setCurrentText(d["colores"])
        self.caja_nombre.setText(d.get("nombre_captura", cfg.NOMBRE_CAPTURA_DEF))
        self.des_valle.setValue(int(d.get("valle", 0)))
        self.des_cima.setValue(int(d.get("cima", 100)))
        self.des_retardo.setValue(int(d.get("retardo_us", 0)) // 10)
        self.d_ref = float(d.get("d_ref", self.d_ref))
        if d.get("curva_medida") and r.barrido_medido is not None:
            r.usar_barrido(r.barrido_medido)
            self._poner_curva(True)
        self.casilla_crudo.setChecked(False)
        self._refrescar_cajas()

    def guardar_config(self):
        r = self.radar
        d = {"n_rampas": r.n_rampas, "ventana": r.ventana, "alcance": r.alcance,
             "ignorar": r.ignorar, "dist_real": self.dist_real,
             "espera": self.espera, "en_metros": r.en_metros,
             "sentido": r.sentido, "sps": int(self.combo_sps.currentText()),
             "ventana_fft": r.ventana_fft, "colores": r.mapa_color,
             "d_ref": self.d_ref, "curva_medida": r.barrido is not None,
             "nombre_captura": self.caja_nombre.text(),
             "valle": self.des_valle.value(), "cima": self.des_cima.value(),
             "retardo_us": self.des_retardo.value() * 10}
        # Con fondo, piso, techo y margen valen otra cosa: no se arrastran a
        # la corrida siguiente, que arranca sin fondo.
        if r.fondo is None:
            d.update(piso=r.piso, techo=r.techo, margen=r.margen)
        try:
            os.makedirs(cfg.DATOS, exist_ok=True)
            with open(cfg.CONFIG_JSON, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=2)
        except OSError:
            pass

    # --- refresco ---

    def _poner_cartel(self, texto):
        if not texto:
            self.cartel.hide()
            return
        self.cartel.setText(texto)
        self.cartel.adjustSize()
        self.cartel.move((self.gl.width() - self.cartel.width()) // 2, 40)
        self.cartel.show()

    def refrescar(self):
        t0 = time.perf_counter()
        f, r = self.fuente, self.radar
        r.alimentar(f.tomar())
        self.cuadro += 1
        cartel = self._atender_cuenta()
        if f.error:
            self.aviso = f.error
        if r.proc is None:
            quieto = time.monotonic() - self.t_inicio > 2.0
            basura = bytes(f.dec.ultima_basura[-60:]).decode("ascii", "replace")
            self._poner_cartel("LA PLACA NO CONTESTA" if quieto else "")
            self.info.setText("esperando a la placa...\n"
                              + (f"\nllega esto, que no es GPRv3:\n{basura}\n\n"
                                 "tiene cargado el firmware\nadquisicion_sync?"
                                 if quieto and f.dec.basura else ""))
            return
        if self.cuadro == 1 or self.rot_valle.text().endswith("%"):
            self._mover_ventana()
        if not cartel and f.en_vivo and not f.error and not r.hay_sync():
            cartel = "SIN SYNC: no llegan flancos"
        self._poner_cartel(cartel)
        self._atender_barrido()
        if self.ajuste is not None:
            fin = self.ajuste.paso()
            self._seguir_retardo()
            if fin:
                self._terminar_auto(fin)

        m = r.matriz()
        if m is not None:
            # La fila mas nueva va abajo: el eje y es "hace cuanto".
            self.img.setImage(np.nan_to_num(m["db"][::-1], nan=-300.0),
                              autoLevels=False)
            self.img.setRect(QtCore.QRectF(m["d0"], 0.0, m["d1"] - m["d0"],
                                           m["span"]))
            self.linea_traza.setData(*r.traza(m))
            t = np.repeat(np.asarray(m["marcas"], dtype=float), 2)
            x = np.tile([m["d0"], m["d1"]], len(t) // 2)
            self.borde_marca.setData(x, t)
            self.lineas_marca.setData(x, t)
            rango = (m["d0"], m["d1"], r.ventana, r.piso, r.techo, r.en_metros)
            if rango != self._rango:
                self._rango = rango
                self.pr.setXRange(m["d0"], m["d1"], padding=0)
                self.pr.setYRange(0, r.ventana, padding=0)
                self.pf.setYRange(r.piso, r.techo + 3, padding=0)
                self.pf.setLabel("bottom", "Distancia [m]" if r.en_metros
                                 else "Frecuencia de batido [Hz]", **NEGRITA)
            c = captura.curva_fft(r)
            i1 = r._i_alcance()
            eje = r.eje_x()
            self.curva_fft.setData(eje[:i1], c[1][:i1])
            pico = r.pico_crudo()
            self.marca.setVisible(pico is not None)
            if pico is not None:
                self.marca.setPos(float(np.interp(pico, r.eje_m_crudo, eje)))
            tr = r.t_rampa()
            if tr:
                self.pr.setTitle(f"Radargrama - {r.n_ef} rampas por fila "
                                 f"({r.n_ef * tr * 1e3:.0f} ms)", size="10pt")
        self._poner_estado()
        if self.cuadro % 3 == 0:
            self._poner_info()
            self._dibujar_triangular()
            for sube, curva in ((True, self.curva_sub), (False, self.curva_baj)):
                if r.ultima[sube] is not None:
                    u, v = r.ultima[sube]
                    curva.setData(u * 100, v / 8388608 * 100)
        self.ms_cuadro += 0.1 * ((time.perf_counter() - t0) * 1e3 - self.ms_cuadro)

    def _poner_estado(self):
        r = self.radar
        pico = r.pico_crudo()
        lin_pico = ("pico: -" if pico is None else
                    f"pico: {float(r.cal.aplicar(pico)):.3f} m  (crudo {pico:.3f})")
        if r.fondo is None:
            lin_fondo = "fondo: sin medir (0 dB = máximo en pantalla)"
        else:
            e = r.energia_actual_db()
            lin_fondo = (f"fondo {'AUTO (MTI)' if r.mti else 'medido'}: "
                         f"{0.0 if e is None else e:+.1f} dB sobre el fondo -> "
                         f"{'HAY BLANCO' if r.hay_blanco() else 'sin blanco'}")
        cal = (f"d = {r.cal.a:.4f}·crudo {r.cal.b:+.3f} m" if r.cal.activa
               else "sin calibrar")
        self.estado.setText(f"<b>{lin_pico}</b><br>{lin_fondo}<br>"
                            f"calibración: {cal} ({len(r.cal.puntos)} puntos)"
                            f"<br><br>{self.aviso}")

    def _poner_info(self):
        f = self.fuente
        g = f.grabador
        e = f.estado
        crudo = (f"{os.path.basename(g.ruta)} ({g.total / 1e6:.1f} MB)"
                 if g else "no")
        # El diagnostico del enlace va abajo, en la barra de estado.
        self.statusBar().showMessage(
            f"fuente {f.nombre}   |   corriendo "
            f"{(time.monotonic() - self.t_inicio) / 60:.1f} min   |   "
            f"paquetes {f.dec.paquetes}   |   bytes malos {f.dec.basura}   |   "
            f"huecos {len(self.radar.muestras.huecos)}   |   placa: desbordes "
            f"{e.get('desbordes', 0)}, descartados {e.get('descartados', 0)}"
            f"   |   crudo a disco: {crudo}   |   {self.ms_cuadro:.1f} ms/cuadro")
        izq, _, der = captura.texto_info(self.radar).partition("\n\n-- barrido")
        self.info.setText(izq)
        self.info2.setText("-- barrido" + der if der else "")

    # --- teclado y cierre ---

    def keyPressEvent(self, ev):
        accion = {"e": self.cambiar_eje, "a": self.autoescala,
                  "f": self.alternar_mti, "s": self.boton_captura,
                  "q": self.close}.get(ev.text().lower())
        if accion:
            accion()
        else:
            super().keyPressEvent(ev)

    def closeEvent(self, ev):
        self.timer.stop()
        self.guardar_config()
        self.fuente.cerrar()
        super().closeEvent(ev)


def main():
    ap = argparse.ArgumentParser(description="GPRv3 - radargrama en vivo")
    ap.add_argument("--sintetico", action="store_true",
                    help="sin placa: blancos simulados")
    ap.add_argument("--archivo", help="reproduce una grabacion .gpr3")
    ap.add_argument("--velocidad", type=float, default=1.0,
                    help="con --archivo, cuantas veces mas rapido")
    args = ap.parse_args()

    curva = cargar_curva()
    cal = Calibracion()
    fecha = cal.cargar()
    print(f"Calibracion de distancia del {fecha}: d = {cal.a:.4f}*crudo "
          f"{cal.b:+.3f} m" if fecha else
          "Sin calibracion de distancia: el eje esta crudo.")
    config = cargar_config()
    sps = config.get("sps", cfg.SPS_DEF)
    if sps not in cfg.SPS_OPCIONES:
        sps = cfg.SPS_DEF

    if args.archivo:
        fuente = FuenteArchivo(args.archivo, args.velocidad)
    elif args.sintetico:
        import sintetico
        fuente = FuenteSintetica(curva, sintetico.banco_demo(), sps)
    else:
        fuente = FuenteSerie(sps)
        print(f"Puerto: {fuente.nombre}")

    app = QtWidgets.QApplication(sys.argv[:1])
    tema_oscuro(app)
    radar = Radar(curva, cal)
    b = radar.cargar_barrido()
    if b:
        print(f"Hay una curva del barrido medida el {b['fecha']} "
              f"(Tprf {b['tprf_ms']} ms).")
    ventana = Ventana(fuente, radar, config)
    fuente.start()
    ventana.showMaximized()
    app.exec()


if __name__ == "__main__":
    main()
