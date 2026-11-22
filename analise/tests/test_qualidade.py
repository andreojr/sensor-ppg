"""Protótipo da qualidade: regras, defeitos fabricados, constantes e vetores em dia."""

import re
from dataclasses import fields
from pathlib import Path

import numpy as np
import pytest

from analise import FS_HZ, qualidade, vetores

RAIZ = Path(__file__).resolve().parents[2]
QUALIDADE_H = RAIZ / "Core/Inc/pds/qualidade/qualidade.h"


def pulso(segundos: float, dc: float = 100_000.0, pi: float = 0.008, bpm: float = 72.0,
          semente: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """PPG sintético: DC + pulso com harmônica (onda dicrótica) + respiração + ruído de 2."""
    rng = np.random.default_rng(semente)
    t = np.arange(int(segundos * FS_HZ)) / FS_HZ
    f = bpm / 60
    ac = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t + 1)
    resp = 0.2 * np.sin(2 * np.pi * 0.25 * t)
    x = dc * (1 + pi / 2.6 * ac + pi * resp / 2.6)
    return x + rng.normal(0, 2, len(t)), 1.05 * x + rng.normal(0, 2, len(t))


def test_limpo_usavel_depois_de_tres_janelas():
    saidas = qualidade.roda(*pulso(10))
    assert [s.n for s in saidas] == list(range(2 * FS_HZ - 1, 10 * FS_HZ, FS_HZ))
    assert all(s.valido and s.dedo_presente and s.motivo == 0 for s in saidas)
    assert [s.indice for s in saidas[:4]] == pytest.approx([1 / 3, 2 / 3, 1, 1])
    assert [s.usavel for s in saidas[:4]] == [False, False, True, True]


@pytest.mark.parametrize("tipo, forca, bit", [
    ("ausente", 1, qualidade.SEM_DEDO_BIT),
    ("sem_pulso", 1, qualidade.PULSO_FRACO_BIT),
    ("saturado", 1, qualidade.SATURADO_BIT),
    ("ruido", 1, qualidade.RUIDO_BIT),
    ("movimento", 4, qualidade.MOVIMENTO_BIT),
])
def test_defeito_depois_do_limpo(tipo, forca, bit):
    ir, vm = pulso(20)
    rng = np.random.default_rng(3)
    d_ir, d_vm = qualidade.degrada(tipo, ir[10 * FS_HZ:], vm[10 * FS_HZ:], rng, forca)
    saidas = qualidade.roda(np.r_[ir[:10 * FS_HZ], d_ir], np.r_[vm[:10 * FS_HZ], d_vm])
    antes = [s for s in saidas if s.n < 10 * FS_HZ]
    dentro = [s for s in saidas if s.n >= 12 * FS_HZ - 1]
    assert antes[-1].usavel
    assert not any(s.usavel for s in dentro)
    assert sum(bool(s.motivo & bit) for s in dentro) >= 0.8 * len(dentro)


def test_nivel_do_sensor_mantem_pi():
    ir, vm = pulso(10)
    a, b = qualidade.no_sensor(ir, vm)
    assert a.mean() == pytest.approx(130_000) and b.mean() == pytest.approx(137_000)
    pa = [s.pi for s in qualidade.roda(ir, vm)]
    pb = [s.pi for s in qualidade.roda(a, b)]
    assert pb == pytest.approx(pa, rel=1e-9)


def test_reinicia_com_n_pulando_e_nan():
    ir, vm = pulso(6)
    n = np.arange(len(ir))
    n[150:] += 37
    assert qualidade.roda(ir, vm, n)[0].n == 150 + 37 + 2 * FS_HZ - 1
    q = qualidade.Qualidade()
    saidas = [q.processa(k, float("nan") if k == 120 else a, b)
              for k, (a, b) in enumerate(zip(ir, vm))]
    primeira = next(k for k, s in enumerate(saidas) if s is not None)
    assert primeira == 121 + 2 * FS_HZ - 1
    q = qualidade.Qualidade()  # NaN só no vermelho também recomeça
    saidas = [q.processa(k, a, float("nan") if k == 120 else b)
              for k, (a, b) in enumerate(zip(ir, vm))]
    primeira = next(k for k, s in enumerate(saidas) if s is not None)
    assert primeira == 121 + 2 * FS_HZ - 1


def test_referencia_esquecida_e_reaprendida():
    ir, vm = pulso(30, pi=0.004)
    grande, grande_vm = pulso(30, pi=0.012, semente=1)
    ir[10 * FS_HZ:], vm[10 * FS_HZ:] = grande[10 * FS_HZ:], grande_vm[10 * FS_HZ:]
    saidas = qualidade.roda(ir, vm)
    logo_depois = [s for s in saidas if 12 * FS_HZ <= s.n < 20 * FS_HZ]
    assert all(s.motivo & qualidade.MOVIMENTO_BIT for s in logo_depois)
    assert saidas[-1].usavel


def test_constantes_iguais_ao_c():
    texto = QUALIDADE_H.read_text(encoding="utf-8")
    define = dict(re.findall(r"#define QUALIDADE_(\w+) ([\d.]+)f?u?\b", texto))
    lim = qualidade.LIMIARES
    for campo in fields(lim):
        assert float(define[campo.name.upper()]) == pytest.approx(getattr(lim, campo.name)), campo
    bits = {"SEM_DEDO": "SEM_DEDO_BIT", "SATURADO": "SATURADO_BIT",
            "PULSO_FRACO": "PULSO_FRACO_BIT", "MOVIMENTO": "MOVIMENTO_BIT", "RUIDO": "RUIDO_BIT"}
    for c, py in bits.items():
        assert int(define[c]) == getattr(qualidade, py)


def _le_vetor(caminho: Path) -> dict[str, np.ndarray]:
    texto = caminho.read_text(encoding="utf-8")
    caso = caminho.stem
    arrays = {}
    for nome, corpo in re.findall(rf"static const \w+ {caso}_(\w+)\[\d+\] = \{{(.*?)\}};",
                                  texto, re.DOTALL):
        arrays[nome] = np.array([float(v.rstrip("f")) for v in corpo.split(",") if v.strip()])
    return arrays


@pytest.mark.parametrize("caso", ["physionet", "bordas"])
def test_vetor_em_dia(caso):
    """O Python de hoje, na entrada gravada no vetor, dá a saída gravada (sem PhysioNet)."""
    a = _le_vetor(vetores.TESTES / "qualidade" / "vetores" / f"{caso}.h")
    saidas = qualidade.roda(a["ir"].astype(np.float32), a["vermelho"].astype(np.float32),
                            a["n"].astype(np.int64))
    esperado = qualidade._arrays(saidas, {})
    for nome, valores in esperado.items():
        assert np.allclose(a[nome], np.asarray(valores, dtype=np.float32), rtol=1e-6), nome
