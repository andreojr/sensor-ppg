"""Grava em CSV o sinal cru do sensor real, lido pela serial.

O firmware manda, a SENSOR_FS_HZ, uma linha "n,ir,vermelho" por amostra
(ver docs/src/content/docs/firmware.md). Linhas com "#" são comentário.
Linhas "b,n,ir,vermelho" e "f,n,ir,vermelho" são o bruto (decimado) e o
filtrado que a placa calculou a 100 Hz, e "r,n,rpm,valido" é a respiração (uma
por segundo): vão pra <nome>_bruto.csv, <nome>_filtrado.csv e
<nome>_respiracao.csv, ao lado do primeiro. Linhas
"p,n_pico,fracao,rr_valido,rr_ms,bpm_valido,bpm" são os batimentos do picos
na placa: vão pra <nome>_picos.csv. Linhas "h,n_pico,valido,sdnn,rmssd" são a
saída do HRV a cada batimento: vão pra <nome>_hrv.csv.
Linhas "q,..." (com -DBANCADA_QUALIDADE=ON) são a qualidade do bruto, uma
por segundo: vão pra <nome>_qualidade.csv.

Uso:
    uv run python -m analise.captura COM3 --segundos 30
    uv run python -m analise.captura /dev/ttyUSB0 -o dados/repouso.csv

Sem --segundos, grava até o Ctrl+C.
"""

from __future__ import annotations

import argparse
import csv
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

import serial

SENSOR_FS_HZ = 400  # igual a MAX30102_FS_HZ em Core/Inc/max30102.h
BAUD = 921600
DADOS = Path(__file__).resolve().parents[2] / "dados"
COLUNAS = ("n", "ir", "vermelho")
# prefixo da linha -> (ponto da cadeia na placa, colunas do CSV)
PONTOS = {
    "b": ("bruto", COLUNAS),
    "f": ("filtrado", COLUNAS),
    "r": ("respiracao", ("n", "rpm", "valido")),
}
COLUNAS_PICOS = ("n_pico", "fracao", "rr_valido", "rr_ms", "bpm_valido", "bpm")
COLUNAS_HRV = ("n_pico", "valido", "sdnn_ms", "rmssd_ms")
COLUNAS_QUALIDADE = (
    "n", "dedo", "usavel", "indice", "motivo", "dc", "pi", "aspereza", "razao", "ritmo",
)


class Fonte(Protocol):
    def readline(self) -> bytes: ...


@dataclass
class Resumo:
    amostras: int = 0
    invalidas: int = 0
    por_ponto: dict[str, int] = field(default_factory=dict)  # "bruto", "filtrado"... -> linhas
    saltos: list[tuple[int, int]] = field(default_factory=list)  # (n antes, n depois)
    comentarios: list[str] = field(default_factory=list)
    segundos: float = 0.0

    @property
    def brutos(self) -> int:
        return self.por_ponto.get("bruto", 0)

    @property
    def perdidas(self) -> int:
        return sum(depois - antes - 1 for antes, depois in self.saltos if depois > antes)


def le_linha(linha: str) -> tuple[int, int, int] | None:
    """Converte "n,ir,vermelho" em inteiros. None se a linha não for de dados."""
    partes = linha.strip().split(",")
    if len(partes) != 3:
        return None
    try:
        n, ir, vermelho = (int(p) for p in partes)
    except ValueError:
        return None
    return n, ir, vermelho


def le_ponto(linha: str) -> tuple[str, tuple[int, float, float]] | None:
    """Converte "b,n,ir,vermelho", "f,..." ou "r,n,rpm,valido" em (ponto, valores)."""
    partes = linha.strip().split(",")
    if len(partes) != 4 or partes[0] not in PONTOS:
        return None
    try:
        return PONTOS[partes[0]][0], (int(partes[1]), float(partes[2]), float(partes[3]))
    except ValueError:
        return None


def le_batimento(linha: str) -> tuple[int, float, int, float, int, float] | None:
    """Converte "p,n_pico,fracao,rr_valido,rr_ms,bpm_valido,bpm". None se não for."""
    partes = linha.strip().split(",")
    if len(partes) != 7 or partes[0] != "p":
        return None
    try:
        return (
            int(partes[1]),
            float(partes[2]),
            int(partes[3]),
            float(partes[4]),
            int(partes[5]),
            float(partes[6]),
        )
    except ValueError:
        return None


def le_hrv(linha: str) -> tuple[int, int, float, float] | None:
    """Converte "h,n_pico,valido,sdnn,rmssd". None se não for."""
    partes = linha.strip().split(",")
    if len(partes) != 5 or partes[0] != "h":
        return None
    try:
        return int(partes[1]), int(partes[2]), float(partes[3]), float(partes[4])
    except ValueError:
        return None


def le_qualidade(
    linha: str,
) -> tuple[int, int, int, float, int, int, float, float, float, float] | None:
    """Converte "q,n,dedo,usavel,indice,motivo,dc,pi,aspereza,razao,ritmo" (inteiros
    escalados, ver Core/Inc/bancada_qualidade.h) em valores. None se não for."""
    partes = linha.strip().split(",")
    if len(partes) != 11 or partes[0] != "q":
        return None
    try:
        n, dedo, usavel, indice, motivo, dc, pi, aspereza, razao, ritmo = (
            int(p) for p in partes[1:]
        )
    except ValueError:
        return None
    return (n, dedo, usavel, indice / 1000, motivo, dc, pi / 1e5, aspereza / 100, razao / 100,
            ritmo / 1000)


# prefixo -> (csv, leitor, colunas) das linhas de saída dos módulos
LINHAS = {
    "p,": ("picos", le_batimento, COLUNAS_PICOS),
    "h,": ("hrv", le_hrv, COLUNAS_HRV),
    "q,": ("qualidade", le_qualidade, COLUNAS_QUALIDADE),
}


def destino_ponto(destino: Path, ponto: str) -> Path:
    return destino.with_name(f"{destino.stem}_{ponto}.csv")


def grava(fonte: Fonte, destino: Path, segundos: float | None = None) -> Resumo:
    """Lê linhas da fonte e grava as amostras em CSV até o tempo acabar (ou Ctrl+C)."""
    resumo = Resumo()
    destino.parent.mkdir(parents=True, exist_ok=True)
    anterior: int | None = None
    inicio = time.monotonic()
    abertos: dict[str, tuple] = {}  # ponto -> (arquivo, escritor)
    with destino.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(COLUNAS)
        try:
            while segundos is None or time.monotonic() - inicio < segundos:
                linha = fonte.readline().decode("ascii", errors="replace").strip()
                if not linha:  # timeout da porta
                    continue
                if linha.startswith("#"):
                    resumo.comentarios.append(linha)
                    continue
                if linha[:2] in LINHAS:
                    ponto, ler, colunas = LINHAS[linha[:2]]
                    valores = ler(linha)
                    if valores is None:
                        resumo.invalidas += 1
                        continue
                    if ponto not in abertos:
                        arq = destino_ponto(destino, ponto).open("w", newline="", encoding="utf-8")
                        abertos[ponto] = (arq, csv.writer(arq))
                        abertos[ponto][1].writerow(colunas)
                    abertos[ponto][1].writerow(valores)
                    resumo.por_ponto[ponto] = resumo.por_ponto.get(ponto, 0) + 1
                    continue
                if linha[:2] in {f"{p}," for p in PONTOS}:
                    lido = le_ponto(linha)
                    if lido is None:
                        resumo.invalidas += 1
                        continue
                    ponto, valores = lido
                    if ponto not in abertos:
                        arq = destino_ponto(destino, ponto).open("w", newline="", encoding="utf-8")
                        abertos[ponto] = (arq, csv.writer(arq))
                        colunas = next(c for nome, c in PONTOS.values() if nome == ponto)
                        abertos[ponto][1].writerow(colunas)
                    abertos[ponto][1].writerow(valores)
                    resumo.por_ponto[ponto] = resumo.por_ponto.get(ponto, 0) + 1
                    continue
                amostra = le_linha(linha)
                if amostra is None:
                    resumo.invalidas += 1  # ex.: linha cortada ao abrir a porta
                    continue
                if anterior is not None and amostra[0] != anterior + 1:
                    resumo.saltos.append((anterior, amostra[0]))
                anterior = amostra[0]
                escritor.writerow(amostra)
                resumo.amostras += 1
        except KeyboardInterrupt:
            pass
        finally:
            for arq, _ in abertos.values():
                arq.close()
    resumo.segundos = time.monotonic() - inicio
    return resumo


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("porta", help="ex.: COM3 ou /dev/ttyUSB0")
    p.add_argument("-s", "--segundos", type=float, help="duração (padrão: até o Ctrl+C)")
    p.add_argument("-o", "--saida", type=Path, help="CSV de saída (padrão: analise/dados/)")
    args = p.parse_args(argv)

    destino = args.saida or DADOS / f"sensor_{datetime.now().astimezone():%Y%m%d_%H%M%S}.csv"
    with serial.Serial(args.porta, BAUD, timeout=0.5) as porta:
        porta.reset_input_buffer()
        print(f"gravando {args.porta} em {destino} (Ctrl+C pra parar)")
        resumo = grava(porta, destino, args.segundos)

    print(f"{resumo.amostras} amostras em {resumo.segundos:.1f} s "
          f"({resumo.amostras / max(resumo.segundos, 1e-9):.1f}/s; esperado {SENSOR_FS_HZ}/s)")
    print(f"saltos no n: {len(resumo.saltos)} ({resumo.perdidas} amostras perdidas); "
          f"linhas inválidas: {resumo.invalidas}")
    for ponto, linhas in resumo.por_ponto.items():
        print(f"{linhas} linhas do {ponto} da placa em {destino_ponto(destino, ponto)}")
    for c in resumo.comentarios:
        print(f"  {c}")


if __name__ == "__main__":
    main()
