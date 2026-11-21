"""Protótipo do módulo picos: batimentos e BPM a partir do PPG filtrado.

Entrada: filtrado (passa-faixa 0,5 a 4 Hz, média zero) a FS_HZ, uma amostra por
vez. Saída: um batimento (ppg_batimento_t) quando há pico, e o BPM
(ppg_bpm_t) sobre os últimos intervalos válidos.

O código é em fluxo e em float32 de propósito: o porte pra C
(Core/Src/pds/picos/picos.c) segue linha a linha, e os vetores de referência
saem daqui.

Método:
  1. Envelope de pico com decaimento: env = max(x, env * DECAI). É o "nível dos
     picos recentes" e se adapta quando a amplitude muda.
  2. Limiar adaptativo: um máximo local só vira candidato se passa de
     LIMIAR * env.
  3. Período refratário: candidato a menos de REFRAT_S do batimento anterior é
     rejeitado (onda dicrótica, ruído logo depois do pico).
  4. Instante por interpolação parabólica (fracao em [0, 1)), menos
     PPG_ATRASO_AMOSTRAS.
  5. Intervalo RR válido só dentro de [RR_MIN_MS, RR_MAX_MS] e perto do
     intervalo típico (RR_FAIXA); senão rr_valido = false e o HRV ignora.

Vetores de referência pro teste em C (testes/picos/vetores/), da pasta analise/:

    uv run python -m analise.picos

Validação contra o ECG: uv run python -m analise.picos_validacao

Placa x Python, no CSV da captura (com _filtrado e _picos ao lado):

    uv run python -m analise.picos --confere dados/sensor_<data>_<hora>.csv
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from analise import FS_HZ, filtro

F32 = np.float32

ATRASO_AMOSTRAS = float(filtro.ATRASO)  # PPG_ATRASO_AMOSTRAS do ppg.h
ESPERA_S = 2.0  # sem detectar enquanto o envelope não conhece o sinal
TAU_ENV_S = 1.0  # decaimento do envelope
LIMIAR = 0.3  # fração do envelope que um pico precisa ter
REFRAT_S = 0.3  # intervalo mínimo entre batimentos (200 bpm)
RR_MIN_MS = 300.0
RR_MAX_MS = 2000.0
RR_FAIXA = (0.7, 1.4)  # RR válido em relação ao RR típico
RR_ALFA = 0.125  # peso de cada RR novo no RR típico
BPM_JANELA = 8  # BPM = média dos últimos 8 RR válidos
BPM_MINIMO = 4  # RR válidos pra o BPM valer
TOL_VETOR = 1e-2  # tolerância dos floats no teste em C (fracao, rr_ms, bpm)

DECAI = F32(math.exp(-1.0 / (TAU_ENV_S * FS_HZ)))
ESPERA = round(ESPERA_S * FS_HZ)
REFRAT = round(REFRAT_S * FS_HZ)
MS_POR_AMOSTRA = 1000.0 / FS_HZ


@dataclass(frozen=True)
class Batimento:
    """ppg_batimento_t (sempre valido)."""

    n_pico: int
    fracao: float
    rr_valido: bool
    rr_ms: float

    @property
    def instante(self) -> float:
        """Em amostras a FS_HZ, fração incluída."""
        return self.n_pico + self.fracao


class Picos:
    def __init__(self) -> None:
        self.reinicia()

    def reinicia(self) -> None:
        """picos_init."""
        self.n = 0
        self.x1 = F32(0)  # x[n-1]
        self.x2 = F32(0)  # x[n-2]
        self.env = F32(0)
        self.ultimo: Batimento | None = None
        self.ultimo_base = 0  # n (sem descontar o atraso) do último batimento
        # Candidato esperando o refratário passar: (base, n_pico, fracao, altura).
        # Um candidato maior dentro do refratário toma o lugar dele.
        self.pendente: tuple[int, int, float, float] | None = None
        self.rr_tipico = F32(0)  # 0 = ainda não conhece
        self.rrs: list[float] = []  # últimos RR válidos

    @property
    def bpm(self) -> tuple[bool, float]:
        """ppg_bpm_t: (valido, bpm)."""
        if len(self.rrs) < BPM_MINIMO:
            return False, 0.0
        soma = F32(0)
        for rr in self.rrs:
            soma += F32(rr)
        return True, float(F32(60000.0) / (soma / F32(len(self.rrs))))

    def processa(self, x: float, n: int | None = None) -> Batimento | None:
        """picos_processa: devolve o batimento se esta amostra fechou um pico.

        n é o da cadeia (ppg_amostra_t.n); sem ele, conta desde o init.
        """
        x = F32(x)
        decaido = F32(self.env * DECAI)
        # Nessa ordem, como o `x > decaido ? x : decaido` do C: com x NaN fica o
        # decaido (max(x, decaido) devolveria o NaN e estragaria o envelope).
        self.env = max(decaido, x)
        if n is None:
            n = self.n
        # Máximo local em x[n-1], visto com uma amostra de atraso. self.n só
        # conta o aquecimento desde o init.
        if (self.n >= ESPERA and n > 0 and self.x1 > self.x2 and self.x1 >= x
                and self.x1 > F32(LIMIAR) * self.env):
            self._candidato(n - 1, self.x2, self.x1, x)
        self.x2, self.x1 = self.x1, x
        self.n += 1
        # Passado o refratário sem aparecer candidato maior, o pendente vira batimento.
        if self.pendente is not None and n - self.pendente[0] >= REFRAT:
            return self._emite()
        return None

    def _candidato(self, base: int, y0: float, y1: float, y2: float) -> None:
        """Candidato em `base` com vizinhos y0, y1 (o pico), y2."""
        # Refratário no n da entrada, sem descontar o atraso (o n_pico já vem descontado).
        if self.ultimo is not None and base - self.ultimo_base < REFRAT:
            return
        # Dentro do refratário do pendente, só vale um pico maior (a corcova do FIR
        # antes do batimento perde pro pico verdadeiro).
        if self.pendente is not None and y1 <= self.pendente[3]:
            return

        # Vértice da parábola por (base-1, y0), (base, y1), (base+1, y2).
        # O denominador é negativo num máximo; y1 > y0 e y1 >= y2 o garante. Só
        # zera por arredondamento num platô (y1 == y2): aí o pico fica em base.
        den = y0 - F32(2) * y1 + y2
        d = F32(0.5) * (y0 - y2) / den if den != 0 else F32(0)
        if not math.isfinite(d):  # vizinho infinito: fica em base, como no C
            d = F32(0)
        f = d - F32(ATRASO_AMOSTRAS)
        k = math.floor(f)
        n_pico = base + k
        fracao = float(f - F32(k))
        if fracao >= 1.0:  # arredondamento do float32
            n_pico, fracao = n_pico + 1, 0.0
        self.pendente = (base, max(n_pico, 0), fracao, float(y1))

    def _emite(self) -> Batimento:
        """O pendente passou do refratário: vira batimento, com RR e BPM."""
        base, n_pico, fracao, _ = self.pendente
        self.pendente = None
        rr_valido, rr_ms = False, 0.0
        if self.ultimo is not None:
            rr_ms = float(
                F32(n_pico - self.ultimo.n_pico + fracao - self.ultimo.fracao) * F32(MS_POR_AMOSTRA)
            )
            if RR_MIN_MS <= rr_ms <= RR_MAX_MS:
                tipico = float(self.rr_tipico)
                rr_valido = tipico == 0.0 or (RR_FAIXA[0] * tipico <= rr_ms <= RR_FAIXA[1] * tipico)
                self.rr_tipico = (
                    F32(rr_ms)
                    if tipico == 0.0
                    else F32(self.rr_tipico + F32(RR_ALFA) * (F32(rr_ms) - self.rr_tipico))
                )
            if rr_valido:
                self.rrs = [*self.rrs, rr_ms][-BPM_JANELA:]

        b = Batimento(n_pico, fracao, rr_valido, rr_ms)
        self.ultimo = b
        self.ultimo_base = base
        return b


def detecta(filtrado: np.ndarray) -> tuple[list[Batimento], np.ndarray]:
    """Roda o detector num trecho. Devolve os batimentos e o BPM em cada um."""
    p = Picos()
    batimentos, bpms = [], []
    for x in filtrado:
        b = p.processa(x)
        if b is not None:
            batimentos.append(b)
            valido, bpm = p.bpm
            bpms.append(bpm if valido else np.nan)
    return batimentos, np.asarray(bpms)


CASOS = (
    ("s1_sit", "limpo, sentado"),
    ("s2_walk", "artefato de movimento: rr_valido e bpm falsos"),
    ("s3_sit", "corcova do FIR antes do batimento: exercita o candidato pendente"),
)
VETOR_DURACAO_S = 40.0


def gera_vetores(testes: Path | None = None) -> list[Path]:
    """Grava testes/picos/vetores/<caso>.h: entrada e o que o C tem que devolver."""
    from analise import fonte_falsa, physionet, vetores

    saidas = []
    for nome, descricao in CASOS:
        f = fonte_falsa.gera(physionet.carrega(nome), 30.0, VETOR_DURACAO_S)
        entrada = f.filtrado_ir.astype(np.float32)
        batimentos, bpm = detecta(entrada)
        arrays = {
            "entrada": entrada,
            "n_pico": [b.n_pico for b in batimentos],
            "fracao": [b.fracao for b in batimentos],
            "rr_valido": [b.rr_valido for b in batimentos],
            "rr_ms": [b.rr_ms for b in batimentos],
            "bpm_valido": ~np.isnan(bpm),
            "bpm": np.nan_to_num(bpm),
        }
        saidas.append(
            vetores.gera_vetor(
                "picos",
                nome,
                arrays,
                tol=TOL_VETOR,
                descricao=f"{nome} ({descricao}): {VETOR_DURACAO_S:g} s do filtrado_ir.",
                **({"testes": testes} if testes else {}),
            )
        )
    return saidas


AQUECE_S = 10.0  # o detector do Python começa do zero no meio da captura
TOL_INSTANTE = 0.05  # amostras: o Python roda sobre o filtrado com 2 casas
TOL_RR_MS = 1.0
TOL_BPM = 0.1


def confere_placa(filtrado: np.ndarray, picos_placa: np.ndarray) -> dict:
    """Roda o picos do Python no filtrado que a placa mandou e compara com os batimentos dela.

    filtrado: colunas n, ir, vermelho (o _filtrado.csv da captura).
    picos_placa: colunas n_pico, fracao, rr_valido, rr_ms, bpm_valido, bpm (o _picos.csv).
    A placa detecta desde o boot e o Python começa no primeiro n capturado: só
    valem os batimentos depois de AQUECE_S (envelope e RR típico já iguais) e
    antes do fim (o pendente do Python precisa do refratário inteiro).
    """
    n = filtrado[:, 0].astype(np.int64)
    if np.any(np.diff(n) != 1):
        raise ValueError("o filtrado tem saltos no n: a comparação não vale")
    p = Picos()
    py = []
    for k, x in zip(n, filtrado[:, 1], strict=True):
        b = p.processa(float(x), int(k))
        if b is not None:
            py.append((b.instante, b.rr_valido, b.rr_ms, *p.bpm))

    inicio = n[0] + AQUECE_S * FS_HZ - ATRASO_AMOSTRAS
    fim = n[-1] - REFRAT - 2 - ATRASO_AMOSTRAS
    placa = [
        (b[0] + b[1], bool(b[2]), b[3], bool(b[4]), b[5])
        for b in picos_placa
        if inicio <= b[0] + b[1] <= fim
    ]
    py = [b for b in py if inicio - 1 <= b[0] <= fim + 1]
    t_py = np.array([b[0] for b in py])
    casados, sobra_py = [], set(range(len(py)))
    for b in placa:
        j = int(np.argmin(np.abs(t_py - b[0]))) if len(py) else -1
        if j >= 0 and abs(t_py[j] - b[0]) <= TOL_INSTANTE and j in sobra_py:
            casados.append((b, py[j]))
            sobra_py.discard(j)
    so_placa = len(placa) - len(casados)
    so_py = sum(1 for j in sobra_py if inicio <= py[j][0] <= fim)

    def maximo(valores: list[float]) -> float:
        return float(max(valores)) if valores else 0.0

    r = {
        "batimentos": len(placa),
        "casados": len(casados),
        "so_placa": so_placa,
        "so_python": so_py,
        "erro_instante": maximo([abs(a[0] - b[0]) for a, b in casados]),
        "erro_rr_ms": maximo([abs(a[2] - b[2]) for a, b in casados if a[1] and b[1]]),
        "rr_valido_diferente": sum(a[1] != b[1] for a, b in casados),
        "erro_bpm": maximo([abs(a[4] - b[4]) for a, b in casados if a[3] and b[3]]),
        "bpm_valido_diferente": sum(a[3] != b[3] for a, b in casados),
    }
    bpms = [a[4] for a, _ in casados if a[3]]
    r["bpm"] = float(np.median(bpms)) if bpms else float("nan")
    r["ok"] = (
        len(placa) > 0
        and so_placa == 0
        and so_py == 0
        and r["rr_valido_diferente"] == 0
        and r["bpm_valido_diferente"] == 0
        and r["erro_instante"] <= TOL_INSTANTE
        and r["erro_rr_ms"] <= TOL_RR_MS
        and r["erro_bpm"] <= TOL_BPM
    )
    return r


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--confere", type=Path, help="CSV da captura (com _filtrado e _picos ao lado)")
    args = ap.parse_args(argv)
    if args.confere:
        lado = args.confere.with_name
        r = confere_placa(
            np.loadtxt(lado(args.confere.stem + "_filtrado.csv"), delimiter=",", skiprows=1),
            np.loadtxt(lado(args.confere.stem + "_picos.csv"), delimiter=",", skiprows=1, ndmin=2),
        )
        print(
            f"{r['batimentos']} batimentos da placa depois de {AQUECE_S:g} s; "
            f"{r['casados']} casados, {r['so_placa']} só na placa, {r['so_python']} só no Python"
        )
        print(
            f"erro máximo: instante {r['erro_instante']:.4f} amostra, rr {r['erro_rr_ms']:.2f} ms, "
            f"bpm {r['erro_bpm']:.2f}; rr_valido diferente em {r['rr_valido_diferente']}, "
            f"bpm_valido em {r['bpm_valido_diferente']}"
        )
        print(f"BPM mediano {r['bpm']:.1f}: {'OK' if r['ok'] else 'DIVERGE'}")
        if not r["ok"]:
            raise SystemExit(1)
        return
    for caminho in gera_vetores():
        print(caminho)


if __name__ == "__main__":
    main()
