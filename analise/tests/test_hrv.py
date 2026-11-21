"""Protótipo do HRV no tempo, com sequências sintéticas (sem rede)."""

import math

import numpy as np
import pytest

from analise import FS_HZ, hrv
from analise.hrv import Batimento


def sequencia(rr_ms, n0=0, fracao=0.0):
    """Batimentos a partir de uma lista de RR (o primeiro sem RR válido)."""
    bats, n = [], n0
    for k, rr in enumerate(rr_ms):
        n += round(rr / 1000 * FS_HZ)
        bats.append(Batimento(True, n, fracao, k > 0, float(rr)))
    return bats


def ultima_valida(saidas):
    validas = [s for s in saidas if s is not None and s.valido]
    assert validas, "nenhuma saída válida"
    return validas[-1]


def test_formulas_conhecidas():
    rr = np.array([800.0, 820.0, 790.0, 810.0])
    assert hrv.sdnn(rr) == pytest.approx(np.sqrt(((rr - rr.mean()) ** 2).sum() / 3))
    assert hrv.rmssd(rr) == pytest.approx(np.sqrt((20**2 + 30**2 + 20**2) / 3))


def test_alternado_da_rmssd_exata():
    # 800, 850, 800, 850...: toda diferença é 50 ms, então RMSSD = 50.
    rr = [800.0 if k % 2 else 850.0 for k in range(120)]
    s = ultima_valida(hrv.roda(sequencia(rr)))
    assert s.rmssd_ms == pytest.approx(50.0)
    assert s.sdnn_ms == pytest.approx(25.0, rel=0.02)


def test_rr_constante_da_zero():
    s = ultima_valida(hrv.roda(sequencia([1000.0] * 100)))
    assert s.sdnn_ms == pytest.approx(0.0, abs=1e-9)
    assert s.rmssd_ms == pytest.approx(0.0, abs=1e-9)


def test_janela_so_fica_valida_com_45_s():
    saidas = hrv.roda(sequencia([1000.0] * 70))
    primeira = next(k for k, s in enumerate(saidas) if s.valido)
    # Batimento k traz k RR de 1 s (o primeiro não tem RR): 45 s no k = 45.
    assert primeira == 45


def test_poucos_batimentos_nunca_valida():
    assert not any(s.valido for s in hrv.roda(sequencia([900.0] * 30)))


def test_janela_esquece_o_passado():
    # 80 batimentos muito variáveis e depois 80 constantes: no fim, só os constantes.
    rr = [700.0 if k % 2 else 1100.0 for k in range(80)] + [1000.0] * 80
    s = hrv.roda(sequencia(rr))[-1]
    assert s.valido and s.rmssd_ms == 0.0 and s.sdnn_ms == 0.0


def test_rr_invalido_quebra_a_diferenca():
    rr = [800.0, 850.0] * 60
    bats = sequencia(rr)
    # Marca um batimento perdido: o RR dele (e a diferença com o anterior) somem,
    # e a diferença seguinte também não existe (não há RR anterior aceito).
    bats[60] = bats[60]._replace(rr_valido=False)
    h = hrv.Hrv()
    for b in bats:
        s = h.processa(b)
    difs = [i.dif for i in h.itens]
    assert sum(d is None for d in difs) == 1
    assert s.rmssd_ms == pytest.approx(50.0)


@pytest.mark.parametrize("rr", [250.0, 2500.0, math.nan, math.inf])
def test_rr_fora_da_faixa_nao_entra(rr):
    bats = sequencia([1000.0] * 60)
    bats[30] = bats[30]._replace(rr_ms=rr)
    h = hrv.Hrv()
    for b in bats:
        h.processa(b)
    assert all(math.isfinite(i.rr) and 300 <= i.rr <= 2000 for i in h.itens)
    assert len(h.itens) == 58  # 60 menos o primeiro e o rejeitado


def test_batimento_invalido_e_ignorado():
    h = hrv.Hrv()
    assert h.processa(Batimento(False, 100, 0.0, True, 800.0)) is None
    assert h.ultimo_n is None and not h.itens


def test_n_voltando_reinicia():
    h = hrv.Hrv()
    for b in sequencia([800.0] * 80, n0=10_000):
        h.processa(b)
    assert h.processa(Batimento(True, 5, 0.0, True, 800.0)).valido is False
    assert len(h.itens) == 1


def test_buffer_cheio_descarta_o_mais_antigo():
    h = hrv.Hrv()
    for k in range(hrv.CAP + 50):
        h.processa(Batimento(True, 20 * k, 0.0, k > 0, 300.0))
    assert len(h.itens) == hrv.CAP
    assert h.itens[0].n == 20 * 50


def test_batimentos_de_tempos_sem_interpolar_quantiza_em_10_ms():
    t = np.array([0.1234, 0.9876, 1.8049])
    b = hrv.batimentos_de_tempos(t, interpola=False)
    assert [x.n_pico for x in b] == [12, 99, 180]
    assert not b[0].rr_valido and b[1].rr_ms == pytest.approx(870.0)
    bi = hrv.batimentos_de_tempos(t, interpola=True)
    assert bi[1].n_pico + bi[1].fracao == pytest.approx(98.76)
    assert bi[2].rr_ms == pytest.approx(817.3)


def test_casa_ppg_com_ecg():
    ecg = np.array([1.0, 2.0, 3.0])
    ppg = np.array([1.25, 1.9, 3.3, 3.4])
    casado = hrv.casa_ppg_com_ecg(ecg, ppg)
    assert casado[0] == 1.25 and np.isnan(casado[1]) and casado[2] == 3.3


def test_vetor_bordas_passa_por_todas_as_regras():
    a = hrv._arrays(hrv.batimentos_bordas())
    assert a["escreveu"].sum() == len(a["escreveu"]) - 1  # só o inválido não escreve
    v = a["saida_valido"]
    assert v.any() and not v.all()
    # Depois do reinício (k = 250) e do buraco (k = 320), volta a ser inválido.
    assert not v[250] and not v[320] and v[249] and v[319]


def test_vetor_bordas_enche_o_buffer():
    h = hrv.Hrv()
    cheio = False
    for b in hrv.batimentos_bordas():
        h.processa(b)
        cheio = cheio or len(h.itens) == hrv.CAP
    assert cheio


def test_hrv_janela_rr_alternado():
    # RR alternando 800/850 ms: RMSSD = 50 em qualquer janela; SDNN ~25.
    rr = np.array([800.0 if k % 2 else 850.0 for k in range(600)])
    t = np.concatenate([[0.0], np.cumsum(rr) / 1000])
    for janela in (60.0, 300.0):
        r = hrv.hrv_janela(t, janela, a_partir_s=300.0)
        assert len(r) > 0
        assert np.allclose(r[:, 1], 50.0)
        assert np.allclose(r[:, 0], 25.0, rtol=0.02)


def test_hrv_janela_ignora_rr_fora_da_faixa():
    rr = np.full(100, 1000.0)
    rr[50] = 2500.0  # rejeitado: sem ele e sem as diferenças vizinhas, tudo constante
    t = np.concatenate([[0.0], np.cumsum(rr) / 1000])
    r = hrv.hrv_janela(t, 60.0, a_partir_s=60.0)
    assert np.allclose(r, 0.0)


def _placa_hrv(segundos: float = 240, rr_medio: float = 0.85):
    """Batimentos e saída do HRV como a placa manda (rr_ms e HRV com 2 casas)."""
    from analise.hrv import Batimento, Hrv

    rng = np.random.default_rng(1)
    t, p, h, ant = 0.0, [], [], None
    estado = Hrv()
    while t < segundos:
        t += rr_medio + 0.04 * np.sin(2 * np.pi * 0.25 * t) + rng.normal(0, 0.01)
        n_pico, fracao = int(t * FS_HZ), round(t * FS_HZ % 1, 4)
        rr = 0.0 if ant is None else round((n_pico + fracao - ant) * 10.0, 2)
        valido_rr = ant is not None
        ant = n_pico + fracao
        p.append((n_pico, fracao, int(valido_rr), rr, 0, 0.0))
        s = estado.processa(Batimento(True, n_pico, fracao, valido_rr, rr))
        h.append((n_pico, int(s.valido), round(s.sdnn_ms, 2), round(s.rmssd_ms, 2)))
    return np.array(p), np.array(h)


def test_confere_placa_desde_o_boot_e_no_meio():
    from analise.hrv import confere_placa

    p, h = _placa_hrv()
    r = confere_placa(p, h)
    assert r["ok"] and r["desde_boot"] and r["validos"] > 100, r
    k = 40  # captura começando no meio: o Python só compara depois de uma janela
    r = confere_placa(p[k:], h[k:])
    assert r["ok"] and not r["desde_boot"] and r["batimentos"] < len(p) - k, r

    errado = h.copy()
    errado[-10, 2] += 0.2  # um SDNN errado
    assert not confere_placa(p, errado)["ok"]
    errado = h.copy()
    errado[-10, 1] = 0  # um válido que virou inválido
    assert not confere_placa(p, errado)["ok"]
