"""Espelho do display OLED numa janela gráfica (tkinter), a partir das linhas "d," da placa.

É o mesmo Espelho do terminal (tela_terminal.py): guarda as 8 páginas e decide quando
redesenhar. Só a saída muda: em vez de caracteres, a janela pinta os 128 x 64 pixels como
quadrados de `escala` x `escala` pixels de tela, em amarelo nas 16 primeiras linhas de pixel
e azul nas outras 48, sobre fundo preto, como o painel bicolor da placa.

O tamanho vem de uma escala inteira escolhida pela resolução do monitor (--monitor): a
janela ocupa uns 40% da largura da tela. Pra uma resolução nova, é só uma linha em RESOLUCOES.

A janela não usa mainloop (ele travaria a leitura da serial): o laço da captura chama tick()
a cada volta, e o tick() chama update() do tkinter.
"""

from __future__ import annotations

import contextlib
from typing import Any

from analise.tela_terminal import (
    CODIGO_AMARELO,
    CODIGO_AZUL,
    CORTE_AMARELO_PX,
    Espelho,
    H,
    W,
    pixel,
)

try:
    import tkinter
except ImportError:  # sem tkinter: abre_tk avisa com ErroJanela
    tkinter = None

# o erro que o tkinter dá com a janela já destruída
ERRO_TK: type[Exception] = tkinter.TclError if tkinter else RuntimeError

RESOLUCOES = {"hd": (1366, 768), "fhd": (1920, 1080), "2k": (2560, 1440), "4k": (3840, 2160)}
MONITOR_PADRAO = "fhd"
FRACAO_LARGURA = 0.4  # a janela ocupa uns 40% da largura da tela
PRETO = "#000000"


class ErroJanela(Exception):
    """Não deu pra abrir a janela (sem tkinter ou sem ambiente gráfico)."""


def escala(monitor: str) -> int:
    """Quantos pixels de tela vale cada pixel do OLED: 40% da largura, inteiro pra baixo."""
    largura, _ = RESOLUCOES[monitor]
    return max(1, int(largura * FRACAO_LARGURA) // W)


def hex_de_256(codigo: int) -> str:
    """O código de 256 cores do ANSI (cubo 6x6x6, de 16 a 231) em "#rrggbb"."""
    n = codigo - 16
    niveis = (0, 95, 135, 175, 215, 255)
    r, g, b = niveis[n // 36], niveis[(n // 6) % 6], niveis[n % 6]
    return f"#{r:02x}{g:02x}{b:02x}"


COR_AMARELO_HEX = hex_de_256(CODIGO_AMARELO)  # #ffd700
COR_AZUL_HEX = hex_de_256(CODIGO_AZUL)  # #00afff


def cor_da_linha_px(y: int) -> str:
    """A cor do pixel aceso na linha de pixel y."""
    return COR_AMARELO_HEX if y < CORTE_AMARELO_PX else COR_AZUL_HEX


def cores_dos_pixels(memoria: bytes) -> list[list[str]]:
    """Uma matriz de H linhas por W colunas com a cor de cada pixel (preto se apagado)."""
    return [
        [cor_da_linha_px(y) if pixel(memoria, x, y) else PRETO for x in range(W)]
        for y in range(H)
    ]


class Desenho:
    """Pinta a matriz de cores num Canvas (ou num falso, nos testes): um quadrado por
    pixel, criado uma vez; depois só muda a cor dos que mudaram."""

    def __init__(self, canvas: Any, escala_px: int) -> None:
        self.canvas = canvas
        self.escala = escala_px
        self.atual = [[PRETO] * W for _ in range(H)]
        self.itens = [
            [
                canvas.create_rectangle(
                    x * escala_px, y * escala_px, (x + 1) * escala_px, (y + 1) * escala_px,
                    fill=PRETO, outline="",
                )
                for x in range(W)
            ]
            for y in range(H)
        ]

    def pinta(self, memoria: bytes) -> None:
        novo = cores_dos_pixels(memoria)
        for y in range(H):
            for x in range(W):
                if novo[y][x] != self.atual[y][x]:
                    self.canvas.itemconfigure(self.itens[y][x], fill=novo[y][x])
        self.atual = novo


def abre_tk(escala_px: int) -> tuple[Any, Any]:
    """Abre a janela tkinter e devolve (raiz, canvas). ErroJanela se não der."""
    if tkinter is None:
        raise ErroJanela("o tkinter não está instalado (no Linux: pacote python3-tk)")
    try:
        raiz = tkinter.Tk()
    except tkinter.TclError as e:
        raise ErroJanela(f"sem ambiente gráfico pra abrir a janela ({e})") from e
    raiz.title("OLED (espelho)")
    raiz.resizable(False, False)
    canvas = tkinter.Canvas(
        raiz, width=W * escala_px, height=H * escala_px, bg=PRETO, highlightthickness=0
    )
    canvas.pack()
    return raiz, canvas


class Janela(Espelho):
    """O Espelho com a saída numa janela. Fechar a janela liga `encerrado`."""

    def __init__(self, monitor: str = MONITOR_PADRAO, intervalo: float = 0.1) -> None:
        super().__init__(intervalo=intervalo)
        self.raiz, canvas = abre_tk(escala(monitor))
        self.desenho = Desenho(canvas, escala(monitor))
        self.raiz.protocol("WM_DELETE_WINDOW", self._fechou)
        self._atualiza()

    @property
    def ativo(self) -> bool:
        return not self.encerrado

    def aviso(self) -> str | None:
        return None

    def inicia(self) -> None:
        self._atualiza()

    def _fechou(self) -> None:
        self.encerrado = True

    def _atualiza(self) -> None:
        if self.encerrado:
            return
        try:
            self.raiz.update()
        except ERRO_TK:  # janela destruída por fora
            self.encerrado = True

    def tick(self) -> None:
        super().tick()
        self._atualiza()

    def desenha(self, espera: bool = False) -> None:
        self.desenho.pinta(self.memoria)
        self._sujo = False
        self._comecou = True

    def fecha(self) -> None:
        if self._sujo and self.ativo:
            self.desenha()
            self._atualiza()
        with contextlib.suppress(ERRO_TK):
            self.raiz.destroy()
        self.encerrado = True
