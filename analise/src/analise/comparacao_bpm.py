"""Comparação do BPM por picos × pela FFT, tendo o ECG como gabarito.

Os dois módulos recebem o mesmo filtrado (fonte falsa, 60 s a partir de 30 s) e são
lidos nos mesmos instantes: os do espectral, a cada HOP_S, com a janela de JANELA_S.
Em cada instante t (no tempo do ECG, descontado o PPG_ATRASO_AMOSTRAS):

  picos      o último bpm_picos que o módulo tinha emitido até a amostra daquele instante
             (média dos últimos 8 RR válidos; "segura" entre batimentos)
  espectral  o bpm_espectral da janela que terminou ali
  ECG        60 / média dos RR dentro da mesma janela de JANELA_S do espectral

Métricas por método e por registro:

  erro        |BPM - BPM do ECG na janela|, mediana e p95, em bpm
  atraso      quantos segundos antes de t o BPM mais combina com a frequência cardíaca
              instantânea do ECG (a mesma medida do espectral_validacao)
  estabilidade  mediana de |BPM[k] - BPM[k-1]| entre saídas seguidas (1 s), em bpm.
              Quanto menor, menos o número treme. O próprio BPM do ECG na janela também
              varia, então ele fica como linha de base (estab_ecg).
  validos     fração dos instantes em que o método deu BPM (valido = true)

Uso (da pasta analise/):
  uv run python -m analise.comparacao_bpm             tabela por registro e por atividade
  uv run python -m analise.comparacao_bpm --figura    grava docs/src/assets/comparacao_bpm.png
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from analise import FS_HZ, filtro
from analise.espectral import JANELA_S, estima
from analise.espectral_validacao import (
    ATRASOS_S,
    REGISTROS,
    bpm_ecg_instantaneo,
    bpm_ecg_janela,
    fonte,
)
from analise.picos import Picos

DESTINO = Path(__file__).resolve().parents[3] / "docs" / "src" / "assets" / "comparacao_bpm.png"
FIGURA_REGISTROS = ("s1_sit", "s1_run", "s2_walk")


@dataclass(frozen=True)
class Metricas:
    erro_mediana: float
    erro_p95: float
    atraso_s: float
    estabilidade: float
    validos: float


@dataclass(frozen=True)
class Comparacao:
    registro: str
    t: np.ndarray  # fim de cada janela, no tempo do ECG (s)
    ecg: np.ndarray  # BPM do ECG na janela
    picos: np.ndarray  # nan onde não há BPM válido
    espectral: np.ndarray
    m_picos: Metricas
    m_espectral: Metricas
    estab_ecg: float


def bpm_picos_em(filtrado: np.ndarray, n_alvo: np.ndarray) -> np.ndarray:
    """O bpm_picos que o módulo tinha depois de processar a amostra n, pra cada n de n_alvo.

    nan antes do primeiro batimento e quando o ritmo não é regular (valido = false).
    """
    p = Picos()
    n_emissao: list[int] = []
    bpm: list[float] = []
    for n, x in enumerate(filtrado):
        if p.processa(x) is not None:
            valido, b = p.bpm
            n_emissao.append(n)
            bpm.append(b if valido else np.nan)
    if not bpm:
        return np.full(len(n_alvo), np.nan)
    i = np.searchsorted(n_emissao, n_alvo, side="right") - 1
    return np.where(i >= 0, np.asarray(bpm)[np.maximum(i, 0)], np.nan)


def estabilidade(bpm: np.ndarray) -> float:
    """Mediana de |BPM[k] - BPM[k-1]| nos pares seguidos em que os dois existem."""
    d = np.abs(np.diff(bpm))
    return float(np.nanmedian(d)) if np.any(~np.isnan(d)) else float("nan")


def metricas(bpm: np.ndarray, t: np.ndarray, t_ecg: np.ndarray, ecg: np.ndarray) -> Metricas:
    erro = np.abs(bpm - ecg)
    sem_dado = np.all(np.isnan(erro))
    medianas = {a: np.nanmedian(np.abs(bpm - bpm_ecg_instantaneo(t_ecg, t - a))) for a in ATRASOS_S}
    return Metricas(
        erro_mediana=float("nan") if sem_dado else float(np.nanmedian(erro)),
        erro_p95=float("nan") if sem_dado else float(np.nanpercentile(erro, 95)),
        atraso_s=float("nan") if sem_dado else float(min(medianas, key=lambda a: medianas[a])),
        estabilidade=estabilidade(bpm),
        validos=float(np.mean(~np.isnan(bpm))),
    )


def compara_sinal(nome: str, filtrado: np.ndarray, t_ecg: np.ndarray) -> Comparacao:
    """Roda os dois módulos no filtrado e compara com os instantes de batimento do ECG (s)."""
    saidas = estima(filtrado)
    n = np.array([s.n for s in saidas])
    # O filtrado chega PPG_ATRASO_AMOSTRAS depois do sinal: o fim da janela, no tempo do ECG,
    # é n menos esse atraso.
    t = (n - filtro.ATRASO) / FS_HZ
    esp = np.array([s.bpm if s.valido else np.nan for s in saidas])
    pic = bpm_picos_em(filtrado, n)
    ecg = np.array([bpm_ecg_janela(t_ecg, tt, JANELA_S) for tt in t])
    return Comparacao(
        nome,
        t,
        ecg,
        pic,
        esp,
        metricas(pic, t, t_ecg, ecg),
        metricas(esp, t, t_ecg, ecg),
        estabilidade(ecg),
    )


def compara(nome: str) -> Comparacao:
    f = fonte(nome)
    return compara_sinal(nome, f.filtrado_ir, f.n_pico / FS_HZ)


def _n(v: float, casas: int = 2) -> str:
    return "--" if np.isnan(v) else f"{v:.{casas}f}".replace(".", ",")


def _par(a: float, b: float, casas: int = 2) -> str:
    return f"{_n(a, casas)} / {_n(b, casas)}"


def _mediana(cs: list[Comparacao], campo: str, atributo: str) -> float:
    return float(np.nanmedian([getattr(getattr(c, campo), atributo) for c in cs]))


def linha(rotulo: str, cs: list[Comparacao]) -> str:
    """Uma linha da tabela (mediana, quando há vários registros): picos / FFT em cada coluna."""

    def par(atributo: str, casas: int = 2) -> str:
        return _par(_mediana(cs, "m_picos", atributo), _mediana(cs, "m_espectral", atributo), casas)

    pct = _par(
        100 * _mediana(cs, "m_picos", "validos"), 100 * _mediana(cs, "m_espectral", "validos"), 0
    )
    return (
        f"| {rotulo} | {par('erro_mediana')} | {par('erro_p95')} | {par('atraso_s', 1)} "
        f"| {par('estabilidade')} | {pct} |"
    )


CABECALHO = (
    "| {} | Erro mediano (bpm) | Erro p95 (bpm) | Atraso (s) | Estabilidade (bpm) | Válidos (%) |\n"
    "|---|---|---|---|---|---|"
)


def tabela(cs: list[Comparacao]) -> str:
    """Markdown: um registro por linha e, no fim, por atividade e geral. Células: picos / FFT."""
    linhas = [CABECALHO.format("Registro"), *(linha(c.registro, [c]) for c in cs)]
    linhas += ["", CABECALHO.format("Atividade (mediana)")]
    for atividade in ("sit", "walk", "run"):
        grupo = [c for c in cs if c.registro.endswith(atividade)]
        if grupo:
            linhas.append(linha(atividade, grupo))
    linhas.append(linha("todos", cs))
    linhas.append(f"\nEstabilidade do próprio ECG (linha de base): {_n(_mediana_ecg(cs))} bpm.")
    linhas.append("\nOnde o picos fica sem BPM parte do tempo, o erro nos instantes em que os dois")
    linhas.append("têm BPM (mediana e p95, picos / FFT):")
    for c in cs:
        if c.m_picos.validos < 1.0:
            linhas.append(f"  {c.registro}: {erro_comum(c)}")
    return "\n".join(linhas)


def erro_comum(c: Comparacao) -> str:
    """Erro dos dois só nos instantes em que os dois têm BPM (sem viés de seleção)."""
    ok = ~np.isnan(c.picos) & ~np.isnan(c.espectral)
    if not ok.any():
        return "nenhum instante em comum"
    ep, ef = np.abs(c.picos - c.ecg)[ok], np.abs(c.espectral - c.ecg)[ok]
    med = _par(float(np.median(ep)), float(np.median(ef)))
    p95 = _par(float(np.percentile(ep, 95)), float(np.percentile(ef, 95)))
    return f"{ok.sum()} instantes, mediana {med}, p95 {p95} bpm"


def _mediana_ecg(cs: list[Comparacao]) -> float:
    return float(np.nanmedian([c.estab_ecg for c in cs]))


def figura(destino: Path = DESTINO) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, eixos = plt.subplots(2, len(FIGURA_REGISTROS), figsize=(12, 6.5), sharex=True)
    for col, nome in enumerate(FIGURA_REGISTROS):
        c = compara(nome)
        ax = eixos[0, col]
        ax.plot(c.t, c.ecg, "k-", lw=2, label="ECG (gabarito)")
        ax.plot(c.t, c.picos, "o-", ms=3, lw=1, label="picos")
        ax.plot(c.t, c.espectral, "s-", ms=3, lw=1, label="espectral (FFT)")
        ax.set_title(nome)
        ax = eixos[1, col]
        ax.plot(c.t, np.abs(c.picos - c.ecg), "o-", ms=3, lw=1)
        ax.plot(c.t, np.abs(c.espectral - c.ecg), "s-", ms=3, lw=1)
        ax.set_xlabel("tempo (s)")
    eixos[0, 0].set_ylabel("BPM")
    eixos[1, 0].set_ylabel("|erro| contra o ECG (bpm)")
    eixos[0, 0].legend(fontsize=8, loc="best")
    fig.suptitle(f"BPM por picos × pela FFT, janela do ECG de {JANELA_S:g} s")
    fig.tight_layout()
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=110)
    return destino


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--figura", action="store_true", help="só grava a figura das páginas")
    args = p.parse_args(argv)
    if args.figura:
        print(figura())
        return
    print(tabela([compara(n) for n in REGISTROS]))


if __name__ == "__main__":
    main()
