"""Figura da página do HRV: RR, SDNN e RMSSD num registro bom e num ruim.

Uso (da pasta analise/):

  uv run python -m analise.plota_hrv            grava docs/src/assets/hrv.png
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from analise import hrv, physionet

DESTINO = Path(__file__).resolve().parents[3] / "docs" / "src" / "assets" / "hrv.png"
REGISTROS = ("s1_sit", "s8_sit")


def _serie(saidas, t, campo):
    y = np.array([getattr(s, campo) if s is not None and s.valido else np.nan for s in saidas])
    return t, y


def main() -> None:
    fig, eixos = plt.subplots(3, 2, figsize=(11, 7.5), sharex="col")
    for col, nome in enumerate(REGISTROS):
        r = physionet.carrega(nome)
        t = r.t_picos_ecg
        ref = hrv.roda(hrv.batimentos_de_tempos(t, interpola=True))
        q = hrv.roda(hrv.batimentos_de_tempos(t, interpola=False))
        t_ppg = hrv.casa_ppg_com_ecg(t, hrv.picos_ppg_validacao(r, interpola=True))
        achou = ~np.isnan(t_ppg)
        ok = achou & np.concatenate([[False], achou[:-1]])
        bats = hrv.batimentos_de_tempos(np.where(achou, t_ppg, t + 0.25), True, ok)
        h = hrv.Hrv()
        ppg = [h.processa(b) if a else None for b, a in zip(bats, achou, strict=True)]

        ax = eixos[0, col]
        ax.plot(t[1:], np.diff(t) * 1000, ".", ms=3, label="ECG (gabarito)")
        rr_ppg = np.diff(t_ppg) * 1000
        ax.plot(t[1:], rr_ppg, ".", ms=3, alpha=0.6, label="PPG")
        ax.set_ylabel("RR (ms)")
        ax.set_title(nome)
        ax.legend(fontsize=8, loc="upper right")

        for linha, campo, rotulo in ((1, "sdnn_ms", "SDNN (ms)"), (2, "rmssd_ms", "RMSSD (ms)")):
            ax = eixos[linha, col]
            ax.plot(*_serie(ref, t, campo), lw=2, label="ECG a 500 Hz (gabarito)")
            ax.plot(*_serie(q, t, campo), lw=1, ls="--", label="ECG na grade de 100 Hz")
            ax.plot(*_serie(ppg, t, campo), lw=1, label="PPG a 100 Hz, com parábola")
            ax.set_ylabel(rotulo)
        eixos[1, col].legend(fontsize=8, loc="upper right")
        eixos[2, col].set_xlabel("tempo (s)")
    fig.suptitle(f"HRV no tempo, janela de {hrv.JANELA_S} s")
    fig.tight_layout()
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(DESTINO, dpi=110)
    print(DESTINO)


if __name__ == "__main__":
    main()
