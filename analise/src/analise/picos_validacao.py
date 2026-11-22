"""Validação do protótipo de picos contra o ECG do PhysioNet.

O gabarito são os picos R. O pico do PPG chega depois do R (tempo de trânsito
do pulso, de 100 a 155 ms nos 15 registros), então o atraso de cada registro é estimado e
descontado antes de contar acertos. Só o BPM e os intervalos importam pro
resto da cadeia.

Métricas por registro:
  sens   batimentos do ECG que têm um pico do PPG junto (acerto / total ECG)
  prec   picos do PPG que têm um batimento do ECG junto (acerto / total PPG)
  rr     erro do intervalo RR, em ms, nos pares de acertos seguidos (mediana, p95)
  bpm    erro do BPM médio do trecho contra o do ECG, em bpm
  valido fração dos batimentos (depois dos 8 primeiros) com picos_bpm().valido ligado

Regularidade do BPM (como se escolheu o critério do valido):

  uv run python -m analise.picos_validacao --regularidade

mede, em todos os registros do PhysioNet que já estão no cache e em ruído sem pulso, quanto do tempo o
valido fica ligado com cada critério e tolerância.

Uso (da pasta analise/):  uv run python -m analise.picos_validacao [registro ...]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np

from analise import FS_HZ, filtro, fonte_falsa, physionet
from analise.picos import ESPERA_S, detecta

JANELA_ATRASO_S = (0.05, 0.6)  # onde procurar o pico do PPG depois do R
TOLERANCIA_S = 0.15  # acerto: perto do atraso estimado, mais ou menos isto
INICIO_S = 30.0
DURACAO_S = 60.0
PADRAO = [f"s{i}_{a}" for i in (1, 2, 3, 4, 5) for a in ("sit", "walk", "run")]


@dataclass(frozen=True)
class Resultado:
    registro: str
    n_ecg: int
    n_ppg: int
    atraso_ms: float
    sens: float
    prec: float
    rr_mediana_ms: float
    rr_p95_ms: float
    bpm_ecg: float
    bpm_ppg: float
    bpm_valido: float  # fração dos batimentos (depois de 8) com picos_bpm().valido


def casa(t_ecg: np.ndarray, t_ppg: np.ndarray) -> tuple[float, np.ndarray]:
    """Atraso mediano do PPG e, pra cada R do ECG, o índice do pico casado (-1 se nenhum)."""
    atrasos = []
    for r in t_ecg:
        depois = t_ppg[(t_ppg >= r + JANELA_ATRASO_S[0]) & (t_ppg <= r + JANELA_ATRASO_S[1])]
        if len(depois):
            atrasos.append(depois[0] - r)
    atraso = float(np.median(atrasos)) if atrasos else 0.0

    par = np.full(len(t_ecg), -1)
    usados: set[int] = set()
    for i, r in enumerate(t_ecg):
        j = int(np.argmin(np.abs(t_ppg - (r + atraso)))) if len(t_ppg) else -1
        if j >= 0 and abs(t_ppg[j] - (r + atraso)) <= TOLERANCIA_S and j not in usados:
            par[i] = j
            usados.add(j)
    return atraso, par


def valida(nome: str) -> Resultado:
    f = fonte_falsa.gera(physionet.carrega(nome), INICIO_S, DURACAO_S)
    batimentos, bpms = detecta(f.filtrado_ir)
    t_ppg = np.array([b.instante for b in batimentos]) / FS_HZ
    # Fora a fase de aquecimento do detector (ele ainda não conhece o sinal).
    t_ecg = f.n_pico / FS_HZ
    t_ecg = t_ecg[t_ecg >= ESPERA_S + JANELA_ATRASO_S[1]]

    atraso, par = casa(t_ecg, t_ppg)
    acertos = par >= 0
    sens = float(acertos.mean()) if len(t_ecg) else 0.0
    prec = float(acertos.sum() / len(t_ppg)) if len(t_ppg) else 0.0

    # RR: só pares de batimentos do ECG seguidos, os dois casados, com rr_valido.
    erros = []
    for i in range(1, len(t_ecg)):
        if par[i] >= 1 and par[i - 1] >= 0 and par[i] == par[i - 1] + 1:
            b = batimentos[par[i]]
            if b.rr_valido:
                erros.append(abs(b.rr_ms - (t_ecg[i] - t_ecg[i - 1]) * 1000.0))
    erros_a = np.asarray(erros) if erros else np.array([np.nan])

    rr_ppg = [b.rr_ms for b in batimentos if b.rr_valido]
    bpm_ppg = 60000.0 / np.mean(rr_ppg) if rr_ppg else float("nan")
    bpm_ecg = 60.0 / np.mean(np.diff(t_ecg)) if len(t_ecg) > 1 else float("nan")

    return Resultado(
        nome,
        len(t_ecg),
        len(t_ppg),
        atraso * 1000.0,
        sens,
        prec,
        float(np.nanmedian(erros_a)),
        float(np.nanpercentile(erros_a, 95)),
        float(bpm_ecg),
        float(bpm_ppg),
        float(np.mean(~np.isnan(bpms[8:]))) if len(bpms) > 8 else 0.0,
    )


def tabela(resultados: list[Resultado]) -> str:
    linhas = [
        "registro  ECG  PPG  atraso   sens   prec  RR med  RR p95  BPM ecg  BPM ppg  erro  BPM válido",
        "--------  ---  ---  ------  -----  -----  ------  ------  -------  -------  -----  ----------",
    ]
    for r in resultados:
        linhas.append(
            f"{r.registro:<8}  {r.n_ecg:>3}  {r.n_ppg:>3}  {r.atraso_ms:>4.0f}ms  "
            f"{r.sens:>5.1%}  {r.prec:>5.1%}  {r.rr_mediana_ms:>4.0f}ms  {r.rr_p95_ms:>4.0f}ms  "
            f"{r.bpm_ecg:>7.1f}  {r.bpm_ppg:>7.1f}  {abs(r.bpm_ppg - r.bpm_ecg):>5.2f}  "
            f"{r.bpm_valido:>9.0%}"
        )
    return "\n".join(linhas)


TOLERANCIAS = (0.10, 0.15, 0.20, 0.25)
MINIMO_DE_BONS = 6
JANELA_REG = 8


def regular(hist: list[tuple[bool, float]], tol: float, todos: bool) -> bool:
    """O critério de regularidade, com a tolerância e a variante à escolha.

    todos = False: pelo menos 6 dos 8 batimentos são bons (RR válido e perto da mediana dos RR válidos).
    É o que o Picos.regular() faz com tol = 0,15. todos = True: TODOS os RR válidos têm que estar perto
    da mediana (uma extrassístole ou uma pessoa com HRV alta derruba o valido).
    """
    if len(hist) < JANELA_REG:
        return False
    val = [rr for ok, rr in hist if ok]
    if len(val) < MINIMO_DE_BONS:
        return False
    med = float(np.median(val))
    perto = [abs(rr - med) < tol * med for rr in val]
    return all(perto) if todos else sum(perto) >= MINIMO_DE_BONS


def fracao_ligada(batimentos, tol: float, todos: bool) -> float:
    hist: list[tuple[bool, float]] = []
    ligado = []
    for b in batimentos:
        hist = [*hist, (b.rr_valido, b.rr_ms)][-JANELA_REG:]
        ligado.append(regular(hist, tol, todos))
    ligado = ligado[JANELA_REG:]
    return float(np.mean(ligado)) if ligado else float("nan")


def varredura_regularidade() -> str:
    """Fração do tempo com o valido ligado, por atividade e por ruído, pra cada critério e tolerância."""
    no_cache = [n for n in physionet.registros() if (physionet.PASTA_PADRAO / f"{n}.dat").exists()]
    por_ativ: dict[str, list[list[float]]] = {}
    for nome in no_cache:
        f = fonte_falsa.gera(physionet.carrega(nome), INICIO_S, DURACAO_S)
        bs, _ = detecta(f.filtrado_ir.astype(np.float32))
        linha = [fracao_ligada(bs, t, todos) for todos in (True, False) for t in TOLERANCIAS]
        por_ativ.setdefault(nome.split("_")[1], []).append(linha)

    # Sem pulso: ruído branco com a mesma passagem pelo filtro e pelo picos (12 trechos de 60 s).
    rng = np.random.default_rng(0)
    ruido = []
    for _ in range(12):
        x = filtro.filtra(80000.0 + 3000.0 * rng.standard_normal(round(DURACAO_S * FS_HZ)))
        bs, _ = detecta(x.astype(np.float32))
        ruido.append([fracao_ligada(bs, t, todos) for todos in (True, False) for t in TOLERANCIAS])
    por_ativ["ruído"] = ruido

    cab = "".join(f"  tod{int(t * 100):>2}%" for t in TOLERANCIAS) + "  |"
    cab += "".join(f"  6de8 {int(t * 100):>2}%" for t in TOLERANCIAS)
    linhas = [
        "valido ligado (fração do tempo). tod = todos os RR válidos perto da mediana; 6de8 = 6 de 8 bons",
        f"{'':<14}{cab}",
    ]
    for ativ, g in por_ativ.items():
        m = np.nanmean(np.array(g), axis=0)
        linhas.append(
            f"{ativ:<7}({len(g):>2}) "
            + "".join(f"  {v:>5.0%}" for v in m[:4])
            + "  |"
            + "".join(f"  {v:>8.0%}" for v in m[4:])
        )
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> None:
    if (argv if argv is not None else sys.argv[1:]) == ["--regularidade"]:
        print(varredura_regularidade())
        return
    nomes = (argv if argv is not None else sys.argv[1:]) or PADRAO
    resultados = [valida(n) for n in nomes]
    print(tabela(resultados))
    sens = np.mean([r.sens for r in resultados])
    prec = np.mean([r.prec for r in resultados])
    erro = np.mean([abs(r.bpm_ppg - r.bpm_ecg) for r in resultados])
    print(
        f"\nmédia de {len(resultados)} registros: sens {sens:.1%}, prec {prec:.1%}, "
        f"erro de BPM {erro:.2f}"
    )


if __name__ == "__main__":
    main()
