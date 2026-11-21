"""Figura da respiração: estimativa do PPG (banda lenta) contra a EDR do ECG.

Um ponto por janela de 60 s (passo 1 s) dos 22 registros sit, só onde as duas
EDR concordam. Em azul as válidas, em cinza as que o módulo marca como
inválidas (qualidade baixa ou pico na ponta da grade).

uv run python -m analise.plota_respiracao ../docs/src/assets/respiracao.png
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from analise import physionet, respiracao

AZUL = "#2a78d6"
TINTA, TINTA_2, MUDA = "#0b0b0b", "#52514e", "#898781"
GRADE, EIXO, FUNDO = "#e1e0d9", "#c3c2b7", "#fcfcfb"


def figura(destino: Path) -> None:
    janelas = []
    for nome in (f"s{i}_sit" for i in range(1, 23)):
        janelas += respiracao.avalia(physionet.carrega(nome))
    ref = np.array([j.ref_rpm for j in janelas])
    est = np.array([j.rpm for j in janelas])
    valida = np.array([j.qualidade for j in janelas]) >= respiracao.QUALIDADE_MIN

    fig, ax = plt.subplots(figsize=(6.4, 6), facecolor=FUNDO)
    ax.set_facecolor(FUNDO)
    ax.grid(True, color=GRADE, linewidth=0.6)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(EIXO)
    ax.tick_params(colors=MUDA, labelcolor=TINTA_2, labelsize=9)

    lim = (4, 31)
    ax.fill_between(lim, [lim[0] - 2, lim[1] - 2], [lim[0] + 2, lim[1] + 2], color=GRADE,
                    alpha=0.6, linewidth=0, label="± 2 rpm")
    ax.plot(lim, lim, color=EIXO, linewidth=1)
    ax.scatter(ref[~valida], est[~valida], s=10, color=MUDA, alpha=0.35, linewidth=0,
               label=f"inválida: {(~valida).sum()}")
    ax.scatter(ref[valida], est[valida], s=12, color=AZUL, alpha=0.6, linewidth=0,
               label=f"válida: {valida.sum()}")
    ax.set_xlim(*lim)
    ax.set_ylim(*lim)
    ax.set_aspect("equal")
    ax.set_xlabel("referência: respiração derivada do ECG (rpm)", color=TINTA_2)
    ax.set_ylabel("PPG, banda lenta (rpm)", color=TINTA_2)
    ax.set_title("Janelas de 60 s, 22 registros sit", loc="left", color=TINTA, fontsize=11)
    ax.legend(frameon=False, fontsize=9, labelcolor=TINTA_2, loc="upper left")

    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=120, bbox_inches="tight", facecolor=FUNDO)
    plt.close(fig)


if __name__ == "__main__":
    figura(Path(sys.argv[1]))
    print(sys.argv[1])
