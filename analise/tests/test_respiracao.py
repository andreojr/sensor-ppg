"""Protótipo da respiração: banda lenta, Goertzel, qualidade, vetores e conferências."""

import numpy as np
import pytest

from analise import FS_HZ, physionet, respiracao, vetores


def test_grade_e_tabelas():
    f = respiracao.grade()
    assert len(f) == 89 and f[0] == pytest.approx(0.08) and f[-1] == pytest.approx(0.52)
    assert respiracao.N_JANELA == 240 and respiracao.PASSO * respiracao.BLOCO == FS_HZ
    # A banda lenta passa 6 a 30 rpm e corta o pulso (>= 0,8 Hz).
    from scipy import signal

    _, h = signal.sosfreqz(respiracao.sos(), worN=[0.1, 0.25, 0.5, 1.0], fs=respiracao.FR_HZ)
    db = 20 * np.log10(np.abs(h))
    assert db[0] > -3 and db[1] > -1 and db[2] > -3 and db[3] < -9


@pytest.mark.parametrize("rpm", [6, 10, 15, 24])
def test_espectro_acha_a_frequencia(rpm):
    t = np.arange(respiracao.N_JANELA) / respiracao.FR_HZ
    x = np.sin(2 * np.pi * rpm / 60 * t) + 0.1 * np.random.default_rng(rpm).normal(size=len(t))
    est, q = respiracao.espectro(x)
    assert est == pytest.approx(rpm, abs=0.2) and q > 0.6


def test_metronomo_sintetico():
    s = respiracao.estima(respiracao.metronomo_sintetico())
    assert len(s) == 360  # uma por segundo, 6 min
    assert not s[s[:, 0] < 60 * FS_HZ - 1, 1].any()  # sem janela cheia, nada válido
    for k, rpm in enumerate((6, 10, 15)):
        m = (s[:, 0] >= k * 12000 + 6000) & (s[:, 0] < (k + 1) * 12000)
        assert s[m, 1].all() and s[m, 2] == pytest.approx(rpm, abs=0.1)


@pytest.mark.parametrize("f_hz", [0.08, 0.52])
def test_pico_na_ponta_nao_vale(f_hz):
    """Máximo numa ponta da grade: a potência sobe pra fora da faixa, não vale."""
    t = np.arange(respiracao.N_JANELA) / respiracao.FR_HZ
    rpm, q = respiracao.espectro(np.sin(2 * np.pi * f_hz * t))
    assert rpm == pytest.approx(60 * f_hz) and q == 0.0


def test_ruido_nao_e_valido():
    x = 100_000 + np.random.default_rng(3).normal(0, 50, 120 * FS_HZ)
    s = respiracao.estima(x)
    assert s[:, 1].mean() < 0.2  # ruído branco quase nunca tem pico que se destaque


def test_edr_sintetica():
    """As duas EDR acham a respiração num ECG sintético com RSA e amplitude moduladas."""
    fs, rpm = 500, 12
    t_r = np.cumsum(0.85 + 0.05 * np.sin(2 * np.pi * rpm / 60 * np.arange(0, 300, 0.85)))
    t_r = t_r[t_r < 290]
    picos = np.round(t_r * fs).astype(np.int64)
    ecg = np.zeros(300 * fs)
    ecg[picos] = 1 + 0.2 * np.sin(2 * np.pi * rpm / 60 * t_r)
    r = physionet.Registro("x", fs, ecg, ecg, ecg, picos)
    rsa, amp = respiracao.edr(r)
    janela = slice(int(100 * respiracao.FR_HZ), int(100 * respiracao.FR_HZ) + respiracao.N_JANELA)
    assert respiracao.espectro(rsa[janela])[0] == pytest.approx(rpm, abs=0.5)
    assert respiracao.espectro(amp[janela])[0] == pytest.approx(rpm, abs=0.5)


def test_coeficientes_e_vetor_em_dia(tmp_path):
    feitos = respiracao.gera_vetores(testes=tmp_path, coef=tmp_path / "c.h", physionet_=False)
    assert feitos[0].read_text(encoding="utf-8") == respiracao.COEF_H.read_text(encoding="utf-8")
    versionado = vetores.TESTES / "respiracao" / "vetores" / "metronomo.h"
    assert feitos[1].read_text(encoding="utf-8") == versionado.read_text(encoding="utf-8"), (
        "rode: uv run python -m analise.respiracao --vetores"
    )


def test_confere_placa_e_metronomo():
    x = respiracao.metronomo_sintetico(rpms=(10,), minutos=2)
    bruto = np.column_stack([np.arange(len(x)), x, x])
    s = respiracao.estima(x)
    placa = np.column_stack([s[:, 0], s[:, 2], s[:, 1]])
    r = respiracao.confere_placa(bruto, placa)
    assert r == {"comparadas": 120, "valido_diferente": 0, "erro_max_rpm": 0.0, "desde_boot": True}
    placa[100, 1] += 1
    assert respiracao.confere_placa(bruto, placa)["erro_max_rpm"] == pytest.approx(1)
    m = respiracao.confere_metronomo(placa, 10)
    assert m["validas"] == m["estimativas"] == 60 and m["mediana_rpm"] == pytest.approx(10, abs=0.1)
    with pytest.raises(ValueError):  # salto no n
        respiracao.confere_placa(np.delete(bruto, 500, axis=0), placa)


def test_confere_no_meio_e_depois_do_reset():
    """Captura aberta com a placa rodando (no meio) e aberta antes do reset."""
    x = respiracao.metronomo_sintetico(rpms=(10,), minutos=4)
    s = respiracao.estima(x)
    placa = np.column_stack([s[:, 0], s[:, 2], s[:, 1]])
    bruto = np.column_stack([np.arange(len(x)), x, x])
    k = 1234  # começa no meio, fora do alinhamento dos blocos
    r = respiracao.confere_placa(bruto[k:], placa[placa[:, 0] >= k])
    assert not r["desde_boot"] and r["comparadas"] > 60
    assert r["valido_diferente"] == 0 and r["erro_max_rpm"] < 0.05
    antes = np.column_stack([np.arange(900, 1500), x[:600], x[:600]])  # fim do boot anterior
    r = respiracao.confere_placa(np.vstack([antes, bruto]), np.vstack([placa[:3] + [5000, 0, 0], placa]))
    assert r["desde_boot"] and r["comparadas"] == len(placa) and r["valido_diferente"] == 0
    m = respiracao.confere_metronomo(np.vstack([placa[:3] + [5000, 0, 0], placa]), 10)
    assert m["estimativas"] == len(placa) - 60
