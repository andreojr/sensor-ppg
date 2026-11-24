"""Espelho do display OLED no terminal, a partir das linhas "d," da placa.

A placa (com -DSERIAL_TELA=ON) manda uma cópia de cada página que enviou ao SSD1306:

    d,<página>,<256 caracteres hexadecimais minúsculos>

A página vai de 0 a 7 e os 256 caracteres são os 128 bytes dela, coluna 0 a 127. Cada
byte é uma coluna e o bit 0 é a linha de cima da página (a memória do SSD1306, igual
à do oled.py). Aqui as 8 páginas são guardadas e a tela inteira (128 x 64 pixels) é
desenhada no terminal:

- meio-blocos (padrão): cada caractere é 1 coluna e 2 linhas de pixels. Dá 128 x 32
  caracteres. Os caracteres são ▀ (só o de cima), ▄ (só o de baixo) e █ (os dois).
- braille (--braille): cada caractere é 2 colunas e 4 linhas de pixels. Dá 64 x 16
  caracteres, pra terminal pequeno.

O desenho é sempre no mesmo lugar (o cursor volta ao topo por ANSI), sem rolar. Pixel
aceso é colorido e o fundo é preto. As cores imitam o painel bicolor da placa: as
16 primeiras linhas de pixel (as páginas 0 e 1) são amarelas e as 48 de baixo são azuis.
A cor não vem nos dados "d,"; é só como o desenho aparece no terminal.
"""

from __future__ import annotations

import sys
import time
from typing import TextIO

W, H = 128, 64
PAGINAS = H // 8
BYTES_PAGINA = W

INICIO = "\033[?1049h\033[?25l\033[2J"  # tela alternativa, sem cursor, limpa
TOPO = "\033[H"  # cursor no canto de cima à esquerda
FIM = "\033[0m\033[?25h\033[?1049l"  # volta as cores, o cursor e a tela de antes
CORES = "\033[97;40m"  # branco sobre preto: só o quadro "esperando"

# Cores do painel bicolor (ANSI de 256 cores, letra = pixel aceso, fundo preto).
CORTE_AMARELO_PX = 16  # linhas de pixel 0 a 15 são amarelas; da 16 em diante, azuis
COR_AMARELO = "\033[38;5;220;40m"
COR_AZUL = "\033[38;5;39;40m"

HEX = frozenset("0123456789abcdef")
ESPERA = "esperando as linhas d, da placa (firmware com -DSERIAL_TELA=ON)"

# Braille: o bit de cada ponto da célula 2 x 4, indexado por [linha][coluna].
PONTOS_BRAILLE = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


def le_pagina(linha: str) -> tuple[int, bytes] | None:
    """Converte "d,<página>,<256 hex>" em (página, 128 bytes). None se não for válida:
    página fora de 0 a 7, tamanho errado ou caractere que não é hexadecimal minúsculo
    (espaço, tab e maiúscula também são recusados: o contrato é só 0-9 e a-f)."""
    partes = linha.strip().split(",")
    if len(partes) != 3 or partes[0] != "d":
        return None
    if not (partes[1].isascii() and partes[1].isdigit()):
        return None
    pagina = int(partes[1])
    hexa = partes[2]
    if pagina >= PAGINAS or len(hexa) != 2 * BYTES_PAGINA:
        return None
    if not set(hexa) <= HEX:
        return None
    dados = bytes.fromhex(hexa)
    return (pagina, dados) if len(dados) == BYTES_PAGINA else None


def linha_d(pagina: int, dados: bytes) -> str:
    """O contrário de le_pagina: monta a linha "d," (serve pros testes e pra simular a placa)."""
    return f"d,{pagina},{dados.hex()}"


def pixel(memoria: bytes, x: int, y: int) -> int:
    """O pixel (x, y) da memória de 1024 bytes: página y // 8, coluna x, bit y % 8."""
    return (memoria[(y // 8) * W + x] >> (y % 8)) & 1


def desenha_blocos(memoria: bytes) -> list[str]:
    """128 x 32 caracteres: cada um junta 2 linhas de pixels (cima e baixo)."""
    linhas = []
    for y in range(0, H, 2):
        linha = []
        for x in range(W):
            cima, baixo = pixel(memoria, x, y), pixel(memoria, x, y + 1)
            linha.append(" ▀▄█"[cima + 2 * baixo])
        linhas.append("".join(linha))
    return linhas


def desenha_braille(memoria: bytes) -> list[str]:
    """64 x 16 caracteres: cada um junta um bloco de 2 colunas x 4 linhas de pixels."""
    linhas = []
    for y in range(0, H, 4):
        linha = []
        for x in range(0, W, 2):
            mascara = 0
            for dy in range(4):
                for dx in range(2):
                    if pixel(memoria, x + dx, y + dy):
                        mascara |= PONTOS_BRAILLE[dy][dx]
            linha.append(chr(0x2800 + mascara))
        linhas.append("".join(linha))
    return linhas


def cor_da_linha(linha: int, px_por_linha: int) -> str:
    """A cor da linha de caractere `linha`, que começa na linha de pixel linha * px_por_linha."""
    return COR_AMARELO if linha * px_por_linha < CORTE_AMARELO_PX else COR_AZUL


class Espelho:
    """Guarda as 8 páginas e redesenha o terminal quando uma muda.

    A página que ainda não chegou fica apagada. Pra não encher o terminal, o redesenho
    espera `intervalo` segundos desde o último (as páginas que chegarem no meio tempo
    entram no próximo desenho)."""

    def __init__(
        self,
        saida: TextIO | None = None,
        braille: bool = False,
        intervalo: float = 0.1,
        terminal: tuple[int, int] | None = None,
    ) -> None:
        self.saida = saida if saida is not None else sys.stdout
        self.braille = braille
        self.intervalo = intervalo
        # terminal = (colunas, linhas), se quem chama quiser conferir que o desenho cabe
        self.terminal = terminal
        self.paginas: list[bytes | None] = [None] * PAGINAS
        self.recebidas = 0
        self._sujo = False
        self._ultimo: float | None = None
        self._comecou = False

    @property
    def memoria(self) -> bytes:
        """Os 1024 bytes da tela; página que não chegou vale zero (apagada)."""
        zero = bytes(BYTES_PAGINA)
        return b"".join(p if p is not None else zero for p in self.paginas)

    @property
    def tamanho(self) -> tuple[int, int]:
        """Colunas e linhas do terminal que o desenho pede."""
        return (W // 2, H // 4) if self.braille else (W, H // 2)

    @property
    def cabe(self) -> bool:
        return self.terminal is None or (
            self.terminal[0] >= self.tamanho[0] and self.terminal[1] >= self.tamanho[1]
        )

    @property
    def ativo(self) -> bool:
        """Só desenha se a saída for um terminal e o desenho couber nele."""
        return self.saida.isatty() and self.cabe

    def aviso(self) -> str | None:
        """Uma linha (antes de começar e no resumo) se o espelho não vai ser desenhado."""
        if not self.saida.isatty():
            return "a saída não é um terminal: o espelho não foi desenhado, só o CSV foi gravado"
        if self.cabe:
            return None
        c, ln = self.tamanho
        return (
            f"terminal pequeno ({self.terminal[0]}x{self.terminal[1]}): o espelho precisa de "
            f"{c}x{ln} e não foi desenhado, só o CSV foi gravado"
        )

    def inicia(self) -> None:
        """Quadro vazio com o aviso de espera, que some quando chega a primeira página."""
        if self.ativo and not self._comecou:
            self.desenha(espera=True)

    def completa(self) -> bool:
        return all(p is not None for p in self.paginas)

    def linha(self, texto: str) -> bool:
        """Guarda a página de uma linha "d,". False (e ignora) se a linha for inválida."""
        lido = le_pagina(texto)
        if lido is None:
            return False
        self.guarda(*lido)
        return True

    def guarda(self, pagina: int, dados: bytes) -> None:
        if self.paginas[pagina] != dados:
            self._sujo = True
        self.paginas[pagina] = dados
        self.recebidas += 1
        self.desenha_se_precisar()

    def quadro(self) -> list[str]:
        memoria = self.memoria
        return desenha_braille(memoria) if self.braille else desenha_blocos(memoria)

    def tick(self) -> None:
        """Chamado a cada volta do laço: o redesenho segurado pelo intervalo sai aqui,
        mesmo que nenhuma linha nova chegue (senão a tela ficaria incompleta)."""
        self.desenha_se_precisar()

    def desenha_se_precisar(self) -> None:
        if not self._sujo or not self.ativo:
            return
        agora = time.monotonic()
        if self._ultimo is not None and agora - self._ultimo < self.intervalo:
            return
        self.desenha()
        self._ultimo = agora

    def desenha(self, espera: bool = False) -> None:
        if not self._comecou:
            self.saida.write(INICIO)
            self._comecou = True
        quadro = self.quadro()
        if espera:
            meio = len(quadro) // 2
            quadro[meio] = ESPERA[: len(quadro[meio])].center(len(quadro[meio]))
        # cada linha acaba com as cores zeradas, pra não pintar o resto do terminal
        px = 4 if self.braille else 2  # linhas de pixel que cada linha de caractere junta
        corpo = "\n".join(
            f"{CORES if espera else cor_da_linha(i, px)}{linha}\033[0m"
            for i, linha in enumerate(quadro)
        )
        self.saida.write(TOPO + corpo)  # sem \n no fim: não rola nem com o terminal justo
        self.saida.flush()
        self._sujo = False

    def fecha(self) -> None:
        """Desenha o que faltou, volta as cores e o cursor."""
        if self._sujo and self.ativo:
            self.desenha()
        if self._comecou:
            self.saida.write(FIM)
            self.saida.flush()
