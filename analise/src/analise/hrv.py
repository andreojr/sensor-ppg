"""HRV no tempo: SDNN e RMSSD numa janela deslizante de batimentos.

HRV (variabilidade da frequência cardíaca) mede o quanto o intervalo entre
batimentos (RR, em ms) muda de um batimento pro outro. Duas medidas no tempo:

  SDNN   desvio padrão dos RR da janela (com N - 1). Variação total, lenta e
         rápida.
  RMSSD  raiz da média dos quadrados das diferenças entre RR seguidos. Só a
         variação rápida, de um batimento pro próximo (respiração, vago).

Este arquivo é o protótipo do módulo hrv/ em C (Core/*/pds/hrv/): a classe
Hrv faz, batimento a batimento, exatamente o que o C faz, com as mesmas
constantes. Os vetores de referência do teste em C saem daqui.

Regras (as mesmas do C):

  - Janela: os batimentos dos últimos JANELA_S segundos, contados pelo n_pico
    (um batimento sai da janela quando n_atual - n_pico >= JANELA_AMOSTRAS).
  - Só entra RR com rr_valido e dentro de RR_MIN_MS..RR_MAX_MS (30 a 200 bpm).
    Um RR rejeitado não entra e quebra a sequência: a diferença do RMSSD só
    existe entre dois RR aceitos seguidos.
  - valido quando os RR aceitos cobrem pelo menos COBERTURA_MIN da janela
    (45 dos 60 s) e há pelo menos MIN_DIF diferenças.
  - Batimento com valido false é ignorado (processa devolve None). Se o n_pico
    voltar pra trás, o módulo reinicia (a fonte falsa recomeçou).

Validação no PhysioNet (uv run python -m analise.hrv): os picos R do ECG a
500 Hz são o gabarito. Mede o erro de SDNN e RMSSD quando os batimentos chegam
na grade de 100 Hz (sem interpolar o pico) e quando vêm do PPG.

Placa x Python, no CSV da captura (com _picos e _hrv ao lado), o passo 5:

    uv run python -m analise.hrv --confere dados/sensor_<data>_<hora>.csv
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
from scipy import signal

from analise import FS_HZ, physionet

JANELA_S = 60
JANELA_AMOSTRAS = JANELA_S * FS_HZ
CAP = 256  # cabe a janela inteira a 200 bpm (RR_MIN_MS); se encher, sai o mais antigo
RR_MIN_MS = 300.0
RR_MAX_MS = 2000.0
COBERTURA_MIN = 0.75
MIN_DIF = 20


class Batimento(NamedTuple):
    """Espelho de ppg_batimento_t."""

    valido: bool
    n_pico: int
    fracao: float
    rr_valido: bool
    rr_ms: float


class SaidaHrv(NamedTuple):
    """Espelho de ppg_hrv_t (sem o LF/HF, que fica pra depois)."""

    valido: bool
    sdnn_ms: float
    rmssd_ms: float


@dataclass
class _Item:
    n: int
    rr: float
    dif: float | None  # rr - rr do anterior aceito, se os dois são seguidos


class Hrv:
    """Estado do módulo. Mesmo comportamento de hrv_init/hrv_processa."""

    def __init__(self) -> None:
        self.reinicia()

    def reinicia(self) -> None:
        self.itens: list[_Item] = []
        self.ultimo_n: int | None = None
        self.rr_anterior: float | None = None

    def processa(self, b: Batimento) -> SaidaHrv | None:
        if not b.valido:
            return None
        if self.ultimo_n is not None and b.n_pico < self.ultimo_n:
            self.reinicia()
        self.ultimo_n = b.n_pico

        # Sai da janela o que ficou velho (antes de entrar o novo).
        self.itens = [i for i in self.itens if b.n_pico - i.n < JANELA_AMOSTRAS]

        aceito = b.rr_valido and math.isfinite(b.rr_ms) and RR_MIN_MS <= b.rr_ms <= RR_MAX_MS
        if aceito:
            dif = None if self.rr_anterior is None else b.rr_ms - self.rr_anterior
            if len(self.itens) == CAP:
                self.itens.pop(0)
            self.itens.append(_Item(b.n_pico, b.rr_ms, dif))
            self.rr_anterior = b.rr_ms
        else:
            self.rr_anterior = None
        return self._resultado()

    def _resultado(self) -> SaidaHrv:
        rr = np.array([i.rr for i in self.itens])
        difs = np.array([i.dif for i in self.itens if i.dif is not None])
        cobertura = rr.sum() >= COBERTURA_MIN * JANELA_S * 1000.0
        if not (cobertura and len(difs) >= MIN_DIF):
            return SaidaHrv(False, 0.0, 0.0)
        return SaidaHrv(True, sdnn(rr), rmssd_de_difs(difs))


def sdnn(rr_ms: np.ndarray) -> float:
    """Desvio padrão amostral (N - 1), como na Task Force de 1996 e no Kubios."""
    return float(np.std(rr_ms, ddof=1))


def rmssd_de_difs(difs_ms: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(difs_ms))))


def rmssd(rr_ms: np.ndarray) -> float:
    """RMSSD de uma sequência sem buracos."""
    return rmssd_de_difs(np.diff(rr_ms))


def roda(batimentos: list[Batimento]) -> list[SaidaHrv | None]:
    h = Hrv()
    return [h.processa(b) for b in batimentos]


# ---- Montagem dos batimentos ---------------------------------------------------


def batimentos_de_tempos(t_s: np.ndarray, interpola: bool,
                         rr_valido: np.ndarray | None = None) -> list[Batimento]:
    """Batimentos a FS_HZ a partir dos instantes exatos de cada pico.

    interpola=True: n_pico + fracao guardam o instante exato, e rr_ms vem dele
    (é o que o picos/ entrega se interpolar o pico). interpola=False: o pico cai
    na amostra mais próxima, fracao = 0, e rr_ms sai de n_pico (múltiplo de 10 ms).
    rr_valido: máscara opcional; o primeiro é sempre inválido.
    """
    x = np.asarray(t_s, dtype=float) * FS_HZ
    if interpola:
        n = np.floor(x).astype(np.int64)
        fracao = x - n
    else:
        n = np.round(x).astype(np.int64)
        fracao = np.zeros_like(x)
    instante = n + fracao
    rr = np.concatenate([[0.0], np.diff(instante) * 1000.0 / FS_HZ])
    ok = np.ones(len(x), dtype=bool) if rr_valido is None else np.asarray(rr_valido, dtype=bool)
    ok = ok.copy()
    if len(ok):
        ok[0] = False
    return [Batimento(True, int(n[k]), float(fracao[k]), bool(ok[k]), float(rr[k]))
            for k in range(len(x))]


def picos_ppg_validacao(r: physionet.Registro, interpola: bool) -> np.ndarray:
    """Instantes (s) dos picos do PPG. SÓ pra validar o HRV: o detector de verdade
    é o módulo picos/, de outra pessoa.

    IR decimado pra 100 Hz, passa-faixa 0,5 a 4 Hz de fase zero, invertido (mais
    sangue absorve mais luz, então o pulso é um vale no IR cru), máximos locais
    com no mínimo 0,3 s entre eles. Com interpola, a parábola pelos três pontos
    em volta do máximo dá a posição entre amostras (no máximo meia amostra).
    """
    fator = r.fs_hz // FS_HZ
    bruto = signal.resample_poly(r.ir - r.ir.mean(), 1, fator)
    sos = signal.butter(2, (0.5, 4.0), btype="band", fs=FS_HZ, output="sos")
    x = -signal.sosfiltfilt(sos, bruto)
    picos, _ = signal.find_peaks(x, distance=round(0.3 * FS_HZ), prominence=np.std(x) * 0.3)
    picos = picos[(picos > 0) & (picos < len(x) - 1)]
    pos = picos.astype(float)
    if interpola:
        a, b, c = x[picos - 1], x[picos], x[picos + 1]
        den = a - 2 * b + c
        desloc = np.where(den < 0, 0.5 * (a - c) / np.where(den < 0, den, -1.0), 0.0)
        pos += np.clip(desloc, -0.5, 0.5)
    return pos / FS_HZ


def casa_ppg_com_ecg(t_ecg: np.ndarray, t_ppg: np.ndarray,
                     atraso_s: tuple[float, float] = (0.1, 0.6)) -> np.ndarray:
    """Pra cada pico R, o pico do PPG que chega atraso_s depois (NaN se não há)."""
    casado = np.full(len(t_ecg), np.nan)
    for k, t in enumerate(t_ecg):
        j = np.searchsorted(t_ppg, t + atraso_s[0])
        if j < len(t_ppg) and t_ppg[j] < t + atraso_s[1]:
            casado[k] = t_ppg[j]
    return casado


# ---- Validação -----------------------------------------------------------------


@dataclass(frozen=True)
class Erro:
    """Erro de um registro: RMS das diferenças contra a referência, por batimento."""

    registro: str
    saidas: int
    sdnn_ref_ms: float  # mediana da referência, pra ter a escala
    rmssd_ref_ms: float
    sdnn_rms_ms: float
    rmssd_rms_ms: float


def compara(ref: list[SaidaHrv | None], obt: list[SaidaHrv | None], nome: str) -> Erro:
    """Compara batimento a batimento onde os dois são válidos."""
    pares = [(a, b) for a, b in zip(ref, obt, strict=True)
             if a is not None and b is not None and a.valido and b.valido]
    if not pares:
        return Erro(nome, 0, math.nan, math.nan, math.nan, math.nan)
    a = np.array([(p.sdnn_ms, p.rmssd_ms) for p, _ in pares])
    b = np.array([(q.sdnn_ms, q.rmssd_ms) for _, q in pares])
    e = np.sqrt(np.mean((b - a) ** 2, axis=0))
    return Erro(nome, len(pares), float(np.median(a[:, 0])), float(np.median(a[:, 1])),
                float(e[0]), float(e[1]))


def valida_registro(r: physionet.Registro) -> dict[str, Erro]:
    t_ecg = r.t_picos_ecg
    ref = roda(batimentos_de_tempos(t_ecg, interpola=True))
    erros = {"ecg_100hz": compara(ref, roda(batimentos_de_tempos(t_ecg, interpola=False)),
                                  r.nome)}
    for interpola, chave in ((False, "ppg_100hz"), (True, "ppg_interpolado")):
        t_ppg = casa_ppg_com_ecg(t_ecg, picos_ppg_validacao(r, interpola))
        achou = ~np.isnan(t_ppg)
        # Batimento perdido: o seguinte tem rr_valido false (como o picos/ faria).
        ok = achou & np.concatenate([[False], achou[:-1]])
        bats = batimentos_de_tempos(np.where(achou, t_ppg, t_ecg + 0.25), interpola, ok)
        # Os perdidos não chegam ao HRV: saem da sequência, mas o alinhamento
        # com o ECG (um por pico R) fica.
        h = Hrv()
        obt = [h.processa(b) if a else None for b, a in zip(bats, achou, strict=True)]
        erros[chave] = compara(ref, obt, r.nome)
    return erros


def tabela(erros: list[dict[str, Erro]]) -> str:
    linhas = ["| Entrada do HRV | SDNN, erro RMS | RMSSD, erro RMS | RMSSD < 5 ms |",
              "|---|---|---|---|"]
    nomes = {
        "ecg_100hz": "picos R na grade de 100 Hz, sem interpolar",
        "ppg_100hz": "picos do PPG a 100 Hz, sem interpolar",
        "ppg_interpolado": "picos do PPG a 100 Hz, com parábola",
    }
    for chave, nome in nomes.items():
        s = np.array([e[chave].sdnn_rms_ms for e in erros])
        m = np.array([e[chave].rmssd_rms_ms for e in erros])
        linhas.append(f"| {nome} | mediana {np.nanmedian(s):.2f} ms (máx {np.nanmax(s):.2f}) "
                      f"| mediana {np.nanmedian(m):.2f} ms (máx {np.nanmax(m):.2f}) "
                      f"| {(m < 5).sum()} de {len(m)} registros |")
    sd = np.array([e["ecg_100hz"].sdnn_ref_ms for e in erros])
    rm = np.array([e["ecg_100hz"].rmssd_ref_ms for e in erros])
    linhas.append(f"\nReferência (ECG a 500 Hz, janela de {JANELA_S} s): SDNN mediano "
                  f"{np.nanmedian(sd):.1f} ms ({np.nanmin(sd):.1f} a {np.nanmax(sd):.1f}), "
                  f"RMSSD mediano {np.nanmedian(rm):.1f} ms ({np.nanmin(rm):.1f} a "
                  f"{np.nanmax(rm):.1f}), {len(erros)} registros.")
    return "\n".join(linhas)


# ---- Vetores do teste em C -----------------------------------------------------


def _arrays(bats: list[Batimento]) -> dict[str, np.ndarray]:
    # A entrada vai em float32, como o C recebe; o Python roda nesses valores.
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
        "saida_valido": np.array([bool(s and s.valido) for s in saidas], dtype=np.int32),
        "sdnn": np.array([s.sdnn_ms if s else 0.0 for s in saidas], dtype=np.float32),
        "rmssd": np.array([s.rmssd_ms if s else 0.0 for s in saidas], dtype=np.float32),
    }


def batimentos_bordas() -> list[Batimento]:
    """Sequência sintética que passa por todas as regras (ver o teste em C)."""
    rng = np.random.default_rng(18)
    bats: list[Batimento] = []
    n = 1000
    for k in range(400):
        rr = 800.0 + 60.0 * math.sin(2 * math.pi * k / 5) + rng.normal(0, 15)
        rr_valido = k > 0
        valido = True
        if k == 90:
            rr = 250.0  # rápido demais: rejeitado
        elif k == 120:
            rr = 2600.0  # lento demais: rejeitado
        elif k in (150, 151, 152):
            rr_valido = False  # batimentos perdidos em sequência
        elif k == 180:
            valido = False  # o picos/ mandou lixo: ignorado
        n += round(rr / 10.0)
        if k == 250:
            n = 500  # n voltou: reinicia
        if k == 320:
            n += 90 * FS_HZ  # 90 s sem batimento: a janela esvazia
            rr_valido = False
        bats.append(Batimento(valido, n, float(rng.uniform(0, 1)), rr_valido, rr))
    # Fim com 300 batimentos de ~302 ms e n andando 20 em 20: enche o buffer (CAP).
    for _ in range(300):
        n += 20
        bats.append(Batimento(True, n, 0.0, True, 301.0 + float(rng.uniform(0, 2))))
    return bats


def gera_vetores() -> list:
    from analise.vetores import gera_vetor

    r = physionet.carrega("s1_sit")
    return [
        gera_vetor("hrv", "s1_sit", _arrays(batimentos_de_tempos(r.t_picos_ecg, True)),
                   tol=0.01, descricao="Picos R do ECG de s1_sit (registro inteiro), "
                   "com fracao exata."),
        gera_vetor("hrv", "bordas", _arrays(batimentos_bordas()), tol=0.01,
                   descricao="Sintético: RR fora da faixa, perdidos, inválido, "
                   "reinício, buraco de 90 s e buffer cheio."),
    ]


# ---- Janela curta contra a de 5 min --------------------------------------------


def hrv_janela(t_s: np.ndarray, janela_s: float, a_partir_s: float) -> np.ndarray:
    """SDNN e RMSSD dos RR que terminam nos últimos janela_s, a cada batimento.

    Cálculo direto (sem o estado do módulo), com os RR exatos e a mesma faixa
    de RR aceitos. Só a partir de t >= a_partir_s, pra que janelas de tamanhos
    diferentes sejam comparadas nos mesmos batimentos. Devolve (k, 2): SDNN, RMSSD.
    """
    rr = np.diff(t_s) * 1000.0
    t_fim = t_s[1:]
    ok = (rr >= RR_MIN_MS) & (rr <= RR_MAX_MS)
    saida = []
    for k in np.flatnonzero(t_fim >= a_partir_s):
        dentro = (t_fim > t_fim[k] - janela_s) & (t_fim <= t_fim[k])
        sel = dentro & ok
        par = sel[1:] & sel[:-1]  # diferença só entre dois RR aceitos seguidos
        saida.append((sdnn(rr[sel]), rmssd_de_difs(np.diff(rr)[par])))
    return np.array(saida).reshape(-1, 2)


def compara_janelas(registros: list[physionet.Registro], curta_s: float = JANELA_S,
                    longa_s: float = 300.0) -> str:
    """Quanto o HRV da janela curta se afasta do da janela de 5 min (o padrão)."""
    linhas = ["| Medida | 60 s − 5 min, mediana | diferença típica (RMS) | razão 60 s / 5 min |",
              "|---|---|---|---|"]
    por_registro = []
    for r in registros:
        t = r.t_picos_ecg
        a_partir = t[0] + longa_s
        c = hrv_janela(t, curta_s, a_partir)
        lg = hrv_janela(t, longa_s, a_partir)
        por_registro.append((np.median(c - lg, axis=0), np.sqrt(np.mean((c - lg) ** 2, axis=0)),
                             np.median(c / lg, axis=0), np.median(lg, axis=0)))
    vies, rms, razao, ref = (np.array([p[i] for p in por_registro]) for i in range(4))
    for j, nome in enumerate(("SDNN", "RMSSD")):
        linhas.append(f"| {nome} | {np.median(vies[:, j]):+.1f} ms "
                      f"({np.min(vies[:, j]):+.1f} a {np.max(vies[:, j]):+.1f}) "
                      f"| {np.median(rms[:, j]):.1f} ms (pior {np.max(rms[:, j]):.1f}) "
                      f"| {np.median(razao[:, j]):.2f} ({np.min(razao[:, j]):.2f} a "
                      f"{np.max(razao[:, j]):.2f}) |")
    linhas.append(f"\nValor de 5 min, mediana dos registros: SDNN {np.median(ref[:, 0]):.1f} ms, "
                  f"RMSSD {np.median(ref[:, 1]):.1f} ms. {len(registros)} registros, "
                  f"comparados a cada batimento depois de {longa_s:g} s.")
    return "\n".join(linhas)


TOL_HRV_MS = 0.05  # a placa manda rr_ms, SDNN e RMSSD com 2 casas
BORDA_COBERTURA_MS = 1.0  # soma dos RR a menos disso da cobertura: as 2 casas viram o valido


def confere_placa(picos_placa: np.ndarray, hrv_placa: np.ndarray) -> dict:
    """Passa os batimentos que a placa mandou pelo HRV do Python e compara com a saída dela.

    picos_placa: colunas n_pico, fracao, rr_valido, rr_ms, bpm_valido, bpm (o _picos.csv).
    hrv_placa: colunas n_pico, valido, sdnn_ms, rmssd_ms[, rr_usado] (o _hrv.csv), uma linha
    por batimento. Com rr_usado = 0 a placa deixou o RR de fora (trecho que a qualidade
    disse não usável), e o Python faz o mesmo; sem a coluna (firmware antigo), entra tudo.
    Captura desde o boot (o primeiro batimento é o primeiro da placa, com
    rr_ms = 0): tudo tem que bater. No meio: só depois de uma janela inteira
    (JANELA_S), quando a janela do Python tem os mesmos batimentos que a da placa.
    """
    from analise.picos import depois_do_reset

    picos_placa = depois_do_reset(picos_placa)
    hrv_placa = depois_do_reset(hrv_placa)
    # A captura pode cortar o par p,/h, nas pontas (começou ou parou entre as duas).
    # A h, sai até ~1 s depois da p, (espera a qualidade): no começo podem sobrar
    # algumas h, sem a p,, e no fim algumas p, sem a h,.
    if len(picos_placa):
        hrv_placa = hrv_placa[hrv_placa[:, 0] >= picos_placa[0, 0]]
    picos_placa = picos_placa[: len(hrv_placa)]
    if len(picos_placa) != len(hrv_placa) or np.any(picos_placa[:, 0] != hrv_placa[:, 0]):
        raise ValueError("as linhas p, e h, não casam batimento a batimento")
    desde_boot = bool(picos_placa[0, 3] == 0 and picos_placa[0, 2] == 0)
    a_partir = -1 if desde_boot else picos_placa[0, 0] + JANELA_AMOSTRAS + 3 * FS_HZ

    h = Hrv()
    comparados = valido_dif = valido_borda = 0
    erro_sdnn = erro_rmssd = 0.0
    validos = []
    for b, o in zip(picos_placa, hrv_placa, strict=True):
        usado = len(o) < 5 or bool(o[4])  # -1: firmware antigo, entrava tudo
        s = h.processa(Batimento(True, int(b[0]), float(b[1]), bool(b[2]) and usado, float(b[3])))
        if b[0] < a_partir:
            continue
        comparados += 1
        if s.valido != bool(o[1]):
            soma = sum(i.rr for i in h.itens)
            if abs(soma - COBERTURA_MIN * JANELA_S * 1000.0) <= BORDA_COBERTURA_MS:
                valido_borda += 1
            else:
                valido_dif += 1
            continue
        if s.valido:
            validos.append((float(o[2]), float(o[3])))
            erro_sdnn = max(erro_sdnn, abs(s.sdnn_ms - o[2]))
            erro_rmssd = max(erro_rmssd, abs(s.rmssd_ms - o[3]))
    r = {
        "desde_boot": desde_boot,
        "batimentos": comparados,
        "validos": len(validos),
        "valido_diferente": valido_dif,
        "valido_na_borda": valido_borda,
        "erro_sdnn_ms": float(erro_sdnn),
        "erro_rmssd_ms": float(erro_rmssd),
        "sdnn_ms": float(np.median([v[0] for v in validos])) if validos else float("nan"),
        "rmssd_ms": float(np.median([v[1] for v in validos])) if validos else float("nan"),
    }
    # Sem nenhum HRV válido comparado, não há o que aprovar (captura curta ou ruim).
    r["ok"] = bool(
        len(validos) > 0
        and valido_dif == 0
        and erro_sdnn <= TOL_HRV_MS
        and erro_rmssd <= TOL_HRV_MS
    )
    return r


# Linha perdida na serial: a placa viu a amostra, o Python não. Se o Python pulasse o n,
# a qualidade dele recomeçaria e julgaria fora de fase com a placa até o fim. Por isso
# buracos de até BURACO_MAX amostras são preenchidos por interpolação, e os batimentos
# perto deles (a interpolação não é o sinal de verdade) ficam fora da comparação.
# Buraco maior: compara só até ele.
BURACO_ANTES, BURACO_DEPOIS = 3 * FS_HZ, 10 * FS_HZ
BURACO_MAX = 10


def _preenche(x: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Preenche buracos pequenos no n por interpolação; corta no primeiro grande.
    Devolve o sinal contínuo e onde estavam os buracos."""
    n = x[:, 0].astype(np.int64)
    saltos = np.flatnonzero(np.diff(n) != 1)
    grandes = [k for k in saltos if n[k + 1] - n[k] > BURACO_MAX + 1 or n[k + 1] <= n[k]]
    if grandes:
        x, n = x[: grandes[0] + 1], n[: grandes[0] + 1]
        saltos = saltos[saltos < grandes[0]]
    todo = np.arange(n[0], n[-1] + 1)
    cheio = np.column_stack([todo] + [np.interp(todo, n, x[:, c]) for c in (1, 2)])
    return cheio, [int(n[k]) for k in saltos]


def confere_rr_usado(bruto: np.ndarray, filtrado: np.ndarray, hrv_placa: np.ndarray) -> dict | None:
    """Refaz no Python a decisão do laço (qual RR entra no HRV) e compara com o rr_usado.

    bruto e filtrado: colunas n, ir, vermelho de uma captura desde o boot. hrv_placa:
    o _hrv.csv. None se a placa não mandou o rr_usado (a captura grava -1). Batimentos
    perto de um buraco no n (linha perdida na serial) ficam de fora da comparação."""
    from analise.picos import depois_do_reset
    from analise.qualidade import rr_entrou_no_hrv

    if hrv_placa.shape[1] < 5 or np.all(hrv_placa[:, 4] < 0):
        return None
    (bruto, b1), (filtrado, b2) = (_preenche(depois_do_reset(x)) for x in (bruto, filtrado))
    placa = depois_do_reset(hrv_placa)
    python = rr_entrou_no_hrv(bruto, filtrado)
    buracos = b1 + b2

    def perto(n: int) -> bool:
        return any(b - BURACO_ANTES <= n <= b + BURACO_DEPOIS for b in buracos)

    comuns = [(int(k), bool(u)) for k, u in placa[:, [0, 4]] if int(k) in python]
    longe = [(k, u) for k, u in comuns if not perto(k)]
    difs = sum(python[k] != u for k, u in longe)
    return {
        "comparados": len(longe),
        "perto_de_buraco": len(comuns) - len(longe),
        "fora": sum(not u for _, u in longe),
        "diferentes": difs,
        "ok": bool(longe) and difs == 0,
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--confere", help="CSV da captura (com _picos e _hrv ao lado)")
    p.add_argument("--vetores", action="store_true", help="grava testes/hrv/vetores/")
    p.add_argument("--janelas", action="store_true", help="compara a janela de 60 s com 5 min")
    a = p.parse_args()
    if a.confere:
        from pathlib import Path

        base = Path(a.confere)
        arqs = [base.with_name(f"{base.stem}_{x}.csv") for x in ("picos", "hrv")]
        for arq in arqs:
            if not arq.exists():
                raise SystemExit(f"sem {arq.name}: a placa não mandou linhas de batimento")
        r = confere_placa(*(np.loadtxt(x, delimiter=",", skiprows=1, ndmin=2) for x in arqs))
        modo = "desde o boot" if r["desde_boot"] else f"no meio (depois de {JANELA_S} s)"
        print(f"captura {modo}: {r['batimentos']} batimentos comparados, {r['validos']} com HRV válido")
        if r["validos"]:
            print(
                f"erro máximo: SDNN {r['erro_sdnn_ms']:.3f} ms, RMSSD {r['erro_rmssd_ms']:.3f} ms; "
                f"valido diferente em {r['valido_diferente']} (+{r['valido_na_borda']} na borda da "
                f"cobertura); SDNN mediano {r['sdnn_ms']:.1f} ms, RMSSD mediano {r['rmssd_ms']:.1f} ms: "
                f"{'OK' if r['ok'] else 'DIVERGE'}"
            )
        else:
            print("HRV: nenhum válido pra comparar; capture mais tempo (3 min) em repouso, com o "
                  "dedo parado")

        # O rr_usado roda mesmo sem HRV válido: é o que mais muda com a qualidade.
        bruto, filtrado = (base.with_name(f"{base.stem}_{x}.csv") for x in ("bruto", "filtrado"))
        rr = None
        if bruto.exists() and filtrado.exists() and r["desde_boot"]:
            rr = confere_rr_usado(
                *(np.loadtxt(x, delimiter=",", skiprows=1, ndmin=2) for x in (bruto, filtrado, arqs[1]))
            )
        if rr is None:
            print("rr_usado: não conferido (precisa de captura desde o boot, com _bruto e "
                  "_filtrado, de firmware que manda a coluna rr_usado)")
        else:
            print(f"rr_usado: {rr['comparados']} batimentos refeitos no Python (qualidade + picos + "
                  f"fila), {rr['fora']} com o RR de fora, {rr['perto_de_buraco']} ignorados perto de "
                  f"linhas perdidas; diferente em {rr['diferentes']}: "
                  f"{'OK' if rr['ok'] else 'DIVERGE'}")
            if rr["ok"] and rr["fora"] == 0:
                print("  (nenhum RR de fora: a captura não exercitou a regra; mexa o dedo um pouco)")
        if not (r["ok"] and (rr is None or rr["ok"])):
            raise SystemExit(1)
        return
    if a.vetores:
        for caminho in gera_vetores():
            print(caminho)
        return
    if a.janelas:
        print(compara_janelas([physionet.carrega(f"s{i}_sit") for i in range(1, 23)]))
        return
    nomes = [f"s{i}_sit" for i in range(1, 23)]
    erros = []
    for nome in nomes:
        e = valida_registro(physionet.carrega(nome))
        erros.append(e)
        print(nome, {k: (round(v.sdnn_rms_ms, 2), round(v.rmssd_rms_ms, 2), v.saidas)
                     for k, v in e.items()})
    print(tabela(erros))


if __name__ == "__main__":
    main()
