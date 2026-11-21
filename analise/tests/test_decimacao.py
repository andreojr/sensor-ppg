"""Protótipo da decimação: projeto do FIR, conta igual à do C, vetores em dia."""

import re
from pathlib import Path

import numpy as np
import pytest

from analise import FS_HZ, decimacao, vetores

RAIZ = Path(__file__).resolve().parents[2]
DECIMACAO_H = RAIZ / "Core/Inc/pds/decimacao/decimacao.h"


def _laco_igual_ao_c(x: np.ndarray, fs: int) -> np.ndarray:
    """decimacao_processa() amostra a amostra, em float64."""
    h = decimacao.coeficientes(fs)
    hist = np.zeros(len(h))
    falta, ref, saida = decimacao.atraso_entrada(fs), x[0], []
    for v in x:
        hist = np.roll(hist, 1)
        hist[0] = v - ref
        if falta:
            falta -= 1
            continue
        falta = decimacao.fator(fs) - 1
        saida.append(ref + h @ hist)
    return np.array(saida)


@pytest.mark.parametrize("fs", decimacao.TAXAS_HZ)
def test_projeto(fs):
    h = decimacao.coeficientes(fs)
    assert len(h) == 2 * decimacao.ATRASO_SAIDA * fs // FS_HZ + 1
    assert np.allclose(h, h[::-1]) and h.sum() == pytest.approx(1, abs=1e-12)
    r = decimacao.resposta(h, fs)
    assert r.ripple_db < 0.05
    assert r.rejeicao_db < -70 and r.alias_db < -70
    # A média do sensor deixa passar muito mais do que dobra pra 0 a 10 Hz.
    assert decimacao.resposta(np.ones(fs // FS_HZ) / (fs // FS_HZ), fs).alias_db > -20


@pytest.mark.parametrize("fs", decimacao.TAXAS_HZ)
def test_vetorizado_igual_ao_laco(fs):
    x = 100_000 + np.random.default_rng(fs).normal(0, 500, 2000)
    y = decimacao.decima(x, fs)
    assert len(y) == (2000 - 1 - decimacao.atraso_entrada(fs)) // decimacao.fator(fs) + 1
    assert y == pytest.approx(_laco_igual_ao_c(x, fs), abs=1e-6)


@pytest.mark.parametrize("fs", decimacao.TAXAS_HZ)
def test_n_alinhado_com_o_tempo(fs):
    """A saída n é o instante n / 100 s da entrada, sem atraso."""
    t = np.arange(10 * fs) / fs
    y = decimacao.decima(np.sin(2 * np.pi * 1.3 * t), fs)
    tn = np.arange(len(y)) / FS_HZ
    assert y[20:] == pytest.approx(np.sin(2 * np.pi * 1.3 * tn[20:]), abs=1e-3)


def test_dc_exato_e_sem_transiente():
    y = decimacao.decima(np.full(1000, 123_456.0), 400)
    assert np.all(y == 123_456.0)


def test_rejeita_alias():
    """Cintilação de 120 Hz a 400 Hz cai em 20 Hz: o FIR some com ela, a média não."""
    t = np.arange(8000) / 400
    x = 100_000 + 500 * np.sin(2 * np.pi * 120 * t)
    assert np.ptp(decimacao.decima(x, 400)[10:]) < 2 * 500 * 10 ** (-70 / 20)
    assert np.ptp(decimacao.media_sensor(x, 400)) > 2 * 500 * 0.1


def test_taxa_sem_filtro():
    with pytest.raises(ValueError):
        decimacao.coeficientes(250)


def test_constantes_iguais_ao_c():
    texto = DECIMACAO_H.read_text(encoding="utf-8")
    assert int(re.search(r"DECIMACAO_LATENCIA_SAIDA (\d+)u", texto)[1]) == decimacao.ATRASO_SAIDA
    n_max = max(len(decimacao.coeficientes(fs)) for fs in decimacao.TAXAS_HZ)
    assert int(re.search(r"DECIMACAO_N_MAX (\d+)u", texto)[1]) == n_max


def test_coeficientes_e_vetor_em_dia(tmp_path):
    """O decimacao_coef.h e o vetor da fonte falsa versionados são o que o gerador faz hoje.

    O vetor do PhysioNet precisa de rede e fica de fora.
    """
    feitos = decimacao.gera_vetores(testes=tmp_path, coef=tmp_path / "coef.h", physionet=False)
    assert feitos[0].read_text(encoding="utf-8") == decimacao.COEF_H.read_text(encoding="utf-8")
    novo = feitos[1].read_text(encoding="utf-8")
    versionado = vetores.TESTES / "decimacao" / "vetores" / "sensor_400hz.h"
    assert novo == versionado.read_text(encoding="utf-8"), (
        "rode: uv run python -m analise.decimacao --vetores"
    )


def test_erro_ibi():
    ecg = np.arange(10) * 0.8
    ppg = ecg + 0.25 + np.r_[0, 0.01, 0, 0, 0, 0, 0, 0, 0, 0]
    erro = decimacao.erro_ibi_ms(ppg, ecg)
    assert len(erro) == 9 and erro[0] == pytest.approx(10) and erro[1] == pytest.approx(-10)


def test_confere_placa():
    x = np.round(100_000 + 800 * np.sin(2 * np.pi * 1.1 * np.arange(4000) / 400))
    placa = decimacao.decima(x, 400)
    bruto = np.column_stack([np.arange(len(placa)), placa, placa])
    # A captura começou com a placa já rodando: o cru começa no n = 1000.
    cru = np.column_stack([np.arange(1000, 4000), x[1000:], x[1000:]])
    r = decimacao.confere_placa(cru, bruto)
    assert r["saidas"] > 600 and r["erro_max_ir"] < 1e-6
    bruto[300, 1] += 1
    assert decimacao.confere_placa(cru, bruto)["erro_max_ir"] == pytest.approx(1)
    with pytest.raises(ValueError):
        decimacao.confere_placa(np.delete(cru, 50, axis=0), bruto)
