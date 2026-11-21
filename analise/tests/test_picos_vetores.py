"""Os vetores de testes/picos/ são o que o picos.py produz hoje (sem rede)."""

import re

import numpy as np
import pytest

from analise import vetores
from analise.picos import CASOS, detecta

PASTA = vetores.TESTES / "picos" / "vetores"


def le_array(texto: str, caso: str, nome: str) -> np.ndarray:
    m = re.search(rf"{caso}_{nome}\[\d+\] = \{{(.*?)\}};", texto, re.DOTALL)
    valores = [v.strip().removesuffix("f") for v in m.group(1).split(",") if v.strip()]
    return np.array([float(v) for v in valores])


@pytest.mark.parametrize("caso", [c for c, _ in CASOS])
def test_vetor_em_dia(caso):
    """Mudou o detector sem regerar? rode: uv run python -m analise.picos"""
    texto = (PASTA / f"{caso}.h").read_text(encoding="utf-8")
    entrada = le_array(texto, caso, "entrada").astype(np.float32)
    batimentos, bpm = detecta(entrada)

    assert [b.n_pico for b in batimentos] == le_array(texto, caso, "n_pico").tolist()
    assert [b.rr_valido for b in batimentos] == le_array(texto, caso, "rr_valido").astype(
        bool
    ).tolist()
    assert np.allclose([b.rr_ms for b in batimentos], le_array(texto, caso, "rr_ms"), atol=1e-3)
    assert np.allclose([b.fracao for b in batimentos], le_array(texto, caso, "fracao"), atol=1e-6)
    assert np.allclose(np.nan_to_num(bpm), le_array(texto, caso, "bpm"), atol=1e-3)
