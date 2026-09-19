import os
import numpy as np
import matplotlib.pyplot as plt

AQUI = os.path.dirname(os.path.abspath(__file__))
ARCHIVO = os.path.join(AQUI, "SDS00001.CSV")


t, v = [], []
with open(ARCHIVO) as f:
    for linea in f:
        c = linea.strip().split(",")
        if len(c) >= 5 and c[3].strip() and c[4].strip():
            try:
                t.append(float(c[3])); v.append(float(c[4]))
            except ValueError:
                pass
t, v = np.array(t), np.array(v)
dt = t[1] - t[0]
fs = 1 / dt
N = len(v)

# ventana rectangular (FFT plana), dBV rms
w = np.ones(N)
X = np.fft.rfft((v - v.mean()) * w)
f = np.fft.rfftfreq(N, dt)
Vrms = np.abs(X) / (w.sum() / 2) / np.sqrt(2)
dBV = 20 * np.log10(np.maximum(Vrms, 1e-12))

print(f"N={N}  fs={fs/1e6:.1f} MS/s  ventana={N*dt*1e6:.2f} us  bin={fs/N/1e3:.1f} kHz")
print(f"DC={v.mean():.3f} V   pp={v.max()-v.min():.2f} V   rms AC={np.std(v):.3f} V")
print("picos (sin DC):")
idx = [i for i in range(2, len(dBV)-1) if dBV[i] > dBV[i-1] and dBV[i] > dBV[i+1]]
for i in sorted(idx, key=lambda i: -dBV[i])[:8]:
    print(f"  {f[i]/1e6:8.3f} MHz   {dBV[i]:7.1f} dBV")

fig, ax = plt.subplots(2, 1, figsize=(10, 7))
ax[0].plot(t * 1e6, v, lw=0.8)
ax[0].set_xlabel("t [us]"); ax[0].set_ylabel("V"); ax[0].set_title("VCC 5 V - muestras"); ax[0].grid(alpha=.3)
ax[1].plot(f[1:] / 1e6, dBV[1:], lw=0.8)
ax[1].set_xlabel("f [MHz]"); ax[1].set_ylabel("dBV rms"); ax[1].set_title("FFT (rectangular, sin DC)")
ax[1].grid(alpha=.3)
plt.tight_layout()
plt.savefig(os.path.join(AQUI, "fft_vcc.png"), dpi=130)
