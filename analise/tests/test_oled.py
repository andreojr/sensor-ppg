"""A referência do display (oled.py) e os arquivos gerados a partir dela (sem rede)."""

import re

import numpy as np
import pytest

from analise import oled, vetores

PASTA = vetores.TESTES / "oled" / "vetores"


def le_array(texto: str, caso: str, nome: str) -> np.ndarray:
    m = re.search(rf"{caso}_{nome}\[\d+\] = \{{(.*?)\}};", texto, re.DOTALL)
    return np.array(
        [float(v.strip().removesuffix("f")) for v in m.group(1).split(",") if v.strip()]
    )


def test_tabela_da_fonte_do_c_em_dia():
    """Mudou a fonte sem regerar? rode: uv run python -m analise.oled"""
    assert oled.FONTE_H.read_text(encoding="utf-8") == oled.gera_fonte_c()


@pytest.mark.parametrize("caso", list(oled.casos()))
def test_vetor_em_dia(caso):
    fb, onda, _ = oled.casos()[caso]
    texto = (PASTA / f"{caso}.h").read_text(encoding="utf-8")
    assert bytes(le_array(texto, caso, "fb").astype(np.uint8)) == fb.paginas()
    if onda is not None:
        assert np.array_equal(le_array(texto, caso, "onda").astype(np.float32), onda)


def test_formato_de_pagina_do_ssd1306():
    """Byte = 8 linhas de uma coluna, o bit 0 é a de cima; 8 páginas de 128 colunas."""
    fb = oled.Fb()
    fb.set(0, 0)
    fb.set(5, 3)
    fb.set(127, 63)
    fb.set(10, 8)
    mem = fb.paginas()
    assert len(mem) == 1024
    assert mem[0] == 0b00000001
    assert mem[5] == 0b00001000
    assert mem[7 * 128 + 127] == 0b10000000
    assert mem[1 * 128 + 10] == 0b00000001  # a linha 8 é a primeira da página 1


def test_pixel_fora_da_tela_e_ignorado():
    fb = oled.Fb()
    for x, y in [(-1, 0), (0, -1), (128, 0), (0, 64), (500, 500)]:
        fb.set(x, y)
    assert fb.p.sum() == 0


def test_letra_a_e_a_do_design():
    fb = oled.Fb()
    fb.text(0, 0, "A")
    assert [("".join("#" if x else "." for x in fb.p[r, :5])) for r in range(7)] == oled.FONTE["A"]
    assert (
        not fb.p[7].any() and not fb.p[:, 5].any()
    )  # a célula é 6x8: a linha e a coluna de espaço


def test_texto_dobrado_e_o_mesmo_com_pixel_dobrado():
    a, b = oled.Fb(), oled.Fb()
    a.text(0, 0, "7")
    b.text(0, 0, "7", 2)
    assert np.array_equal(np.kron(a.p[:8, :6], np.ones((2, 2), dtype=np.uint8)), b.p[:16, :12])


def test_alinhamentos():
    fb = oled.Fb()
    assert fb.text_r(36, 0, "72", 2) == 36 - 24 + 2 + 24  # termina na célula depois do último
    fb = oled.Fb()
    fb.text_c(0, "SENSOR PPG", 2)  # 10 letras de 12 px, a última sem o espaço = 118 px
    colunas = np.flatnonzero(fb.p.any(axis=0))
    assert colunas[0] >= 5 and colunas[-1] <= 122
    assert (colunas[0] + colunas[-1]) // 2 in (63, 64)


def test_meio_pra_cima_como_o_javascript():
    assert [oled.meio_pra_cima(x) for x in (0.5, 1.5, 2.5, -0.5, -1.5, 0.49)] == [1, 2, 3, 0, -1, 0]


def test_barras_cheias_e_vazias():
    fb = oled.Fb()
    fb.barras(81, 0, 16, 7, 3, 3)
    alturas = [int(fb.p[:, 81 + b * 10 + 3].sum()) for b in range(5)]
    assert alturas == [4, 7, 10, 1, 1]  # 3 cheias; as vazias são um traço de 1 px


def test_onda_ocupa_a_faixa_toda_com_folga():
    fb = oled.Fb()
    v = np.sin(np.linspace(0, 6 * np.pi, 128)).astype(np.float32)
    fb.onda(0, 16, 128, 48, v)
    linhas = np.flatnonzero(fb.p.any(axis=1))
    assert linhas[0] >= 16 and linhas[-1] <= 63
    assert linhas[-1] - linhas[0] >= 40  # usa a maior parte da faixa
    assert (fb.p[:, :].sum(axis=0) > 0).all()  # tem pixel em todas as colunas


def test_onda_constante_nao_divide_por_zero():
    fb = oled.Fb()
    fb.onda(0, 0, 128, 64, np.full(128, 5.0, dtype=np.float32))
    assert fb.p.sum() > 0


def test_toda_tela_usa_so_caracteres_da_fonte(monkeypatch):
    vistos = []
    original = oled.glifo
    monkeypatch.setattr(oled, "glifo", lambda c: (vistos.append(c), original(c))[1])
    oled.casos()
    desconhecidos = {c for c in vistos if (c.upper() if c.isalpha() else c) not in oled.FONTE}
    assert not desconhecidos


def test_ppg_de_exemplo_e_deterministico_e_tem_o_tamanho_pedido():
    a, b = oled.ppg(n=256, bpm=72), oled.ppg(n=256, bpm=72)
    assert len(a) == 256 and np.array_equal(a, b)
    assert not np.array_equal(a, oled.ppg(n=256, bpm=72, seed=11))
    assert 1.0 < a.max() < 1.4 and a.min() > -0.1  # o pulso sobe a ~1,1 e volta perto de 0
