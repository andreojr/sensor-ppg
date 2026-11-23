"""Carrega um CSV da captura que só existe com -DSERIAL_COMPLETA=ON.

Desde a #17, o firmware padrão manda pela serial só o bruto (b,), os resultados e as
linhas #. As cruas (o CSV principal) e o filtrado (_filtrado.csv) só saem com
-DSERIAL_COMPLETA=ON. Sem elas, os --confere param com uma mensagem clara, e não
com um erro do numpy.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

AVISO = "grave o firmware com -DSERIAL_COMPLETA=ON e capture de novo"


def carrega(caminho: Path) -> np.ndarray:
    """As linhas do CSV (sem o cabeçalho), em n x colunas. SystemExit se faltar ou vazio."""
    if not caminho.exists():
        raise SystemExit(f"falta {caminho.name}: {AVISO}")
    with caminho.open(encoding="utf-8") as f:
        if sum(1 for linha in f if linha.strip()) < 2:
            raise SystemExit(f"{caminho.name} está vazio (só o cabeçalho): {AVISO}")
    return np.loadtxt(caminho, delimiter=",", skiprows=1, ndmin=2)
