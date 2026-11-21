"""Protótipo do filtro: projeto do FIR, conta igual à do C, atraso, vetores em dia."""

import re
from pathlib import Path

import numpy as np
import pytest

from analise import FS_HZ, filtro, vetores

PPG_H = Path(__file__).resolve().parents[2] / "Core/Inc/pds/comum/ppg.h"


def test_projeto():
    h = filtro.coeficientes()
    assert len(h) == filtro.N_COEF and np.allclose(h, h[::-1])
    assert abs(h.sum()) < 1e-15  # DC = 0
    r = filtro.resposta()
    assert r["0.5 Hz"] == pytest.approx(-6, abs=0.5) and r["4 Hz"] == pytest.approx(-6, abs=0.5)
    assert abs(r["2 Hz"]) < 0.1
    assert r["0.05 Hz"] < -40 and r["0.2 Hz"] < -15 and r["6 Hz"] < -60


def test_atraso_igual_ao_ppg_h():
    texto = PPG_H.read_text(encoding="utf-8")
    atraso = float(re.search(r"#define PPG_ATRASO_AMOSTRAS ([\d.]+)f", texto)[1])
    assert atraso == filtro.ATRASO == (filtro.N_COEF - 1) / 2


def test_filtra_igual_ao_laco():
    """filtro_processa() amostra a amostra, em float64."""
    x = 70_000 + np.random.default_rng(1).normal(0, 300, 600)
    h = filtro.coeficientes()
    hist = np.zeros(len(h))
    laco = []
    for v in x:
        hist = np.roll(hist, 1)
        hist[0] = v - x[0]
        laco.append(h @ hist)
    assert filtro.filtra(x) == pytest.approx(np.array(laco), abs=1e-9)


def test_dc_some_e_pulso_atrasa_exatamente():
    t = np.arange(3000) / FS_HZ
    y = filtro.filtra(100_000 + 800 * np.sin(2 * np.pi * 1.5 * t))
    esperado = 800 * np.sin(2 * np.pi * 1.5 * (t - filtro.ATRASO / FS_HZ))
    assert y[filtro.N_COEF :] == pytest.approx(esperado[filtro.N_COEF :], abs=8)  # ripple < 0,1 dB
    assert np.all(filtro.filtra(np.full(500, 123_456.0)) == 0)


def test_iir_desloca_o_pico_conforme_a_fc():
    """O efeito que fez a gente escolher o FIR: no IIR, o pico anda com a FC."""
    t = np.arange(6000) / FS_HZ
    desloc = {}
    for f_hz in (0.9, 2.0):
        x = 100_000 + 800 * np.sin(2 * np.pi * f_hz * t)
        ref = filtro.picos(filtro.fase_zero(x))
        for nome, (y, atraso) in filtro.caminhos(x).items():
            d = filtro.deslocamento_s(filtro.picos(y) - atraso / FS_HZ, ref[ref > 10])
            desloc[nome, f_hz] = 1000 * np.median(d)
    fir = f"FIR {filtro.N_COEF} (nosso)"
    assert abs(desloc[fir, 0.9]) < 2 and abs(desloc[fir, 2.0]) < 2
    assert abs(desloc["IIR Butterworth 4", 0.9] - desloc["IIR Butterworth 4", 2.0]) > 50


def test_coeficientes_e_vetor_em_dia(tmp_path):
    feitos = filtro.gera_vetores(testes=tmp_path, coef=tmp_path / "coef.h")
    assert feitos[0].read_text(encoding="utf-8") == filtro.COEF_H.read_text(encoding="utf-8")
    versionado = vetores.TESTES / "filtro" / "vetores" / "bruto_100hz.h"
    assert feitos[1].read_text(encoding="utf-8") == versionado.read_text(encoding="utf-8"), (
        "rode: uv run python -m analise.filtro --vetores"
    )


def test_confere_placa():
    n = np.arange(500, 3500)
    x = np.round(100_000 + 800 * np.sin(2 * np.pi * 1.2 * n / FS_HZ), 2)
    bruto = np.column_stack([n, x, x])
    # A placa filtrou desde o boot: aqui, o mesmo FIR sobre o mesmo bruto.
    y = np.convolve(x, filtro.coeficientes())[: len(x)]
    placa = np.column_stack([n, y, y])
    r = filtro.confere_placa(bruto, placa)
    assert r["saidas"] == len(n) - filtro.N_COEF + 1 and r["erro_max_ir"] < 1e-6
    assert abs(r["desloc_ms"]) < 5 and r["bpm"] == pytest.approx(72, abs=1)
    placa[1000, 2] += 2
    assert filtro.confere_placa(bruto, placa)["erro_max_vermelho"] == pytest.approx(2)
    with pytest.raises(ValueError):
        filtro.confere_placa(np.delete(bruto, 10, axis=0), placa)
