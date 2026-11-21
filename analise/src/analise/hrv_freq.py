"""HRV na frequência: razão LF/HF numa janela deslizante de batimentos.

A série de intervalos RR (ms) varia com o tempo. Olhando essa variação como
um sinal, ela tem "ritmos":

  LF  (0,04 a 0,15 Hz, período de 7 a 25 s): mistura do simpático e do vago,
      ligada ao barorreflexo (ajuste da pressão).
  HF  (0,15 a 0,40 Hz, período de 2,5 a 7 s): a respiração (vago).

LF/HF é a razão entre a potência dessas duas faixas. É um indicador grosseiro
de "equilíbrio simpático-vagal" (Task Force de 1996), com muitas ressalvas.

Método (o mesmo do C em Core/*/pds/hrv/hrv_freq.c):

  1. Os RR aceitos dos últimos JANELA_S segundos, cada um no instante do
     batimento que fecha o intervalo. Os batimentos não são igualmente
     espaçados, então:
  2. spline cúbica natural pelos pontos (t, RR) e reamostragem a FS_REAMOSTRA
     (2 Hz): vira um sinal com amostras regulares;
  3. tira a reta (tendência linear) e aplica a janela de Hann;
  4. DFT só nas frequências k / JANELA_S que caem nas bandas (109 delas) e
     soma |X|² em cada banda. Na razão, as escalas se cancelam.

Regras dos batimentos (as mesmas do HRV no tempo, hrv.py): só RR com
rr_valido e entre 300 e 2000 ms; janela pelo n_pico; batimento com valido
false é ignorado; n_pico voltando reinicia. A mais: um RR cujo instante não
anda pra frente (mesmo n_pico e fracao do último) não entra na spline. LF/HF válido quando os RR aceitos
cobrem pelo menos COBERTURA_MIN da janela.

Estudos (uv run python -m analise.hrv_freq):
  --janelas    LF/HF de 60, 120 e 180 s contra o de 300 s
  --metodos    a nossa conta contra interpolação linear, 4 Hz, periodograma e Lomb-Scargle
  (sem opção)  ECG na grade de 100 Hz e PPG contra o ECG exato
  --vetores    grava testes/hrv/vetores/freq_*.h
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
from scipy import interpolate, signal

from analise import FS_HZ, hrv, physionet
from analise.hrv import Batimento

JANELA_S = 300
JANELA_AMOSTRAS = JANELA_S * FS_HZ
FS_REAMOSTRA = 2  # Hz; o dobro de 0,4 Hz já basta (Nyquist), e 4 Hz dá o mesmo (--metodos)
CAP = 600  # cabe a janela de 300 s até 120 bpm de média; cheio, sai o mais antigo
RR_MIN_MS = hrv.RR_MIN_MS
RR_MAX_MS = hrv.RR_MAX_MS
COBERTURA_MIN = 0.9
MIN_RR = 4  # a spline precisa de pelo menos alguns pontos

# Bandas em índices da grade f_k = k / JANELA_S (inteiros, iguais no C).
K_LF = round(0.04 * JANELA_S)  # 12: 0,04 Hz
K_HF = round(0.15 * JANELA_S)  # 45: 0,15 Hz (LF vai até K_HF - 1)
K_FIM = round(0.40 * JANELA_S)  # 120: 0,40 Hz, inclusive


class SaidaFreq(NamedTuple):
    """Os campos de LF/HF de ppg_hrv_t."""

    lf_hf_valido: bool
    lf_hf: float


# ---- A conta -------------------------------------------------------------------


def reamostra(t_s: np.ndarray, rr_ms: np.ndarray, fs: float = FS_REAMOSTRA,
              spline: bool = True) -> np.ndarray:
    """RR em instantes irregulares -> amostras regulares a fs, de t[0] a t[-1]."""
    t = np.asarray(t_s, dtype=float) - t_s[0]
    n = math.floor(t[-1] * fs) + 1
    tg = np.arange(n) / fs
    if spline:
        return interpolate.CubicSpline(t, rr_ms, bc_type="natural")(tg)
    return np.interp(tg, t, rr_ms)


def prepara(y: np.ndarray) -> np.ndarray:
    """Tira a reta e aplica a janela de Hann (simétrica)."""
    y = signal.detrend(np.asarray(y, dtype=float), type="linear")
    return y * signal.windows.hann(len(y), sym=True)


def potencias(y: np.ndarray, fs: float = FS_REAMOSTRA, janela_s: float = JANELA_S
              ) -> tuple[float, float]:
    """Potência LF e HF: |X(f)|² somado nas frequências k / janela_s de cada banda."""
    k_lf, k_hf, k_fim = (round(f * janela_s) for f in (0.04, 0.15, 0.40))
    f = np.arange(k_lf, k_fim + 1) / janela_s
    x = np.exp(-2j * np.pi * np.outer(f, np.arange(len(y))) / fs) @ y
    p = np.abs(x) ** 2
    return float(p[: k_hf - k_lf].sum()), float(p[k_hf - k_lf:].sum())


def lf_hf(t_s: np.ndarray, rr_ms: np.ndarray, fs: float = FS_REAMOSTRA,
          spline: bool = True, grade_s: float = JANELA_S) -> float:
    """LF/HF de uma série (t, RR), pela nossa conta."""
    lf, hf = potencias(prepara(reamostra(t_s, rr_ms, fs, spline)), fs, grade_s)
    return lf / hf


# ---- O módulo, batimento a batimento --------------------------------------------


@dataclass
class _Item:
    n: int
    fracao: float
    rr: float


class HrvFreq:
    """Estado do módulo. Mesmo comportamento de hrv_freq_init/hrv_freq_processa."""

    def __init__(self) -> None:
        self.reinicia()

    def reinicia(self) -> None:
        self.itens: list[_Item] = []
        self.ultimo_n: int | None = None

    def processa(self, b: Batimento) -> SaidaFreq | None:
        if not b.valido:
            return None
        if self.ultimo_n is not None and b.n_pico < self.ultimo_n:
            self.reinicia()
        self.ultimo_n = b.n_pico
        self.itens = [i for i in self.itens if b.n_pico - i.n < JANELA_AMOSTRAS]
        if self._aceita(b):
            if len(self.itens) == CAP:
                self.itens.pop(0)
            self.itens.append(_Item(b.n_pico, b.fracao, b.rr_ms))
        return self._resultado()

    def _aceita(self, b: Batimento) -> bool:
        if not (b.rr_valido and math.isfinite(b.rr_ms) and RR_MIN_MS <= b.rr_ms <= RR_MAX_MS):
            return False
        # O instante tem que andar pra frente: a spline não aceita dois pontos
        # no mesmo instante.
        u = self.itens[-1] if self.itens else None
        return u is None or b.n_pico > u.n or (b.n_pico == u.n and b.fracao > u.fracao)

    def _resultado(self) -> SaidaFreq:
        rr = np.array([i.rr for i in self.itens])
        if len(rr) < MIN_RR or rr.sum() < COBERTURA_MIN * JANELA_S * 1000.0:
            return SaidaFreq(False, 0.0)
        p = self.itens[0]
        # Instante relativo ao primeiro: subtrai os inteiros antes (no C, em
        # float32, n_pico / 100 perderia os milissegundos depois de ~2 dias).
        t = np.array([((i.n - p.n) + (i.fracao - p.fracao)) / FS_HZ for i in self.itens])
        lf, hf = potencias(prepara(reamostra(t, rr)))
        if not (hf > 0 and math.isfinite(lf) and math.isfinite(hf)):
            return SaidaFreq(False, 0.0)
        return SaidaFreq(True, lf / hf)


def roda(batimentos: list[Batimento]) -> list[SaidaFreq | None]:
    h = HrvFreq()
    return [h.processa(b) for b in batimentos]


# ---- Estudos no PhysioNet --------------------------------------------------------


def _serie_ecg(r: physionet.Registro) -> tuple[np.ndarray, np.ndarray]:
    t = r.t_picos_ecg
    rr = np.diff(t) * 1000.0
    ok = (rr >= RR_MIN_MS) & (rr <= RR_MAX_MS)
    return t[1:][ok], rr[ok]


def _fator(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Quantas vezes a difere de b, pra cima ou pra baixo (1 = igual)."""
    return 2.0 ** np.abs(np.log2(np.asarray(a) / np.asarray(b)))


def compara_janelas(registros: list[physionet.Registro], janelas=(60, 120, 180),
                    passo: int = 5) -> str:
    """LF/HF de janelas curtas contra o de 300 s, nos mesmos instantes (ECG exato).

    A cada `passo` batimentos depois de 300 s de registro: a série dos últimos W
    segundos, pela nossa conta. "Fator" = quantas vezes o valor da janela curta
    difere do de 300 s (2 = metade ou o dobro).
    """
    fat = {w: [] for w in janelas}
    pior = {w: [] for w in janelas}
    ref_med = []
    for r in registros:
        t, rr = _serie_ecg(r)
        ks = np.flatnonzero(t >= r.t_picos_ecg[0] + JANELA_S)[::passo]
        ref = np.array([lf_hf(*_janela(t, rr, k, JANELA_S)) for k in ks])
        ref_med.append(np.median(ref))
        for w in janelas:
            v = np.array([lf_hf(*_janela(t, rr, k, w)) for k in ks])
            f = _fator(v, ref)
            fat[w].append(np.median(f))
            pior[w].append(np.percentile(f, 90))
    linhas = ["| Janela | fator típico (mediana) | pior registro | 1 em 10 passa de |",
              "|---|---|---|---|"]
    for w in janelas:
        linhas.append(f"| {w} s | {np.median(fat[w]):.2f} | {np.max(fat[w]):.2f} "
                      f"| {np.median(pior[w]):.2f} |")
    linhas.append(f"\nLF/HF de 300 s, mediana dos registros: {np.median(ref_med):.2f} "
                  f"({np.min(ref_med):.2f} a {np.max(ref_med):.2f}), {len(registros)} registros.")
    return "\n".join(linhas)


def _janela(t: np.ndarray, rr: np.ndarray, k: int, w: float) -> tuple[np.ndarray, np.ndarray]:
    sel = (t > t[k] - w) & (t <= t[k])
    return t[sel], rr[sel]


def _lf_hf_periodograma(t: np.ndarray, rr: np.ndarray, fs: float = 4.0) -> float:
    """Receita de livro: spline a 4 Hz, periodograma de Hann, bins da FFT."""
    y = signal.detrend(reamostra(t, rr, fs), type="linear")
    f, p = signal.periodogram(y, fs, window="hann", detrend=False)
    return p[(f >= 0.04) & (f < 0.15)].sum() / p[(f >= 0.15) & (f <= 0.40)].sum()


def _lf_hf_lomb(t: np.ndarray, rr: np.ndarray) -> float:
    """Lomb-Scargle: espectro direto dos pontos irregulares, sem reamostrar."""
    f = np.arange(0.04, 0.40001, 1.0 / JANELA_S)
    p = signal.lombscargle(t - t[0], rr - rr.mean(), 2 * np.pi * f)
    return p[f < 0.15].sum() / p[f >= 0.15].sum()


def compara_metodos(registros: list[physionet.Registro], passo: int = 5) -> str:
    """Janela de 300 s: outras contas contra a nossa (razão outra / nossa)."""
    contas = {
        "spline a 4 Hz (em vez de 2 Hz)": lambda t, rr: lf_hf(t, rr, fs=4.0),
        "interpolação linear (em vez de spline)": lambda t, rr: lf_hf(t, rr, spline=False),
        "periodograma nos bins da FFT, 4 Hz": _lf_hf_periodograma,
        "Lomb-Scargle (sem reamostrar)": _lf_hf_lomb,
    }
    razoes = {c: [] for c in contas}
    for r in registros:
        t, rr = _serie_ecg(r)
        ks = np.flatnonzero(t >= r.t_picos_ecg[0] + JANELA_S)[::passo]
        for k in ks:
            tj, rj = _janela(t, rr, k, JANELA_S)
            nosso = lf_hf(tj, rj)
            for c, f in contas.items():
                razoes[c].append(f(tj, rj) / nosso)
    linhas = ["| Conta | razão contra a nossa, mediana | faixa (5% a 95%) |", "|---|---|---|"]
    for c, v in razoes.items():
        v = np.array(v)
        linhas.append(f"| {c} | {np.median(v):.3f} | {np.percentile(v, 5):.2f} a "
                      f"{np.percentile(v, 95):.2f} |")
    return "\n".join(linhas)


def valida_registro(r: physionet.Registro) -> dict[str, tuple[float, int]]:
    """Fator típico de erro (e saídas válidas) contra o ECG exato no mesmo módulo."""
    t_ecg = r.t_picos_ecg
    ref = roda(hrv.batimentos_de_tempos(t_ecg, interpola=True))
    obtidos = {"ecg_100hz": roda(hrv.batimentos_de_tempos(t_ecg, interpola=False))}
    for interpola, chave in ((False, "ppg_100hz"), (True, "ppg_interpolado")):
        t_ppg = hrv.casa_ppg_com_ecg(t_ecg, hrv.picos_ppg_validacao(r, interpola))
        achou = ~np.isnan(t_ppg)
        ok = achou & np.concatenate([[False], achou[:-1]])
        bats = hrv.batimentos_de_tempos(np.where(achou, t_ppg, t_ecg + 0.25), interpola, ok)
        h = HrvFreq()
        obtidos[chave] = [h.processa(b) if a else None for b, a in zip(bats, achou, strict=True)]
    saida = {}
    for chave, obt in obtidos.items():
        pares = [(a.lf_hf, b.lf_hf) for a, b in zip(ref, obt, strict=True)
                 if a and b and a.lf_hf_valido and b.lf_hf_valido]
        if not pares:
            saida[chave] = (math.nan, 0)
            continue
        a, b = np.array(pares).T
        saida[chave] = (float(np.median(_fator(b, a))), len(pares))
    n_ref = sum(1 for s in ref if s and s.lf_hf_valido)
    saida["ref"] = (float(np.median([s.lf_hf for s in ref if s and s.lf_hf_valido])), n_ref)
    return saida


def tabela_validacao(res: list[dict[str, tuple[float, int]]]) -> str:
    nomes = {
        "ecg_100hz": "picos R na grade de 100 Hz, sem interpolar",
        "ppg_100hz": "picos do PPG a 100 Hz, sem interpolar",
        "ppg_interpolado": "picos do PPG a 100 Hz, com parábola",
    }
    linhas = [("| Entrada | fator de erro, mediana | pior registro | registros abaixo de 1,2 "
               "| saídas válidas (do ECG exato) |"), "|---|---|---|---|---|"]
    n_ref = sum(e["ref"][1] for e in res)
    for chave, nome in nomes.items():
        f = np.array([e[chave][0] for e in res])
        n = sum(e[chave][1] for e in res)
        linhas.append(f"| {nome} | {np.nanmedian(f):.3f} | {np.nanmax(f):.2f} "
                      f"| {(f < 1.2).sum()} de {len(f)} | {n} de {n_ref} |")
    return "\n".join(linhas)


# ---- Vetores do teste em C -------------------------------------------------------


def _arrays(bats: list[Batimento]) -> dict[str, np.ndarray]:
    bats = [b._replace(fracao=float(np.float32(b.fracao)), rr_ms=float(np.float32(b.rr_ms)))
            for b in bats]
    saidas = roda(bats)
    return {
        "valido": np.array([b.valido for b in bats], dtype=np.int32),
        "n_pico": np.array([b.n_pico for b in bats], dtype=np.int64),
        "fracao": np.array([b.fracao for b in bats], dtype=np.float32),
        "rr_valido": np.array([b.rr_valido for b in bats], dtype=np.int32),
        "rr_ms": np.array([b.rr_ms for b in bats], dtype=np.float32),
        "escreveu": np.array([s is not None for s in saidas], dtype=np.int32),
        "lf_hf_valido": np.array([bool(s and s.lf_hf_valido) for s in saidas], dtype=np.int32),
        "lf_hf": np.array([s.lf_hf if s else 0.0 for s in saidas], dtype=np.float32),
    }


def rr_senoidal(duracao_s: float, a_lf: float, a_hf: float, rr0: float = 900.0,
                f_lf: float = 0.1, f_hf: float = 0.25) -> tuple[np.ndarray, np.ndarray]:
    """Batimentos com RR(t) = rr0 + a_lf sen(2π f_lf t) + a_hf sen(2π f_hf t).

    Devolve (instantes em s, RR em ms). O LF/HF esperado é ~(a_lf / a_hf)².
    """
    t, ts, rrs = 0.0, [0.0], [0.0]
    while t < duracao_s:
        rr = rr0 + a_lf * math.sin(2 * math.pi * f_lf * t) + a_hf * math.sin(2 * math.pi * f_hf * t)
        t += rr / 1000.0
        ts.append(t)
        rrs.append(rr)
    return np.array(ts), np.array(rrs)


def batimentos_bordas() -> list[Batimento]:
    """Sequência sintética que passa por todas as regras (ver o teste em C)."""
    rng = np.random.default_rng(21)
    t, _ = rr_senoidal(1500.0, 40.0, 25.0)
    bats: list[Batimento] = []
    n = 1000
    for k in range(1, len(t)):
        rr = (t[k] - t[k - 1]) * 1000.0 + rng.normal(0, 5)
        valido, rr_valido = True, k > 1
        if k == 400:
            rr = 250.0  # rápido demais: rejeitado
        elif k == 450:
            rr = 2600.0  # lento demais: rejeitado
        elif k in (500, 501, 502):
            rr_valido = False  # perdidos em sequência
        elif k == 520:
            valido = False  # lixo do picos/: ignorado
        n += round(rr / 10.0)
        if k == 700:
            n = 500  # n voltou: reinicia
        if k == 1150:
            n += 400 * FS_HZ  # 400 s sem batimento: a janela esvazia
            rr_valido = False
        bats.append(Batimento(valido, n, float(rng.uniform(0, 1)), rr_valido, rr))
    # Fim: 800 batimentos de ~380 ms (158 bpm): mais de CAP RR em 300 s.
    for _ in range(800):
        rr = 375.0 + float(rng.uniform(0, 10))
        n += round(rr / 10.0)
        bats.append(Batimento(True, n, 0.0, True, rr))
    return bats


def gera_vetores() -> list:
    from analise.vetores import gera_vetor

    r = physionet.carrega("s1_sit")
    return [
        gera_vetor("hrv", "freq_s1_sit", _arrays(hrv.batimentos_de_tempos(r.t_picos_ecg, True)),
                   tol=0.002, descricao="LF/HF: picos R do ECG de s1_sit (registro "
                   "inteiro), com fracao exata."),
        gera_vetor("hrv", "freq_bordas", _arrays(batimentos_bordas()), tol=0.002,
                   descricao="LF/HF, sintético: RR fora da faixa, perdidos, inválido, "
                   "reinício, buraco de 400 s e buffer cheio."),
    ]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--vetores", action="store_true", help="grava testes/hrv/vetores/freq_*.h")
    p.add_argument("--janelas", action="store_true", help="60/120/180 s contra 300 s")
    p.add_argument("--metodos", action="store_true", help="outras contas contra a nossa")
    a = p.parse_args()
    if a.vetores:
        for caminho in gera_vetores():
            print(caminho)
        return
    registros = [physionet.carrega(f"s{i}_sit") for i in range(1, 23)]
    if a.janelas:
        print(compara_janelas(registros))
        return
    if a.metodos:
        print(compara_metodos(registros))
        return
    res = []
    for r in registros:
        e = valida_registro(r)
        res.append(e)
        print(r.nome, {k: (round(v[0], 3), v[1]) for k, v in e.items()})
    print(tabela_validacao(res))


if __name__ == "__main__":
    main()
