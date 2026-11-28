"""Efeito da fase do filtro no pico, num registro sintético (sem rede)."""

import numpy as np
import pytest

from analise import FS_HZ, fase_pico, filtro, physionet

FS = 500


def sintetico(rr_s: float) -> physionet.Registro:
    """340 s de PPG: pulso com onda dicrótica, 250 ms depois de cada R, com o RR
    (em torno de rr_s) modulado pela respiração (arritmia sinusal)."""
    t_r = [1.0]
    while t_r[-1] < 338:
        t_r.append(t_r[-1] + rr_s * (1 + 0.06 * np.sin(2 * np.pi * 0.25 * t_r[-1])))
    t_r = np.array(t_r[:-1])
    t = np.arange(340 * FS) / FS
    ppg = np.zeros_like(t)
    for r in t_r:
        ppg += np.exp(-0.5 * ((t - r - 0.25) / 0.06) ** 2)  # sístole
        ppg += 0.4 * np.exp(-0.5 * ((t - r - 0.55) / 0.08) ** 2)  # onda dicrótica
    ir = 100_000 + 1000 * ppg
    picos = np.round(t_r * FS).astype(np.int64)
    return physionet.Registro("sintetico", FS, ir, ir * 0.7, ppg, picos)


@pytest.fixture(scope="module")
def resultado() -> dict[str, fase_pico.Resultado]:
    return {x.caminho: x for x in fase_pico.avalia(sintetico(1.0))}  # 60 bpm


@pytest.fixture(scope="module")
def rapido() -> dict[str, fase_pico.Resultado]:
    return {x.caminho: x for x in fase_pico.avalia(sintetico(60 / 110))}  # 110 bpm


def test_atraso_de_grupo():
    f = np.linspace(0.8, 2.5, 20)
    assert fase_pico.atraso_de_grupo(fase_pico.FIR, f) == pytest.approx(filtro.ATRASO, abs=1e-6)
    iir = fase_pico.atraso_de_grupo("IIR Butterworth 4", f)
    assert iir.max() - iir.min() > 10  # mais de 100 ms de diferença dentro da banda do pulso


def test_fir_nao_desloca_nem_estraga_o_hrv(resultado):
    fir, zero = resultado[fase_pico.FIR], resultado[fase_pico.REFERENCIA]
    assert abs(fir.desloc_ms) < 5 and fir.jitter_ms < 3
    assert fir.rr_rms_ms < 6 and fir.janelas_hrv > 100
    assert fir.rmssd_rms_ms < 3 and fir.sdnn_rms_ms < 3
    assert zero.desloc_ms == 0


def test_iir_desloca_o_pico_e_o_fir_nao(resultado, rapido):
    """Nas duas FC, o IIR tira o pico do lugar (o sentido e o tamanho dependem da
    forma da onda) e o FIR, descontado o atraso, não; nem muda com a FC.

    Aqui o pulso tem forma fixa, e o deslocamento do IIR sai quase constante (um
    atraso fixo corrigiria): o teste só cobre isso. Que no IIR o deslocamento muda
    de registro pra registro e de batimento a batimento, e estraga o HRV, é medido
    no PhysioNet (uv run python -m analise.fase_pico), com pulsos reais.
    """
    for r in (resultado, rapido):
        fir = abs(r[fase_pico.FIR].desloc_ms)
        assert fir < 3
        for ordem in (2, 4):
            iir = abs(r[f"IIR Butterworth {ordem}"].desloc_ms)
            assert iir > 20 and iir > 5 * fir
    assert abs(rapido[fase_pico.FIR].desloc_ms - resultado[fase_pico.FIR].desloc_ms) < 3


def test_melhor_constante():
    def r(caminho, d):
        return fase_pico.Resultado("x", caminho, 60, d, 0, 0, 0, 0, 0, 0, 0)

    res = [r("a", -10.0), r("a", 0.0), r("a", 30.0)]
    c, rms, pior = fase_pico.melhor_constante(res, "a")
    assert c == 0.0 and pior == 30.0 and rms == pytest.approx(np.sqrt((100 + 900) / 3))


def test_caminhos_cobrem_a_comparacao():
    nomes = list(fase_pico.caminhos())
    assert nomes[0] == fase_pico.REFERENCIA and fase_pico.FIR in nomes
    assert fase_pico.caminhos()[fase_pico.FIR][1] * 1000 / FS_HZ == 1000  # 1 s
