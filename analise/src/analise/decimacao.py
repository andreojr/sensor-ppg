"""Decimação: FIR anti-aliasing próprio e redução da taxa pra 100 Hz.

Protótipo do módulo Core/*/pds/decimacao/. O C faz exatamente a mesma conta,
amostra a amostra; decima() é a versão vetorizada e é dela que saem os
vetores de referência do teste no PC.

Projeto (ver docs/src/content/docs/modulos/decimacao.md):

  - FIR de fase linear, equiripple (Parks-McClellan), passa 0 a 20 Hz e
    rejeita de 50 Hz pra cima. 49 coeficientes a 400 Hz (placa), 61 a 500 Hz
    (PhysioNet). Ganho em DC exatamente 1: o bruto mantém o DC.
  - O atraso do FIR, (N - 1) / 2 amostras de entrada, é 6 amostras de saída
    (60 ms) nas duas taxas. A saída de índice n sai quando chega a entrada
    n * fator + atraso e corresponde ao instante n / 100 s da entrada: o n da
    decimação fica alinhado com o tempo do sensor (latência de 60 ms).
  - Antes da primeira amostra, o histórico vale a primeira amostra (sem
    transiente de DC no começo). Na conta, a primeira amostra é subtraída e
    somada de volta: o float32 do C só carrega o desvio, não os ~100 mil de DC.

Uso (da pasta analise/):

  uv run python -m analise.decimacao                 relatório (PhysioNet, sit)
  uv run python -m analise.decimacao --vetores       vetores do teste e coeficientes do C
  uv run python -m analise.decimacao --figura X.png  resposta em frequência
  uv run python -m analise.decimacao --confere CSV   placa x Python, no CSV da captura
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from scipy import signal

from analise import FS_HZ, serial_completa

TAXAS_HZ = (400, 500)  # placa (MAX30102_FS_HZ) e PhysioNet
PASSA_HZ = 20.0
REJEITA_HZ = 50.0
PESO_REJEICAO = 10.0
ATRASO_SAIDA = 6  # amostras a FS_HZ: (N - 1) / 2 = ATRASO_SAIDA * fator

RAIZ = Path(__file__).resolve().parents[3]
COEF_H = RAIZ / "Core" / "Inc" / "pds" / "decimacao" / "decimacao_coef.h"


def fator(fs_entrada: int) -> int:
    if fs_entrada not in TAXAS_HZ:
        raise ValueError(f"taxa {fs_entrada} Hz sem filtro; suportadas: {TAXAS_HZ}")
    return fs_entrada // FS_HZ


def atraso_entrada(fs_entrada: int) -> int:
    """Atraso do FIR em amostras de entrada: (N - 1) / 2."""
    return ATRASO_SAIDA * fator(fs_entrada)


@cache
def _coeficientes(fs_entrada: int) -> tuple[float, ...]:
    n = 2 * atraso_entrada(fs_entrada) + 1
    h = signal.remez(
        n, [0, PASSA_HZ, REJEITA_HZ, fs_entrada / 2], [1, 0], weight=[1, PESO_REJEICAO],
        fs=fs_entrada,
    )
    h = (h + h[::-1]) / 2  # simetria exata (fase linear)
    return tuple(h / h.sum())  # ganho em DC = 1


def coeficientes(fs_entrada: int) -> np.ndarray:
    """Coeficientes do FIR anti-aliasing para a taxa de entrada (soma 1, simétricos)."""
    return np.array(_coeficientes(fs_entrada))


def decima(x: np.ndarray, fs_entrada: int) -> np.ndarray:
    """Mesma conta do decimacao_processa() do C, com o sinal todo de uma vez.

    Saída n = sum_j h[j] * x[n * fator + atraso - j], com x[i < 0] = x[0].
    Devolve as saídas que já saíram quando chega a última entrada.
    """
    x = np.asarray(x, dtype=np.float64)
    h = coeficientes(fs_entrada)
    m, d = fator(fs_entrada), atraso_entrada(fs_entrada)
    if len(x) <= d:
        return np.empty(0)
    ref = x[0]
    desvio = np.concatenate([np.zeros(d), x - ref])  # histórico = x[0] antes do começo
    y = np.convolve(desvio, h)[2 * d : len(desvio)]  # y[i] usa a entrada i
    return ref + y[::m]


def media_sensor(x: np.ndarray, fs_entrada: int) -> np.ndarray:
    """O que o MAX30102 faria com SMP_AVE = fator: média de blocos de fator amostras."""
    m = fator(fs_entrada)
    k = len(x) // m
    return np.asarray(x[: k * m], dtype=np.float64).reshape(k, m).mean(axis=1)


# ---- Resposta em frequência -------------------------------------------------


@dataclass(frozen=True)
class Resposta:
    ripple_db: float  # pior desvio de 0 dB na banda passante
    rejeicao_db: float  # pior ganho de REJEITA_HZ pra cima
    alias_db: float  # pior ganho do que dobra pra dentro de 0 a 10 Hz


def resposta(h: np.ndarray, fs_entrada: int) -> Resposta:
    f, H = signal.freqz(h, worN=1 << 15, fs=fs_entrada)
    db = 20 * np.log10(np.maximum(np.abs(H), 1e-12))
    # O que está a k*100 +- 10 Hz cai em 0 a 10 Hz depois da decimação.
    dobra = np.zeros_like(f, dtype=bool)
    for k in range(1, fs_entrada // (2 * FS_HZ) + 1):
        dobra |= np.abs(f - k * FS_HZ) <= 10
    return Resposta(
        ripple_db=float(np.abs(db[f <= PASSA_HZ]).max()),
        rejeicao_db=float(db[f >= REJEITA_HZ].max()),
        alias_db=float(db[dobra].max()),
    )


# ---- Validação no PhysioNet -------------------------------------------------


def _picos_ppg(x: np.ndarray, fs: float) -> np.ndarray:
    """Instante (s) de cada pico do PPG: passa-faixa, máximos e interpolação parabólica."""
    sos = signal.butter(2, (0.5, 4.0), btype="band", fs=fs, output="sos")
    y = signal.sosfiltfilt(sos, x - x.mean())
    i, _ = signal.find_peaks(y, distance=round(0.33 * fs), prominence=0.3 * np.std(y))
    i = i[(i > 0) & (i < len(y) - 1)]
    a, b, c = y[i - 1], y[i], y[i + 1]
    desvio = 0.5 * (a - c) / (a - 2 * b + c)
    return (i + desvio) / fs


def erro_ibi_ms(t_ppg: np.ndarray, t_ecg: np.ndarray) -> np.ndarray:
    """Intervalo entre picos do PPG menos o RR do ECG, batimento a batimento.

    Cada pico R casa com o primeiro pico do PPG de 0,1 a 0,7 s depois dele
    (o pulso leva esse tempo pra chegar ao dedo). Só pares consecutivos casados.
    """
    casado = np.full(len(t_ecg), np.nan)
    for k, r in enumerate(t_ecg):
        j = np.searchsorted(t_ppg, r + 0.1)
        if j < len(t_ppg) and t_ppg[j] <= r + 0.7:
            casado[k] = t_ppg[j]
    erro = (np.diff(casado) - np.diff(t_ecg)) * 1000
    return erro[np.isfinite(erro)]


@dataclass(frozen=True)
class Avaliacao:
    registro: str
    caminho: str  # "500 Hz", "FIR 500->100", "média 400->100"...
    rms_counts: float  # contra a referência de fase zero (scipy), em contagens
    rms_pct_ac: float  # o mesmo, em % da amplitude do pulso
    ibi_rms_ms: float  # IBI do PPG contra o RR do ECG
    batimentos: int


def avalia(r, inicio_s: float = 30.0, duracao_s: float = 60.0) -> list[Avaliacao]:
    """Decima o trecho por três caminhos e compara com o scipy (forma) e o ECG (tempo)."""
    from analise import fonte_falsa

    trecho = r.recorta(inicio_s, inicio_s + duracao_s)
    ir = trecho.ir
    t_ecg = trecho.t_picos_ecg
    m500 = r.fs_hz // FS_HZ
    referencia = signal.resample_poly(ir - ir.mean(), 1, m500) + ir.mean()  # fase zero
    ac = np.percentile(referencia, 95) - np.percentile(referencia, 5)

    # O sensor da placa: 500 -> 400 Hz, inteiros (igual à fonte falsa).
    ir400 = np.round(signal.resample_poly(ir, fonte_falsa.FS_SENSOR_HZ, r.fs_hz))

    caminhos = {
        f"original {r.fs_hz} Hz": (ir, r.fs_hz, None),
        f"FIR {r.fs_hz}->100": (decima(ir, r.fs_hz), FS_HZ, 0.0),
        "FIR 400->100": (decima(ir400, 400), FS_HZ, 0.0),
        # A média de 4 atrasa 1,5 amostra a 400 Hz (3,75 ms): compensado na forma.
        "média 400->100": (media_sensor(ir400, 400), FS_HZ, 1.5 / 400),
    }
    saida = []
    margem = 2 * ATRASO_SAIDA  # bordas: começo com histórico repetido, fim do resample
    for nome, (y, fs, atraso_s) in caminhos.items():
        if atraso_s is None:
            rms = 0.0
        else:
            t = np.arange(len(y)) / fs
            ref = np.interp(t + atraso_s, np.arange(len(referencia)) / FS_HZ, referencia)
            rms = float(np.sqrt(np.mean((y - ref)[margem:-margem] ** 2)))
        erro = erro_ibi_ms(_picos_ppg(y, fs), t_ecg)
        saida.append(
            Avaliacao(r.nome, nome, rms, 100 * rms / ac, float(np.sqrt(np.mean(erro**2))), len(erro))
        )
    return saida


def relatorio(nomes: list[str]) -> list[Avaliacao]:
    from analise import physionet

    todas = []
    for nome in nomes:
        todas += avalia(physionet.carrega(nome))
    print(f"{'caminho':18s} {'RMS (contagens)':>16s} {'RMS (% do AC)':>14s} "
          f"{'IBI-RR RMS (ms)':>16s} {'pares':>6s}")
    for caminho in dict.fromkeys(a.caminho for a in todas):
        grupo = [a for a in todas if a.caminho == caminho]
        print(
            f"{caminho:18s} {np.median([a.rms_counts for a in grupo]):16.2f} "
            f"{np.median([a.rms_pct_ac for a in grupo]):14.3f} "
            f"{np.median([a.ibi_rms_ms for a in grupo]):16.1f} "
            f"{sum(a.batimentos for a in grupo):6d}"
        )
    print(f"(mediana de {len(nomes)} registros; RMS contra a decimação de fase zero do scipy)")
    return todas


# ---- Vetores do teste e coeficientes do C -----------------------------------


def coef_h() -> str:
    """Texto do decimacao_coef.h: as tabelas de coeficientes, em float32."""
    linhas = [
        "/*",
        " * decimacao_coef.h: coeficientes do FIR anti-aliasing, um por taxa de entrada.",
        f" * Remez, passa 0 a {PASSA_HZ:g} Hz, rejeita de {REJEITA_HZ:g} Hz pra cima, soma 1.",
        " * Gerado por analise/src/analise/decimacao.py (--vetores). Não edite à mão.",
        " * Só o decimacao.c inclui este arquivo.",
        " */",
        "#ifndef PDS_DECIMACAO_COEF_H",
        "#define PDS_DECIMACAO_COEF_H",
        "",
    ]
    for fs in TAXAS_HZ:
        h = coeficientes(fs).astype(np.float32)
        linhas += [f"#define DECIMACAO_COEF_{fs}_N {len(h)}u",
                   f"static const float decimacao_coef_{fs}[{len(h)}] = {{"]
        for i in range(0, len(h), 6):
            linhas.append("    " + ", ".join(f"{v!s}f" for v in h[i : i + 6]) + ",")
        linhas += ["};", ""]
    linhas += ["#endif /* PDS_DECIMACAO_COEF_H */", ""]
    return "\n".join(linhas)


TOL_COUNTS = 0.05  # float32 no C contra float64 aqui, em contagens do ADC


def vetor_sensor_400hz() -> dict[str, np.ndarray]:
    """Caso 1: a fonte falsa a 400 Hz (testes/comum/vetores/sensor_400hz.txt)."""
    from analise import fonte_falsa

    dados = np.loadtxt(fonte_falsa.PASTA_VETORES / "sensor_400hz.txt", comments="#", skiprows=2)
    ir, vermelho = dados[:, 1].astype(np.int64), dados[:, 2].astype(np.int64)
    return {"ir": ir, "vermelho": vermelho,
            "esperado_ir": decima(ir, 400), "esperado_vermelho": decima(vermelho, 400)}


def vetor_physionet_500hz(inicio_s: float = 30.0, duracao_s: float = 10.0) -> dict[str, np.ndarray]:
    """Caso 2: s1_sit cru a 500 Hz (baixa do PhysioNet na primeira vez)."""
    from analise import physionet

    r = physionet.carrega().recorta(inicio_s, inicio_s + duracao_s)
    ir, vermelho = (np.round(x).astype(np.int64) for x in (r.ir, r.vermelho))
    return {"ir": ir, "vermelho": vermelho,
            "esperado_ir": decima(ir, 500), "esperado_vermelho": decima(vermelho, 500)}


def gera_vetores(testes: Path | None = None, coef: Path = COEF_H, physionet: bool = True) -> list[Path]:
    from analise import vetores

    testes = testes or vetores.TESTES
    coef.parent.mkdir(parents=True, exist_ok=True)
    coef.write_text(coef_h(), encoding="utf-8", newline="\n")
    feitos = [coef, vetores.gera_vetor(
        "decimacao", "sensor_400hz", vetor_sensor_400hz(), TOL_COUNTS, testes=testes,
        descricao="Fonte falsa a 400 Hz (inteiros do ADC) e a saída a 100 Hz.")]
    if physionet:
        feitos.append(vetores.gera_vetor(
            "decimacao", "physionet_500hz", vetor_physionet_500hz(), TOL_COUNTS, testes=testes,
            descricao="s1_sit de 30 a 40 s, cru a 500 Hz (arredondado), e a saída a 100 Hz."))
    return feitos


# ---- Placa x Python (sensor real) -------------------------------------------


def confere_placa(cru: np.ndarray, bruto_placa: np.ndarray, fs_entrada: int = 400) -> dict:
    """Compara o bruto que a placa decimou com a decimação do Python no mesmo sinal cru.

    cru: colunas n, ir, vermelho a fs_entrada (n desde o boot, sem saltos).
    bruto_placa: colunas n, ir, vermelho a 100 Hz, como a placa mandou.
    """
    n_cru = cru[:, 0].astype(np.int64)
    if np.any(np.diff(n_cru) != 1):
        raise ValueError("o sinal cru tem saltos no n: amostras perdidas, a comparação não vale")
    m, d = fator(fs_entrada), atraso_entrada(fs_entrada)
    # A placa começa a decimar no n = 0 do boot. Se a captura começou depois,
    # o histórico do Python não bate até o FIR encher de novo: pula essas saídas.
    # A saída k usa as entradas k*m - d a k*m + d.
    k0 = -(-(n_cru[0] + d) // m)  # primeira saída que só usa amostras capturadas
    n_placa = bruto_placa[:, 0].astype(np.int64)
    k = n_placa[(n_placa >= k0) & (n_placa * m + d <= n_cru[-1])]
    if len(k) == 0:
        raise ValueError("nenhuma saída da placa dentro do trecho cru capturado")
    resultado = {"saidas": len(k)}
    for col, nome in ((1, "ir"), (2, "vermelho")):
        janela = cru[:, col]
        idx = k * m + d - n_cru[0]  # entrada que solta a saída k
        h = coeficientes(fs_entrada)
        py = np.array([h @ janela[i - 2 * d : i + 1][::-1] for i in idx])
        placa = bruto_placa[np.isin(n_placa, k), col]
        resultado[f"erro_max_{nome}"] = float(np.abs(placa - py).max())
    return resultado


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--vetores", action="store_true", help="gera os vetores e o decimacao_coef.h")
    p.add_argument("--figura", type=Path, help="PNG da resposta em frequência")
    p.add_argument("--confere", type=Path, help="CSV da captura (com o _bruto.csv ao lado)")
    p.add_argument("--registros", default="sit", help="sit, walk, run ou lista s1_sit,s2_sit")
    args = p.parse_args(argv)

    if args.vetores:
        for caminho in gera_vetores():
            print(caminho)
        return
    if args.figura:
        from analise.plota_decimacao import figura

        figura(args.figura)
        print(args.figura)
        return
    if args.confere:
        bruto = args.confere.with_name(args.confere.stem + "_bruto.csv")
        r = confere_placa(serial_completa.carrega(args.confere), serial_completa.carrega(bruto))
        ok = max(r["erro_max_ir"], r["erro_max_vermelho"]) <= TOL_COUNTS * 10
        print(f"{r['saidas']} saídas comparadas; erro máximo IR {r['erro_max_ir']:.3f}, "
              f"vermelho {r['erro_max_vermelho']:.3f} contagens: {'OK' if ok else 'DIVERGE'}")
        return

    for fs in TAXAS_HZ:
        r = resposta(coeficientes(fs), fs)
        print(f"FIR {fs} Hz, {len(coeficientes(fs))} coef: ripple {r.ripple_db:.3f} dB, "
              f"rejeição {r.rejeicao_db:.1f} dB, alias em 0-10 Hz {r.alias_db:.1f} dB")
        caixa = resposta(np.ones(fator(fs)) / fator(fs), fs)
        print(f"  média de {fator(fs)} (sensor): queda {caixa.ripple_db:.2f} dB até {PASSA_HZ:g} Hz, "
              f"{caixa.rejeicao_db:.1f} dB em {REJEITA_HZ:g} Hz, alias em 0-10 Hz {caixa.alias_db:.1f} dB")
    if args.registros in ("sit", "walk", "run"):
        nomes = [f"s{i}_{args.registros}" for i in range(1, 23)]
    else:
        nomes = args.registros.split(",")
    relatorio(nomes)


if __name__ == "__main__":
    main()
