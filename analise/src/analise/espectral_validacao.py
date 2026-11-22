"""Validação do protótipo espectral contra o ECG do PhysioNet, e estudo da janela.

Gabarito: a frequência cardíaca do ECG. Duas medidas por registro:

  erro    |BPM da FFT - BPM do ECG na mesma janela|: o BPM do ECG é 60 / média
          dos intervalos R-R dentro da janela da FFT. Mede a exatidão.
  atraso  quantos segundos antes do fim da janela o BPM da FFT mais combina
          com a frequência cardíaca instantânea do ECG (RR suavizado em 5
          batimentos). Uma janela longa responde devagar; o atraso mede quanto.

Cada registro: 60 s a partir de 30 s do filtrado_ir da fonte falsa.

Uso (da pasta analise/):
  uv run python -m analise.espectral_validacao            estudo da janela
  uv run python -m analise.espectral_validacao --tabela   um registro por linha
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import cache

import numpy as np

from analise import FS_HZ, filtro, fonte_falsa, physionet
from analise.espectral import Espectral, estima

INICIO_S = 30.0
DURACAO_S = 60.0
REGISTROS = [f"s{i}_{a}" for i in (1, 2, 3, 4, 5) for a in ("sit", "walk", "run")]
ATRASOS_S = np.arange(0.0, 8.01, 0.5)


@cache
def fonte(nome: str) -> fonte_falsa.FonteFalsa:
    return fonte_falsa.gera(physionet.carrega(nome), INICIO_S, DURACAO_S)


def bpm_ecg_janela(t_ecg: np.ndarray, fim_s: float, janela_s: float) -> float:
    """60 / média dos RR dos batimentos dentro de (fim - janela, fim]."""
    dentro = t_ecg[(t_ecg > fim_s - janela_s) & (t_ecg <= fim_s)]
    if len(dentro) < 3:
        return float("nan")
    return 60.0 * (len(dentro) - 1) / (dentro[-1] - dentro[0])


def bpm_ecg_instantaneo(t_ecg: np.ndarray, t: np.ndarray) -> np.ndarray:
    """Frequência cardíaca do ECG em cada instante t, RR suavizado em 5 batimentos."""
    rr = np.diff(t_ecg)
    suave = np.convolve(rr, np.ones(5) / 5, mode="valid")
    t_meio = ((t_ecg[1:] + t_ecg[:-1]) / 2)[2:-2]
    return np.interp(t, t_meio, 60.0 / suave, left=np.nan, right=np.nan)


@dataclass(frozen=True)
class Resultado:
    registro: str
    n: int
    validos: float  # fração de saídas com valido = True
    erro_mediana: float
    erro_p95: float
    atraso_s: float


def valida(nome: str, **parametros) -> Resultado:
    f = fonte(nome)
    janela_s = Espectral(**parametros).n_janela / FS_HZ
    saidas = estima(f.filtrado_ir, **parametros)
    t_ecg = f.n_pico / FS_HZ
    # O filtrado chega PPG_ATRASO_AMOSTRAS (1 s) depois do sinal: o fim da janela,
    # no tempo do ECG, é n menos esse atraso.
    t = (np.array([s.n for s in saidas]) - filtro.ATRASO) / FS_HZ
    bpm = np.array([s.bpm if s.valido else np.nan for s in saidas])

    gabarito = np.array([bpm_ecg_janela(t_ecg, tt, janela_s) for tt in t])
    erro = np.abs(bpm - gabarito)

    instantaneo = {a: bpm_ecg_instantaneo(t_ecg, t - a) for a in ATRASOS_S}
    medianas = {a: np.nanmedian(np.abs(bpm - v)) for a, v in instantaneo.items()}
    atraso = min(medianas, key=lambda a: medianas[a])

    return Resultado(
        nome,
        len(saidas),
        float(np.mean([s.valido for s in saidas])),
        float(np.nanmedian(erro)),
        float(np.nanpercentile(erro, 95)),
        float(atraso),
    )


def resumo(resultados: list[Resultado]) -> tuple[float, float, float, float]:
    return (
        float(np.mean([r.validos for r in resultados])),
        float(np.median([r.erro_mediana for r in resultados])),
        float(np.mean([r.erro_p95 for r in resultados])),
        float(np.median([r.atraso_s for r in resultados])),
    )


def estudo() -> None:
    print("janela  nfft  resolução  válidos  erro med  erro p95  atraso")
    print("------  ----  ---------  -------  --------  --------  ------")
    for janela_s, nfft in [(4, 1024), (6, 1024), (8, 1024), (10, 1024), (12, 2048), (16, 2048)]:
        rs = [valida(n, janela_s=janela_s, nfft=nfft) for n in REGISTROS]
        validos, med, p95, atraso = resumo(rs)
        print(
            f"{janela_s:>4} s  {nfft:>4}  {60 / janela_s:>5.1f} bpm  {validos:>6.1%}  "
            f"{med:>5.2f} bpm  {p95:>5.2f} bpm  {atraso:>4.1f} s"
        )


def tabela(**parametros) -> None:
    print("registro  saídas  válidos  erro med  erro p95  atraso")
    print("--------  ------  -------  --------  --------  ------")
    rs = [valida(n, **parametros) for n in REGISTROS]
    for r in rs:
        print(
            f"{r.registro:<8}  {r.n:>6}  {r.validos:>6.1%}  {r.erro_mediana:>5.2f} bpm  "
            f"{r.erro_p95:>5.2f} bpm  {r.atraso_s:>4.1f} s"
        )
    validos, med, _, atraso = resumo(rs)
    print(
        f"\nmediana dos {len(rs)}: erro {med:.2f} bpm, válidos {validos:.1%}, atraso {atraso:.1f} s"
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--tabela", action="store_true", help="um registro por linha, parâmetros padrão")
    args = p.parse_args()
    tabela() if args.tabela else estudo()


if __name__ == "__main__":
    main()
