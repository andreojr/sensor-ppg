from itertools import pairwise

import numpy as np
import pytest

from analise import FS_HZ
from analise.espectral import Espectral, estima


def senoide(f_hz: float, segundos: float, amp: float = 1.0) -> np.ndarray:
    n = np.arange(round(segundos * FS_HZ))
    return (amp * np.sin(2 * np.pi * f_hz * n / FS_HZ)).astype(np.float32)


@pytest.mark.parametrize("bpm", [48, 60, 72, 90, 120, 150, 180])
def test_acha_a_frequencia(bpm):
    """A interpolação parabólica acerta bem melhor que a resolução de 7,5 bpm."""
    saidas = estima(senoide(bpm / 60, 30))
    assert all(s.valido for s in saidas)
    assert all(abs(s.bpm - bpm) < 0.5 for s in saidas)


def test_so_sai_com_a_janela_cheia_e_a_cada_hop():
    saidas = estima(senoide(1.2, 30))
    # janela de 8 s, passo de 1 s, 30 s de sinal: saídas em 8, 9, ..., 30 s.
    assert len(saidas) == 23
    assert saidas[0].n == 8 * FS_HZ - 1
    assert all(b.n - a.n == FS_HZ for a, b in pairwise(saidas))


def test_ignora_o_dc():
    saidas = estima(senoide(1.2, 20) + 5000.0)
    assert all(abs(s.bpm - 72) < 0.5 for s in saidas)


def test_ruido_branco_nao_e_valido():
    rng = np.random.default_rng(0)
    ruido = rng.standard_normal(3000).astype(np.float32)
    saidas = estima(ruido)
    assert np.mean([s.valido for s in saidas]) < 0.3


def test_senoide_com_ruido_ainda_vale():
    rng = np.random.default_rng(1)
    x = senoide(1.5, 30) + 0.5 * rng.standard_normal(3000).astype(np.float32)
    saidas = estima(x)
    assert all(s.valido and abs(s.bpm - 90) < 1.0 for s in saidas)


def test_tem_que_caber_na_fft():
    with pytest.raises(ValueError):
        Espectral(janela_s=12, nfft=1024)


def test_reinicia_zera_o_estado():
    e = Espectral()
    for x in senoide(1.2, 12):
        e.processa(x)
    e.reinicia()
    q = Espectral()
    entrada = senoide(1.2, 12)
    assert [e.processa(x) for x in entrada] == [q.processa(x) for x in entrada]


@pytest.mark.parametrize("f_hz", [0.55, 0.6, 3.6])
def test_fora_da_banda_nao_vira_bpm_valido(f_hz):
    """Um componente fora da banda vaza pro bin da borda; não é pulso."""
    saidas = estima(senoide(f_hz, 20, amp=100.0))
    assert not any(s.valido for s in saidas)
    assert all(s.prominencia <= 1.0 for s in saidas)


@pytest.mark.parametrize("bpm", [45, 205])
def test_perto_da_borda_ainda_vale(bpm):
    saidas = estima(senoide(bpm / 60, 20))
    assert all(s.valido and abs(s.bpm - bpm) < 1.0 for s in saidas)
    assert all(s.prominencia <= 1.0 for s in saidas)


def test_silencio_nao_e_valido():
    saidas = estima(np.zeros(1000, dtype=np.float32))
    assert saidas and not any(s.valido or s.bpm for s in saidas)


def test_confere_placa_bate_com_ele_mesmo():
    """O --confere do passo 5: saída do próprio Python, filtrado com 2 casas."""
    from analise.espectral import confere_placa

    x = senoide(1.1, 20, amp=300.0)
    x = np.round(x, 2).astype(np.float32)
    saidas = estima(x)
    filtrado = np.column_stack([np.arange(len(x)), x, np.zeros(len(x))])
    placa = np.array([[s.n, s.valido, round(s.bpm, 2)] for s in saidas])
    r = confere_placa(filtrado, placa)
    assert r["janelas"] == len(saidas) and r["valido_diferente"] == 0
    assert r["bpm_dif_max"] < 0.01
    # Uma amostra perdida tira as janelas que a contêm.
    r = confere_placa(np.delete(filtrado, 1500, axis=0), placa)
    assert 0 < r["janelas"] < len(saidas)
