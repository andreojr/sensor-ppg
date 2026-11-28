"""Efeito da fase do filtro no instante do pico, no RR e no HRV (issue #32).

O filtro/ é um FIR de fase linear, e o picos/ desconta dele um atraso constante
(PPG_ATRASO_AMOSTRAS = 100). Aqui se mede o que aconteceria com um IIR no lugar
dele, com o detector de verdade (picos.detecta, o mesmo da cadeia) e o HRV de
verdade (hrv.Hrv):

  - deslocamento do pico, em ms, contra o mesmo passa-faixa de fase zero
    (filtfilt, a referência da fonte falsa), por registro;
  - o melhor atraso constante pra cada filtro e o que sobra depois dele: é o
    que um PPG_ATRASO_AMOSTRAS consegue corrigir;
  - erro do RR (intervalo entre picos do PPG contra o RR do ECG);
  - erro do SDNN e do RMSSD (janela de 60 s) contra o HRV dos picos R do ECG.

Uso (da pasta analise/):

  uv run python -m analise.fase_pico                     22 registros sit
  uv run python -m analise.fase_pico --figura X.png      atraso de grupo e erro do HRV
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import signal

from analise import FS_HZ, decimacao, filtro, hrv, picos

INICIO_S = 30.0
DURACAO_S = 300.0  # 5 janelas de HRV de 60 s por registro
AQUECIMENTO_S = 5.0  # o FIR enche em 2 s, o IIR acomoda, o picos espera 2 s
REFERENCIA = "fase zero (referência)"
FIR = f"FIR {filtro.N_COEF} (nosso)"


def caminhos() -> dict[str, tuple[Callable[[np.ndarray], np.ndarray], float]]:
    """Filtro e atraso nominal (amostras) que o picos/ teria que descontar."""
    return {
        REFERENCIA: (filtro.fase_zero, 0.0),
        FIR: (filtro.filtra, float(filtro.ATRASO)),
        "IIR Butterworth 2": (lambda x: filtro.iir(x, 2), 0.0),
        "IIR Butterworth 4": (lambda x: filtro.iir(x, 4), 0.0),
    }


def atraso_de_grupo(nome: str, f_hz: np.ndarray) -> np.ndarray:
    """Atraso de grupo (amostras a FS_HZ) de cada filtro causal."""
    if nome == FIR:
        ba = (filtro.coeficientes(), [1.0])
    else:
        ordem = int(nome.rsplit(" ", 1)[1])
        ba = signal.butter(ordem // 2, filtro.BANDA_HZ, btype="band", fs=FS_HZ)
    _, gd = signal.group_delay(ba, w=f_hz, fs=FS_HZ)
    return gd


def instantes(filtrado: np.ndarray, atraso: float) -> np.ndarray:
    """Instantes (s) dos picos que o picos/ acha, corrigidos do atraso nominal.

    O picos.detecta já desconta PPG_ATRASO_AMOSTRAS; aqui ele volta e sai o
    atraso nominal do caminho (0 nos IIR e na referência).
    """
    bats, _ = picos.detecta(filtrado.astype(np.float32))
    t = np.array([(b.instante + picos.ATRASO_AMOSTRAS - atraso) / FS_HZ for b in bats])
    return t[t > AQUECIMENTO_S]


@dataclass(frozen=True)
class Resultado:
    registro: str
    caminho: str
    fc_bpm: float
    desloc_ms: float  # médio, contra o pico de fase zero
    jitter_ms: float  # desvio padrão do deslocamento dentro do registro
    rr_rms_ms: float  # intervalo entre picos do PPG - RR do ECG
    sdnn_ref_ms: float
    rmssd_ref_ms: float
    sdnn_rms_ms: float
    rmssd_rms_ms: float
    janelas_hrv: int


def _hrv(t_ecg: np.ndarray, t_ppg: np.ndarray, ptt_s: float) -> hrv.Erro:
    """SDNN e RMSSD dos picos do PPG contra os do ECG, batimento a batimento.

    Igual ao hrv.valida_registro: cada R casa com o pico do PPG que chega perto
    do tempo de trânsito típico do registro. Batimento perdido sai da sequência,
    e o seguinte tem rr_valido false.
    """
    ref = hrv.roda(hrv.batimentos_de_tempos(t_ecg, interpola=True))
    t = hrv.casa_ppg_com_ecg(t_ecg, t_ppg, (ptt_s - 0.2, ptt_s + 0.2))
    achou = ~np.isnan(t)
    ok = achou & np.concatenate([[False], achou[:-1]])
    bats = hrv.batimentos_de_tempos(np.where(achou, t, t_ecg + ptt_s), True, ok)
    h = hrv.Hrv()
    obt = [h.processa(b) if a else None for b, a in zip(bats, achou, strict=True)]
    return hrv.compara(ref, obt, "")


def avalia(r) -> list[Resultado]:
    trecho = r.recorta(INICIO_S, INICIO_S + DURACAO_S)
    bruto = decimacao.decima(trecho.ir, r.fs_hz)
    t_ecg = trecho.t_picos_ecg
    fc = 60 / np.median(np.diff(t_ecg))
    t = {nome: instantes(f(bruto), atraso) for nome, (f, atraso) in caminhos().items()}
    ref = t[REFERENCIA]
    # Tempo de trânsito típico (R -> pico de fase zero), pra casar PPG com ECG.
    depois = ref[np.searchsorted(ref, t_ecg[t_ecg < ref[-1]])]
    ptt = float(np.median(depois - t_ecg[t_ecg < ref[-1]]))

    saida = []
    for nome, tp in t.items():
        d = filtro.deslocamento_s(tp, ref)
        alinhado = tp - np.median(d)  # o RR e o HRV não dependem de deslocamento constante
        rr = decimacao.erro_ibi_ms(alinhado - ptt + 0.3, t_ecg)  # janela 0,1 a 0,7 s
        e = _hrv(t_ecg, alinhado, ptt)
        saida.append(Resultado(r.nome, nome, float(fc), float(1000 * d.mean()),
                               float(1000 * d.std()), float(np.sqrt(np.mean(rr**2))),
                               e.sdnn_ref_ms, e.rmssd_ref_ms, e.sdnn_rms_ms, e.rmssd_rms_ms,
                               e.saidas))
    return saida


def melhor_constante(res: list[Resultado], caminho: str) -> tuple[float, float, float]:
    """O atraso extra (ms) que melhor corrige o caminho em todos os registros (a mediana
    dos deslocamentos médios), e o erro que sobra entre registros: RMS e pior registro.
    Não inclui a variação dentro do registro (o jitter)."""
    d = np.array([x.desloc_ms for x in res if x.caminho == caminho])
    c = float(np.median(d))
    return c, float(np.sqrt(np.mean((d - c) ** 2))), float(np.abs(d - c).max())


def relatorio(registros: list) -> list[Resultado]:
    res: list[Resultado] = []
    for r in registros:
        res += avalia(r)
    fcs = sorted({round(x.fc_bpm) for x in res})
    print(f"{len(registros)} registros de {DURACAO_S:g} s, FC de {fcs[0]} a {fcs[-1]} bpm. "
          "Mediana dos registros (mín..máx):\n")
    print(f"{'caminho':24s} {'pico - fase zero (ms)':>24s} {'jitter':>7s} {'RR (ms)':>8s} "
          f"{'SDNN (ms)':>10s} {'RMSSD (ms)':>11s}")
    for caminho in caminhos():
        g = [x for x in res if x.caminho == caminho]
        d = [x.desloc_ms for x in g]
        med = {k: np.median([getattr(x, k) for x in g])
               for k in ("jitter_ms", "rr_rms_ms", "sdnn_rms_ms", "rmssd_rms_ms")}
        print(f"{caminho:24s} {np.median(d):7.1f} ({min(d):6.1f}..{max(d):6.1f}) "
              f"{med['jitter_ms']:7.1f} {med['rr_rms_ms']:8.1f} {med['sdnn_rms_ms']:10.1f} "
              f"{med['rmssd_rms_ms']:11.1f}")
    g = [x for x in res if x.caminho == FIR]
    print(f"\nHRV de referência (ECG), mediana: SDNN {np.median([x.sdnn_ref_ms for x in g]):.0f} ms, "
          f"RMSSD {np.median([x.rmssd_ref_ms for x in g]):.0f} ms")
    print("\nMelhor atraso constante extra e o que sobra entre registros (média de cada registro):")
    for caminho in list(caminhos())[1:]:
        c, rms, pior = melhor_constante(res, caminho)
        print(f"  {caminho:22s} {c:+7.1f} ms ({c * FS_HZ / 1000:+.1f} amostras): "
              f"sobra {rms:5.1f} ms RMS, pior registro {pior:5.1f} ms")
    d = np.array([x.desloc_ms for x in res if x.caminho == FIR])
    print(f"\nCom o atraso nominal ({filtro.ATRASO} amostras, sem constante extra), o FIR deixa "
          f"{np.sqrt(np.mean(d**2)):.1f} ms RMS entre registros, pior registro "
          f"{np.abs(d).max():.1f} ms")
    return res


def figura(res: list[Resultado], destino: Path) -> None:
    """Atraso de grupo na banda do pulso e erro do RMSSD por registro."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cores = {FIR: "#2a78d6", "IIR Butterworth 2": "#eb6834", "IIR Butterworth 4": "#1baf7a"}
    tinta, tinta2, muda, grade, eixo, fundo = ("#0b0b0b", "#52514e", "#898781", "#e1e0d9",
                                               "#c3c2b7", "#fcfcfb")
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.5, 4.2), facecolor=fundo,
                                 gridspec_kw={"wspace": 0.3, "width_ratios": (1.2, 1)})
    for ax in (a1, a2):
        ax.set_facecolor(fundo)
        ax.grid(True, color=grade, linewidth=0.6)
        for lado in ("top", "right"):
            ax.spines[lado].set_visible(False)
        for lado in ("left", "bottom"):
            ax.spines[lado].set_color(eixo)
        ax.tick_params(colors=muda, labelcolor=tinta2, labelsize=9)

    f = np.linspace(0.5, 4.0, 300)
    a1.axvspan(55 / 60, 123 / 60, color=grade, alpha=0.6, linewidth=0)
    for nome, cor in cores.items():
        a1.plot(f, 1000 * atraso_de_grupo(nome, f) / FS_HZ, color=cor, linewidth=2, label=nome)
    a1.set_xlabel("frequência (Hz)", color=tinta2)
    a1.set_ylabel("atraso de grupo (ms)", color=tinta2)
    a1.set_title("Atraso de grupo; cinza: fundamental do pulso nos registros",
                 loc="left", color=tinta, fontsize=10)
    a1.legend(frameon=False, fontsize=9, labelcolor=tinta2, loc="center right",
               bbox_to_anchor=(1, 0.62))

    # A referência de fase zero entra em cinza: o que ela erra é da detecção, não da fase.
    cores_hrv = {REFERENCIA: muda, **cores}
    nomes = list(cores_hrv)
    for i, nome in enumerate(nomes):
        v = [x.rmssd_rms_ms for x in res if x.caminho == nome]
        jit = np.random.default_rng(i).uniform(-0.15, 0.15, len(v))
        a2.scatter(i + jit, v, s=28, color=cores_hrv[nome], edgecolor=fundo, linewidth=1,
                   zorder=3)
        a2.plot([i - 0.25, i + 0.25], [np.median(v)] * 2, color=tinta, linewidth=1.5)
    rotulos = {REFERENCIA: "fase zero", FIR: f"FIR {filtro.N_COEF}",
               "IIR Butterworth 2": "IIR 2", "IIR Butterworth 4": "IIR 4"}
    a2.set_xticks(range(len(nomes)), [rotulos[n] for n in nomes])
    a2.set_yscale("log")
    a2.set_ylabel("erro do RMSSD contra o ECG, RMS (ms)", color=tinta2)
    a2.set_title("Erro do RMSSD por registro (traço: mediana)", loc="left", color=tinta,
                 fontsize=10)

    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=120, bbox_inches="tight", facecolor=fundo)
    plt.close(fig)


def main(argv: list[str] | None = None) -> None:
    from analise import physionet

    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--figura", type=Path, help="PNG do atraso de grupo e do erro do HRV")
    p.add_argument("--registros", default="sit", help="sit, walk, run ou lista s1_sit,s2_sit")
    args = p.parse_args(argv)
    if args.registros in ("sit", "walk", "run"):
        nomes = [f"s{i}_{args.registros}" for i in range(1, 23)]
    else:
        nomes = args.registros.split(",")
    res = relatorio([physionet.carrega(n) for n in nomes])
    if args.figura:
        figura(res, args.figura)
        print(args.figura)


if __name__ == "__main__":
    main()
