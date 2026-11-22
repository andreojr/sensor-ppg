"""Os vetores de testes/espectral/ são o que o espectral.py produz hoje (sem rede)."""

import re

import numpy as np
import pytest

from analise import vetores
from analise.espectral import CASOS, estima

PASTA = vetores.TESTES / "espectral" / "vetores"


def le_array(texto: str, caso: str, nome: str) -> np.ndarray:
    m = re.search(rf"{caso}_{nome}\[\d+\] = \{{(.*?)\}};", texto, re.DOTALL)
    return np.array(
        [float(v.strip().removesuffix("f")) for v in m.group(1).split(",") if v.strip()]
    )


@pytest.mark.parametrize("caso", [c for c, _ in CASOS])
def test_vetor_em_dia(caso):
    """Mudou o detector sem regerar? rode: uv run python -m analise.espectral"""
    texto = (PASTA / f"{caso}.h").read_text(encoding="utf-8")
    entrada = le_array(texto, caso, "entrada").astype(np.float32)
    saidas = estima(entrada)

    assert [s.valido for s in saidas] == le_array(texto, caso, "valido").astype(bool).tolist()
    assert np.allclose([s.bpm for s in saidas], le_array(texto, caso, "bpm"), atol=1e-4)
    assert np.allclose(
        [s.prominencia for s in saidas], le_array(texto, caso, "prominencia"), atol=1e-6
    )


def test_invalido_sai_com_bpm_zero():
    """Convenção do picos_bpm(): sem confiança, bpm = 0 (o display mostra "--")."""
    texto = (PASTA / "s2_walk.h").read_text(encoding="utf-8")
    valido = le_array(texto, "s2_walk", "valido").astype(bool)
    bpm = le_array(texto, "s2_walk", "bpm")
    assert not valido.all() and valido.any()  # o caso exercita os dois lados
    assert (bpm[~valido] == 0).all() and (bpm[valido] > 0).all()
