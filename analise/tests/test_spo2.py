from itertools import pairwise

import numpy as np
import pytest

from analise import FS_HZ
from analise.spo2 import DC_MIN, HOP, JANELA, R_MAX, R_MIN, Spo2, estima


def bruto(
    r_real: float,
    segundos: float = 20,
    dc_ir: float = 80000.0,
    dc_vm: float = 78000.0,
    ruido: float = 0.0,
    semente: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """IR e vermelho de um pulso de 1,2 Hz: o AC/DC do IR é 1% e o do vermelho é r_real vezes isso,
    então o R que o módulo deve achar é r_real."""
    n = np.arange(round(segundos * FS_HZ))
    pulso = np.sin(2 * np.pi * 1.2 * n / FS_HZ)
    rng = np.random.default_rng(semente)
    ir = dc_ir * (1 + 0.01 * pulso) + rng.normal(0, ruido, len(n))
    vm = dc_vm * (1 + 0.01 * r_real * pulso) + rng.normal(0, ruido, len(n))
    return ir.astype(np.float32), vm.astype(np.float32)


@pytest.mark.parametrize("r_real", [0.4, 0.5, 0.8, 1.0, 1.4])
def test_acha_o_r_e_a_curva(r_real):
    ir, vm = bruto(r_real)
    saidas = estima(ir, vm)
    assert all(s.valido for s in saidas)
    assert all(abs(s.r - r_real) < 0.01 * r_real for s in saidas)
    assert all(abs(s.spo2 - min(100.0, 110.0 - 25.0 * r_real)) < 0.5 for s in saidas)


def test_saidas_a_cada_segundo_depois_da_janela_cheia():
    ir, vm = bruto(0.5, segundos=20)
    saidas = estima(ir, vm)
    assert saidas[0].n == JANELA - 1  # a primeira, na amostra 800
    assert all(b.n - a.n == HOP for a, b in pairwise(saidas))
    assert len(saidas) == (20 * FS_HZ - JANELA) // HOP + 1


def test_sem_dedo_nao_e_valido():
    ir, vm = bruto(0.5, dc_ir=DC_MIN / 2, dc_vm=DC_MIN / 2)  # DC de quem não tem dedo
    assert not any(s.valido for s in estima(ir, vm))
    assert all(s.spo2 == 0.0 for s in estima(ir, vm))


def test_sem_pulso_nao_divide_por_zero():
    ir = np.full(2000, 80000.0, dtype=np.float32)
    saidas = estima(ir, ir)
    assert saidas and not any(s.valido for s in saidas)
    assert all(np.isfinite(s.spo2) and np.isfinite(s.r) for s in saidas)


def test_canais_trocados_ficam_fora_da_faixa():
    """R de 0,5 vira 2,0 se vermelho e IR trocam de lugar: acima do R_MAX, inválido."""
    ir, vm = bruto(0.5)
    assert all(s.valido for s in estima(ir, vm))
    assert not any(s.valido for s in estima(vm, ir))


@pytest.mark.parametrize("r_real", [0.1, R_MAX + 0.4])
def test_r_fora_da_faixa_e_invalido(r_real):
    ir, vm = bruto(r_real)
    assert not any(s.valido for s in estima(ir, vm))


def test_spo2_acima_de_100_e_limitada():
    ir, vm = bruto(R_MIN + 0.01)  # 110 - 25 * 0,21 = 104,75
    saidas = estima(ir, vm)
    assert all(s.valido and s.spo2 == 100.0 for s in saidas)


def test_aguenta_ruido():
    ir, vm = bruto(0.6, ruido=30.0, semente=3)
    saidas = estima(ir, vm)
    assert all(s.valido and abs(s.r - 0.6) < 0.06 for s in saidas)


def test_amostra_nao_finita_e_descartada():
    ir, vm = bruto(0.5)
    ir[1000], vm[1500] = np.nan, np.inf
    saidas = estima(ir, vm)
    assert saidas and all(np.isfinite(s.spo2) and np.isfinite(s.r) for s in saidas)
    assert all(s.valido for s in saidas)


def test_reinicia_zera_o_estado():
    ir, vm = bruto(0.7)
    a = Spo2()
    for x, y in zip(ir, vm, strict=True):
        a.processa(x, y)
    a.reinicia()
    b = Spo2()
    assert [a.processa(x, y) for x, y in zip(ir, vm, strict=True)] == [
        b.processa(x, y) for x, y in zip(ir, vm, strict=True)
    ]


def test_dedo_que_sai_no_meio_da_janela_nao_vira_valor_errado():
    """O degrau do DC vira AC nos dois canais, o R fica perto de 1 e daria ~85%: tem que ser inválido."""
    ir, vm = bruto(0.5, segundos=30)
    a = 15 * FS_HZ
    ir[a:], vm[a:] = 1500.0, 1500.0
    saidas = estima(ir, vm)
    com_valor = [s for s in saidas if s.valido]
    assert com_valor and all(
        abs(s.r - 0.5) < 0.01 for s in com_valor
    )  # só as janelas inteiras com dedo
    assert not any(s.valido for s in saidas if s.n >= a)  # nenhuma que já pega o dedo saindo


def test_dc_que_varia_demais_entre_os_segundos_e_invalido():
    ir, vm = bruto(0.5, segundos=30)
    ir[15 * FS_HZ :] *= 0.5  # o DC cai pela metade, mas continua bem acima do mínimo
    vm[15 * FS_HZ :] *= 0.5
    saidas = estima(ir, vm)
    assert not any(s.valido for s in saidas if 15 * FS_HZ <= s.n < 15 * FS_HZ + JANELA - HOP)
