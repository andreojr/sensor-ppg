"""Referência do módulo oled: as telas do display OLED, em Python.

É um porte do oled.js do protótipo do display (o design aprovado): fonte 5x7 em
células de 6x8 (só maiúsculas, algarismos e alguns sinais), as primitivas de
desenho e as telas. O C (Core/Src/pds/oled/) é conferido byte a byte contra isto,
pelos vetores de testes/oled/vetores/.

A memória é a do SSD1306: 8 páginas de 128 colunas, 1 byte por coluna, o bit 0 é a
linha de cima da página. As contas da onda são em float32, na mesma ordem do C, e o
arredondamento é o do JavaScript (meio pra cima), pra não sair um pixel diferente.

Gerar os vetores e a tabela da fonte do C (da pasta analise/):

    uv run python -m analise.oled
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

F32 = np.float32
W, H = 128, 64
PAGINAS = H // 8
ONDA_N = 256  # amostras da onda: 2 por coluna = 2,56 s a 100 Hz
TESTES = Path(__file__).resolve().parents[3] / "testes"
FONTE_H = Path(__file__).resolve().parents[3] / "Core" / "Inc" / "pds" / "oled" / "oled_fonte.h"

# Fonte 5x7: cada letra cabe numa célula 6x8 (1 coluna e 1 linha vazias de espaço).
# Sem acento nem cedilha. '*' é o coração.
FONTE = {
    " ": [".....", ".....", ".....", ".....", ".....", ".....", "....."],
    "0": [".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."],
    "1": ["..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "2": [".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"],
    "3": ["#####", "...#.", "..#..", "...#.", "....#", "#...#", ".###."],
    "4": ["...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."],
    "5": ["#####", "#....", "####.", "....#", "....#", "#...#", ".###."],
    "6": ["..##.", ".#...", "#....", "####.", "#...#", "#...#", ".###."],
    "7": ["#####", "....#", "...#.", "..#..", ".#...", ".#...", ".#..."],
    "8": [".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."],
    "9": [".###.", "#...#", "#...#", ".####", "....#", "...#.", ".##.."],
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "B": ["####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."],
    "C": [".###.", "#...#", "#....", "#....", "#....", "#...#", ".###."],
    "D": ["###..", "#..#.", "#...#", "#...#", "#...#", "#..#.", "###.."],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "F": ["#####", "#....", "#....", "####.", "#....", "#....", "#...."],
    "G": [".###.", "#...#", "#....", "#.###", "#...#", "#...#", ".####"],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": [".###.", "..#..", "..#..", "..#..", "..#..", "..#..", ".###."],
    "J": ["..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."],
    "K": ["#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "M": ["#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"],
    "N": ["#...#", "#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "Q": [".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"],
    "R": ["####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "U": ["#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "V": ["#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."],
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "#.#.#", ".#.#."],
    "X": ["#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"],
    "Y": ["#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."],
    "Z": ["#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"],
    "-": [".....", ".....", ".....", "#####", ".....", ".....", "....."],
    ".": [".....", ".....", ".....", ".....", ".....", ".##..", ".##.."],
    ",": [".....", ".....", ".....", ".....", ".##..", "..#..", ".#..."],
    ":": [".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."],
    "%": ["##...", "##..#", "...#.", "..#..", ".#...", "#..##", "...##"],
    "/": [".....", "....#", "...#.", "..#..", ".#...", "#....", "....."],
    "!": ["..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."],
    "?": [".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."],
    "(": ["...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."],
    ")": [".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."],
    ">": [".#...", "..#..", "...#.", "....#", "...#.", "..#..", ".#..."],
    "=": [".....", ".....", "#####", ".....", "#####", ".....", "....."],
    "*": [".....", ".#.#.", "#####", "#####", ".###.", "..#..", "....."],
}


def meio_pra_cima(x: float) -> int:
    """Math.round do JavaScript: o meio vai pra cima (o round do Python vai pro par)."""
    return math.floor(x + 0.5)


def glifo(c: str) -> list[str]:
    """Letra minúscula vira maiúscula; o que não está na fonte vira '?'."""
    c = c.upper() if c.isascii() and c.isalpha() else c
    return FONTE.get(c, FONTE["?"])


class Fb:
    """Os 128 x 64 pixels de 1 bit, uma linha de pixels por linha do array."""

    def __init__(self, w: int = W, h: int = H) -> None:
        self.w, self.h = w, h
        self.p = np.zeros((h, w), dtype=np.uint8)

    def set(self, x: int, y: int, v: int = 1) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.p[y, x] = 0 if v == 0 else 1

    def rect(self, x: int, y: int, w: int, h: int, cheio: bool, v: int = 1) -> None:
        for j in range(h):
            for i in range(w):
                if cheio or i == 0 or j == 0 or i == w - 1 or j == h - 1:
                    self.set(x + i, y + j, v)

    def line(self, x0: int, y0: int, x1: int, y1: int) -> None:
        dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
        dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
        e = dx + dy
        while True:
            self.set(x0, y0)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * e
            if e2 >= dy:
                e += dy
                x0 += sx
            if e2 <= dx:
                e += dx
                y0 += sy

    def text(self, x: int, y: int, s: str, k: int = 1, v: int = 1) -> int:
        """k = 1 dá células 6x8; k = 2 dá 12x16 (a mesma fonte com cada pixel dobrado)."""
        for c in s:
            g = glifo(c)
            for r in range(7):
                for col in range(5):
                    if g[r][col] == "#":
                        self.rect(x + col * k, y + r * k, k, k, True, v)
            x += 6 * k
        return x

    def text_r(self, x_dir: int, y: int, s: str, k: int = 1, v: int = 1) -> int:
        return self.text(x_dir - len(s) * 6 * k + k, y, s, k, v)

    def text_c(self, y: int, s: str, k: int = 1, v: int = 1) -> int:
        w = len(s) * 6 * k - k
        return self.text((self.w - w) // 2, y, s, k, v)

    def barras(self, x: int, y: int, alt: int, w: int, gap: int, q: int) -> None:
        """5 barras de qualidade: as q acesas são cheias; a vazia é um traço de 1 px na base."""
        for b, h16 in enumerate((4, 7, 10, 13, 16)):
            bh = max(2, meio_pra_cima(h16 * alt / 16))
            bx = x + b * (w + gap)
            if b < q:
                self.rect(bx, y + alt - bh, w, bh, True)
            else:
                self.rect(bx, y + alt - 1, w, 1, True)

    def onda(self, x0: int, y0: int, w: int, h: int, v: np.ndarray) -> None:
        """Onda com escala automática: o mínimo e o máximo dos pontos viram o fundo e o
        topo da faixa (com 8% de folga); pontos vizinhos ligados por reta."""
        v = np.asarray(v, dtype=F32)
        n = min(w, len(v))
        if n == 0:
            return
        mn, mx = F32(v[:n].min()), F32(v[:n].max())
        faixa = F32(mx - mn)
        if faixa == 0:
            faixa = F32(1)
        folga = F32(faixa * F32(0.08))
        mn = F32(mn - folga)
        faixa = F32(faixa + F32(2) * folga)
        py = None
        for i in range(n):
            t = F32(F32(F32(v[i] - mn) * F32(h - 1)) / faixa)
            y = y0 + (h - 1) - math.floor(float(F32(t + F32(0.5))))
            if py is None:
                self.set(x0 + i, y)
            else:
                self.line(x0 + i - 1, py, x0 + i, y)
            py = y

    def paginas(self) -> bytes:
        """A memória do SSD1306: página a página, uma coluna por byte, bit 0 em cima."""
        out = bytearray()
        for pg in range(self.h // 8):
            for col in range(self.w):
                b = 0
                for bit in range(8):
                    b |= int(self.p[pg * 8 + bit, col]) << bit
                out.append(b)
        return bytes(out)


def media2(v: np.ndarray) -> np.ndarray:
    """Uma coluna de pixel a cada 2 amostras: a média das duas."""
    v = np.asarray(v, dtype=F32)
    n = len(v) // 2
    return (v[0 : 2 * n : 2] + v[1 : 2 * n : 2]) * F32(0.5)


def _rng(seed: int):
    s = (seed & 0xFFFFFFFF) or 1

    def prox() -> float:
        nonlocal s
        s = (s * 1664525 + 1013904223) & 0xFFFFFFFF
        return s / 4294967296

    return prox


def ppg(
    n: int = 256,
    bpm: float = 72,
    seed: int = 7,
    ruido: float = 0.03,
    resp: float = 0,
    mexe: tuple[int, int] | None = None,
    fase: float = 0.3,
) -> np.ndarray:
    """O sinal de exemplo do design, a 100 amostras/s: pulso com entalhe dicrótico,
    leve variação do batimento, ruído e, se pedido, um trecho de movimento."""
    fs = 100
    r = _rng(seed)
    out = []
    for i in range(n):
        t = i / fs
        fase += bpm * (1 + 0.04 * math.sin(2 * math.pi * 0.25 * t)) / 60 / fs
        p = fase % 1
        v = math.exp(-(((p - 0.14) / 0.055) ** 2)) + 0.45 * math.exp(-(((p - 0.40) / 0.09) ** 2))
        v += 0.25 * math.sin(2 * math.pi * 0.25 * t) * resp
        v += (r() - 0.5) * ruido
        if mexe and mexe[0] <= i < mexe[1]:
            k = (i - mexe[0]) / (mexe[1] - mexe[0])
            v += 2.6 * math.sin(math.pi * k) * math.sin(i * 0.11) + (r() - 0.5) * 0.9
        out.append(v)
    return np.asarray(out, dtype=F32)


# ---- As telas (uma por artboard do design) -------------------------------------------


def topo(fb: Fb, bpm: str, coracao: bool, q: int) -> None:
    """Faixa de cima (páginas 0 e 1): BPM, coração, rótulo e as 5 barras de qualidade."""
    fb.text_r(36, 0, bpm, 2)
    if coracao:
        fb.text(40, 0, "*")
    fb.text(40, 8, "BPM")
    fb.barras(81, 0, 16, 7, 3, q)


def tela_fonte(onda: np.ndarray) -> Fb:
    fb = Fb()
    fb.text(0, 0, "FONTE 6X8: 21 COLUNAS")
    fb.text(0, 8, "ABCDEFGHIJKLMNOPQRSTU")
    fb.text(1, 16, "0123456789", 2)
    fb.text(0, 32, "PAGINA = 8 LINHAS PX")
    fb.onda(0, 41, 128, 23, media2(onda))
    return fb


def tela_principal(bpm: str, coracao: bool, q: int, onda: np.ndarray) -> Fb:
    fb = Fb()
    topo(fb, bpm, coracao, q)
    fb.onda(0, 17, 128, 47, media2(onda))
    return fb


def tela_resumo(linhas: list[tuple[str, str]], pos: str, spo2: str, resp: str) -> Fb:
    fb = Fb()
    fb.rect(0, 0, 128, 8, True)
    fb.text(1, 0, "RESUMO", 1, 0)
    fb.text_r(127, 0, pos, 1, 0)
    for i, (rotulo, valor) in enumerate(linhas):
        fb.text(0, 8 * (i + 1), rotulo)
        fb.text_r(128, 8 * (i + 1), valor)
    fb.text(0, 56, "SPO2 " + spo2)
    fb.text_r(128, 56, "RESP " + resp)
    return fb


def tela_sem_dedo(q: int) -> Fb:
    fb = Fb()
    topo(fb, "--", False, q)
    fb.text_c(24, "SEM DEDO", 2)
    fb.text_c(48, "APOIE O DEDO E")
    fb.text_c(56, "FIQUE PARADO")
    return fb


def tela_sinal_ruim(q: int, onda: np.ndarray) -> Fb:
    fb = Fb()
    topo(fb, "--", False, q)
    fb.rect(0, 16, 128, 8, True)
    fb.text_c(16, "SINAL RUIM: NAO MEXA", 1, 0)
    fb.onda(0, 25, 128, 39, media2(onda))
    return fb


def tela_inicio(etapas: list[str], aguarde: bool) -> Fb:
    fb = Fb()
    fb.text_c(0, "SENSOR PPG", 2)
    fb.text_c(16, "ENGG54 - UFBA")
    for nome, y, estado in zip(("MAX30102", "DECIMACAO", "FILTRO"), (32, 40, 48), etapas):
        fb.text(0, y, nome)
        fb.text_r(128, y, estado)
    if aguarde:
        fb.text_c(56, "AGUARDE")
    return fb


ERROS = {
    "sensor": (
        "SENSOR NAO RESPONDE",
        "NA I2C1 (END. 0X57)",
        "CONFIRA SCL SDA VIN",
        "E APERTE RESET",
    ),
    "decimacao": (
        "DECIMACAO SEM FILTRO",
        "PARA ESSA TAXA DO",
        "MAX30102. VEJA A",
        "SERIAL E APERTE RESET",
    ),
}


def tela_erro(qual: str) -> Fb:
    a, b, c, d = ERROS[qual]
    fb = Fb()
    fb.rect(0, 0, 128, 16, True)
    fb.text_c(1, "ERRO", 2, 0)
    fb.text_c(24, a)
    fb.text_c(32, b)
    fb.text_c(48, c)
    fb.text_c(56, d)
    return fb


def tela_alvo(spo2: str, resp: str, bpm: str, sinal: str, onda: np.ndarray) -> Fb:
    fb = Fb()
    fb.text_r(36, 0, spo2, 2)
    fb.text(40, 0, "SPO2")
    fb.text(40, 8, "%")
    fb.text_r(100, 0, resp, 2)
    fb.text(102, 0, "RESP")
    fb.text(102, 8, "/MIN")
    fb.text(0, 24, "BPM " + bpm)
    fb.text_r(128, 24, "SINAL " + sinal)
    fb.onda(0, 32, 128, 32, media2(onda))
    return fb


# ---- Os casos dos vetores: os mesmos números do design --------------------------------


def casos() -> dict[str, tuple[Fb, np.ndarray | None, str]]:
    """nome -> (tela, amostras da onda que o C recebe, descrição). Os mesmos valores que as
    artboards do design usam; o teste em C (testes/oled/teste_oled.c) repete esses números."""
    base = ppg(n=256, bpm=72)
    ruim = ppg(n=256, bpm=76, seed=11, mexe=(60, 200))
    alvo = ppg(n=256, bpm=72, resp=1, seed=5)
    linhas = [
        ("BPM PICOS", "72"),
        ("BPM FFT", "71"),
        ("SDNN", "48 MS"),
        ("RMSSD", "35 MS"),
        ("LF/HF", "--"),
        ("QUALIDADE", "82%"),
    ]
    return {
        "fonte": (tela_fonte(base), base, "amostra de fonte, páginas e onda de 23 linhas"),
        "principal": (
            tela_principal("72", True, 4, base),
            base,
            "BPM 72, coração, qualidade 4 de 5",
        ),
        "principal_sem_valor": (
            tela_principal("--", False, 2, base),
            base,
            "BPM sem valor, sem coração",
        ),
        "resumo": (
            tela_resumo(linhas, "2/2", "--", "--"),
            None,
            "resumo, módulos de alvo sem valor",
        ),
        "sem_dedo": (tela_sem_dedo(0), None, "dedo ausente"),
        "sinal_ruim": (tela_sinal_ruim(1, ruim), ruim, "sinal ruim, com movimento na onda"),
        "inicio": (
            tela_inicio(["OK", "OK", "..."], True),
            None,
            "inicialização, filtro ainda não pronto",
        ),
        "erro_sensor": (tela_erro("sensor"), None, "erro: sensor não responde"),
        "erro_decimacao": (tela_erro("decimacao"), None, "erro: decimação sem filtro"),
        "alvo": (tela_alvo("97", "16", "72", "82%", alvo), alvo, "SpO2 97%, respiração 16/min"),
    }


def gera_fonte_c() -> str:
    """Texto do oled_fonte.h: a tabela da fonte, 7 linhas de 5 bits por letra (bit 4 = esquerda)."""
    chaves = list(FONTE)
    linhas = [
        "/* Gerado por analise/src/analise/oled.py (uv run python -m analise.oled). Não edite à mão.",
        " * Fonte 5x7 do design do display: cada linha da letra tem 5 bits, o bit 4 é a coluna da",
        " * esquerda. Só maiúsculas, algarismos e alguns sinais; '*' é o coração. */",
        "#ifndef PDS_OLED_OLED_FONTE_H",
        "#define PDS_OLED_OLED_FONTE_H",
        "",
        "#include <stdint.h>",
        "",
        f"#define OLED_FONTE_N {len(chaves)}u",
        "",
        'static const char OLED_FONTE_CHAVES[OLED_FONTE_N + 1u] = "'
        + "".join(chaves).replace("\\", "\\\\").replace('"', '\\"')
        + '";',
        "",
        "static const uint8_t OLED_FONTE[OLED_FONTE_N][7] = {",
    ]
    for c in chaves:
        linhas_bits = [int("".join("1" if x == "#" else "0" for x in r), 2) for r in FONTE[c]]
        linhas.append("    {" + ", ".join(f"0x{b:02X}" for b in linhas_bits) + f"}}, /* '{c}' */")
    linhas += ["};", "", "#endif /* PDS_OLED_OLED_FONTE_H */", ""]
    return "\n".join(linhas)


def gera_vetores(testes: Path | None = None) -> list[Path]:
    """Grava testes/oled/vetores/<caso>.h: as amostras da onda e a memória esperada (1024 bytes)."""
    from analise import vetores

    saidas = []
    for nome, (fb, onda, descricao) in casos().items():
        arrays: dict[str, object] = {"fb": list(fb.paginas())}
        if onda is not None:
            arrays["onda"] = onda
        extra = {"testes": testes} if testes else {}
        saidas.append(
            vetores.gera_vetor("oled", nome, arrays, tol=0.0, descricao=descricao, **extra)
        )
    return saidas


if __name__ == "__main__":
    FONTE_H.write_text(gera_fonte_c(), encoding="utf-8", newline="\n")
    print(FONTE_H)
    for caminho in gera_vetores():
        print(caminho)
