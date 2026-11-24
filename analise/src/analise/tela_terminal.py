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
aceso é claro e o fundo é escuro.
"""

from __future__ import annotations

import sys
import time
from typing import TextIO

W, H = 128, 64
PAGINAS = H // 8
BYTES_PAGINA = W

INICIO = "\033[2J\033[?25l"  # limpa a tela e esconde o cursor
TOPO = "\033[H"  # cursor no canto de cima à esquerda
FIM = "\033[0m\033[?25h"  # volta as cores e mostra o cursor
CORES = "\033[97;40m"  # letra branca (pixel aceso) sobre fundo preto

# Braille: o bit de cada ponto da célula 2 x 4, indexado por [linha][coluna].
PONTOS_BRAILLE = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


def le_pagina(linha: str) -> tuple[int, bytes] | None:
    """Converte "d,<página>,<256 hex>" em (página, 128 bytes). None se não for válida:
    página fora de 0 a 7, tamanho errado ou caractere que não é hexadecimal."""
    partes = linha.strip().split(",")
    if len(partes) != 3 or partes[0] != "d":
        return None
    if not (partes[1].isascii() and partes[1].isdigit()):
        return None
    pagina = int(partes[1])
    hexa = partes[2]
    if pagina >= PAGINAS or len(hexa) != 2 * BYTES_PAGINA:
        return None
    try:
        return pagina, bytes.fromhex(hexa)
    except ValueError:
        return None


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
    ) -> None:
        self.saida = saida if saida is not None else sys.stdout
        self.braille = braille
        self.intervalo = intervalo
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

    def desenha_se_precisar(self) -> None:
        if not self._sujo:
            return
        agora = time.monotonic()
        if self._ultimo is not None and agora - self._ultimo < self.intervalo:
            return
        self.desenha()
        self._ultimo = agora

    def desenha(self) -> None:
        if not self._comecou:
            self.saida.write(INICIO)
            self._comecou = True
        # cada linha acaba com as cores zeradas, pra não pintar o resto do terminal
        corpo = "\n".join(f"{CORES}{linha}\033[0m" for linha in self.quadro())
        self.saida.write(TOPO + corpo + "\n")
        self.saida.flush()
        self._sujo = False

    def fecha(self) -> None:
        """Desenha o que faltou, volta as cores e o cursor."""
        if self._sujo:
            self.desenha()
        if self._comecou:
            self.saida.write(FIM)
            self.saida.flush()
