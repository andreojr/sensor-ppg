"""Carregador do PhysioNet, sem rede: um registro pequeno escrito em WFDB."""

from pathlib import Path

import numpy as np
import pytest
import wfdb

from analise import physionet

FS = 500
DURACAO_S = 4


@pytest.fixture
def registro_falso(tmp_path: Path) -> str:
    """s0_sit: 4 s de senoide a 1,2 Hz nos dois canais, com DC, e 5 picos."""
    n = FS * DURACAO_S
    t = np.arange(n) / FS
    pulso = np.sin(2 * np.pi * 1.2 * t)
    ecg = np.round(1000 * pulso).astype(np.int64)  # ganho 10000/mV -> 0,1 mV
    vermelho = np.round(70_000 + 500 * pulso).astype(np.int64)
    ir = np.round(100_000 + 1500 * pulso).astype(np.int64)
    # Os outros canais do dataset não importam; só os três que lemos. Escrito
    # como contagem crua (d_signal), que é o que le_local() lê.
    wfdb.wrsamp(
        "s0_sit",
        fs=FS,
        units=["mV", "NU", "NU"],
        sig_name=["ecg", "pleth_1", "pleth_2"],
        d_signal=np.column_stack([ecg, vermelho, ir]),
        fmt=["32", "32", "32"],
        adc_gain=[10000, 1, 1],
        baseline=[0, 0, 0],
        write_dir=str(tmp_path),
    )
    picos = (np.array([0.2, 1.0, 1.9, 2.7, 3.5]) * FS).astype(np.int64)
    wfdb.wrann("s0_sit", "atr", sample=picos, symbol=["N"] * len(picos), write_dir=str(tmp_path))
    return "s0_sit"


def test_le_local(registro_falso: str, tmp_path: Path):
    r = physionet.le_local(registro_falso, tmp_path)
    assert r.fs_hz == FS
    assert r.duracao_s == DURACAO_S
    assert len(r.ir) == len(r.vermelho) == len(r.ecg) == FS * DURACAO_S
    # Canais no lugar certo: IR tem DC maior e pulso maior que o vermelho.
    assert r.ir.mean() > r.vermelho.mean()
    assert np.ptp(r.ir) > np.ptp(r.vermelho)
    assert list(r.picos_ecg) == [100, 500, 950, 1350, 1750]
    assert r.t_picos_ecg[1] == pytest.approx(1.0)


def test_recorta(registro_falso: str, tmp_path: Path):
    r = physionet.le_local(registro_falso, tmp_path).recorta(0.5, 3.0)
    assert r.duracao_s == 2.5
    # Só os picos dentro do trecho, relativos ao novo início.
    assert list(r.picos_ecg) == [250, 700, 1100]


def test_registros():
    nomes = physionet.registros()
    assert len(nomes) == 66
    assert nomes[0] == "s1_sit" and nomes[-1] == "s22_run"
    assert physionet.REGISTRO_PADRAO in nomes
