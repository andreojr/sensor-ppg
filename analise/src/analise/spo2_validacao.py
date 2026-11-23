"""Validação do protótipo spo2 nos registros do PhysioNet.

O PhysioNet NÃO traz SpO2 de referência (o gabarito dele é o ECG, que não mede oxigenação), então
não há "erro contra a referência". O que se confere é o que a issue #27 pede e o que dá pra
checar sem oxímetro:

  estabilidade   o R varia pouco de uma janela pra outra dentro de um registro (desvio do R).
                 Duas medidas: entre todas as saídas (janelas de 8 s a cada 1 s, que dividem
                 7 s de dados e por isso variam pouco por construção) e entre janelas SEM
                 sobreposição (uma saída a cada 8 s), o critério "R estável entre janelas";
  plausibilidade a SpO2 estimada de pessoas saudáveis fica entre 95 e 100%;
  canais         trocando vermelho e IR, o R vira ~1/R (perto de 2), fora da faixa que a
                 fisiologia permite: quase tudo fica inválido. A atribuição dos canais faz
                 diferença, e o R_MAX protege contra LEDs trocados no sensor.

Cada registro: 60 s a partir de 30 s do bruto da fonte falsa (com DC, a 100 Hz).

Uso (da pasta analise/):  uv run python -m analise.spo2_validacao [registro ...]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np

from analise import fonte_falsa, physionet
from analise.spo2 import JANELA_S, estima

INICIO_S = 30.0
DURACAO_S = 60.0
PADRAO = [f"s{i}_{a}" for i in (1, 2, 3, 4, 5) for a in ("sit", "walk", "run")]


@dataclass(frozen=True)
class Resultado:
    registro: str
    dc_vermelho: float
    dc_ir: float
    validos: float  # fração de saídas com valido = True
    r_medio: float
    r_desvio: float  # entre todas as saídas válidas (janelas sobrepostas)
    r_desvio_disjunto: float  # entre janelas sem sobreposição (uma saída a cada JANELA_S)
    spo2_medio: float
    validos_trocado: float  # fração válida com os canais trocados


def valida(nome: str) -> Resultado:
    f = fonte_falsa.gera(physionet.carrega(nome), INICIO_S, DURACAO_S)
    s = estima(f.bruto_ir, f.bruto_vermelho)
    t = estima(f.bruto_vermelho, f.bruto_ir)  # canais trocados
    boas = [x for x in s if x.valido]
    disjuntas = [x for x in s[::JANELA_S] if x.valido]  # uma saída por segundo: passo de 8 s
    return Resultado(
        nome,
        float(f.bruto_vermelho.mean()),
        float(f.bruto_ir.mean()),
        len(boas) / len(s),
        float(np.mean([x.r for x in boas])),
        float(np.std([x.r for x in boas])),
        float(np.std([x.r for x in disjuntas])) if len(disjuntas) > 1 else float("nan"),
        float(np.mean([x.spo2 for x in boas])),
        sum(x.valido for x in t) / len(t),
    )


def tabela(rs: list[Resultado]) -> str:
    linhas = [
        (
            "registro  DC verm.  DC IR   válidos  R médio  R desvio  sem sobrep.  SpO2   "
            "válidos (canais trocados)"
        ),
        (
            "--------  --------  ------  -------  -------  --------  -----------  -----  "
            "-------------------------"
        ),
    ]
    for r in rs:
        linhas.append(
            f"{r.registro:<8}  {r.dc_vermelho:>8.0f}  {r.dc_ir:>6.0f}  {r.validos:>6.0%}  "
            f"{r.r_medio:>7.3f}  {r.r_desvio:>8.3f}  {r.r_desvio_disjunto:>11.3f}  {r.spo2_medio:>4.1f}%  {r.validos_trocado:>24.0%}"
        )
    return "\n".join(linhas)


def resumo(rs: list[Resultado]) -> str:
    linhas = []
    for ativ in ("sit", "walk", "run"):
        g = [r for r in rs if r.registro.endswith(ativ)]
        if not g:
            continue
        linhas.append(
            f"{ativ:<5} R médio {np.mean([r.r_medio for r in g]):.3f} | desvio do R (mediana) "
            f"{np.median([r.r_desvio for r in g]):.3f}, sem sobreposição "
            f"{np.nanmedian([r.r_desvio_disjunto for r in g]):.3f} "
            f"(máx. {np.nanmax([r.r_desvio_disjunto for r in g]):.3f}) | "
            f"SpO2 {np.mean([r.spo2_medio for r in g]):.1f}% "
            f"[{min(r.spo2_medio for r in g):.1f}, {max(r.spo2_medio for r in g):.1f}] | "
            f"válidos com canais trocados {np.mean([r.validos_trocado for r in g]):.0%} "
            f"(máx. {max(r.validos_trocado for r in g):.0%})"
        )
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> None:
    nomes = (argv if argv is not None else sys.argv[1:]) or PADRAO
    rs = [valida(n) for n in nomes]
    print(tabela(rs))
    print()
    print(resumo(rs))


if __name__ == "__main__":
    main()
