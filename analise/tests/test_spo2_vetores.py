"""Os vetores de testes/spo2/ são o que o spo2.py produz hoje (sem rede)."""

import re

import numpy as np
import pytest

from analise import vetores
from analise.spo2 import CASOS, estima

PASTA = vetores.TESTES / "spo2" / "vetores"


def le_array(texto: str, caso: str, nome: str) -> np.ndarray:
    m = re.search(rf"{caso}_{nome}\[\d+\] = \{{(.*?)\}};", texto, re.DOTALL)
    return np.array(
        [float(v.strip().removesuffix("f")) for v in m.group(1).split(",") if v.strip()]
    )


@pytest.mark.parametrize("caso", [c for c, _ in CASOS])
def test_vetor_em_dia(caso):
    """Mudou o módulo sem regerar? rode: uv run python -m analise.spo2"""
    texto = (PASTA / f"{caso}.h").read_text(encoding="utf-8")
    ir = le_array(texto, caso, "ir").astype(np.float32)
    vm = le_array(texto, caso, "vermelho").astype(np.float32)
    saidas = estima(ir, vm)
    assert [s.valido for s in saidas] == le_array(texto, caso, "valido").astype(bool).tolist()
    assert np.allclose([s.spo2 for s in saidas], le_array(texto, caso, "spo2"), atol=1e-4)
    assert np.allclose([s.r for s in saidas], le_array(texto, caso, "r"), atol=1e-5)


def test_o_caso_sem_dedo_exercita_os_dois_lados():
    texto = (PASTA / "sem_dedo.h").read_text(encoding="utf-8")
    valido = le_array(texto, "sem_dedo", "valido").astype(bool)
    spo2 = le_array(texto, "sem_dedo", "spo2")
    assert valido.any() and not valido.all()
    assert (spo2[~valido] == 0).all() and (spo2[valido] > 90).all()  # nenhum valor errado passa
