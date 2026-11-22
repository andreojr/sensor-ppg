"""Os vetores de testes/fft/ são o que o NumPy dá pra entrada deles (sem rede)."""

import re

import numpy as np
import pytest

from analise import fft_vetores, vetores

PASTA = vetores.TESTES / "fft" / "vetores"
CASOS = ["n256", "n512", "n1024", "ppg1024"]


def le_array(texto: str, caso: str, nome: str) -> np.ndarray:
    m = re.search(rf"{caso}_{nome}\[\d+\] = \{{(.*?)\}};", texto, re.DOTALL)
    return np.array(
        [float(v.strip().removesuffix("f")) for v in m.group(1).split(",") if v.strip()]
    )


@pytest.mark.parametrize("caso", CASOS)
def test_potencia_e_a_do_numpy(caso):
    """Mudou o gerador sem regerar? rode: uv run python -m analise.fft_vetores"""
    texto = (PASTA / f"{caso}.h").read_text(encoding="utf-8")
    entrada = le_array(texto, caso, "entrada").astype(np.float32)
    potencia = le_array(texto, caso, "potencia")
    assert len(potencia) == len(entrada) // 2 + 1
    assert np.allclose(potencia, fft_vetores.potencia(entrada), atol=1e-7)


def test_senoide_pura_tem_o_pico_certo():
    """Senoide de amplitude 1 tem pico de potência 0,25 (na escala dividida por n^2)."""
    n = 256
    x = np.sin(2 * np.pi * 8 * np.arange(n) / n).astype(np.float32)  # 8 ciclos exatos
    p = fft_vetores.potencia(x)
    assert np.argmax(p) == 8
    assert p[8] == pytest.approx(0.25, rel=1e-5)


def test_ppg1024_e_janelado_e_preenchido():
    texto = (PASTA / "ppg1024.h").read_text(encoding="utf-8")
    entrada = le_array(texto, "ppg1024", "entrada")
    assert len(entrada) == 1024
    assert np.abs(entrada).max() == pytest.approx(1.0, rel=1e-6)  # normalizado
    assert not entrada[800:].any()  # 8 s a 100 Hz, o resto é zero-padding
