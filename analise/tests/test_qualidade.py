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
    """As 3 primeiras janelas ainda não têm 4 s de ritmo; usável na 6ª saída (7º s)."""
    saidas = qualidade.roda(*pulso(10))
    assert [s.n for s in saidas] == list(range(2 * FS_HZ - 1, 10 * FS_HZ, FS_HZ))
    assert all(s.valido and s.dedo_presente for s in saidas)
    assert [s.motivo for s in saidas[:4]] == [qualidade.SEM_RITMO_BIT] * 3 + [0]
    assert all(s.motivo == 0 for s in saidas[3:])
    assert [s.indice for s in saidas[:7]] == pytest.approx([0, 0, 0, 1 / 3, 2 / 3, 1, 1])
    assert [s.usavel for s in saidas[:7]] == [False] * 5 + [True, True]


def faixa_do_pulso(segundos: float, dc: float = 100_000.0, pi: float = 0.008,
                   semente: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Ruído filtrado de 0,7 a 3,5 Hz com a altura do pulso de pulso(): parece pulso, sem ritmo."""
    from scipy.signal import butter, sosfiltfilt

    rng = np.random.default_rng(semente)
    m = int(segundos * FS_HZ)
    z = sosfiltfilt(butter(4, [0.7, 3.5], "bandpass", fs=FS_HZ, output="sos"), rng.normal(size=m))
    ref, _ = pulso(segundos)
    x = dc + z * ((ref - ref.mean()).std() / z.std())
    return x + rng.normal(0, 2, m), 1.05 * x + rng.normal(0, 2, m)


def test_ritmo_de_pulso_e_de_ruido():
    t = np.arange(qualidade.RITMO_N) / 25
    assert qualidade.ritmo_de(np.sin(2 * np.pi * 1.2 * t)) > 0.75  # (N - k) / N no atraso de 1 período
    assert qualidade.ritmo_de(np.zeros(qualidade.RITMO_N)) == 0.0
    rng = np.random.default_rng(1)
    assert qualidade.ritmo_de(rng.normal(size=qualidade.RITMO_N)) < 0.5


@pytest.mark.parametrize("bpm", [42.0, 72.0, 145.0])
def test_pulso_limpo_tem_ritmo(bpm):
    saidas = qualidade.roda(*pulso(12, bpm=bpm))
    assert all(s.ritmo >= 0.5 for s in saidas[3:])
    assert saidas[-1].usavel


def test_sem_ritmo_antes_de_quatro_segundos():
    saidas = qualidade.roda(*pulso(10))
    assert all(s.motivo & qualidade.SEM_RITMO_BIT and s.ritmo == 0.0 for s in saidas[:3])
    assert [s.usavel for s in saidas[:6]] == [False] * 5 + [True]


def test_ruido_na_faixa_do_pulso_e_barrado():
    saidas = qualidade.roda(*faixa_do_pulso(30, semente=4))
    depois = saidas[4:]
    # com o limiar 0,45, uma janela ou outra passa no ritmo; 3 seguidas, não
    assert sum(bool(s.motivo & qualidade.SEM_RITMO_BIT) for s in depois) >= 0.8 * len(depois)
    assert not any(s.usavel for s in saidas)


def test_movimento_ritmico_continua_barrado():
    """Bater o dedo a 1 Hz: o ritmo sobe, mas a razão barra enquanto a referência vale.

    Limitação conhecida: depois de RUINS_ESQUECE janelas ruins a referência é esquecida
    e uma batida regular com altura de pulso passa a ser aceita (sem acelerômetro, um
    artefato periódico na faixa do pulso não se distingue de pulso).
    """
    ir, vm = pulso(30)
    t = np.arange(len(ir)) / FS_HZ
    batida = np.where(np.sin(2 * np.pi * t) > 0, np.sin(2 * np.pi * t), 0.0)
    altura = ir[:FS_HZ * 5].max() - ir[:FS_HZ * 5].min()
    ir, vm = ir.copy(), vm.copy()
    ir[10 * FS_HZ:] += 4 * altura * batida[10 * FS_HZ:]
    vm[10 * FS_HZ:] += 4 * 1.05 * altura * batida[10 * FS_HZ:]
    saidas = qualidade.roda(ir, vm)
    lembra = (10 + qualidade.LIMIARES.ruins_esquece) * FS_HZ
    dentro = [s for s in saidas if 12 * FS_HZ - 1 <= s.n < lembra]
    assert dentro and not any(s.usavel for s in dentro)
    assert all(s.ritmo >= 0.5 for s in dentro[2:])  # o ritmo sozinho não barraria


def test_reinicio_apaga_o_ritmo():
    ir, vm = pulso(20)
    n = np.arange(len(ir))
    n[1000:] += 50
    depois = [s for s in qualidade.roda(ir, vm, n) if s.n >= 1050]
    assert all(s.motivo & qualidade.SEM_RITMO_BIT for s in depois[:3])
    assert depois[5].usavel


@pytest.mark.parametrize("tipo, forca, bit", [
    ("ausente", 1, qualidade.SEM_DEDO_BIT),
    ("sem_pulso", 1, qualidade.PULSO_FRACO_BIT),
    ("saturado", 1, qualidade.SATURADO_BIT),
    ("ruido", 1, qualidade.RUIDO_BIT),
    ("movimento", 4, qualidade.MOVIMENTO_BIT),
    ("sem_ritmo", 1, qualidade.SEM_RITMO_BIT),
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
            "PULSO_FRACO": "PULSO_FRACO_BIT", "MOVIMENTO": "MOVIMENTO_BIT", "RUIDO": "RUIDO_BIT",
            "SEM_RITMO": "SEM_RITMO_BIT", "RITMO_DECIMA": "RITMO_DECIMA", "RITMO_N": "RITMO_N",
            "RITMO_ATRASO_MIN": "RITMO_ATRASO_MIN", "RITMO_ATRASO_MAX": "RITMO_ATRASO_MAX"}
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


def test_filtro_do_ritmo_e_o_butterworth():
    """O ritmo usa um passa-faixa 0,5-4 Hz (Butterworth 2ª ordem, passa-altas primeiro)."""
    from scipy.signal import butter, sosfilt

    sos = butter(2, [0.5, 4], "bandpass", fs=FS_HZ, output="sos")
    assert np.allclose(np.array(qualidade.RITMO_SOS), sos[::-1], rtol=1e-12, atol=1e-15)
    ir, vm = pulso(5)
    q = qualidade.Qualidade()
    for k, (a, b) in enumerate(zip(ir, vm)):
        q.processa(k, a, b)
    y = sosfilt(np.ascontiguousarray(sos[::-1]), ir - ir[0])
    esperado = y[: len(y) // 4 * 4].reshape(-1, 4).mean(1)[-qualidade.RITMO_N:]
    anel = np.array(q.anel[q.pos:] + q.anel[: q.pos])
    assert np.allclose(anel, esperado, rtol=1e-9, atol=1e-9)


@pytest.mark.parametrize("usavel, valido, tem, n, n_pico, mostra", [
    (True, True, True, 1000, 900, True),     # os dois concordam, batimento recente
    (True, False, True, 1000, 900, False),   # picos sem ritmo regular
    (False, True, True, 1000, 900, False),   # qualidade diz que não dá
    (False, False, True, 1000, 900, False),
    (True, True, False, 1000, 0, False),     # nenhum batimento ainda
    (True, True, True, 1000, 700, True),     # idade = BATIMENTO_VALE: ainda vale
    (True, True, True, 1001, 700, False),    # idade = BATIMENTO_VALE + 1: velho
    (True, True, True, 1000, 1080, False),   # n_pico > n: anomalia (n reiniciado), bloqueia
    (True, True, True, 50, 2**32 - 50, True),  # o n deu a volta no uint32: idade 100
])
def test_bpm_confiavel(usavel, valido, tem, n, n_pico, mostra):
    assert qualidade.BATIMENTO_VALE == 3 * FS_HZ
    assert qualidade.bpm_confiavel(usavel, valido, tem, n, n_pico) is mostra
