"""Protótipo do LF/HF, com sequências sintéticas (sem rede)."""

import math

import numpy as np
import pytest

from analise import FS_HZ, hrv_freq
from analise.hrv import Batimento


def batimentos(t_s, rr_ms, rr_valido=None):
    x = np.asarray(t_s) * FS_HZ
    ok = np.ones(len(x), bool) if rr_valido is None else np.asarray(rr_valido)
    return [Batimento(True, int(np.floor(v)), float(v - np.floor(v)), bool(k > 0 and ok[k]),
                      float(rr)) for k, (v, rr) in enumerate(zip(x, rr_ms, strict=True))]


def ultima(saidas):
    return [s for s in saidas if s is not None][-1]


def test_bandas_em_indices_da_grade():
    assert (hrv_freq.K_LF, hrv_freq.K_HF, hrv_freq.K_FIM) == (12, 45, 120)


def test_senoide_num_bin_cai_na_banda_certa():
    n = hrv_freq.JANELA_S * hrv_freq.FS_REAMOSTRA
    j = np.arange(n)
    lf, hf = hrv_freq.potencias(np.sin(2 * np.pi * 20 * j / n))
    assert lf == pytest.approx((n / 2) ** 2) and hf < 1e-12 * lf
    lf, hf = hrv_freq.potencias(np.sin(2 * np.pi * 80 * j / n))
    assert hf == pytest.approx((n / 2) ** 2) and lf < 1e-12 * hf


def test_lf_hf_de_senoides_conhecidas():
    t, rr = hrv_freq.rr_senoidal(400.0, 40.0, 20.0)
    s = ultima(hrv_freq.roda(batimentos(t, rr)))
    assert s.lf_hf_valido and s.lf_hf == pytest.approx(4.0, rel=0.1)


def test_interpolacao_linear_infla_o_lf_hf():
    # Interpolar com retas atenua a HF (a respiração): o LF/HF sobe.
    t, rr = hrv_freq.rr_senoidal(300.0, 40.0, 20.0)
    assert hrv_freq.lf_hf(t[1:], rr[1:], spline=False) > 1.1 * hrv_freq.lf_hf(t[1:], rr[1:])


def test_janela_incompleta_nao_valida():
    t = np.arange(400) * 1.0
    rr = 1000.0 + 30.0 * (-1.0) ** np.arange(400)
    saidas = hrv_freq.roda(batimentos(t, rr))
    primeira = next(k for k, s in enumerate(saidas) if s.lf_hf_valido)
    assert primeira == 270  # 270 RR de ~1 s = 90% de 300 s


def test_cada_perdido_tira_dois_rr():
    t, rr = hrv_freq.rr_senoidal(400.0, 40.0, 20.0)
    cheio = ultima(hrv_freq.roda(batimentos(t, rr)))
    for pula, valido in ((40, True), (20, False)):
        manter = np.arange(len(t)) % pula != pula - 1
        ok = np.concatenate([[False], manter[:-1]])[manter]
        s = ultima(hrv_freq.roda(batimentos(t[manter], rr[manter], ok)))
        assert s.lf_hf_valido is valido
        if valido:
            assert s.lf_hf == pytest.approx(cheio.lf_hf, rel=0.1)


def test_poucos_batimentos_e_invalido_ignorado():
    h = hrv_freq.HrvFreq()
    assert h.processa(Batimento(False, 100, 0.0, True, 800.0)) is None
    for k in range(3):
        assert h.processa(Batimento(True, 200 * (k + 1), 0.0, k > 0, 2000.0)).lf_hf_valido is False


@pytest.mark.parametrize("rr", [250.0, 2500.0, math.nan, math.inf])
def test_rr_fora_da_faixa_nao_entra(rr):
    h = hrv_freq.HrvFreq()
    for k in range(10):
        h.processa(Batimento(True, 100 * k, 0.0, k > 0, rr if k == 5 else 1000.0))
    assert len(h.itens) == 8


def test_mesmo_instante_nao_entra():
    h = hrv_freq.HrvFreq()
    h.processa(Batimento(True, 100, 0.5, True, 1000.0))
    h.processa(Batimento(True, 100, 0.5, True, 1000.0))
    h.processa(Batimento(True, 100, 0.4, True, 1000.0))
    assert len(h.itens) == 1


def test_n_voltando_reinicia_e_buffer_cheio():
    h = hrv_freq.HrvFreq()
    for k in range(hrv_freq.CAP + 50):
        h.processa(Batimento(True, 40 * k, 0.0, k > 0, 400.0))
    assert len(h.itens) == hrv_freq.CAP and h.itens[0].n == 40 * 50  # o k = 0 não tem RR
    h.processa(Batimento(True, 5, 0.0, True, 400.0))
    assert len(h.itens) == 1


def test_vetor_bordas_passa_por_todas_as_regras():
    a = hrv_freq._arrays(hrv_freq.batimentos_bordas())
    v = a["lf_hf_valido"]
    assert a["escreveu"].sum() == len(v) - 1  # só o inválido não escreve
    # Válido antes do reinício (k = 699), do buraco (k = 1149) e do buffer cheio.
    assert v[698] and not v[699] and v[1148] and not v[1149] and not v[-1]
