"""Figura da decimação: FIR nosso x média interna do sensor (SMP_AVE = 4), a 400 Hz.

Em cima, a resposta em frequência, com as faixas que dobram pra dentro de 0 a
10 Hz depois da decimação. Embaixo, o espectro do bruto a 100 Hz de um trecho
do PhysioNet com cintilação de lâmpada a 120 Hz somada (vira 20 Hz).

uv run python -m analise.decimacao --figura ../docs/src/assets/decimacao.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal

from analise import FS_HZ, decimacao, fonte_falsa, physionet

FS = 400
CINTILACAO_HZ = 120.0
CINTILACAO_PCT = 0.5  # % do DC

AZUL, LARANJA = "#2a78d6", "#eb6834"  # slots 1 e 2 da paleta categórica
TINTA, TINTA_2, MUDA = "#0b0b0b", "#52514e", "#898781"
GRADE, EIXO, FUNDO = "#e1e0d9", "#c3c2b7", "#fcfcfb"


def _eixo(ax: plt.Axes) -> None:
    ax.set_facecolor(FUNDO)
    ax.grid(True, color=GRADE, linewidth=0.6)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(EIXO)
    ax.tick_params(colors=MUDA, labelcolor=TINTA_2, labelsize=9)


def figura(destino: Path) -> None:
    h = decimacao.coeficientes(FS)
    caixa = np.ones(decimacao.fator(FS)) / decimacao.fator(FS)

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 6.4), facecolor=FUNDO,
                                 gridspec_kw={"hspace": 0.45})

    # Resposta em frequência.
    _eixo(a1)
    for k in range(1, FS // (2 * FS_HZ) + 1):
        a1.axvspan(k * FS_HZ - 10, k * FS_HZ + 10, color=GRADE, alpha=0.6, linewidth=0)
    for coef, cor, nome in ((h, AZUL, f"FIR nosso ({len(h)} coef.)"),
                            (caixa, LARANJA, "média do sensor (SMP_AVE = 4)")):
        f, H = signal.freqz(coef, worN=4096, fs=FS)
        a1.plot(f, 20 * np.log10(np.maximum(np.abs(H), 1e-6)), color=cor, linewidth=2, label=nome)
    a1.set_xlim(0, FS / 2)
    a1.set_ylim(-110, 5)
    a1.set_xlabel("frequência na entrada (Hz)", color=TINTA_2)
    a1.set_ylabel("ganho (dB)", color=TINTA_2)
    a1.set_title("Resposta a 400 Hz; faixas cinza dobram para 0 a 10 Hz",
                 loc="left", color=TINTA, fontsize=11)
    a1.legend(frameon=False, fontsize=9, labelcolor=TINTA_2, loc="center right")

    # Espectro do bruto com cintilação de 120 Hz.
    _eixo(a2)
    r = physionet.carrega().recorta(30, 90)
    ir = np.round(signal.resample_poly(r.ir, fonte_falsa.FS_SENSOR_HZ, r.fs_hz))
    t = np.arange(len(ir)) / FS
    ir = ir + CINTILACAO_PCT / 100 * ir.mean() * np.sin(2 * np.pi * CINTILACAO_HZ * t)
    for y, cor, nome in ((decimacao.decima(ir, FS), AZUL, "FIR nosso"),
                         (decimacao.media_sensor(ir, FS), LARANJA, "média do sensor")):
        f, p = signal.welch(y - y.mean(), fs=FS_HZ, nperseg=1024)
        a2.semilogy(f, p, color=cor, linewidth=2, label=nome)
    a2.text(CINTILACAO_HZ - FS_HZ + 0.8, 1e3, f"{CINTILACAO_HZ:g} Hz dobrado em 20 Hz",
            color=TINTA_2, fontsize=9)
    a2.set_xlim(0, FS_HZ / 2)
    a2.set_xlabel("frequência no bruto a 100 Hz (Hz)", color=TINTA_2)
    a2.set_ylabel("densidade (contagens²/Hz)", color=TINTA_2)
    pct = f"{CINTILACAO_PCT:g}".replace(".", ",")
    a2.set_title(f"s1_sit com cintilação de {CINTILACAO_HZ:g} Hz ({pct}% do DC)",
                 loc="left", color=TINTA, fontsize=11)
    a2.legend(frameon=False, fontsize=9, labelcolor=TINTA_2, loc="upper right")

    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=120, bbox_inches="tight", facecolor=FUNDO)
    plt.close(fig)
