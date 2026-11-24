"""Grava em CSV o que a placa manda pela serial.

Com -DSERIAL_COMPLETA=ON, o firmware manda, a SENSOR_FS_HZ, uma linha
"n,ir,vermelho" por amostra crua (ver docs/src/content/docs/firmware.md); no
firmware padrão essas linhas e as "f," não saem, e o CSV principal fica só com o
cabeçalho. Linhas com "#" são comentário.
Linhas "b,n,ir,vermelho" e "f,n,ir,vermelho" são o bruto (decimado) e o
filtrado que a placa calculou a 100 Hz, e "r,n,rpm,valido" é a respiração (uma
por segundo): vão pra <nome>_bruto.csv, <nome>_filtrado.csv e
<nome>_respiracao.csv, ao lado do primeiro. Linhas
"p,n_pico,fracao,rr_valido,rr_ms,bpm_valido,bpm" são os batimentos do picos
na placa: vão pra <nome>_picos.csv. Linhas "e,n,bpm_valido,bpm" são o BPM do
espectral (um por segundo): vão pra <nome>_espectral.csv. Linhas
"h,n_pico,valido,sdnn,rmssd,rr_usado" são a saída do HRV a cada batimento: vão pra
<nome>_hrv.csv. Linhas "s,n,valido,spo2,r" são a SpO2
estimada, uma por segundo: vão pra <nome>_spo2.csv.
Linhas "q,..." (com -DBANCADA_QUALIDADE=ON) são a qualidade do bruto, uma
por segundo: vão pra <nome>_qualidade.csv. Linhas "t,n,mostra,bpm" são o BPM
que a tela mostraria (qualidade + picos), uma por segundo: <nome>_tela.csv.

Com --qualidade, a captura roda a qualidade do Python (a mesma conta do C) nas
linhas "b," enquanto grava e mostra, uma vez por segundo, se o sinal está
usável e, se não está, por quê. Serve pra ajeitar o dedo antes de valer.

Uso:
    uv run python -m analise.captura COM3 --segundos 30
    uv run python -m analise.captura COM3 --segundos 60 --qualidade
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

from analise import qualidade as ql

SENSOR_FS_HZ = 400  # igual a MAX30102_FS_HZ em Core/Inc/max30102.h
BAUD = 460800  # igual a huart1.Init.BaudRate (main.c); ver firmware.md, "Por que 460800"
DADOS = Path(__file__).resolve().parents[2] / "dados"
COLUNAS = ("n", "ir", "vermelho")
# prefixo da linha -> (ponto da cadeia na placa, colunas do CSV)
PONTOS = {
    "b": ("bruto", COLUNAS),
    "f": ("filtrado", COLUNAS),
    "r": ("respiracao", ("n", "rpm", "valido")),
}
COLUNAS_PICOS = ("n_pico", "fracao", "rr_valido", "rr_ms", "bpm_valido", "bpm")
COLUNAS_ESPECTRAL = ("n", "bpm_valido", "bpm")
COLUNAS_HRV = ("n_pico", "valido", "sdnn_ms", "rmssd_ms", "rr_usado")
COLUNAS_SPO2 = ("n", "valido", "spo2", "r")
COLUNAS_TELA = ("n", "mostra", "bpm")
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
    saltos_bruto: list[tuple[int, int]] = field(default_factory=list)  # o mesmo, nas b,
    comentarios: list[str] = field(default_factory=list)
    segundos: float = 0.0

    @property
    def brutos(self) -> int:
        return self.por_ponto.get("bruto", 0)

    @property
    def perdidas(self) -> int:
        return _perdidas(self.saltos)

    @property
    def brutos_perdidos(self) -> int:
        return _perdidas(self.saltos_bruto)

    def texto(self) -> list[str]:
        """O resumo do fim da captura. Sem cruas (firmware padrão), conta pelas b,."""
        taxa = 1 / max(self.segundos, 1e-9)
        if self.amostras:
            taxa_txt = (
                f"{self.amostras} amostras em {self.segundos:.1f} s "
                f"({self.amostras * taxa:.1f}/s; esperado {SENSOR_FS_HZ}/s)"
            )
            saltos_txt = (
                f"saltos no n: {len(self.saltos)} ({self.perdidas} amostras perdidas); "
                f"linhas inválidas: {self.invalidas}"
            )
        else:
            taxa_txt = (
                f"sem linhas cruas (só saem com -DSERIAL_COMPLETA=ON); "
                f"{self.brutos} linhas b, em {self.segundos:.1f} s "
                f"({self.brutos * taxa:.1f}/s; esperado 100/s)"
            )
            saltos_txt = (
                f"saltos no n das b,: {len(self.saltos_bruto)} "
                f"({self.brutos_perdidos} linhas perdidas); linhas inválidas: {self.invalidas}"
            )
        return [taxa_txt, saltos_txt]


def _perdidas(saltos: list[tuple[int, int]]) -> int:
    return sum(depois - antes - 1 for antes, depois in saltos if depois > antes)


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


def le_espectral(linha: str) -> tuple[int, int, float] | None:
    """Converte "e,n,bpm_valido,bpm". None se não for."""
    partes = linha.strip().split(",")
    if len(partes) != 4 or partes[0] != "e":
        return None
    try:
        return int(partes[1]), int(partes[2]), float(partes[3])
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


def le_hrv(linha: str) -> tuple[int, int, float, float, int] | None:
    """Converte "h,n_pico,valido,sdnn,rmssd,rr_usado". None se não for."""
    partes = linha.strip().split(",")
    if len(partes) != 6 or partes[0] != "h":
        return None
    try:
        return int(partes[1]), int(partes[2]), float(partes[3]), float(partes[4]), int(partes[5])
    except ValueError:
        return None


def le_spo2(linha: str) -> tuple[int, int, float, float] | None:
    """Converte "s,n,valido,spo2,r". None se não for."""
    partes = linha.strip().split(",")
    if len(partes) != 5 or partes[0] != "s":
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


def le_tela(linha: str) -> tuple[int, int, float] | None:
    """Converte "t,n,mostra,bpm x100" (o BPM que a tela mostraria). None se não for."""
    partes = linha.strip().split(",")
    if len(partes) != 4 or partes[0] != "t":
        return None
    try:
        n, mostra, bpm = (int(p) for p in partes[1:])
    except ValueError:
        return None
    return n, mostra, bpm / 100


# Prefixo da linha -> (ponto, leitor, colunas do CSV) das saídas que não são amostra.
LEITORES = {
    "p,": ("picos", le_batimento, COLUNAS_PICOS),
    "h,": ("hrv", le_hrv, COLUNAS_HRV),
    "e,": ("espectral", le_espectral, COLUNAS_ESPECTRAL),
    "q,": ("qualidade", le_qualidade, COLUNAS_QUALIDADE),
    "t,": ("tela", le_tela, COLUNAS_TELA),
    "s,": ("spo2", le_spo2, COLUNAS_SPO2),
}


# Bit do motivo da qualidade -> o que dizer na tela.
MOTIVOS = (
    (ql.SEM_DEDO_BIT, "sem dedo"),
    (ql.SATURADO_BIT, "saturado (aperte menos)"),
    (ql.PULSO_FRACO_BIT, "pulso fraco"),
    (ql.MOVIMENTO_BIT, "movimento"),
    (ql.RUIDO_BIT, "ruido"),
    (ql.SEM_RITMO_BIT, "sem ritmo"),
)
VERDE, VERMELHO, AMARELO, FIM = "\033[32m", "\033[31m", "\033[33m", "\033[0m"


# Um n que pula mais que isso é linha embaralhada, não perda (igual a cadeia.SALTO_MAX).
SALTO_MAX = 64


class AoVivo:
    """Fonte que, a cada linha "b," lida, passa a amostra pela Qualidade e imprime
    o julgamento (1/s). Devolve as linhas sem mexer: a gravação continua igual.
    O relógio é o do sinal: segundos desde a 1ª linha "b," (ou desde o reinício).

    A serial perde bytes de vez em quando e uma linha "b," some ou chega estragada. A
    placa não perdeu a amostra, mas a qualidade do Python recomeçaria do zero (~5 s de
    "sem ritmo"). Por isso a linha perdida entra como a anterior repetida, como no
    replay (analise.cadeia), e um n que volta sem ser 0 é linha estragada: fica de fora."""

    def __init__(self, fonte: Fonte):
        self.fonte = fonte
        self._recomeca()
        self.ultimo: int | None = None
        self.anterior = (0.0, 0.0)

    def _recomeca(self) -> None:
        self.q = ql.Qualidade()
        self.n0: int | None = None
        self.seguidos = 0

    def readline(self) -> bytes:
        linha = self.fonte.readline()
        if linha.startswith(b"b,"):
            lido = le_ponto(linha.decode("ascii", errors="replace"))
            if lido is not None:
                self._julga(*lido[1])
        return linha

    def _julga(self, n: int, ir: float, vm: float) -> None:
        if self.ultimo is not None and n <= self.ultimo:
            if n != 0:  # linha estragada pela serial ("b,419" que chegou "b,19")
                return
            self._recomeca()  # o n voltou a 0: a placa reiniciou
            print(f"{AMARELO}--- placa reiniciou: a gravacao vale daqui ---{FIM}", flush=True)
        elif self.ultimo is not None and n - self.ultimo <= SALTO_MAX:
            for k in range(self.ultimo + 1, n):  # linhas perdidas: repete a anterior
                self._avalia(k, *self.anterior)
        self.ultimo = n
        self.anterior = (ir, vm)
        if self.n0 is None:
            self.n0 = n
        self._avalia(n, ir, vm)

    def _avalia(self, n: int, ir: float, vm: float) -> None:
        s = self.q.processa(n, ir, vm)
        if s is None:
            return
        t = (n + 1 - self.n0) / ql.FS_HZ
        if s.usavel:
            self.seguidos += 1
            print(f"{t:6.1f} s  {VERDE}USAVEL{FIM}  ({self.seguidos} seguidos)", flush=True)
            return
        self.seguidos = 0
        porque = ", ".join(txt for bit, txt in MOTIVOS if s.motivo & bit)
        print(
            f"{t:6.1f} s  {VERMELHO}nao usavel{FIM}: {porque or 'esperando 3 janelas boas'}"
            f"  (pi {100 * s.pi:.2f}%)",
            flush=True,
        )


def destino_ponto(destino: Path, ponto: str) -> Path:
    return destino.with_name(f"{destino.stem}_{ponto}.csv")


def grava(fonte: Fonte, destino: Path, segundos: float | None = None) -> Resumo:
    """Lê linhas da fonte e grava as amostras em CSV até o tempo acabar (ou Ctrl+C)."""
    resumo = Resumo()
    destino.parent.mkdir(parents=True, exist_ok=True)
    anterior: int | None = None
    anterior_bruto: int | None = None
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
                if linha[:2] in LEITORES:
                    ponto, ler, colunas = LEITORES[linha[:2]]
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
                    if ponto == "bruto":
                        n = int(valores[0])
                        if anterior_bruto is not None and n != anterior_bruto + 1:
                            resumo.saltos_bruto.append((anterior_bruto, n))
                        anterior_bruto = n
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
    p.add_argument(
        "--qualidade", action="store_true",
        help="mostra ao vivo, 1/s, se o sinal está usável (precisa das linhas b,)",
    )
    args = p.parse_args(argv)

    destino = args.saida or DADOS / f"sensor_{datetime.now().astimezone():%Y%m%d_%H%M%S}.csv"
    with serial.Serial(args.porta, BAUD, timeout=0.5) as porta:
        porta.reset_input_buffer()
        print(f"gravando {args.porta} em {destino} (Ctrl+C pra parar)")
        resumo = grava(AoVivo(porta) if args.qualidade else porta, destino, args.segundos)

    for linha in resumo.texto():
        print(linha)
    for ponto, linhas in resumo.por_ponto.items():
        print(f"{linhas} linhas do {ponto} da placa em {destino_ponto(destino, ponto)}")
    for c in resumo.comentarios:
        print(f"  {c}")


if __name__ == "__main__":
    main()
