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
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from analise import FS_HZ

F32 = np.float32

ATRASO_AMOSTRAS = 0.0  # PPG_ATRASO_AMOSTRAS do ppg.h
ESPERA_S = 2.0  # sem detectar enquanto o envelope não conhece o sinal
TAU_ENV_S = 1.0  # decaimento do envelope
LIMIAR = 0.4  # fração do envelope que um pico precisa ter
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

    def processa(self, x: float) -> Batimento | None:
        """picos_processa: devolve o batimento se esta amostra fechou um pico."""
        x = F32(x)
        self.env = max(x, F32(self.env * DECAI))
        n = self.n
        pico = None
        # Máximo local em x[n-1], visto com uma amostra de atraso.
        if n >= ESPERA and self.x1 > self.x2 and self.x1 >= x and self.x1 > F32(LIMIAR) * self.env:
            pico = self._batimento(n - 1, self.x2, self.x1, x)
        self.x2, self.x1 = self.x1, x
        self.n = n + 1
        return pico

    def _batimento(self, base: int, y0: float, y1: float, y2: float) -> Batimento | None:
        """Candidato em `base` com vizinhos y0, y1 (o pico), y2."""
        if self.ultimo is not None and base - self.ultimo.n_pico < REFRAT:
            return None

        # Vértice da parábola por (base-1, y0), (base, y1), (base+1, y2).
        # O denominador é negativo num máximo; y1 > y0 e y1 >= y2 o garante.
        d = F32(0.5) * (y0 - y2) / (y0 - F32(2) * y1 + y2)
        f = d - F32(ATRASO_AMOSTRAS)
        k = math.floor(f)
        n_pico = base + k
        fracao = float(f - F32(k))
        if fracao >= 1.0:  # arredondamento do float32
            n_pico, fracao = n_pico + 1, 0.0
        n_pico = max(n_pico, 0)

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


CASOS = (("s1_sit", "limpo, sentado"), ("s2_walk", "artefato de movimento: rr_valido e bpm falsos"))
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


if __name__ == "__main__":
    for caminho in gera_vetores():
        print(caminho)
