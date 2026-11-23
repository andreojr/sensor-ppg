"""Comparação picos × FFT: as contas, sem baixar nada (sinal sintético com ECG conhecido)."""

import numpy as np

from analise import FS_HZ, filtro
from analise.comparacao_bpm import bpm_picos_em, compara_sinal, estabilidade, tabela

BPM = 75.0


def pulso(duracao_s: float = 60.0, bpm: float = BPM) -> tuple[np.ndarray, np.ndarray]:
    """Trem de pulsos a bpm constante, filtrado como na cadeia, e os instantes do 'ECG'."""
    t_ecg = np.arange(1.0, duracao_s, 60.0 / bpm)
    n = np.arange(round(duracao_s * FS_HZ))
    x = np.zeros(len(n))
    for t in t_ecg:
        x += np.exp(-0.5 * ((n / FS_HZ - t - 0.2) / 0.06) ** 2)
    return filtro.filtra(x - x.mean()), t_ecg


def test_estabilidade_de_serie_constante_e_zero():
    assert estabilidade(np.full(10, 70.0)) == 0.0


def test_estabilidade_ignora_buracos():
    assert estabilidade(np.array([70.0, np.nan, 72.0, 73.0])) == 1.0
    assert np.isnan(estabilidade(np.array([np.nan, 70.0, np.nan])))


def test_picos_segura_o_bpm_entre_batimentos():
    x, _ = pulso()
    n = np.arange(len(x))
    bpm = bpm_picos_em(x, n)
    assert np.isnan(bpm[0])  # nada antes do primeiro batimento
    depois = bpm[-1]
    assert abs(depois - BPM) < 1.0
    # segurar = degraus: bem menos valores distintos que amostras
    assert len(np.unique(bpm[~np.isnan(bpm)])) < len(x) / 20


def test_os_dois_acham_o_bpm_do_sinal_limpo():
    x, t_ecg = pulso()
    c = compara_sinal("sintetico", x, t_ecg)
    assert c.m_espectral.erro_mediana < 1.5
    assert c.m_picos.erro_mediana < 1.5
    assert c.m_espectral.validos == 1.0
    assert 0.0 <= c.m_picos.validos <= 1.0
    assert len(c.t) == len(c.picos) == len(c.espectral) == len(c.ecg)


def test_tabela_tem_as_colunas_e_a_linha_de_cada_atividade():
    x, t_ecg = pulso()
    c = compara_sinal("s1_sit", x, t_ecg)
    texto = tabela([c])
    assert "Estabilidade (bpm)" in texto
    assert "| s1_sit |" in texto
    assert "| sit |" in texto and "| todos |" in texto
