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


def _placa_hrv(segundos: float = 240, rr_medio: float = 0.85, ruim: tuple = ()):
    """Batimentos e saída do HRV como a placa manda (rr_ms e HRV com 2 casas).

    ruim: trechos (início_s, fim_s) em que a qualidade disse não usável: a placa deixa
    o RR de fora do HRV e manda rr_usado = 0 na linha h,."""
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
        usado = not any(a <= t < b for a, b in ruim)
        p.append((n_pico, fracao, int(valido_rr), rr, 0, 0.0))
        s = estado.processa(Batimento(True, n_pico, fracao, valido_rr and usado, rr))
        h.append((n_pico, int(s.valido), round(s.sdnn_ms, 2), round(s.rmssd_ms, 2), int(usado)))
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


def test_confere_par_cortado_nas_pontas_e_sem_validos():
    from analise.hrv import confere_placa

    p, h = _placa_hrv()
    assert confere_placa(p, h[:-1])["ok"]  # parou entre o último p, e o h,
    assert confere_placa(p[11:], h[10:])["ok"]  # começou entre um p, e o h,
    assert not confere_placa(p[:30], h[:30])["ok"]  # 30 batimentos: nenhum HRV válido


def test_confere_placa_com_rr_fora_por_qualidade():
    """A placa deixa de fora o RR dos trechos não usáveis; o Python segue o rr_usado."""
    from analise.hrv import confere_placa

    p, h = _placa_hrv(ruim=((100, 110), (150, 152)))
    assert (h[:, 4] == 0).sum() > 5
    r = confere_placa(p, h)
    assert r["ok"] and r["validos"] > 50, r
    assert not confere_placa(p, h[:, :4])["ok"]  # ignorando o rr_usado, não bate
    assert confere_placa(*_placa_hrv()[:1], _placa_hrv()[1][:, :4])["ok"]  # firmware antigo


def _captura_com_qualidade(segundos: int = 120, so_antes: bool = False, ruido: bool = True):
    """Captura desde o boot como a placa mandaria, com a qualidade escolhendo o RR:
    bruto, filtrado (2 casas) e o _hrv.csv com rr_usado. Ruído de 10 s no meio.
    so_antes: uma placa com erro, que ignora o julgamento de depois."""
    from analise import filtro
    from analise.hrv import Batimento, Hrv
    from analise.picos import Picos
    from analise.qualidade import Fila, Qualidade, batimento_usavel

    rng = np.random.default_rng(5)
    t = np.arange(segundos * FS_HZ) / FS_HZ
    ac = np.sin(2 * np.pi * 1.15 * t) + 0.3 * np.sin(4 * np.pi * 1.15 * t + 1)
    ir = 100_000.0 * (1 + 0.008 / 2.6 * ac) + rng.normal(0, 2, len(t))
    if ruido:
        ir[60 * FS_HZ:70 * FS_HZ] += rng.normal(0, 600, 10 * FS_HZ)
    vm = 1.05 * ir
    n = np.arange(len(t))
    fi, fv = np.round(filtro.filtra(ir), 2), np.round(filtro.filtra(vm), 2)
    q, p, fila, h = Qualidade(), Picos(), Fila(), Hrv()
    julg, linhas = None, []

    def hrv(b, entra):
        s = h.processa(Batimento(True, b.n_pico, b.fracao, entra, b.rr_ms))
        linhas.append((b.n_pico, int(s.valido), round(s.sdnn_ms, 2), round(s.rmssd_ms, 2), int(entra)))

    for k in n.tolist():
        b = p.processa(float(fi[k]), k)
        if b is not None:
            velho = fila.poe(b, julg is not None and batimento_usavel(julg[1], True, julg[0], k))
            if velho is not None:
                hrv(velho, False)
        s = q.processa(k, float(ir[k]), float(vm[k]))
        if s is not None:
            julg = (k, s.usavel)
            for bb, e in fila.tira(True if so_antes else s.usavel):
                hrv(bb, e)
    return (np.column_stack([n, ir, vm]), np.column_stack([n, fi, fv]), np.array(linhas, float))


def test_confere_rr_usado_refaz_a_decisao_da_placa():
    from analise.hrv import confere_rr_usado

    bruto, filtrado, h = _captura_com_qualidade()
    r = confere_rr_usado(bruto, filtrado, h)
    assert r["ok"] and r["barrados"] > 3 and r["perto_de_buraco"] == 0, r

    errado = h.copy()
    k = int(np.flatnonzero((errado[:, 4] == 1) & (errado[:, 0] < 100 * FS_HZ))[-1])
    errado[k, 4] = 0  # a placa teria deixado um RR bom de fora
    assert not confere_rr_usado(bruto, filtrado, errado)["ok"]

    antigo = h.copy()
    antigo[:, 4] = -1  # firmware sem a coluna: não confere
    assert confere_rr_usado(bruto, filtrado, antigo) is None


def test_confere_rr_usado_ignora_o_trecho_de_uma_linha_perdida():
    """Uma linha perdida na serial faz a qualidade do Python recomeçar; a da placa não."""
    from analise.hrv import confere_rr_usado

    bruto, filtrado, h = _captura_com_qualidade()
    buraco = 30 * FS_HZ
    sem = np.ones(len(bruto), bool)
    sem[buraco:buraco + 2] = False
    r = confere_rr_usado(bruto[sem], filtrado[sem], h)
    assert r["ok"] and r["perto_de_buraco"] > 2, r


def test_confere_nao_compara_captura_que_nao_comeca_no_boot():
    from analise.hrv import confere_rr_usado

    bruto, filtrado, h = _captura_com_qualidade()
    r = confere_rr_usado(bruto[50:], filtrado[50:], h)
    assert not r["ok"] and r["inicio"] == 50 and "comparados" not in r


def test_confere_placa_retoma_depois_de_uma_linha_perdida():
    """Uma p, ou h, perdida no meio (ou a primeira): pula uma janela e volta a comparar."""
    from analise.hrv import confere_placa

    p, h = _placa_hrv()
    inteiro = confere_placa(p, h)
    assert inteiro["linhas_perdidas"] == 0 and inteiro["pulados"] == 0
    for pp, hh in ((np.delete(p, 150, axis=0), h), (p, np.delete(h, 150, axis=0)),
                   (p[1:], h), (p, h[1:])):
        r = confere_placa(pp, hh)
        # A primeira p, perdida não aparece como perda: a captura vira "no meio".
        assert r["ok"] and r["linhas_perdidas"] <= 1, r
        assert 0 < r["batimentos"] < inteiro["batimentos"], r
    errado = h.copy()
    errado[-5, 2] += 0.2  # um SDNN errado depois da linha perdida ainda é pego
    assert not confere_placa(np.delete(p, 150, axis=0), errado)["ok"]


def test_confere_rr_usado_tolera_perder_as_primeiras_linhas():
    from analise.hrv import confere_rr_usado

    bruto, filtrado, h = _captura_com_qualidade()
    r = confere_rr_usado(bruto[3:], filtrado, h)
    assert r["ok"] and r["inicio"] == 3, r


def test_confere_rr_usado_exige_os_casos_que_distinguem_a_regra():
    """Barrado nos dois julgamentos (o começo da captura) não distingue nada: o aceite
    pede o sinal piorando e melhorando perto de um pulso, e pega a placa que só olha o
    julgamento de antes."""
    from analise.hrv import confere_rr_usado

    bruto, filtrado, h = _captura_com_qualidade()
    r = confere_rr_usado(bruto, filtrado, h)
    assert r["ok"] and r["sai"] > 0 and r["volta"] > 0, r

    so_antes = _captura_com_qualidade(so_antes=True)
    assert not confere_rr_usado(*so_antes)["ok"]

    limpa = _captura_com_qualidade(40, ruido=False)  # só o começo: barrados, mas nenhum "sai"
    r = confere_rr_usado(*limpa)
    assert r["barrados"] > 0 and r["sai"] == 0, r
