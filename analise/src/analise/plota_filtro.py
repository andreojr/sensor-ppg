"""Figura do filtro: FIR nosso x IIR (Butterworth) e o efeito da fase no pico.

Em cima, o ganho. Embaixo, quanto o pico se desloca contra o filtro de fase
zero (já descontado o atraso nominal), por registro do PhysioNet, contra a
FC. As linhas são o atraso de fase de cada filtro na fundamental,
-fase(f) / (2 pi f) com f = FC / 60, menos o atraso nominal: o que a teoria
prevê se o pico seguisse só a fundamental.

uv run python -m analise.filtro --figura ../docs/src/assets/filtro.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal

from analise import FS_HZ, filtro, physionet

AZUL, LARANJA, AQUA = "#2a78d6", "#eb6834", "#1baf7a"  # slots 1 a 3 da paleta
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


def _filtros() -> dict[str, tuple[str, tuple, float]]:
    """nome -> (cor, (b, a), atraso nominal em amostras)."""
    saida = {f"FIR {filtro.N_COEF} (nosso)": (AZUL, (filtro.coeficientes(), [1.0]),
                                              float(filtro.ATRASO))}
    for ordem, cor in ((2, LARANJA), (4, AQUA)):
        ba = signal.butter(ordem // 2, filtro.BANDA_HZ, btype="band", fs=FS_HZ)
        saida[f"IIR Butterworth {ordem}"] = (cor, ba, 0.0)
    return saida


def figura(destino: Path) -> None:
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(8, 7), facecolor=FUNDO,
                                 gridspec_kw={"hspace": 0.45})
    filtros = _filtros()

    _eixo(a1)
    a1.axvspan(*filtro.BANDA_HZ, color=GRADE, alpha=0.6, linewidth=0)
    for nome, (cor, (b, a), _) in filtros.items():
        f, H = signal.freqz(b, a, worN=np.linspace(0.01, 10, 2000), fs=FS_HZ)
        a1.plot(f, 20 * np.log10(np.maximum(np.abs(H), 1e-6)), color=cor, linewidth=2, label=nome)
    a1.set_xlim(0, 10)
    a1.set_ylim(-80, 5)
    a1.set_xlabel("frequência (Hz)", color=TINTA_2)
    a1.set_ylabel("ganho (dB)", color=TINTA_2)
    a1.set_title("Ganho a 100 Hz; faixa cinza: 0,5 a 4 Hz", loc="left", color=TINTA, fontsize=11)
    a1.legend(frameon=False, fontsize=9, labelcolor=TINTA_2, loc="center right",
               bbox_to_anchor=(1, 0.6))

    _eixo(a2)
    avaliacoes = []
    for nome in (f"s{i}_sit" for i in range(1, 23)):
        avaliacoes += filtro.avalia(physionet.carrega(nome))
    fc = np.linspace(50, 130, 200)
    for nome, (cor, (b, a), atraso) in filtros.items():
        _, H = signal.freqz(b, a, worN=fc / 60, fs=FS_HZ)
        w = 2 * np.pi * fc / 60
        # Fase que sobra depois de descontar o atraso nominal (0 num FIR de fase linear).
        resto = np.angle(H * np.exp(1j * w * atraso / FS_HZ))
        teoria = 1000 * (-resto / w)
        a2.plot(fc, teoria, color=cor, linewidth=1, alpha=0.7)
        pts = [(v.fc_bpm, v.desloc_ms) for v in avaliacoes if v.caminho == nome]
        a2.scatter(*zip(*pts), s=36, color=cor, edgecolor=FUNDO, linewidth=1.5, zorder=3,
                   label=nome)
    a2.axhline(0, color=EIXO, linewidth=1)
    a2.set_xlim(50, 130)
    a2.set_ylim(-250, 100)
    a2.set_xlabel("FC do registro (bpm)", color=TINTA_2)
    a2.set_ylabel("pico − pico de fase zero (ms)", color=TINTA_2)
    a2.set_title("Efeito da fase no pico, 22 registros sit (pontos: medido; linhas: fundamental)",
                 loc="left", color=TINTA, fontsize=11)
    a2.legend(frameon=False, fontsize=9, labelcolor=TINTA_2, loc="lower right")

    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=120, bbox_inches="tight", facecolor=FUNDO)
    plt.close(fig)
