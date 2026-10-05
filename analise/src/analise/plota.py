"""Plota o sinal bruto (IR e vermelho, com DC) de um CSV gravado pelo analise.captura.

Uso:
    uv run python -m analise.plota dados/sensor_20261001_101500.csv
    uv run python -m analise.plota dados/repouso.csv --png repouso.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from analise.captura import COLUNAS, SENSOR_FS_HZ


def carrega(caminho: Path) -> pd.DataFrame:
    """Lê o CSV e acrescenta a coluna t (s), a partir de n e da taxa do sensor."""
    df = pd.read_csv(caminho)
    faltando = set(COLUNAS) - set(df.columns)
    if faltando:
        raise ValueError(f"{caminho}: faltam as colunas {sorted(faltando)}")
    df["t"] = (df["n"] - df["n"].iloc[0]) / SENSOR_FS_HZ
    return df


def figura(df: pd.DataFrame, titulo: str = ""):
    """Um gráfico por canal, com eixo de tempo comum."""
    fig, eixos = plt.subplots(2, 1, sharex=True, figsize=(12, 6))
    for eixo, canal, cor in zip(eixos, ("ir", "vermelho"), ("tab:purple", "tab:red")):
        eixo.plot(df["t"], df[canal], color=cor, linewidth=0.8)
        eixo.set_ylabel(f"{canal} (contagens)")
        eixo.grid(True, alpha=0.3)
    eixos[-1].set_xlabel("tempo (s)")
    fig.suptitle(titulo or f"Sinal bruto do MAX30102 a {SENSOR_FS_HZ} Hz")
    fig.tight_layout()
    return fig


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("csv", type=Path)
    p.add_argument("--png", type=Path, help="salva a figura em vez de abrir a janela")
    args = p.parse_args(argv)

    df = carrega(args.csv)
    fig = figura(df, args.csv.name)
    if args.png:
        fig.savefig(args.png, dpi=150)
        print(f"figura salva em {args.png}")
    else:
        plt.show()


if __name__ == "__main__":
    main()
