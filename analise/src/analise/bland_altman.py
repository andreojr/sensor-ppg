"""Validação com Bland-Altman: os resultados da cadeia contra o ECG do PhysioNet.

Cada registro (60 s a partir de 30 s, o mesmo trecho da fonte falsa) dá um par
(medida da cadeia, medida do ECG) por grandeza:

  BPM do picos      60000 / média dos RR válidos do picos  x  60 / média dos RR do ECG
  BPM da FFT        média das saídas válidas do espectral  x  BPM do ECG na janela de cada saída
  SDNN (ms)         dos RR válidos do picos                x  dos RR do ECG
  RMSSD (ms)        idem                                   x  idem

Bland-Altman: no eixo x a média dos dois métodos, no y a diferença (cadeia - ECG).
Viés = média das diferenças; limites de concordância = viés ± 1,96 desvio padrão.

O sensor real não tem referência contínua (só o BPM do relógio, anotado à mão
nas tabelas de qualidade.md). Ele entra como comparação qualitativa e limitação,
não aqui: este script só usa o PhysioNet.

Uso (da pasta analise/):

  uv run python -m analise.bland_altman                 tabela + docs/src/assets/bland_altman.png
  uv run python -m analise.bland_altman s1_sit s2_run   só esses registros
  uv run python -m analise.bland_altman --sem-figura    só a tabela
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from analise import FS_HZ, filtro, fonte_falsa, hrv, physionet
from analise.espectral import Espectral, estima
from analise.espectral_validacao import bpm_ecg_janela
from analise.picos import detecta

INICIO_S = 30.0
DURACAO_S = 60.0
JANELA_FFT_S = Espectral().n_janela / FS_HZ
Z95 = 1.96
ATIVIDADES = ("sit", "walk", "run")
DESTINO = Path(__file__).resolve().parents[3] / "docs" / "src" / "assets" / "bland_altman.png"

# (chave, rótulo, unidade)
GRANDEZAS = (
    ("bpm_picos", "BPM do picos", "bpm"),
    ("bpm_fft", "BPM da FFT", "bpm"),
    ("sdnn", "SDNN", "ms"),
    ("rmssd", "RMSSD", "ms"),
)


@dataclass(frozen=True)
class Concordancia:
    """Estatística de Bland-Altman de uma grandeza."""

    n: int
    vies: float
    dp: float
    inferior: float
    superior: float

    @classmethod
    def de(cls, cadeia: np.ndarray, ecg: np.ndarray) -> Concordancia:
        dif = np.asarray(cadeia, float) - np.asarray(ecg, float)
        dif = dif[np.isfinite(dif)]
        if len(dif) < 2:
            return cls(len(dif), math.nan, math.nan, math.nan, math.nan)
        vies = float(np.mean(dif))
        dp = float(np.std(dif, ddof=1))
        return cls(len(dif), vies, dp, vies - Z95 * dp, vies + Z95 * dp)


def _medidas_ppg(f: fonte_falsa.FonteFalsa) -> tuple[np.ndarray, float]:
    """RR válidos (ms) do picos e o BPM deles, no trecho da fonte falsa."""
    batimentos, _ = detecta(f.filtrado_ir)
    rr = np.array([b.rr_ms for b in batimentos if b.rr_valido])
    return rr, (60000.0 / rr.mean() if len(rr) else float("nan"))


def pares_registro(nome: str) -> dict[str, tuple[float, float]]:
    """(cadeia, ecg) de cada grandeza num registro. NaN onde não há medida."""
    f = fonte_falsa.gera(physionet.carrega(nome), INICIO_S, DURACAO_S)
    t_ecg = f.n_pico / FS_HZ
    rr_ecg = np.diff(t_ecg) * 1000.0
    rr_ppg, bpm_ppg = _medidas_ppg(f)

    saidas = [s for s in estima(f.filtrado_ir) if s.valido]
    fft, gab = [], []
    for s in saidas:
        # O filtrado atrasa PPG_ATRASO_AMOSTRAS; o fim da janela, no tempo do ECG, é n menos isso.
        fim = (s.n - filtro.ATRASO) / FS_HZ
        g = bpm_ecg_janela(t_ecg, fim, JANELA_FFT_S)
        if np.isfinite(g):
            fft.append(s.bpm)
            gab.append(g)

    nan = math.nan
    tem = len(rr_ppg) >= 3 and len(rr_ecg) >= 3
    return {
        "bpm_picos": (bpm_ppg, 60000.0 / rr_ecg.mean() if len(rr_ecg) else nan),
        "bpm_fft": (float(np.mean(fft)) if fft else nan, float(np.mean(gab)) if gab else nan),
        "sdnn": (hrv.sdnn(rr_ppg), hrv.sdnn(rr_ecg)) if tem else (nan, nan),
        "rmssd": (hrv.rmssd(rr_ppg), hrv.rmssd(rr_ecg)) if tem else (nan, nan),
    }


def coleta(nomes: list[str]) -> dict[str, np.ndarray]:
    """Pares de todos os registros: chave -> array (n, 2) de (cadeia, ecg), mais 'registro'."""
    por_registro = [pares_registro(n) for n in nomes]
    saida = {k: np.array([p[k] for p in por_registro]) for k, _, _ in GRANDEZAS}
    saida["registro"] = np.array(nomes)
    return saida


def tabela(dados: dict[str, np.ndarray]) -> str:
    linhas = [
        "| Grandeza | Registros | Viés | DP da diferença | Limite inferior | Limite superior |",
        "|---|---|---|---|---|---|",
    ]
    for chave, rotulo, un in GRANDEZAS:
        c = Concordancia.de(dados[chave][:, 0], dados[chave][:, 1])
        linhas.append(
            f"| {rotulo} | {c.n} | {c.vies:+.2f} {un} | {c.dp:.2f} {un} | "
            f"{c.inferior:+.2f} {un} | {c.superior:+.2f} {un} |"
        )
    return "\n".join(linhas)


def figura(dados: dict[str, np.ndarray], destino: Path = DESTINO) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cores = {"sit": "#1b9e77", "walk": "#d95f02", "run": "#7570b3"}
    fig, eixos = plt.subplots(2, 2, figsize=(11, 8))
    atividade = np.array([n.rsplit("_", 1)[1] for n in dados["registro"]])
    for ax, (chave, rotulo, un) in zip(eixos.ravel(), GRANDEZAS, strict=True):
        cadeia, ecg = dados[chave][:, 0], dados[chave][:, 1]
        media, dif = (cadeia + ecg) / 2, cadeia - ecg
        for a in ATIVIDADES:
            m = atividade == a
            ax.scatter(media[m], dif[m], s=18, color=cores[a], label=a, alpha=0.85)
        c = Concordancia.de(cadeia, ecg)
        ax.axhline(0, color="0.7", lw=0.8)
        ax.axhline(c.vies, color="k", lw=1.2)
        for lim in (c.inferior, c.superior):
            ax.axhline(lim, color="k", lw=1, ls="--")
        for y, txt in ((c.vies, "viés"), (c.superior, "+1,96 DP"), (c.inferior, "−1,96 DP")):
            ax.annotate(
                f"{txt} {y:+.1f}",
                (1, y),
                xycoords=("axes fraction", "data"),
                xytext=(-4, 3),
                textcoords="offset points",
                ha="right",
                fontsize=8,
            )
        ax.set_title(f"{rotulo} (n = {c.n})")
        ax.set_xlabel(f"média cadeia e ECG ({un})")
        ax.set_ylabel(f"cadeia − ECG ({un})")
    eixos[0, 0].legend(fontsize=8, loc="upper left")
    fig.suptitle("Bland-Altman: cadeia do sensor-ppg contra o ECG do PhysioNet")
    fig.tight_layout()
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=110)
    return destino


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("registros", nargs="*", help="ex.: s1_sit s3_run (padrão: todos os 66)")
    p.add_argument("--sem-figura", action="store_true", help="só imprime a tabela")
    args = p.parse_args(argv)

    dados = coleta(args.registros or physionet.registros())
    print(tabela(dados))
    if not args.sem_figura:
        print(figura(dados))


if __name__ == "__main__":
    main()
