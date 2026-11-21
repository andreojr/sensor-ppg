"""Gerador da fonte falsa, com um registro sintético (sem rede)."""

from pathlib import Path

import numpy as np
import pytest

from analise import FS_HZ, fonte_falsa, physionet

FS = 500
F_PULSO_HZ = 1.2


@pytest.fixture
def registro() -> physionet.Registro:
    """40 s de pulso a 1,2 Hz (72 bpm) com deriva lenta e DC, picos exatos."""
    t = np.arange(40 * FS) / FS
    pulso = np.sin(2 * np.pi * F_PULSO_HZ * t)
    deriva = 2000 * np.sin(2 * np.pi * 0.05 * t)
    picos = np.round(np.arange(0.1, 40, 1 / F_PULSO_HZ) * FS).astype(np.int64)
    return physionet.Registro(
        nome="sintetico",
        fs_hz=FS,
        ir=100_000 + 1500 * pulso + deriva,
        vermelho=70_000 + 500 * pulso + deriva,
        ecg=0.1 * pulso,
        picos_ecg=picos,
    )


@pytest.fixture
def fonte(registro: physionet.Registro) -> fonte_falsa.FonteFalsa:
    return fonte_falsa.gera(registro, inicio_s=5.0, duracao_s=30.0)


def test_tamanhos_e_taxas(fonte: fonte_falsa.FonteFalsa):
    assert len(fonte.bruto_ir) == len(fonte.filtrado_vermelho) == 30 * FS_HZ
    assert len(fonte.sensor_ir) == fonte_falsa.DURACAO_SENSOR_S * fonte_falsa.FS_SENSOR_HZ
    assert fonte.sensor_ir.dtype.kind == "f" and np.all(
        fonte.sensor_ir == np.round(fonte.sensor_ir)
    )


def test_bruto_mantem_dc_e_filtrado_nao(fonte: fonte_falsa.FonteFalsa):
    assert fonte.bruto_ir.mean() == pytest.approx(100_000, rel=0.01)
    assert abs(fonte.filtrado_ir.mean()) < 10
    assert abs(fonte.filtrado_ir[:50]).max() < 1.1 * 1500  # sem transiente na borda
    # O filtro tira a deriva de 0,05 Hz (2000) e deixa o pulso (1500).
    assert np.ptp(fonte.filtrado_ir) == pytest.approx(2 * 1500, rel=0.1)


def test_batimentos(fonte: fonte_falsa.FonteFalsa):
    assert fonte.rr_ms[0] == 0.0
    assert fonte.rr_ms[1:] == pytest.approx(1000 / F_PULSO_HZ, abs=2.1)  # grade de 2 ms a 500 Hz
    # Primeiro pico depois de 5 s: o de 5,1 s -> n = 10 a 100 Hz.
    assert fonte.n_pico[0] == 10
    assert fonte.n_pico[-1] < 30 * FS_HZ


def test_escreve_vetores(fonte: fonte_falsa.FonteFalsa, tmp_path: Path):
    arquivos = fonte_falsa.escreve_vetores(fonte, tmp_path)
    assert {a.name for a in arquivos} == {
        "sensor_400hz.txt",
        "bruto_100hz.txt",
        "filtrado_100hz.txt",
        "batimentos.txt",
    }
    dados = np.loadtxt(tmp_path / "bruto_100hz.txt", comments="#", skiprows=2)
    assert dados.shape == (30 * FS_HZ, 3)
    assert dados[:, 0].tolist() == list(range(30 * FS_HZ))
    assert dados[:, 1] == pytest.approx(fonte.bruto_ir, abs=1e-3)


def test_escreve_c(fonte: fonte_falsa.FonteFalsa, tmp_path: Path):
    h, c = fonte_falsa.escreve_c(fonte, tmp_path)
    texto_h = h.read_text(encoding="utf-8")
    assert f"#define FONTE_N {30 * FS_HZ}u" in texto_h
    assert f"#define FONTE_SENSOR_FS_HZ {fonte_falsa.FS_SENSOR_HZ}u" in texto_h
    texto_c = c.read_text(encoding="utf-8")
    assert texto_c.count("const float") == 5 and texto_c.count("const uint32_t") == 3
    assert f"fonte_batimento_n[{len(fonte.n_pico)}]" in texto_c
