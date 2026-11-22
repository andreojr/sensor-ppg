"""Figura da qualidade: o vetor "bordas" (dedo entra, defeitos, dedo sai).

Em cima, o IR bruto com as janelas usáveis em verde. No meio e embaixo, o
índice de perfusão e a aspereza de cada janela, com a faixa aceita.

uv run python -m analise.qualidade --figura ../docs/src/assets/qualidade.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from analise import FS_HZ, qualidade
from analise.plota_decimacao import AZUL, FUNDO, GRADE, LARANJA, MUDA, TINTA, TINTA_2, _eixo

VERDE = "#3c9a5f"
TRECHOS = (  # (início s, rótulo), na ordem de sinal_bordas()
    (0, "sem dedo"), (4.5, "limpo"), (14.5, "saturado"), (18.5, "limpo"), (24.5, "ruído"),
    (28.5, "limpo"), (34.5, "movimento"), (38.5, "limpo"), (44.5, "sem pulso"),
    (48.5, "limpo"), (54, "sem dedo"),
)


def figura(destino: Path) -> None:
    n, ir, vm = qualidade.sinal_bordas()
    saidas = qualidade.roda(ir, vm, n)
    t = np.arange(len(ir)) / FS_HZ
    pos = {int(k): i for i, k in enumerate(n)}
    t_fim = np.array([pos[s.n] / FS_HZ for s in saidas])  # fim de cada janela, em s

    fig, (a1, a2, a3) = plt.subplots(3, 1, figsize=(8, 7.2), facecolor=FUNDO, sharex=True,
                                     gridspec_kw={"hspace": 0.35, "height_ratios": [2, 1, 1]})
    _eixo(a1)
    for s, fim in zip(saidas, t_fim):
        if s.usavel:
            a1.axvspan(fim - 1, fim, color=VERDE, alpha=0.18, linewidth=0)
    a1.plot(t, ir / 1000, color=AZUL, linewidth=0.8)
    for inicio, rotulo in TRECHOS:
        a1.text(inicio + 0.2, 268, rotulo, color=TINTA_2, fontsize=8, rotation=90, va="top")
    a1.axvline(9.5, color=MUDA, linewidth=0.8, linestyle=":")
    a1.set_ylim(0, 270)
    a1.set_ylabel("IR bruto (mil contagens)", color=TINTA_2)
    a1.set_title("Vetor bordas: em verde, o último segundo das janelas usáveis; "
                 "pontilhado: n pula",
                 loc="left", color=TINTA, fontsize=11)

    lim = qualidade.LIMIARES
    for ax, valores, faixa, nome in (
        (a2, [100 * s.pi for s in saidas], (100 * lim.pi_min, 100 * lim.pi_max), "pi (%)"),
        (a3, [s.aspereza for s in saidas], (lim.aspereza_min, lim.aspereza_max), "aspereza"),
    ):
        _eixo(ax)
        ax.axhspan(*faixa, color=GRADE, alpha=0.7, linewidth=0)
        boas = np.array([s.motivo == 0 for s in saidas])
        v = np.array(valores)
        ax.semilogy(t_fim, v, color=MUDA, linewidth=0.8)
        ax.semilogy(t_fim[boas], v[boas], "o", color=VERDE, markersize=3.5, label="janela boa")
        ax.semilogy(t_fim[~boas], v[~boas], "o", color=LARANJA, markersize=3.5,
                    label="janela ruim")
        ax.set_ylabel(nome, color=TINTA_2)
    a2.legend(frameon=False, fontsize=8, labelcolor=TINTA_2, loc="lower right",
               bbox_to_anchor=(1, 0.98), ncols=2)
    a3.set_xlabel("tempo (s); cada ponto é uma janela de 2 s, no instante em que ela fecha",
                  color=TINTA_2)

    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=120, bbox_inches="tight", facecolor=FUNDO)
    plt.close(fig)
