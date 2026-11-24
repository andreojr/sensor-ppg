"""Grava TODAS as linhas da serial, cada uma com o horário, só leitura.

A captura.py separa as linhas em CSVs e joga fora o que não conhece (como as linhas "d,"
do espelho do display). Aqui nada se perde: cada linha que a placa manda vira uma linha
do arquivo, no formato

    <segundos desde o início>\\t<linha da serial>

O horário é o de recebimento no PC (a placa não manda relógio): leva o atraso do USB e do
sistema, de alguns milissegundos. Serve de evidência (o oled_confere.py lê esse arquivo) e pra rever uma sessão depois. O
programa só lê a serial: não manda nada pra placa.

Uso:
    uv run python -m analise.grava_log COM3 --segundos 400 -o dados/sessao.log
    uv run python -m analise.grava_log /dev/ttyUSB0 --espera 10 --segundos 400 -o dados/sessao.log

--espera dá uns segundos pra pôr o dedo no sensor antes de começar a gravar.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import TextIO

import serial

from analise.captura import BAUD, Fonte


def grava(
    fonte: Fonte,
    saida: TextIO,
    segundos: float,
    relogio: Callable[[], float] = time.monotonic,
) -> int:
    """Lê linhas de `fonte` por `segundos` e escreve "tempo<TAB>linha" em `saida`.

    O tempo conta desde a primeira chamada. Linha vazia é ignorada. Devolve quantas
    linhas gravou. `relogio` existe só pra os testes não dependerem do relógio de verdade."""
    inicio = relogio()
    n = 0
    while relogio() - inicio < segundos:
        linha = fonte.readline().decode("ascii", "replace").rstrip("\r\n")
        if linha:
            saida.write(f"{relogio() - inicio:.3f}\t{linha}\n")
            n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Grava todas as linhas da serial com o horário")
    ap.add_argument("porta", help="porta serial (COM3, /dev/ttyUSB0)")
    ap.add_argument("--segundos", type=float, required=True, help="quanto tempo gravar")
    ap.add_argument("--espera", type=float, default=0.0, help="segundos de espera antes de gravar")
    ap.add_argument("--baud", type=int, default=BAUD, help=f"velocidade (padrão {BAUD})")
    ap.add_argument("-o", "--saida", type=Path, required=True, help="arquivo de saída (.log)")
    args = ap.parse_args(argv)

    if args.espera > 0:
        print(f"começa a gravar em {args.espera:.0f} s: ponha o dedo agora", flush=True)
        time.sleep(args.espera)
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    with serial.Serial(args.porta, args.baud, timeout=0.5) as porta, args.saida.open("w") as f:
        porta.reset_input_buffer()
        print("gravando...", flush=True)
        n = grava(porta, f, args.segundos)
    print(f"fim: {n} linhas em {args.saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
