"""Filtro: remoção de DC e passa-faixa 0,5 a 4 Hz (protótipo do Core/*/pds/filtro/).

Entra o bruto a 100 Hz (com DC), sai o filtrado (média zero), uma saída por
entrada, com o mesmo n. O C faz a mesma conta; filtra() é a versão vetorizada
de onde saem os vetores de referência.

Projeto (ver docs/src/content/docs/modulos/filtro.md):

  - FIR de fase linear, janela de Hamming, 201 coeficientes, -6 dB em 0,5 e
    4 Hz (como o passa-faixa de referência da fonte falsa). A média dos
    coeficientes é subtraída: ganho em DC exatamente 0.
  - Atraso constante de (N - 1) / 2 = 100 amostras (1 s), em todas as
    frequências: é o PPG_ATRASO_AMOSTRAS do ppg.h. Um IIR (Butterworth) tem
    atraso que depende da frequência, e o pico se desloca conforme a FC: ver
    compara() e a página do módulo.
  - Antes da primeira amostra, o histórico vale a primeira amostra: como o
    ganho em DC é 0, o filtrado começa em 0, sem transiente de DC. Na conta,
    a primeira amostra é subtraída (o float32 do C só carrega o desvio).

Uso (da pasta analise/):

  uv run python -m analise.filtro                 FIR x IIR no PhysioNet (sit)
  uv run python -m analise.filtro --vetores       vetor do teste e coeficientes do C
  uv run python -m analise.filtro --figura X.png  resposta e efeito da fase no pico
  uv run python -m analise.filtro --confere CSV   placa x Python, no CSV da captura
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from scipy import signal

from analise import FS_HZ, decimacao, fonte_falsa, serial_completa

N_COEF = 201
BANDA_HZ = fonte_falsa.BANDA_HZ  # (0,5, 4): mesma banda da referência
ATRASO = (N_COEF - 1) // 2  # amostras a FS_HZ: PPG_ATRASO_AMOSTRAS
AQUECIMENTO_S = 5.0  # ignorado na avaliação: o FIR enche em 2 s, o IIR acomoda

RAIZ = Path(__file__).resolve().parents[3]
COEF_H = RAIZ / "Core" / "Inc" / "pds" / "filtro" / "filtro_coef.h"
TOL_COUNTS = 0.05


@cache
def _coeficientes() -> tuple[float, ...]:
    h = signal.firwin(N_COEF, BANDA_HZ, pass_zero=False, fs=FS_HZ, window="hamming")
    return tuple(h - h.mean())  # DC = 0; continua simétrico


def coeficientes() -> np.ndarray:
    return np.array(_coeficientes())


def filtra(x: np.ndarray) -> np.ndarray:
    """Mesma conta do filtro_processa() do C: y[n] = sum_j h[j] (x[n - j] - x[0])."""
    x = np.asarray(x, dtype=np.float64)
    if len(x) == 0:
        return np.empty(0)
    return np.convolve(x - x[0], coeficientes())[: len(x)]


def iir(x: np.ndarray, ordem: int = 4) -> np.ndarray:
    """Butterworth passa-faixa causal (só pra comparação). ordem = ordem total."""
    sos = signal.butter(ordem // 2, BANDA_HZ, btype="band", fs=FS_HZ, output="sos")
    x = np.asarray(x, dtype=np.float64)
    return signal.sosfilt(sos, x - x[0])


def fase_zero(x: np.ndarray) -> np.ndarray:
    """Referência de comparação: Butterworth de fase zero (filtfilt), atraso 0."""
    sos = signal.butter(fonte_falsa.ORDEM_FILTRO, BANDA_HZ, btype="band", fs=FS_HZ, output="sos")
    return signal.sosfiltfilt(sos, x - np.mean(x))


# ---- Comparação FIR x IIR ---------------------------------------------------


def picos(y: np.ndarray) -> np.ndarray:
    """Instantes (s) dos picos do filtrado: máximos e interpolação parabólica.

    Detector simples, só pra validação (o de verdade é o módulo picos/).
    """
    i, _ = signal.find_peaks(y, distance=round(0.33 * FS_HZ), prominence=0.3 * np.std(y))
    i = i[(i > 0) & (i < len(y) - 1)]
    a, b, c = y[i - 1], y[i], y[i + 1]
    return (i + 0.5 * (a - c) / (a - 2 * b + c)) / FS_HZ


def deslocamento_s(t: np.ndarray, ref: np.ndarray, janela_s: float = 0.25) -> np.ndarray:
    """Pra cada pico em t, a distância ao pico mais próximo de ref (só os casados)."""
    if len(ref) < 2 or len(t) == 0:
        return np.empty(0)
    j = np.clip(np.searchsorted(ref, t), 1, len(ref) - 1)
    perto = np.where(np.abs(ref[j - 1] - t) < np.abs(ref[j] - t), j - 1, j)
    d = t - ref[perto]
    return d[np.abs(d) < janela_s]


@dataclass(frozen=True)
class Avaliacao:
    registro: str
    caminho: str
    fc_bpm: float
    desloc_ms: float  # pico (já descontado o atraso nominal) - pico de fase zero, médio
    jitter_ms: float  # desvio padrão desse deslocamento dentro do registro
    ibi_rms_ms: float  # intervalo entre picos - RR do ECG
    batimentos: int


def caminhos(bruto: np.ndarray) -> dict[str, tuple[np.ndarray, float]]:
    """Saída e atraso nominal (amostras) de cada filtro comparado."""
    return {
        f"FIR {N_COEF} (nosso)": (filtra(bruto), float(ATRASO)),
        "IIR Butterworth 2": (iir(bruto, 2), 0.0),
        "IIR Butterworth 4": (iir(bruto, 4), 0.0),
    }


def avalia(r, inicio_s: float = 30.0, duracao_s: float = 120.0) -> list[Avaliacao]:
    trecho = r.recorta(inicio_s, inicio_s + duracao_s)
    bruto = decimacao.decima(trecho.ir, r.fs_hz)  # a entrada real do filtro
    t_ecg = trecho.t_picos_ecg
    ref = picos(fase_zero(bruto))
    ref = ref[ref > AQUECIMENTO_S]
    fc = 60 / np.median(np.diff(t_ecg))
    saida = []
    for nome, (y, atraso) in caminhos(bruto).items():
        t = picos(y) - atraso / FS_HZ
        t = t[t > AQUECIMENTO_S]
        d = deslocamento_s(t, ref)
        # O IBI não depende de deslocamento constante: tira o do registro só pra
        # casar com o ECG na janela de 0,1 a 0,7 s depois do R.
        erro = decimacao.erro_ibi_ms(t - np.median(d), t_ecg)
        saida.append(Avaliacao(r.nome, nome, fc, 1000 * d.mean(), 1000 * d.std(),
                               float(np.sqrt(np.mean(erro**2))), len(erro)))
    return saida


def compara(nomes: list[str]) -> list[Avaliacao]:
    from analise import physionet

    todas = []
    for nome in nomes:
        todas += avalia(physionet.carrega(nome))
    fcs = [a.fc_bpm for a in todas]
    print(f"{len(nomes)} registros, FC de {min(fcs):.0f} a {max(fcs):.0f} bpm. Mediana (mín..máx):")
    print(f"{'caminho':20s} {'desloc. do pico (ms)':>26s} {'jitter (ms)':>12s} "
          f"{'IBI-RR RMS (ms)':>16s} {'pares':>6s}")
    for caminho in dict.fromkeys(a.caminho for a in todas):
        g = [a for a in todas if a.caminho == caminho]
        d = [a.desloc_ms for a in g]
        print(f"{caminho:20s} {np.median(d):7.1f} ({min(d):6.1f}..{max(d):6.1f})    "
              f"{np.median([a.jitter_ms for a in g]):12.1f} "
              f"{np.median([a.ibi_rms_ms for a in g]):16.1f} {sum(a.batimentos for a in g):6d}")
    return todas


def resposta() -> dict[str, float]:
    f, H = signal.freqz(coeficientes(), worN=[0.0, 0.05, 0.2, 0.5, 1.0, 2.0, 4.0, 6.0], fs=FS_HZ)
    return {f"{fi:g} Hz": float(20 * np.log10(max(abs(h), 1e-12))) for fi, h in zip(f, H)}


# ---- Vetores do teste e coeficientes do C -----------------------------------


def coef_h() -> str:
    h = coeficientes().astype(np.float32)
    linhas = [
        "/*",
        " * filtro_coef.h: coeficientes do FIR passa-faixa (0,5 a 4 Hz a PPG_FS_HZ).",
        f" * Hamming, {N_COEF} coeficientes simétricos, média subtraída (DC = 0).",
        " * Gerado por analise/src/analise/filtro.py (--vetores). Não edite à mão.",
        " * Só o filtro.c inclui este arquivo.",
        " */",
        "#ifndef PDS_FILTRO_COEF_H",
        "#define PDS_FILTRO_COEF_H",
        "",
        f"#define FILTRO_N {len(h)}u",
        f"static const float filtro_coef[{len(h)}] = {{",
    ]
    for i in range(0, len(h), 6):
        linhas.append("    " + ", ".join(f"{v!s}f" for v in h[i : i + 6]) + ",")
    linhas += ["};", "", "#endif /* PDS_FILTRO_COEF_H */", ""]
    return "\n".join(linhas)


def vetor_bruto_100hz() -> dict[str, np.ndarray]:
    """O bruto da fonte falsa (60 s a 100 Hz) e o filtrado que o nosso FIR dá."""
    dados = np.loadtxt(fonte_falsa.PASTA_VETORES / "bruto_100hz.txt", comments="#", skiprows=2)
    ir, vermelho = dados[:, 1].astype(np.float32), dados[:, 2].astype(np.float32)
    return {"ir": ir, "vermelho": vermelho,
            "esperado_ir": filtra(ir), "esperado_vermelho": filtra(vermelho)}


def gera_vetores(testes: Path | None = None, coef: Path = COEF_H) -> list[Path]:
    from analise import vetores

    coef.parent.mkdir(parents=True, exist_ok=True)
    coef.write_text(coef_h(), encoding="utf-8", newline="\n")
    return [coef, vetores.gera_vetor(
        "filtro", "bruto_100hz", vetor_bruto_100hz(), TOL_COUNTS, testes=testes or vetores.TESTES,
        descricao="Bruto da fonte falsa (60 s a 100 Hz) e o filtrado do FIR, mesmo n.")]


# ---- Placa x Python (sensor real) -------------------------------------------


def confere_placa(bruto: np.ndarray, filtrado_placa: np.ndarray) -> dict:
    """Filtra no Python o bruto que a placa mandou e compara com o filtrado dela.

    bruto e filtrado_placa: colunas n, ir, vermelho a 100 Hz, como na captura.
    A placa filtra desde o n = 0 do boot; só valem as saídas cuja janela inteira
    (n - 200 a n) está no bruto capturado e sem saltos.
    """
    n_bruto = bruto[:, 0].astype(np.int64)
    if np.any(np.diff(n_bruto) != 1):
        raise ValueError("o bruto tem saltos no n: a comparação não vale")
    h = coeficientes()
    n_f = filtrado_placa[:, 0].astype(np.int64)
    validos = (n_f >= n_bruto[0] + N_COEF - 1) & (n_f <= n_bruto[-1])
    if not validos.any():
        raise ValueError("nenhuma saída da placa com a janela inteira no bruto capturado")
    idx = n_f[validos] - n_bruto[0]
    resultado = {"saidas": int(validos.sum())}
    for col, nome in ((1, "ir"), (2, "vermelho")):
        py = np.array([h @ bruto[i - N_COEF + 1 : i + 1, col][::-1] for i in idx])
        resultado[f"erro_max_{nome}"] = float(np.abs(filtrado_placa[validos, col] - py).max())
    # Sem ECG: a referência disponível é o mesmo bruto filtrado com fase zero.
    t_placa = picos(filtrado_placa[:, 1]) + (n_f[0] - ATRASO) / FS_HZ
    ref = picos(fase_zero(bruto[:, 1])) + n_bruto[0] / FS_HZ
    d = deslocamento_s(t_placa[t_placa > (n_f[0] + N_COEF) / FS_HZ], ref)
    resultado["picos"] = len(d)
    resultado["desloc_ms"] = float(1000 * d.mean()) if len(d) else float("nan")
    if len(ref) > 2:
        resultado["bpm"] = float(60 / np.median(np.diff(ref)))
    return resultado


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--vetores", action="store_true", help="gera o vetor e o filtro_coef.h")
    p.add_argument("--figura", type=Path, help="PNG da resposta e do efeito da fase")
    p.add_argument("--confere", type=Path, help="CSV da captura (com _bruto e _filtrado ao lado)")
    p.add_argument("--registros", default="sit", help="sit, walk, run ou lista s1_sit,s2_sit")
    args = p.parse_args(argv)

    if args.vetores:
        for caminho in gera_vetores():
            print(caminho)
        return
    if args.figura:
        from analise.plota_filtro import figura

        figura(args.figura)
        print(args.figura)
        return
    if args.confere:
        lado = args.confere.with_name
        r = confere_placa(
            serial_completa.carrega(lado(args.confere.stem + "_bruto.csv")),
            serial_completa.carrega(lado(args.confere.stem + "_filtrado.csv")))
        ok = max(r["erro_max_ir"], r["erro_max_vermelho"]) <= 0.5
        print(f"{r['saidas']} saídas comparadas; erro máximo IR {r['erro_max_ir']:.3f}, "
              f"vermelho {r['erro_max_vermelho']:.3f} contagens: {'OK' if ok else 'DIVERGE'}")
        print(f"{r['picos']} picos; deslocamento médio contra fase zero {r['desloc_ms']:.1f} ms; "
              f"{r.get('bpm', float('nan')):.0f} bpm")
        return

    print("FIR", N_COEF, "coef., ganho:", ", ".join(f"{k} {v:.1f} dB" for k, v in resposta().items()))
    if args.registros in ("sit", "walk", "run"):
        nomes = [f"s{i}_{args.registros}" for i in range(1, 23)]
    else:
        nomes = args.registros.split(",")
    compara(nomes)


if __name__ == "__main__":
    main()
