"""Figura do LF/HF na página do HRV: espectro de uma janela e LF/HF por janela.

Uso (da pasta analise/):

  uv run python -m analise.plota_hrv_freq       grava docs/src/assets/hrv_freq.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
import matplotlib.ticker

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from analise import hrv_freq, physionet

DESTINO = Path(__file__).resolve().parents[3] / "docs" / "src" / "assets" / "hrv_freq.png"
REGISTRO = "s1_sit"


def main() -> None:
    r = physionet.carrega(REGISTRO)
    t, rr = hrv_freq._serie_ecg(r)
    fig, (esp, tempo) = plt.subplots(1, 2, figsize=(11, 3.8))

    # Espectro da última janela de 300 s, na grade da nossa conta (k / 300 Hz).
    k = len(t) - 1
    tj, rj = hrv_freq._janela(t, rr, k, hrv_freq.JANELA_S)
    y = hrv_freq.prepara(hrv_freq.reamostra(tj, rj))
    f = np.arange(1, hrv_freq.K_FIM + 30) / hrv_freq.JANELA_S
    x = np.exp(-2j * np.pi * np.outer(f, np.arange(len(y))) / hrv_freq.FS_REAMOSTRA) @ y
    p = np.abs(x) ** 2
    esp.plot(f, p / p.max(), color="0.2", lw=1)
    esp.axvspan(0.04, 0.15, color="tab:blue", alpha=0.15, label="LF (0,04 a 0,15 Hz)")
    esp.axvspan(0.15, 0.40, color="tab:orange", alpha=0.15, label="HF (0,15 a 0,40 Hz)")
    esp.set_xlabel("frequência (Hz)")
    esp.set_ylabel("|X(f)|², normalizado")
    esp.set_title(f"{REGISTRO}, últimos 300 s: LF/HF = {hrv_freq.lf_hf(tj, rj):.2f}")
    esp.legend(fontsize=8)

    # LF/HF a cada batimento, por janela, depois dos primeiros 300 s.
    ks = np.flatnonzero(t >= r.t_picos_ecg[0] + hrv_freq.JANELA_S)
    for w, cor in ((60, "tab:red"), (120, "tab:green"), (300, "k")):
        v = [hrv_freq.lf_hf(*hrv_freq._janela(t, rr, j, w)) for j in ks]
        tempo.plot(t[ks], v, color=cor, lw=1.5 if w == 300 else 1, label=f"janela de {w} s")
    tempo.set_yscale("log")
    tempo.yaxis.set_major_formatter(matplotlib.ticker.ScalarFormatter())
    tempo.yaxis.set_minor_formatter(matplotlib.ticker.ScalarFormatter())
    tempo.set_xlabel("tempo (s)")
    tempo.set_ylabel("LF/HF (escala log)")
    tempo.set_title("A mesma pessoa, a cada batimento")
    tempo.legend(fontsize=8)

    fig.tight_layout()
    fig.savefig(DESTINO, dpi=110)
    print(DESTINO)


if __name__ == "__main__":
    main()
