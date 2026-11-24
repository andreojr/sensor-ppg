"""Confere o que o OLED mostrou contra o que a placa calculou, numa sessão gravada.

Entrada: o arquivo do grava_log.py (uma linha da serial por linha, com o horário em que o PC
recebeu a linha). A placa mandou, na mesma sessão, as linhas de resultado (b, p, e, h, s, r, t,
l) e as páginas do display (d,, com -DSERIAL_TELA=ON). Aqui:

A) integridade: linhas estragadas (inclusive as que não têm o número certo de campos), saltos
   no contador das b,, amostras perdidas (# laco) e linhas d, descartadas pelo buffer (# tela);
B) remonta os quadros de 128 x 64 pixels a partir das d,, descobre qual tela era (principal,
   resumo, alvo, sem dedo, sinal ruim), mede quanto tempo cada trecho durou e confere o
   rodízio (as durações de 8, 4 e 4 s e a ordem principal, resumo, alvo);
C) desenha de novo, pelo oled.py, o texto de cada campo a partir das linhas de resultado e
   compara, pixel a pixel, com o que estava na tela. Os campos (CAMPOS_ESPERADOS): BPM grande,
   BPM PICOS, BPM FFT, SDNN, RMSSD, LF/HF, SPO2~ e RESP do resumo, SPO2 e RESP grandes do alvo.
   NÃO são conferidos: QUALIDADE, barras de qualidade, coração, "2/3", BPM e SINAL do alvo, onda.

Os quadros são amostrados a cada 0,25 s. Um campo "bate" se algum dos valores que a placa
mandou por perto no tempo desenha exatamente os pixels que estavam na tela. "Por perto" é uma
janela curta (JANELA): as últimas linhas do tipo, não mais velhas que `atras` segundos, e até
FRENTE_S depois do quadro (o horário do log é o de recebimento no PC, com o atraso do USB, então
a linha pode ter sido calculada antes do quadro e chegado depois). Valor x,50 (a linha traz 2 casas)
pode ter arredondado pra qualquer lado, e então os dois lados valem.

Os PNGs (--png) saem coloridos como o painel bicolor: amarelo nas 16 primeiras linhas de
pixel e azul nas outras 48 (as cores e o corte vêm do tela_terminal.py). Cada PNG é um quadro
escolhido sempre do mesmo jeito: o primeiro, depois de 120 s, em que todos os campos da tela
batem, têm um único valor possível e valem número (não "--"); sem ele, o primeiro depois de 120 s,
e sem esse, o primeiro da tela. (No resumo o LF/HF não conta: ele fica "--" quase sempre.)

Uso:
    uv run python -m analise.oled_confere dados/sessao.log
    uv run python -m analise.oled_confere dados/sessao.log --png dados/oled_telas
    uv run python -m analise.oled_confere dados/sessao.log --desencontros

Sai com código 1 se: algum campo bater menos que --minimo; faltar algum campo de
CAMPOS_ESPERADOS; o rodízio não bater; houver linha estragada, salto nas b, ou amostra perdida;
ou as d, descartadas passarem de --max-descartadas (fração das d, válidas).
"""

from __future__ import annotations

import argparse
import collections
import math
import re
import sys
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import numpy as np
from matplotlib.image import imsave

from analise import captura
from analise.oled import Fb
from analise.tela_janela import COR_AMARELO_HEX, COR_AZUL_HEX
from analise.tela_terminal import CORTE_AMARELO_PX, H, W, le_pagina

PASSO_S = 0.25  # de quanto em quanto tempo a tela é amostrada
ESCALA_PNG = 6  # cada pixel do OLED vira 6 x 6 no PNG (768 x 384)
MINIMO_PADRAO = 0.95
MAX_DESCARTADAS_PADRAO = 0.005  # fração das d, válidas que o buffer pode descartar
PRIMEIRA_TELA_S = 120.0  # os PNGs saem de depois da partida, quando a tela já é a de regime
RESULTADOS = "hperstl"  # linhas de resultado que o display mostra
TELAS_COM_TOPO = ("principal", "sinal_ruim", "sem_dedo")  # têm o BPM grande na faixa de cima
TELAS_PNG = ("principal", "resumo", "alvo", "sem_dedo", "sinal_ruim")
# o rodízio previsto no display.c: duração de cada tela em segundos
RODIZIO_S = {"principal": 8.0, "resumo": 4.0, "alvo": 4.0}
TOLERANCIA_RODIZIO_S = 0.5
# o que pode vir logo depois de cada tela (o alvo só entra se SpO2 ou respiração têm valor)
PROXIMAS = {"principal": {"resumo"}, "resumo": {"alvo", "principal"}, "alvo": {"principal"}}
EMPATE = 0.00501  # as linhas trazem 2 casas: x,50 pode ter arredondado pra qualquer lado

# Quantos campos numéricos (depois do prefixo) cada tipo de linha tem. Vem da captura.py.
NCAMPOS = {
    "b": len(captura.COLUNAS),
    "f": len(captura.COLUNAS),
    "p": len(captura.COLUNAS_PICOS),
    "e": len(captura.COLUNAS_ESPECTRAL),
    "h": len(captura.COLUNAS_HRV),
    "s": len(captura.COLUNAS_SPO2),
    "r": len(captura.PONTOS["r"][1]),
    "t": len(captura.COLUNAS_TELA),
    "l": len(captura.COLUNAS_LFHF),
    "q": len(captura.COLUNAS_QUALIDADE),
}

# De quanto tempo pra trás e quantas linhas (as últimas) cada campo considera. As s, r, t, e
# saem 1 vez por segundo; p, h saem a cada batimento; l a cada 5 s; o resumo mostra o último
# valor de qualquer idade, então só limita pela quantidade.
FRENTE_S = 0.5
JANELA = {
    "t": (1.1, None),
    "pt": (1.1, None),  # os p, que o BPM grande também usa
    "p": (3600.0, 3),
    "e": (3600.0, 2),
    "h": (3600.0, 4),
    "l": (3600.0, 2),
    "s": (1.1, None),
    "r": (1.1, None),
}


# ---------- A) integridade ----------


@dataclass
class Integridade:
    linhas: int = 0
    b_linhas: int = 0
    b_saltos: int = 0  # vezes que o contador das b, não andou de 1 em 1
    estragadas: int = 0  # linhas que não são d, e não fazem sentido (inclui as do log sem tempo)
    d_validas: int = 0
    d_estragadas: int = 0
    laco_avisos: int = 0  # linhas "# laco" (uma por segundo)
    laco_perdidas: int = 0  # amostras que a placa disse ter perdido
    d_descartadas: int = 0  # linhas d, que o buffer da serial descartou (# tela)


def le_log(caminho: Path) -> tuple[list[tuple[float, str]], int]:
    """Lê o arquivo do grava_log.py. Devolve (lista de (segundos, linha da serial), quantas
    linhas do arquivo estavam estragadas: vazias, sem tab ou com tempo que não é número)."""
    eventos = []
    ruins = 0
    with caminho.open() as f:
        for linha in f:
            tempo, _, resto = linha.rstrip("\n").partition("\t")
            try:
                t = float(tempo)
            except ValueError:
                t = math.nan
            if not math.isfinite(t) or not resto:
                ruins += 1
                continue
            eventos.append((t, resto))
    return eventos, ruins


def _numeros(linha: str) -> list[float] | None:
    """Os números depois do prefixo ("p,3,0.5,..." -> [3, 0.5, ...]). None se algum não for
    número ou se faltarem (ou sobrarem) campos pro tipo da linha."""
    partes = linha.split(",")
    try:
        nums = [float(x) for x in partes[1:]]
    except ValueError:
        return None
    return nums if len(nums) == NCAMPOS.get(partes[0]) else None


def mede_integridade(eventos: list[tuple[float, str]], log_ruins: int = 0) -> Integridade:
    r = Integridade(linhas=len(eventos), estragadas=log_ruins)
    contador_b: list[int] = []
    for _, s in eventos:
        if s.startswith("# laco:"):
            m = re.search(r"perdidas (\d+)", s)
            if m:
                r.laco_perdidas += int(m.group(1))
                r.laco_avisos += 1
            else:
                r.estragadas += 1
        elif s.startswith("# tela:"):
            try:
                r.d_descartadas += int(s.split()[-1])
            except ValueError:
                r.estragadas += 1
        elif s.startswith("d,"):
            if le_pagina(s) is None:
                r.d_estragadas += 1
            else:
                r.d_validas += 1
        elif s.startswith("b,"):
            nums = _numeros(s)
            if nums is None:
                r.estragadas += 1
            else:
                contador_b.append(int(nums[0]))
        elif s[:2] in tuple(c + "," for c in "fq" + RESULTADOS):
            if _numeros(s) is None:
                r.estragadas += 1
        elif not s.startswith("#"):
            r.estragadas += 1
    r.b_linhas = len(contador_b)
    r.b_saltos = int((np.diff(np.array(contador_b)) != 1).sum()) if contador_b else 0
    return r


# ---------- B) quadros e telas ----------


def pixels(memoria: bytes) -> np.ndarray:
    """Os 1024 bytes da memória do SSD1306 em 64 linhas x 128 colunas de 0 ou 1."""
    m = np.frombuffer(memoria, np.uint8).reshape(H // 8, W)
    return (((m[:, None, :] >> np.arange(8)[None, :, None]) & 1).reshape(H, W)).astype(np.uint8)


def remonta_quadros(eventos: list[tuple[float, str]]) -> list[tuple[float, bytes]]:
    """Cada vez que chega uma página e as 8 já são conhecidas, sai um quadro (tempo, memória)."""
    paginas: list[bytes | None] = [None] * (H // 8)
    quadros = []
    for t, s in eventos:
        if s.startswith("d,"):
            r = le_pagina(s)
            if r is None:
                continue
            paginas[r[0]] = r[1]
            if all(p is not None for p in paginas):
                quadros.append((t, b"".join(p for p in paginas if p is not None)))
    return quadros


def _desenha(fn) -> np.ndarray:
    fb = Fb()
    fn(fb)
    return fb.p


# trechos de texto que só existem em uma tela (desenhados pelo oled.py)
_ALVO = _desenha(lambda f: f.text(40, 0, "SPO2~"))
_BPM = _desenha(lambda f: f.text(40, 8, "BPM"))
_SEM_DEDO = _desenha(lambda f: f.text_c(24, "SEM DEDO", 2))


def _contem(p: np.ndarray, modelo: np.ndarray) -> bool:
    """Todo pixel aceso do modelo está aceso em p."""
    return not bool(((modelo == 1) & (p == 0)).any())


def classifica(p: np.ndarray) -> str:
    """Qual tela é: resumo, alvo, sem_dedo, sinal_ruim, principal ou outra."""
    if p[7, :].all() and p[0, :].sum() > 60:  # a faixa invertida de cima
        return "resumo"
    if _contem(p, _ALVO):
        return "alvo"
    if _contem(p, _SEM_DEDO):
        return "sem_dedo"
    if p[23, :].sum() > 120 and p[16, :].sum() > 60:  # a faixa invertida de "sinal ruim"
        return "sinal_ruim"
    if _contem(p, _BPM):
        return "principal"
    return "outra"


def amostra_quadros(quadros: list[tuple[float, bytes]]) -> list[tuple[float, np.ndarray]]:
    """O quadro que valia a cada PASSO_S segundos, do primeiro ao último quadro."""
    saida = []
    i = 0
    t = quadros[0][0]
    while t <= quadros[-1][0]:
        while i + 1 < len(quadros) and quadros[i + 1][0] <= t:
            i += 1
        saida.append((t, pixels(quadros[i][1])))
        t += PASSO_S
    return saida


def trechos(tipos: list[tuple[float, str]]) -> list[list]:
    """Agrupa amostras seguidas da mesma tela: [tela, tempo inicial, tempo final]."""
    seg: list[list] = []
    for t, k in tipos:
        if seg and seg[-1][0] == k:
            seg[-1][2] = t
        else:
            seg.append([k, t, t])
    return seg


def duracoes(seg: list[list]) -> dict[str, list[float]]:
    """Duração de cada trecho que não é o primeiro nem o último (esses podem estar cortados)."""
    d: dict[str, list[float]] = collections.defaultdict(list)
    for k, a, b in seg[1:-1]:
        d[k].append(b - a + PASSO_S)
    return d


def duracao_confere(dur: dict[str, list[float]]) -> bool:
    """A mediana de cada tela do rodízio (principal, resumo, alvo) está a menos de
    TOLERANCIA_RODIZIO_S do previsto (8, 4 e 4 s)? Tela que não apareceu não conta, mas ao
    menos uma precisa ter aparecido."""
    achou = False
    for tela, esperado in RODIZIO_S.items():
        if dur.get(tela):
            achou = True
            if abs(float(np.median(dur[tela])) - esperado) > TOLERANCIA_RODIZIO_S:
                return False
    return achou


def ordem_confere(seg: list[list]) -> bool:
    """Duas telas do rodízio coladas seguem a ordem principal, resumo, alvo, principal (o
    resumo pode ir direto pra principal, se o alvo estava sem valor). Telas que não são do
    rodízio (SINAL RUIM, SEM DEDO) interrompem a conta: a ordem só vale pros vizinhos diretos."""
    for (a, *_), (b, *_) in pairwise(seg):
        if a in PROXIMAS and b in PROXIMAS and b not in PROXIMAS[a]:
            return False
    return True


def nominais(dur: dict[str, list[float]]) -> dict[str, tuple[int, int]]:
    """Por tela do rodízio: (trechos completos, os que estão a TOLERANCIA_RODIZIO_S do previsto)."""
    return {
        k: (len(v), sum(abs(x - RODIZIO_S[k]) <= TOLERANCIA_RODIZIO_S for x in v))
        for k, v in dur.items()
        if k in RODIZIO_S
    }


# ---------- C) números na tela x resultados da placa ----------


class Historico:
    """As linhas de resultado por tipo, em ordem de tempo, com busca por janela."""

    def __init__(self, eventos: list[tuple[float, str]]) -> None:
        self.tempos: dict[str, list[float]] = collections.defaultdict(list)
        self.dados: dict[str, list[list[float]]] = collections.defaultdict(list)
        for t, s in eventos:
            if s[:2] in tuple(c + "," for c in RESULTADOS):
                nums = _numeros(s)
                if nums is not None:
                    self.tempos[s[0]].append(t)
                    self.dados[s[0]].append(nums)

    def ultimas(self, tipo: str, t: float) -> list[list[float]]:
        """As linhas do tipo (e da janela JANELA[tipo]) com horário em [t - atras, t + FRENTE_S],
        só as `n` últimas."""
        atras, n = JANELA[tipo]
        base = tipo[0]
        ts = self.tempos[base]
        achadas = self.dados[base][bisect_left(ts, t - atras) : bisect_right(ts, t + FRENTE_S)]
        return achadas if n is None else achadas[-n:]


def textos_numero(x: float, maximo: int) -> set[str]:
    """Os textos que o display pode ter desenhado pro valor x (a linha tem só 2 casas):
    negativo ou NaN é "--"; acima do máximo vira o máximo; o resto arredonda com o meio pra
    cima. Se x é um empate (x,50 na linha), o valor real pode ter ficado de qualquer lado do
    meio, e os dois textos valem."""
    if not (x >= 0):
        return {"--"}
    if x >= maximo:
        return {str(maximo)}
    piso = math.floor(x)
    if abs(x - piso - 0.5) <= EMPATE:
        return {str(piso), str(min(piso + 1, maximo))}
    return {str(math.floor(x + 0.5))}


def texto_lf_hf(x: float) -> set[str]:
    """O LF/HF no display: x * 10 arredondado e escrito "x.y" (6.044 vira "6.0")."""
    return {
        "--" if v == "--" else f"{int(v) // 10}.{int(v) % 10}" for v in textos_numero(x * 10, 999)
    }


def candidatos_principal(h: Historico, t: float) -> set[str]:
    """Textos possíveis do BPM grande. Da linha t, (um por segundo): "--" se mostra = 0, senão o
    BPM. Com mostra = 1 também vale o BPM do último batimento (p,), que muda entre um t, e
    outro, ou "--" se esse batimento não tem BPM válido."""
    c: set[str] = set()
    mostrou = False
    for d in h.ultimas("t", t):  # t,n,mostra,bpm x 100
        if d[1] == 1:
            mostrou = True
            c |= textos_numero(d[2] / 100, 999)
        else:
            c.add("--")
    if mostrou:
        for dp in h.ultimas("pt", t):  # p,n_pico,fracao,rr_valido,rr_ms,bpm_valido,bpm
            c |= textos_numero(dp[5], 999) if dp[4] == 1 else {"--"}
    return c


@dataclass
class Campo:
    ok: int = 0
    total: int = 0
    exemplos: list[tuple[float, str]] = field(default_factory=list)  # (tempo, candidatos)

    @property
    def fracao(self) -> float:
        return self.ok / self.total if self.total else 1.0


# os campos que a conferência exige (log sem algum deles não passa)
CAMPOS_ESPERADOS = (
    "principal: BPM grande (t,)",
    "resumo: BPM PICOS (p,)",
    "resumo: BPM FFT (e,)",
    "resumo: SDNN (h,)",
    "resumo: RMSSD (h,)",
    "resumo: LF/HF (l,)",
    "resumo: SPO2~ (s,)",
    "resumo: RESP (r,)",
    "alvo: SPO2 grande (s,)",
    "alvo: RESP grande (r,)",
)


def _igual(p: np.ndarray, desenho, caixa: tuple[int, int, int, int]) -> bool:
    fb = Fb()
    desenho(fb)
    x0, y0, x1, y1 = caixa
    return bool((p[y0:y1, x0:x1] == fb.p[y0:y1, x0:x1]).all())


def _bate(p: np.ndarray, candidatos, desenho, caixa) -> bool:
    return any(_igual(p, lambda fb, c=c: desenho(fb, c), caixa) for c in candidatos)


def _soma(linhas: list[list[float]], i: int, maximo: int, j: int = 1) -> set[str]:
    """Textos possíveis do campo i de várias linhas, cada uma com o flag "valido" na posição j
    (o valor só vale se o flag é 1; senão é "--")."""
    c: set[str] = set()
    for d in linhas:
        c |= textos_numero(d[i], maximo) if d[j] == 1 else {"--"}
    return c


def _ms(valor: set[str]) -> set[str]:
    return {v if v == "--" else v + " MS" for v in valor}


def confere_numeros(
    amostras: list[tuple[float, np.ndarray]],
    tipos: list[tuple[float, str]],
    h: Historico,
) -> tuple[dict[str, Campo], list[bool]]:
    """Compara cada campo numérico da tela com os candidatos vindos das linhas de resultado.
    Devolve os campos e, por amostra, se ela serve de exemplo (todos os campos obrigatórios da
    tela batem, com um único valor possível e que é número)."""
    campos: dict[str, Campo] = collections.defaultdict(Campo)
    bons: list[bool] = []

    for (t, p), (_, tela) in zip(amostras, tipos, strict=True):
        resultados: list[tuple[bool, bool]] = []  # (bateu, único e número), por campo

        def registra(nome, ok, cands, obrigatorio=True, t=t, resultados=resultados):
            c = campos[nome]
            c.total += 1
            if ok:
                c.ok += 1
            elif len(c.exemplos) < 4:
                c.exemplos.append((round(t, 1), str(sorted(cands))))
            if obrigatorio:
                resultados.append((ok, len(cands) == 1 and "--" not in cands))

        if tela in TELAS_COM_TOPO:  # a faixa de cima (BPM grande) é a mesma nas três
            c = candidatos_principal(h, t)
            ok = bool(c) and _bate(p, c, lambda fb, s: fb.text_r(36, 0, s, 2), (0, 0, 37, 16))
            registra("principal: BPM grande (t,)", ok, c)
        elif tela == "resumo":
            P, E, Hr = h.ultimas("p", t), h.ultimas("e", t), h.ultimas("h", t)
            L, S, R = h.ultimas("l", t), h.ultimas("s", t), h.ultimas("r", t)
            if P:
                c = _soma(P, 5, 999, 4)
                ok = _bate(p, c, lambda fb, s: fb.text_r(128, 8, s), (64, 8, 128, 16))
                registra("resumo: BPM PICOS (p,)", ok, c)
            if E:
                c = _soma(E, 2, 999)
                ok = _bate(p, c, lambda fb, s: fb.text_r(128, 16, s), (64, 16, 128, 24))
                registra("resumo: BPM FFT (e,)", ok, c)
            if Hr:
                for nome, i, y in (("SDNN", 2, 24), ("RMSSD", 3, 32)):
                    c = _ms(_soma(Hr, i, 999))
                    ok = _bate(p, c, lambda fb, s, y=y: fb.text_r(128, y, s), (64, y, 128, y + 8))
                    registra(f"resumo: {nome} (h,)", ok, c)
            if L:
                c = set()
                for d in L:
                    c |= texto_lf_hf(d[2]) if d[1] == 1 else {"--"}
                ok = _bate(p, c, lambda fb, s: fb.text_r(128, 40, s), (64, 40, 128, 48))
                registra("resumo: LF/HF (l,)", ok, c, obrigatorio=False)
            if S:
                c = _soma(S, 2, 100)
                ok = _bate(p, c, lambda fb, s: fb.text(0, 56, "SPO2~ " + s), (0, 56, 64, 64))
                registra("resumo: SPO2~ (s,)", ok, c)
            if R:
                c = _soma(R, 1, 99, 2)
                ok = _bate(p, c, lambda fb, s: fb.text_r(128, 56, "RESP " + s), (64, 56, 128, 64))
                registra("resumo: RESP (r,)", ok, c)
        elif tela == "alvo":
            S, R = h.ultimas("s", t), h.ultimas("r", t)
            if S:
                c = _soma(S, 2, 100)
                ok = _bate(p, c, lambda fb, s: fb.text_r(36, 0, s, 2), (0, 0, 38, 16))
                registra("alvo: SPO2 grande (s,)", ok, c)
            if R:
                c = _soma(R, 1, 99, 2)
                ok = _bate(p, c, lambda fb, s: fb.text_r(100, 0, s, 2), (72, 0, 101, 16))
                registra("alvo: RESP grande (r,)", ok, c)
        bons.append(bool(resultados) and all(a and b for a, b in resultados))
    return dict(sorted(campos.items())), bons


# ---------- PNGs ----------


def _rgb(cor_hex: str) -> tuple[int, int, int]:
    return int(cor_hex[1:3], 16), int(cor_hex[3:5], 16), int(cor_hex[5:7], 16)


def imagem_colorida(p: np.ndarray, escala: int = ESCALA_PNG) -> np.ndarray:
    """A tela (64 x 128 de 0/1) em RGB como o painel: amarelo nas CORTE_AMARELO_PX linhas de
    cima, azul nas de baixo, fundo preto, cada pixel do OLED virando escala x escala."""
    img = np.zeros((H, W, 3), np.uint8)
    cima = p[:CORTE_AMARELO_PX] == 1
    baixo = p[CORTE_AMARELO_PX:] == 1
    img[:CORTE_AMARELO_PX][cima] = _rgb(COR_AMARELO_HEX)
    img[CORTE_AMARELO_PX:][baixo] = _rgb(COR_AZUL_HEX)
    return np.kron(img, np.ones((escala, escala, 1), np.uint8))


def escolhe_quadro(
    amostras: list[tuple[float, np.ndarray]],
    tipos: list[tuple[float, str]],
    bons: list[bool],
    tela: str,
    a_partir_de: float = PRIMEIRA_TELA_S,
) -> tuple[float, np.ndarray] | None:
    """O quadro da tela que vira PNG: o primeiro bom depois de `a_partir_de` s; se não há,
    o primeiro depois de `a_partir_de`; se não há, o primeiro da tela. None se a tela não
    apareceu."""
    todos = [(a, b) for a, (_, k), b in zip(amostras, tipos, bons, strict=True) if k == tela]
    for filtro in (
        lambda a, b: b and a[0] >= a_partir_de,
        lambda a, b: a[0] >= a_partir_de,
        lambda a, b: True,
    ):
        for a, b in todos:
            if filtro(a, b):
                return a
    return None


def salva_pngs(
    amostras: list[tuple[float, np.ndarray]],
    tipos: list[tuple[float, str]],
    bons: list[bool],
    pasta: Path,
    a_partir_de: float = PRIMEIRA_TELA_S,
) -> list[str]:
    """Salva oled_<tela>.png na pasta (ver escolhe_quadro). Devolve as telas salvas."""
    pasta.mkdir(parents=True, exist_ok=True)
    salvas = []
    for k in TELAS_PNG:
        q = escolhe_quadro(amostras, tipos, bons, k, a_partir_de)
        if q is not None:
            imsave(pasta / f"oled_{k}.png", imagem_colorida(q[1]))
            salvas.append(k)
    return salvas


# ---------- tudo junto ----------


@dataclass
class Relatorio:
    integridade: Integridade
    quadros: int
    inicio_s: float
    fim_s: float
    segundos_por_tela: dict[str, int]
    duracao_por_tela: dict[str, tuple[float, float, float, int]]  # mediana, mín, máx, n
    nominais: dict[str, tuple[int, int]]  # completos, a 0,5 s do previsto
    sequencia: list[str]
    duracao_ok: bool
    ordem_ok: bool
    campos: dict[str, Campo]
    pngs: list[str]

    @property
    def rodizio_ok(self) -> bool:
        return self.duracao_ok and self.ordem_ok

    def falhas(
        self, minimo: float = MINIMO_PADRAO, max_descartadas: float = MAX_DESCARTADAS_PADRAO
    ) -> list[str]:
        """Tudo que reprova a sessão, em texto. Lista vazia = passou."""
        f = []
        i = self.integridade
        for nome in CAMPOS_ESPERADOS:
            if nome not in self.campos:
                f.append(f"campo sem conferência: {nome}")
        for nome, c in self.campos.items():
            if c.fracao < minimo:
                f.append(f"{nome}: {100 * c.fracao:.1f}% (mínimo {100 * minimo:.0f}%)")
        if not self.duracao_ok:
            f.append("rodízio: a duração das telas não é 8 / 4 / 4 s")
        if not self.ordem_ok:
            f.append("rodízio: a ordem das telas não é principal, resumo, alvo")
        if i.estragadas:
            f.append(f"{i.estragadas} linhas estragadas")
        if i.d_estragadas:
            f.append(f"{i.d_estragadas} linhas d, estragadas")
        if i.b_saltos:
            f.append(f"{i.b_saltos} saltos no contador das b,")
        if i.laco_perdidas:
            f.append(f"{i.laco_perdidas} amostras perdidas (# laco)")
        if i.d_descartadas > max_descartadas * i.d_validas:
            f.append(f"{i.d_descartadas} d, descartadas (máximo {100 * max_descartadas:g}%)")
        return f

    def passou(
        self, minimo: float = MINIMO_PADRAO, max_descartadas: float = MAX_DESCARTADAS_PADRAO
    ) -> bool:
        return not self.falhas(minimo, max_descartadas)


def confere(
    eventos: list[tuple[float, str]], pasta_png: Path | None = None, log_ruins: int = 0
) -> Relatorio | None:
    """Roda a conferência inteira. None se o log não tem nenhum quadro completo do display."""
    integ = mede_integridade(eventos, log_ruins)
    quadros = remonta_quadros(eventos)
    if not quadros:
        return None
    amostras = amostra_quadros(quadros)
    tipos = [(t, classifica(p)) for t, p in amostras]
    seg = trechos(tipos)
    dur = duracoes(seg)
    por_tela = collections.Counter(k for _, k in tipos)
    campos, bons = confere_numeros(amostras, tipos, Historico(eventos))
    pngs = salva_pngs(amostras, tipos, bons, pasta_png) if pasta_png else []
    return Relatorio(
        integridade=integ,
        quadros=len(quadros),
        inicio_s=quadros[0][0],
        fim_s=quadros[-1][0],
        segundos_por_tela={k: round(v * PASSO_S) for k, v in por_tela.items()},
        duracao_por_tela={
            k: (round(float(np.median(v)), 2), min(v), max(v), len(v)) for k, v in dur.items()
        },
        nominais=nominais(dur),
        sequencia=[k for k, *_ in seg],
        duracao_ok=duracao_confere(dur),
        ordem_ok=ordem_confere(seg),
        campos=campos,
        pngs=pngs,
    )


def imprime(r: Relatorio, minimo: float, desencontros: bool) -> None:
    i = r.integridade
    print(
        f"A) linhas {i.linhas} | b, {i.b_linhas} (saltos no n: {i.b_saltos}) | "
        f"linhas estragadas (fora as d,): {i.estragadas}"
    )
    print(f"   d, válidas {i.d_validas}, d, estragadas {i.d_estragadas}")
    print(
        f"   # laco ({i.laco_avisos} avisos de 1 s): amostras perdidas = {i.laco_perdidas} | "
        f"# tela: d, descartadas = {i.d_descartadas}"
    )
    print(f"B) quadros completos: {r.quadros}, de {r.inicio_s:.1f} a {r.fim_s:.1f} s")
    print(f"   tempo por tela (s): {r.segundos_por_tela}")
    print(f"   duração dos trechos (mediana, mín, máx, n): {r.duracao_por_tela}")
    print(f"   trechos a 0,5 s do previsto (de quantos completos): {r.nominais}")
    print(
        f"   rodízio: durações {'ok' if r.duracao_ok else 'NÃO'}, "
        f"ordem {'ok' if r.ordem_ok else 'NÃO'}"
    )
    print(f"   sequência (primeiras 14): {' > '.join(r.sequencia[:14])}")
    for nome, c in r.campos.items():
        marca = "" if c.fracao >= minimo else "  <-- ABAIXO DO MÍNIMO"
        print(f"C) {nome}: {c.ok}/{c.total} ({100 * c.fracao:.1f}%){marca}")
        if desencontros and c.exemplos:
            print(f"     desencontros (tempo, valores que a placa mandou): {c.exemplos}")
    if r.pngs:
        print(f"   PNGs: {r.pngs}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Confere o OLED contra a serial de uma sessão")
    ap.add_argument("log", type=Path, help="arquivo do grava_log.py")
    ap.add_argument("--png", type=Path, help="pasta onde salvar os PNGs coloridos das telas")
    ap.add_argument(
        "--minimo",
        type=float,
        default=MINIMO_PADRAO,
        help=f"fração mínima de acerto por campo (padrão {MINIMO_PADRAO})",
    )
    ap.add_argument(
        "--max-descartadas",
        type=float,
        default=MAX_DESCARTADAS_PADRAO,
        help="fração máxima de d, descartadas pelo buffer, sobre as d, válidas "
        f"(padrão {MAX_DESCARTADAS_PADRAO})",
    )
    ap.add_argument(
        "--desencontros", action="store_true", help="mostra os primeiros desencontros de cada campo"
    )
    args = ap.parse_args(argv)

    eventos, ruins = le_log(args.log)
    r = confere(eventos, args.png, ruins)
    if r is None:
        print("nenhum quadro completo do display: o firmware tinha -DSERIAL_TELA=ON?")
        return 1
    imprime(r, args.minimo, args.desencontros)
    falhas = r.falhas(args.minimo, args.max_descartadas)
    if falhas:
        print("FALHOU:")
        for f in falhas:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
