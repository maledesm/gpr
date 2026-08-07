"""
Simulación LPDA en MEEP — Far field 1–1.75 GHz
===============================================
Unidades: 1 MEEP unit = 10 cm
  → f(MEEP) = f(Hz) * 0.10 / 3e10
  → A 1 GHz:   f_meep = 0.333
  → A 1.75 GHz: f_meep = 0.583

Geometría: dipolos PEC sobre boom PEC.
La línea cruzada se modela conectando brazos alternos
al conductor superior/inferior del boom (ver comentario).
"""

import meep as mp
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ─── Conversión de unidades ───────────────────────────────────────────────────

UNIT_CM = 10.0      # 1 MEEP unit = 10 cm
C_CM    = 3e10      # velocidad de la luz en cm/s

def hz2m(f):  return f * UNIT_CM / C_CM   # Hz → MEEP
def m2hz(f):  return f * C_CM / UNIT_CM   # MEEP → Hz
def cm2m(x):  return x / UNIT_CM          # cm → MEEP

# ─── Parámetros de frecuencia ─────────────────────────────────────────────────

F_MIN_HZ = 1.00e9
F_MAX_HZ = 1.75e9
NFREQS   = 30        # frecuencias a evaluar en el farfield

f_min = hz2m(F_MIN_HZ)
f_max = hz2m(F_MAX_HZ)
f_cen = (f_min + f_max) / 2    # 0.458
f_wid = (f_max - f_min) * 1.5  # ancho del pulso (factor 1.5 para asegurar cobertura)

freqs = np.linspace(f_min, f_max, NFREQS)

# ─── Parámetros LPDA ──────────────────────────────────────────────────────────

TAU   = 0.85
SIGMA = 0.12
N_EL  = 8

L1_cm     = 15.0
tan_alpha = (1 - TAU) / (4 * SIGMA)   # = 0.3125
R1_cm     = L1_cm / (2 * tan_alpha)   # = 24.0 cm

# Longitudes y posiciones de cada dipolo (en cm)
L_cm = np.array([L1_cm * TAU**n for n in range(N_EL)])
R_cm = np.array([R1_cm * TAU**n for n in range(N_EL)])

# Convertir a unidades MEEP
L = cm2m(L_cm)   # longitudes totales de cada dipolo
R = cm2m(R_cm)   # distancias desde el vértice

# Centrar la antena en x=0
x_offset = -(R[0] + R[-1]) / 2
boom_x1  = R[-1] + x_offset   # extremo del elemento más corto (feed)
boom_x2  = R[0]  + x_offset   # extremo del elemento más largo

print("Parámetros de la antena:")
for n in range(N_EL):
    print(f"  Elem {n+1}: L={L_cm[n]:.2f} cm  "
          f"R={R_cm[n]:.2f} cm  x={( R[n]+x_offset)*UNIT_CM:.2f} cm")

# ─── Dominio de simulación ────────────────────────────────────────────────────

resolution = 25    # celdas / MEEP unit ≈ λ/29 en f_min (λ/17 en f_max)
                   # Subir a 40 para mayor precisión (4× más tiempo/memoria)

dpml = 1.2         # grosor PML (> λ_max/2 ≈ 1.5 MEEP units — ajustar si hay reflexiones)
pad  = 1.8         # margen entre antena y PML

boom_len = R[0] - R[-1]
max_arm  = L[0] / 2    # brazo más largo = λ/2 @ f_min

sx = boom_len + 2*pad + 2*dpml
sy = max_arm  + 2*pad + 2*dpml
sz = max_arm  + 2*pad + 2*dpml

cell = mp.Vector3(sx, sy, sz)

wire_r = 1.5 / resolution   # radio del hilo PEC (≈ 2 celdas)
gap_src = 2.0 / resolution  # gap de la fuente en el dipolo feed

print(f"\nDominio: {sx*UNIT_CM:.1f} × {sy*UNIT_CM:.1f} × {sz*UNIT_CM:.1f} cm")
print(f"Resolución: {resolution} celdas/unit  ({UNIT_CM/resolution*10:.1f} mm/celda)")
print(f"Total celdas: ~{int(sx*resolution)*int(sy*resolution)*int(sz*resolution)/1e6:.1f} M")

# ─── Geometría PEC ────────────────────────────────────────────────────────────
#
# Línea de transmisión cruzada:
#   Los dipolos pares (n=0,2,4,6) se conectan al conductor superior (+y).
#   Los dipolos impares (n=1,3,5,7) se conectan al conductor inferior (-y).
#   Esto se modela como DOS conductores del boom separados en z:
#   boom_top (z=+wire_r) y boom_bot (z=-wire_r), con barras de conexión
#   alternadas.  Simplificación válida para el patrón de radiación.

geometry = []

# Boom superior e inferior (línea de transmisión cruzada)
for z_sign in [+1, -1]:
    geometry.append(mp.Block(
        size   = mp.Vector3(boom_x2 - boom_x1 + wire_r*2, wire_r*2, wire_r*2),
        center = mp.Vector3((boom_x1+boom_x2)/2, 0, z_sign*wire_r*2),
        material = mp.metal
    ))

# Dipolos
for n in range(N_EL):
    xn   = R[n] + x_offset
    arm  = L[n] / 2          # longitud de cada brazo
    z_side = +1 if n % 2 == 0 else -1   # alternado

    # Barra de conexión al conductor correspondiente del boom
    geometry.append(mp.Block(
        size   = mp.Vector3(wire_r*2, wire_r*2, wire_r*4),
        center = mp.Vector3(xn, 0, z_side * wire_r),
        material = mp.metal
    ))

    # Brazo superior del dipolo
    geometry.append(mp.Block(
        size   = mp.Vector3(wire_r*2, arm - gap_src/2, wire_r*2),
        center = mp.Vector3(xn, arm/2 + gap_src/4, 0),
        material = mp.metal
    ))
    # Brazo inferior del dipolo
    geometry.append(mp.Block(
        size   = mp.Vector3(wire_r*2, arm - gap_src/2, wire_r*2),
        center = mp.Vector3(xn, -arm/2 - gap_src/4, 0),
        material = mp.metal
    ))

# ─── Fuente ───────────────────────────────────────────────────────────────────
# Corriente en el gap del dipolo feed (el más corto, n = N_EL-1)

feed_x = R[-1] + x_offset

sources = [mp.Source(
    src       = mp.GaussianSource(frequency=f_cen, fwidth=f_wid),
    component = mp.Ey,
    center    = mp.Vector3(feed_x, 0, 0),
    size      = mp.Vector3(0, gap_src, 0),
)]

# ─── Near-to-far field ────────────────────────────────────────────────────────
# Caja cerrada que rodea la antena, bien adentro del PML.

nf_dist = pad * 0.75   # distancia desde el centro a cada cara

n2f_regions = [
    mp.Near2FarRegion(center=mp.Vector3( nf_dist, 0, 0),
                      size=mp.Vector3(0, sy-2*dpml, sz-2*dpml), weight=+1),
    mp.Near2FarRegion(center=mp.Vector3(-nf_dist, 0, 0),
                      size=mp.Vector3(0, sy-2*dpml, sz-2*dpml), weight=-1),
    mp.Near2FarRegion(center=mp.Vector3(0,  nf_dist, 0),
                      size=mp.Vector3(sx-2*dpml, 0, sz-2*dpml), weight=+1),
    mp.Near2FarRegion(center=mp.Vector3(0, -nf_dist, 0),
                      size=mp.Vector3(sx-2*dpml, 0, sz-2*dpml), weight=-1),
    mp.Near2FarRegion(center=mp.Vector3(0, 0,  nf_dist),
                      size=mp.Vector3(sx-2*dpml, sy-2*dpml, 0), weight=+1),
    mp.Near2FarRegion(center=mp.Vector3(0, 0, -nf_dist),
                      size=mp.Vector3(sx-2*dpml, sy-2*dpml, 0), weight=-1),
]

# ─── Simulación ───────────────────────────────────────────────────────────────

sim = mp.Simulation(
    cell_size       = cell,
    boundary_layers = [mp.PML(thickness=dpml)],
    geometry        = geometry,
    sources         = sources,
    resolution      = resolution,
    eps_averaging   = False,
)

n2f = sim.add_near2far(f_cen, f_wid, NFREQS, *n2f_regions)

# Correr hasta que los campos decaigan 6 órdenes de magnitud
sim.run(
    until_after_sources=mp.stop_when_fields_decayed(
        dt=50, c=mp.Ey,
        pt=mp.Vector3(feed_x, 0.1, 0),
        decay_by=1e-6
    )
)

# ─── Extracción del farfield ──────────────────────────────────────────────────
# Se calculan dos planos de corte:
#   Plano E (xz, phi=0°):  contiene el eje del boom → muestra directividad axial
#   Plano H (xy, phi=90°): corte transversal

N_ANGLES = 360
theta_rad = np.linspace(0, 2*np.pi, N_ANGLES, endpoint=False)
r_ff = 1e6   # radio farfield (campo lejano, en MEEP units)

# Para cada frecuencia de interés (inicio, centro, fin de banda)
freq_plot = [f_min, f_cen, f_max]
freq_labels = [f"{m2hz(f)/1e9:.2f} GHz" for f in freq_plot]

fig, axes = plt.subplots(1, 3, subplot_kw={"projection": "polar"},
                         figsize=(15, 5))
fig.suptitle("Far Field LPDA — Plano E (φ=0°, plano xz)", fontsize=13)

colors = ["steelblue", "darkorange", "seagreen"]

for ax, fq, label, color in zip(axes, freq_plot, freq_labels, colors):
    # Puntos en el plano xz: y=0
    pts = [mp.Vector3(r_ff*np.sin(th), 0, r_ff*np.cos(th))
           for th in theta_rad]

    ff = sim.get_farfields(n2f, r_ff, theta=theta_rad, phi=np.zeros_like(theta_rad))

    # Potencia normalizada en dB
    Ex = ff["Ex"]
    Ey = ff["Ey"]
    Ez = ff["Ez"]
    E2 = np.abs(Ex)**2 + np.abs(Ey)**2 + np.abs(Ez)**2
    E2_dB = 10 * np.log10(E2 / E2.max() + 1e-12)

    ax.plot(theta_rad, E2_dB, color=color, linewidth=1.2)
    ax.set_title(label, pad=10)
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_rlim(-30, 0)
    ax.set_yticks([-30, -20, -10, 0])
    ax.grid(True, alpha=0.4)

plt.tight_layout()
plt.savefig("farfield_lpda.png", dpi=150)
print("\nGuardado: farfield_lpda.png")
