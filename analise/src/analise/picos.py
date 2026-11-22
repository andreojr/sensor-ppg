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
REG_JANELA = 8  # batimentos que o teste de regularidade olha
REG_MINIMO = 6  # desses, quantos têm que ser "bons": RR válido e perto da mediana dos RR válidos
REG_TOL = 0.15  # "perto da mediana": a menos de 15% dela
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
        self.hist: list[
            tuple[bool, float]
        ] = []  # (rr_valido, rr_ms) dos últimos REG_JANELA batimentos

    def regular(self) -> bool:
        """Os últimos REG_JANELA batimentos formam um ritmo: pelo menos REG_MINIMO deles são "bons",
        isto é, têm RR válido e esse RR está a menos de REG_TOL da mediana dos RR válidos.

        Sinal sem pulso (dedo mal apoiado) também gera "batimentos", com RR de 300 a 1500 ms: os RR
        podem passar um a um pela faixa de rr_valido, mas não ficam juntos perto de uma mediana.
        """
        if len(self.hist) < REG_JANELA:
            return False
        val = sorted(F32(rr) for ok, rr in self.hist if ok)
        n = len(val)
        if n < REG_MINIMO:
            return False
        med = val[n // 2] if n % 2 else F32(F32(val[n // 2 - 1] + val[n // 2]) * F32(0.5))
        bons = sum(1 for rr in val if abs(F32(rr - med)) < F32(F32(REG_TOL) * med))
        return bons >= REG_MINIMO

    @property
    def bpm(self) -> tuple[bool, float]:
        """ppg_bpm_t: (valido, bpm). valido = ritmo regular (regular()), que já exige
        REG_MINIMO RR válidos, todos em self.rrs."""
        if not self.regular():
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
        if (
            self.n >= ESPERA
            and n > 0
            and self.x1 > self.x2
            and self.x1 >= x
            and self.x1 > F32(LIMIAR) * self.env
        ):
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

        self.hist = [*self.hist, (rr_valido, rr_ms)][-REG_JANELA:]
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
    (
        "ritmo_misto",
        "sintético: ritmo, extrassístole, arritmia, ritmo: o valido liga, desliga e volta",
    ),
)
VETOR_DURACAO_S = 40.0
# ritmo_misto, em amostras entre pulsos: 15 de 800 ms, uma extrassístole (1000 ms), 12 de 800 ms, 10 pares
# de 600 e 1000 ms (cada um passa pelo rr_valido, nenhum fica perto da mediana) e 20 de 800 ms.
RITMO_MISTO = [80] * 15 + [100] + [80] * 12 + [60, 100] * 10 + [80] * 20


def trem_de_pulsos(intervalos: list[int], inicio: int = 300) -> np.ndarray:
    """Pulsos de 40 ms de largura (gaussianas) a cada intervalo, com 3 s de silêncio antes e depois."""
    em = inicio + np.concatenate([[0], np.cumsum(intervalos)])
    t = np.arange(int(em[-1]) + 300, dtype=float)
    x = np.zeros_like(t)
    for t0 in em:
        x += np.exp(-((t - t0) ** 2) / (2 * 4**2))
    return x.astype(np.float32)


def gera_vetores(testes: Path | None = None) -> list[Path]:
    """Grava testes/picos/vetores/<caso>.h: entrada e o que o C tem que devolver."""
    from analise import fonte_falsa, physionet, vetores

    saidas = []
    for nome, descricao in CASOS:
        if nome == "ritmo_misto":
            entrada = trem_de_pulsos(RITMO_MISTO)
        else:
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
                descricao=f"{nome} ({descricao})"
                + ("" if nome == "ritmo_misto" else f": {VETOR_DURACAO_S:g} s do filtrado_ir."),
                **({"testes": testes} if testes else {}),
            )
        )
    return saidas


AQUECE_S = 10.0  # captura no meio: o envelope do Python começa do zero
TOL_INSTANTE = 0.15  # amostras: o Python roda sobre o filtrado com 2 casas
TOL_RR_MS = 2.0
TOL_BPM = 0.1
MEMORIA_TIPICO = 24  # batimentos: 0,875^24 ≈ 4% de uma diferença no RR típico


def depois_do_reset(dados: np.ndarray, coluna: int = 0) -> np.ndarray:
    """As linhas depois do último reset da placa (onde o n volta pra trás)."""
    voltas = np.flatnonzero(np.diff(dados[:, coluna]) < 0)
    return dados[voltas[-1] + 1 :] if len(voltas) else dados


def confere_placa(filtrado: np.ndarray, picos_placa: np.ndarray) -> dict:
    """Roda o picos do Python no filtrado que a placa mandou e compara com os batimentos dela.

    filtrado: colunas n, ir, vermelho (o _filtrado.csv da captura).
    picos_placa: colunas n_pico, fracao, rr_valido, rr_ms, bpm_valido, bpm (o _picos.csv).

    Captura desde o boot (primeiro n = 0, a placa resetada com a captura
    aberta): o Python vê o mesmo filtrado desde o começo e tudo tem que bater,
    instante, RR, rr_valido e BPM. Captura no meio: o Python começa do zero, e
    o rr_valido e o BPM dependem do RR típico e dos últimos 8 RR, que ele só
    alcança depois de vários batimentos (ou nunca, se pegou um batimento falso
    no começo). Aí só o instante e o RR entram no OK (depois de AQUECE_S, pro
    envelope); rr_valido e BPM saem como informação.
    """
    # Captura aberta antes do reset: fica só o que veio depois do boot.
    filtrado = depois_do_reset(filtrado)
    picos_placa = depois_do_reset(picos_placa)
    n = filtrado[:, 0].astype(np.int64)
    if np.any(np.diff(n) != 1):
        raise ValueError("o filtrado tem saltos no n: a comparação não vale")
    desde_boot = bool(n[0] == 0)
    p = Picos()
    py = []
    for k, x in zip(n, filtrado[:, 1], strict=True):
        tipico = float(p.rr_tipico)  # o que a decisão do rr_valido usa
        b = p.processa(float(x), int(k))
        if b is not None:
            bordas = (RR_MIN_MS, RR_MAX_MS, RR_FAIXA[0] * tipico, RR_FAIXA[1] * tipico)
            na_borda = min(abs(b.rr_ms - v) for v in bordas) <= TOL_RR_MS
            py.append((b.instante, b.rr_valido, b.rr_ms, *p.bpm, na_borda))

    inicio = -np.inf if desde_boot else n[0] + AQUECE_S * FS_HZ - ATRASO_AMOSTRAS
    # O último batimento do Python precisa do refratário inteiro depois do pico.
    fim = n[-1] - REFRAT - 2 - ATRASO_AMOSTRAS
    margem = 1.0  # amostras: um batimento na borda pode cair de um lado só
    placa = [(b[0] + b[1], bool(b[2]), b[3], bool(b[4]), b[5]) for b in picos_placa]
    placa = [b for b in placa if inicio - margem <= b[0] <= fim + margem]
    py = [b for b in py if inicio - margem <= b[0] <= fim + margem]
    t_py = np.array([b[0] for b in py])

    # Casa por instante; casados[i] = índice no Python do i-ésimo da placa (ou -1).
    livres = set(range(len(py)))
    casados = []
    for b in placa:
        j = int(np.argmin(np.abs(t_py - b[0]))) if len(py) else -1
        if j >= 0 and abs(t_py[j] - b[0]) <= TOL_INSTANTE and j in livres:
            casados.append(j)
            livres.discard(j)
        else:
            casados.append(-1)

    def dentro(t: float) -> bool:
        return inicio + margem <= t <= fim - margem

    so_placa = sum(1 for b, j in zip(placa, casados, strict=True) if j < 0 and dentro(b[0]))
    so_py = sum(1 for j in livres if dentro(py[j][0]))
    pares = [(b, py[j]) for b, j in zip(placa, casados, strict=True) if j >= 0 and dentro(b[0])]
    # RR só quando o batimento anterior também casou com o anterior do Python.
    rr = [
        abs(placa[i][2] - py[casados[i]][2])
        for i in range(1, len(placa))
        if casados[i] > 0 and casados[i - 1] == casados[i] - 1 and dentro(placa[i][0])
    ]

    def maximo(valores: list[float]) -> float:
        return float(max(valores)) if valores else 0.0

    # rr_valido diferente só é erro longe das bordas da faixa: na borda, o
    # filtrado com 2 casas mexe no rr_ms o bastante pra virar a decisão. Aí a
    # janela de 8 RR do BPM fica diferente pelos próximos BPM_JANELA batimentos.
    # Um RR na borda de 300/2000 ms também muda se o RR típico atualiza (média
    # móvel com alfa 1/8): a diferença leva uns 24 batimentos pra sumir.
    rr_valido_dif = rr_valido_borda = 0
    bpm_erros, bpm_valido_dif, pula_bpm, perto_borda = [], 0, 0, 0
    for a, b in pares:
        if b[5]:
            perto_borda = MEMORIA_TIPICO
        elif perto_borda:
            perto_borda -= 1
        if a[1] != b[1]:
            if perto_borda:
                rr_valido_borda += 1
                pula_bpm = BPM_JANELA
                continue
            rr_valido_dif += 1
        if pula_bpm:  # a janela de 8 RR válidos ainda tem o RR que divergiu
            pula_bpm -= a[1] and b[1]
            continue
        bpm_valido_dif += a[3] != b[3]
        if a[3] and b[3]:
            bpm_erros.append(abs(a[4] - b[4]))

    r = {
        "desde_boot": desde_boot,
        "batimentos": sum(1 for b in placa if dentro(b[0])),
        "casados": len(pares),
        "so_placa": so_placa,
        "so_python": so_py,
        "erro_instante": maximo([abs(a[0] - b[0]) for a, b in pares]),
        "erro_rr_ms": maximo(rr),
        "rr_valido_diferente": rr_valido_dif,
        "rr_valido_na_borda": rr_valido_borda,
        "erro_bpm": maximo(bpm_erros),
        "bpm_valido_diferente": bpm_valido_dif,
    }
    bpms = [a[4] for a, _ in pares if a[3]]
    r["bpm"] = float(np.median(bpms)) if bpms else float("nan")
    ok = (
        r["batimentos"] > 0
        and so_placa == 0
        and so_py == 0
        and r["erro_instante"] <= TOL_INSTANTE
        and r["erro_rr_ms"] <= TOL_RR_MS
    )
    if desde_boot:
        ok = (
            ok
            and r["rr_valido_diferente"] == 0
            and r["bpm_valido_diferente"] == 0
            and r["erro_bpm"] <= TOL_BPM
        )
    r["ok"] = ok
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
        arq_picos = lado(args.confere.stem + "_picos.csv")
        if not arq_picos.exists():
            raise SystemExit(
                f"sem {arq_picos.name}: a placa não mandou nenhuma linha p, (dedo no sensor?)"
            )
        r = confere_placa(
            np.loadtxt(lado(args.confere.stem + "_filtrado.csv"), delimiter=",", skiprows=1),
            np.loadtxt(arq_picos, delimiter=",", skiprows=1, ndmin=2),
        )
        modo = (
            "desde o boot"
            if r["desde_boot"]
            else f"no meio (depois de {AQUECE_S:g} s; rr_valido e BPM só informativos)"
        )
        print(
            f"captura {modo}: {r['batimentos']} batimentos da placa, "
            f"{r['casados']} casados, {r['so_placa']} só na placa, {r['so_python']} só no Python"
        )
        print(
            f"erro máximo: instante {r['erro_instante']:.4f} amostra, rr {r['erro_rr_ms']:.2f} ms, "
            f"bpm {r['erro_bpm']:.2f}; rr_valido diferente em {r['rr_valido_diferente']} "
            f"(+{r['rr_valido_na_borda']} na borda da faixa), "
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
