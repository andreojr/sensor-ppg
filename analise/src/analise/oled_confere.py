"""Confere o que o OLED mostrou contra o que a placa calculou, numa sessão gravada.

Entrada: o arquivo do grava_log.py (uma linha da serial por linha, com o horário). A placa
mandou, na mesma sessão, as linhas de resultado (b, p, e, h, s, r, t, l) e as páginas do
display (d,, com -DSERIAL_TELA=ON). Aqui:

A) integridade: linhas estragadas, saltos no contador das b,, amostras perdidas (# laco)
   e linhas d, descartadas pelo buffer (# tela);
B) remonta os quadros de 128 x 64 pixels a partir das d,, descobre qual tela era (principal,
   resumo, alvo, sem dedo, sinal ruim) e mede quanto tempo cada trecho durou (o rodízio);
C) refaz o texto de cada campo pelo oled.py a partir das linhas de resultado e compara,
   pixel a pixel, com o que estava na tela (BPM grande, BPM PICOS e FFT, SDNN, RMSSD,
   SPO2~ e RESP do resumo, SPO2 e RESP grandes do alvo).

Os quadros são amostrados a cada 0,25 s. Um campo "bate" se algum dos valores que a placa
mandou por perto no tempo (o último e alguns anteriores) desenha exatamente os pixels que
estavam na tela. Sobram poucos desencontros: o quadro lido com páginas novas e velhas
misturadas, ou o número cortado em casas diferentes. Por isso o limite padrão é 95%, não 100%.

Os PNGs (--png) saem coloridos como o painel bicolor: amarelo nas 16 primeiras linhas de
pixel e azul nas outras 48 (as cores e o corte vêm do tela_terminal.py).

Uso:
    uv run python -m analise.oled_confere dados/sessao.log
    uv run python -m analise.oled_confere dados/sessao.log --png dados/oled_telas
    uv run python -m analise.oled_confere dados/sessao.log --desencontros

Sai com código 1 se algum campo bater menos que --minimo ou se nenhum campo pôde ser conferido.
"""

from __future__ import annotations

import argparse
import collections
import math
import re
import sys
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from matplotlib.image import imsave

from analise.oled import Fb
from analise.tela_janela import COR_AMARELO_HEX, COR_AZUL_HEX
from analise.tela_terminal import CORTE_AMARELO_PX, H, W, le_pagina

PASSO_S = 0.25  # de quanto em quanto tempo a tela é amostrada
ESCALA_PNG = 6  # cada pixel do OLED vira 6 x 6 no PNG (768 x 384)
MINIMO_PADRAO = 0.95
PRIMEIRA_TELA_S = 120.0  # os PNGs saem de depois da partida, quando a tela já é a de regime
RESULTADOS = "hperstl"  # linhas de resultado que o display mostra (a primeira letra antes da vírgula)
NUMERICAS = RESULTADOS + "fq"  # linhas que só têm números depois do prefixo
TELAS_COM_TOPO = ("principal", "sinal_ruim", "sem_dedo")
TELAS_PNG = ("principal", "resumo", "alvo", "sem_dedo", "sinal_ruim")
# o rodízio previsto no display.c: duração de cada tela em segundos
RODIZIO_S = {"principal": 8.0, "resumo": 4.0, "alvo": 4.0}
TOLERANCIA_RODIZIO_S = 0.5


# ---------- A) integridade ----------


@dataclass
class Integridade:
    linhas: int = 0
    b_linhas: int = 0
    b_saltos: int = 0  # vezes que o contador das b, não andou de 1 em 1
    estragadas: int = 0  # linhas que não são d, e não fazem sentido
    d_validas: int = 0
    d_estragadas: int = 0
    laco_avisos: int = 0  # linhas "# laco" (uma por segundo)
    laco_perdidas: int = 0  # amostras que a placa disse ter perdido
    d_descartadas: int = 0  # linhas d, que o buffer da serial descartou (# tela)


def le_log(caminho: Path) -> list[tuple[float, str]]:
    """Lê o arquivo do grava_log.py: lista de (segundos, linha da serial)."""
    eventos = []
    with caminho.open() as f:
        for linha in f:
            tempo, _, resto = linha.rstrip("\n").partition("\t")
            eventos.append((float(tempo), resto))
    return eventos


def _numeros(linha: str) -> list[float] | None:
    """Os números depois do prefixo ("p,3,0.5,..." -> [3, 0.5, ...]). None se algum não for."""
    try:
        return [float(x) for x in linha.split(",")[1:]]
    except ValueError:
        return None


def mede_integridade(eventos: list[tuple[float, str]]) -> Integridade:
    r = Integridade(linhas=len(eventos))
    contador_b: list[int] = []
    for _, s in eventos:
        if s.startswith("# laco:"):
            m = re.search(r"perdidas (\d+)", s)
            r.laco_perdidas += int(m.group(1)) if m else 0
            r.laco_avisos += 1
        elif s.startswith("# tela:"):
            r.d_descartadas += int(s.split()[-1])
        elif s.startswith("d,"):
            if le_pagina(s) is None:
                r.d_estragadas += 1
            else:
                r.d_validas += 1
        elif s.startswith("b,"):
            p = s.split(",")
            try:
                n = int(p[1])
                float(p[2])
                float(p[3])
            except (ValueError, IndexError):
                r.estragadas += 1
            else:
                contador_b.append(n)
        elif s[:2] in tuple(c + "," for c in NUMERICAS):
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
    """Duração de cada trecho completo (o primeiro e o último podem estar cortados)."""
    d: dict[str, list[float]] = collections.defaultdict(list)
    for k, a, b in seg[1:-1]:
        d[k].append(b - a + PASSO_S)
    return d


def rodizio_confere(dur: dict[str, list[float]]) -> bool:
    """A mediana de cada tela do rodízio (principal, resumo, alvo) está perto do previsto
    (8, 4 e 4 s)? Telas que não apareceram não contam, mas ao menos uma precisa ter aparecido."""
    achou = False
    for tela, esperado in RODIZIO_S.items():
        if dur.get(tela):
            achou = True
            if abs(float(np.median(dur[tela])) - esperado) > TOLERANCIA_RODIZIO_S:
                return False
    return achou


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

    def janela(self, tipo: str, t: float, atras: float, frente: float = 0.7) -> list[list[float]]:
        """As linhas do tipo com horário em [t - atras, t + frente]."""
        ts = self.tempos[tipo]
        return self.dados[tipo][bisect_left(ts, t - atras) : bisect_right(ts, t + frente)]


def _arredonda(x: float, maximo: int) -> int:
    """Como o display: negativo ou NaN vira -1 (sem valor), acima do máximo vira o máximo,
    o resto arredonda com o meio pra cima."""
    if not (x >= 0):
        return -1
    return maximo if x >= maximo else math.floor(x + 0.5)


def _texto(v: int) -> str:
    return "--" if v < 0 else str(v)


def candidatos_principal(h: Historico, t: float) -> set[str]:
    """Textos possíveis do BPM grande: o da linha t, (um por segundo) e, com mostra = 1, o
    BPM do último batimento (p,), que muda entre um t, e outro."""
    c = set()
    for d in h.janela("t", t, 1.6):  # t,n,mostra,bpm x 100
        c.add(_texto(_arredonda(d[2] / 100, 999)) if d[1] == 1 else "--")
        if d[1] == 1:
            for dp in h.janela("p", t, 1.6):  # p,n_pico,fracao,rr_valido,rr_ms,bpm_valido,bpm
                if dp[4] == 1:
                    c.add(_texto(_arredonda(dp[5], 999)))
    return c


@dataclass
class Campo:
    ok: int = 0
    total: int = 0
    exemplos: list[tuple[float, str]] = field(default_factory=list)  # (tempo, candidatos)

    @property
    def fracao(self) -> float:
        return self.ok / self.total if self.total else 1.0


def _igual(p: np.ndarray, desenho, caixa: tuple[int, int, int, int]) -> bool:
    fb = Fb()
    desenho(fb)
    x0, y0, x1, y1 = caixa
    return bool((p[y0:y1, x0:x1] == fb.p[y0:y1, x0:x1]).all())


def _bate(p: np.ndarray, candidatos, desenho, caixa) -> bool:
    return any(_igual(p, lambda fb, c=c: desenho(fb, c), caixa) for c in candidatos)


def confere_numeros(
    amostras: list[tuple[float, np.ndarray]],
    tipos: list[tuple[float, str]],
    h: Historico,
) -> dict[str, Campo]:
    """Compara cada campo numérico da tela com os candidatos vindos das linhas de resultado."""
    campos: dict[str, Campo] = collections.defaultdict(Campo)

    def registra(nome: str, passou: bool, t: float, cands) -> None:
        c = campos[nome]
        c.total += 1
        if passou:
            c.ok += 1
        elif len(c.exemplos) < 4:
            c.exemplos.append((round(t, 1), str(cands)))

    for (t, p), (_, tela) in zip(amostras, tipos, strict=True):
        if tela in TELAS_COM_TOPO:  # a faixa de cima (BPM grande) é a mesma nas três
            c = candidatos_principal(h, t)
            ok = bool(c) and _bate(p, c, lambda fb, s: fb.text_r(36, 0, s, 2), (0, 0, 37, 16))
            registra("principal: BPM grande (t,)", ok, t, c)
        elif tela == "resumo":
            tudo = 3600  # o resumo mostra o último valor, de qualquer momento antes
            P, E, H_ = h.janela("p", t, tudo), h.janela("e", t, tudo), h.janela("h", t, tudo)
            S, R = h.janela("s", t, 2.5), h.janela("r", t, 2.5)
            if P:
                c = {_texto(_arredonda(d[5], 999)) if d[4] == 1 else "--" for d in P[-6:]}
                ok = _bate(p, c, lambda fb, s: fb.text_r(128, 8, s), (64, 8, 128, 16))
                registra("resumo: BPM PICOS (p,)", ok, t, c)
            if E:
                c = {_texto(_arredonda(d[2], 999)) if d[1] == 1 else "--" for d in E[-3:]}
                ok = _bate(p, c, lambda fb, s: fb.text_r(128, 16, s), (64, 16, 128, 24))
                registra("resumo: BPM FFT (e,)", ok, t, c)
            if H_:
                par = {
                    (_texto(_arredonda(d[2], 999)) + " MS", _texto(_arredonda(d[3], 999)) + " MS")
                    if d[1] == 1
                    else ("-- ", "-- ")
                    for d in H_[-8:]
                }

                def ms(y):
                    return lambda fb, s: fb.text_r(128, y, s.replace("-- ", "--"))

                registra(
                    "resumo: SDNN (h,)",
                    _bate(p, {a for a, _ in par}, ms(24), (64, 24, 128, 32)),
                    t,
                    par,
                )
                registra(
                    "resumo: RMSSD (h,)",
                    _bate(p, {b for _, b in par}, ms(32), (64, 32, 128, 40)),
                    t,
                    par,
                )
            if S:
                c = {_texto(_arredonda(d[2], 100)) if d[1] == 1 else "--" for d in S}
                ok = _bate(p, c, lambda fb, s: fb.text(0, 56, "SPO2~ " + s), (0, 56, 64, 64))
                registra("resumo: SPO2~ (s,)", ok, t, c)
            if R:
                c = {_texto(_arredonda(d[1], 99)) if d[2] == 1 else "--" for d in R}
                ok = _bate(p, c, lambda fb, s: fb.text_r(128, 56, "RESP " + s), (64, 56, 128, 64))
                registra("resumo: RESP (r,)", ok, t, c)
        elif tela == "alvo":
            S, R = h.janela("s", t, 2.5), h.janela("r", t, 2.5)
            if S:
                c = {_texto(_arredonda(d[2], 100)) if d[1] == 1 else "--" for d in S}
                ok = _bate(p, c, lambda fb, s: fb.text_r(36, 0, s, 2), (0, 0, 38, 16))
                registra("alvo: SPO2 grande (s,)", ok, t, c)
            if R:
                c = {_texto(_arredonda(d[1], 99)) if d[2] == 1 else "--" for d in R}
                ok = _bate(p, c, lambda fb, s: fb.text_r(100, 0, s, 2), (72, 0, 101, 16))
                registra("alvo: RESP grande (r,)", ok, t, c)
    return dict(sorted(campos.items()))


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


def salva_pngs(
    amostras: list[tuple[float, np.ndarray]],
    tipos: list[tuple[float, str]],
    pasta: Path,
    a_partir_de: float = PRIMEIRA_TELA_S,
) -> list[str]:
    """Salva oled_<tela>.png na pasta: a primeira amostra de cada tela depois de `a_partir_de`
    (ou a primeira de todas, se a tela só apareceu antes). Devolve as telas salvas."""
    escolhidas: dict[str, np.ndarray] = {}
    primeiras: dict[str, np.ndarray] = {}
    for (t, p), (_, k) in zip(amostras, tipos, strict=True):
        if k not in TELAS_PNG:
            continue
        primeiras.setdefault(k, p)
        if t >= a_partir_de:
            escolhidas.setdefault(k, p)
    pasta.mkdir(parents=True, exist_ok=True)
    salvas = []
    for k in TELAS_PNG:
        p = escolhidas.get(k, primeiras.get(k))
        if p is not None:
            imsave(pasta / f"oled_{k}.png", imagem_colorida(p))
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
    sequencia: list[str]
    rodizio_ok: bool
    campos: dict[str, Campo]
    pngs: list[str]

    def passou(self, minimo: float = MINIMO_PADRAO) -> bool:
        """Há campos conferidos e todos batem pelo menos `minimo`."""
        return bool(self.campos) and all(c.fracao >= minimo for c in self.campos.values())


def confere(
    eventos: list[tuple[float, str]], pasta_png: Path | None = None
) -> Relatorio | None:
    """Roda a conferência inteira. None se o log não tem nenhum quadro completo do display."""
    integ = mede_integridade(eventos)
    quadros = remonta_quadros(eventos)
    if not quadros:
        return None
    amostras = amostra_quadros(quadros)
    tipos = [(t, classifica(p)) for t, p in amostras]
    seg = trechos(tipos)
    dur = duracoes(seg)
    por_tela = collections.Counter(k for _, k in tipos)
    campos = confere_numeros(amostras, tipos, Historico(eventos))
    pngs = salva_pngs(amostras, tipos, pasta_png) if pasta_png else []
    return Relatorio(
        integridade=integ,
        quadros=len(quadros),
        inicio_s=quadros[0][0],
        fim_s=quadros[-1][0],
        segundos_por_tela={k: round(v * PASSO_S) for k, v in por_tela.items()},
        duracao_por_tela={
            k: (round(float(np.median(v)), 2), min(v), max(v), len(v)) for k, v in dur.items()
        },
        sequencia=[k for k, *_ in seg],
        rodizio_ok=rodizio_confere(dur),
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
    print(f"   rodízio como previsto (8/4/4 s): {'sim' if r.rodizio_ok else 'NÃO'}")
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
        "--desencontros", action="store_true", help="mostra os primeiros desencontros de cada campo"
    )
    args = ap.parse_args(argv)

    r = confere(le_log(args.log), args.png)
    if r is None:
        print("nenhum quadro completo do display: o firmware tinha -DSERIAL_TELA=ON?")
        return 1
    imprime(r, args.minimo, args.desencontros)
    if not r.passou(args.minimo):
        print("FALHOU: algum campo ficou abaixo do mínimo, ou nada foi conferido")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
