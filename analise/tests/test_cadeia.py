"""A cadeia de referência (analise.cadeia) é a soma dos módulos, na ordem da placa."""

import re
from pathlib import Path

import numpy as np
import pytest

from analise import cadeia, espectral, filtro, picos, qualidade, respiracao, vetores

FS = 100


def sinal(dur_s: float = 90.0, bpm: float = 72.0) -> tuple[np.ndarray, np.ndarray]:
    """PPG sintético no nível do sensor: pulso gaussiano e respiração a 15 rpm (com
    entalhe dicrótico o picos vê batimento duplo e o BPM nunca fica válido)."""
    t = np.arange(round(dur_s * FS)) / FS
    fase = (t * bpm / 60.0) % 1.0
    pulso = np.exp(-(((fase - 0.2) / 0.07) ** 2))
    resp = 1.0 + 0.003 * np.sin(2 * np.pi * 0.25 * t)
    ir = 130_000.0 * resp + 600.0 * pulso
    vm = 137_000.0 * resp + 500.0 * pulso
    return ir.astype(np.float32), vm.astype(np.float32)


@pytest.fixture(scope="module")
def caso():
    ir, vm = sinal()
    return ir, vm, cadeia.roda(ir, vm)


def test_batimentos_iguais_ao_picos(caso):
    ir, _, s = caso
    esperados, _ = picos.detecta(filtro.filtra(ir))
    assert len(s.batimentos) > 50
    assert [b.n_pico for b in s.batimentos] == [b.n_pico for b in esperados]
    assert [b.rr_valido for b in s.batimentos] == [b.rr_valido for b in esperados]


def test_hrv_usa_a_fila(caso):
    ir, vm, s = caso
    n = np.arange(len(ir))
    bruto = np.column_stack([n, ir, vm])
    filtrado = np.column_stack([n, filtro.filtra(ir), filtro.filtra(vm)])
    entrou = qualidade.rr_entrou_no_hrv(bruto, filtrado)
    assert len(s.hrv) > 50
    assert {h.n_pico: h.rr_usado for h in s.hrv} == entrou


def test_tela_segue_a_regra(caso):
    ir, vm, s = caso
    julgamentos = qualidade.roda(ir, vm)
    assert [t.n for t in s.tela] == [j.n for j in julgamentos]
    assert any(t.mostra for t in s.tela)
    # O último batimento que já tinha SAÍDO do picos em cada n (sai depois do n_pico).
    p, ultimo, ate = picos.Picos(), {}, None
    for n, x in enumerate(filtro.filtra(ir)):
        if p.processa(float(x), n) is not None:
            ate = (p.ultimo.n_pico, *p.bpm)
        ultimo[n] = ate
    for t, j in zip(s.tela, julgamentos, strict=True):
        u = ultimo[t.n]
        esperado = qualidade.bpm_confiavel(j.usavel, u is not None and u[1], u is not None, t.n,
                                           u[0] if u else 0)
        assert t.mostra == esperado, t.n
        assert t.bpm == (u[2] if t.mostra else 0.0)


def test_espectral_e_respiracao_iguais_aos_modulos(caso):
    ir, _, s = caso
    esperado = espectral.estima(filtro.filtra(ir))
    assert [(e.n, e.valido, e.bpm) for e in s.espectral] == [(e.n, e.valido, e.bpm) for e in esperado]
    resp = respiracao.estima(ir)
    assert [(r.n, r.valido, r.rpm) for r in s.respiracao] == [
        (int(i), bool(v), float(rpm)) for i, v, rpm, _ in resp]


def test_vetor_em_dia():
    """O Python de hoje, na entrada gravada no vetor, dá a saída gravada (sem PhysioNet)."""
    caminho = vetores.TESTES / "cadeia" / "vetores" / "physionet.h"
    a = _le_vetor(caminho)
    s = cadeia.roda(a["ir"].astype(np.float32), a["vermelho"].astype(np.float32))
    for nome, valores in cadeia.arrays(s).items():
        assert np.allclose(a[nome], np.asarray(valores, dtype=np.float32), rtol=1e-6), nome


def _le_vetor(caminho: Path) -> dict[str, np.ndarray]:
    texto = caminho.read_text(encoding="utf-8")
    caso = caminho.stem
    arrays = {}
    for nome, corpo in re.findall(rf"static const \w+ {caso}_(\w+)\[\d+\] = \{{(.*?)\}};",
                                  texto, re.DOTALL):
        arrays[nome] = np.array([float(v.rstrip("f")) for v in corpo.split(",") if v.strip()])
    return arrays
