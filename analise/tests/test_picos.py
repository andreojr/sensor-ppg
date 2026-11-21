import numpy as np

from analise import FS_HZ
from analise.picos import ATRASO_AMOSTRAS, ESPERA, Picos, detecta

# A senoide entra direto, sem o filtro: o instante na entrada é n_pico + o atraso
# que o picos desconta (PPG_ATRASO_AMOSTRAS).
A = round(ATRASO_AMOSTRAS)


def senoide(f_hz: float, segundos: float, amp: float = 1.0) -> np.ndarray:
    n = np.arange(round(segundos * FS_HZ))
    return (amp * np.sin(2 * np.pi * f_hz * n / FS_HZ)).astype(np.float32)


def test_senoide_72_bpm():
    b, bpm = detecta(senoide(1.2, 30))
    # 30 s a 1,2 Hz: 36 picos; os 2 s de aquecimento tiram 2 ou 3.
    assert 32 <= len(b) <= 36
    assert all(abs(x.rr_ms - 833.3) < 5 for x in b[1:])
    assert not b[0].rr_valido and all(x.rr_valido for x in b[1:])
    assert abs(bpm[-1] - 72.0) < 0.5


def test_instante_com_fracao():
    """O pico da senoide cai em (k + 1/4) / f; a parábola acerta bem melhor que 1 amostra."""
    b, _ = detecta(senoide(1.2, 20))
    esperado = (np.arange(30) + 0.25) / 1.2 * FS_HZ
    for x in b:
        assert 0.0 <= x.fracao < 1.0
        assert np.min(np.abs(esperado - (x.instante + A))) < 0.1


def test_sem_sinal_sem_batimento():
    assert detecta(np.zeros(1000, dtype=np.float32))[0] == []


def test_nada_antes_do_aquecimento():
    b, _ = detecta(senoide(1.2, 30))
    assert all(x.n_pico + A >= ESPERA - 1 for x in b)


def test_periodo_refratario():
    """Segundo máximo 150 ms depois do primeiro (onda dicrótica forte) é rejeitado."""
    t = np.arange(30 * FS_HZ) / FS_HZ
    x = np.zeros_like(t)
    for c in np.arange(0.5, 30, 0.8):  # 75 bpm
        x += np.exp(-(((t - c) / 0.04) ** 2)) + 0.7 * np.exp(-(((t - c - 0.15) / 0.04) ** 2))
    b, _ = detecta(x.astype(np.float32))
    assert len(b) > 30
    assert all(y.rr_ms > 300 for y in b[1:])


def test_pico_pequeno_e_rejeitado():
    """Um pulso a 5% do nível dos vizinhos não passa do limiar adaptativo."""
    x = senoide(1.0, 20)
    x[1250:1350] *= 0.05  # um ciclo pequeno no meio
    b, _ = detecta(x)
    n = np.array([y.n_pico + A for y in b])
    assert not np.any((n > 1250) & (n < 1350))


def test_batimento_perdido_invalida_rr():
    """Sem um ciclo no meio, o RR dobra: rr_valido false, e o seguinte volta a ser válido."""
    x = senoide(1.0, 30)
    x[1300:1400] = 0.0
    b, _ = detecta(x)
    longo = [i for i, y in enumerate(b) if y.rr_ms > 1500]
    assert len(longo) == 1 and not b[longo[0]].rr_valido
    assert b[longo[0] + 1].rr_valido


def test_bpm_so_depois_de_rr_suficientes():
    p = Picos()
    validos = []
    for x in senoide(1.0, 30):
        if p.processa(x) is not None:
            validos.append(p.bpm[0])
    assert not validos[0] and not validos[2] and validos[-1]


def test_reinicia_zera_o_estado():
    p = Picos()
    for x in senoide(1.2, 10):
        p.processa(x)
    p.reinicia()
    q = Picos()
    entrada = senoide(1.2, 10)
    assert [p.processa(x) for x in entrada] == [q.processa(x) for x in entrada]


def test_n_pico_segue_o_n_da_cadeia():
    entrada = senoide(1.2, 10)
    p, q = Picos(), Picos()
    a = [p.processa(x) for x in entrada]
    b = [q.processa(x, 5000 + i) for i, x in enumerate(entrada)]
    picos_a = [y for y in a if y is not None]
    picos_b = [y for y in b if y is not None]
    assert picos_a and len(picos_a) == len(picos_b)
    for ya, yb in zip(picos_a, picos_b, strict=True):
        assert yb.n_pico == ya.n_pico + 5000
        assert (yb.fracao, yb.rr_ms, yb.rr_valido) == (ya.fracao, ya.rr_ms, ya.rr_valido)


def test_nan_nao_estraga_o_envelope():
    p = Picos()
    for x in senoide(1.0, 6):
        p.processa(x)
    env = p.env
    p.processa(float("nan"))
    assert 0 < p.env < env


def test_plato_com_denominador_zero_nao_quebra():
    # y0 meio ulp abaixo de y1 == y2 = 1: o denominador da parábola zera.
    p = Picos()
    y0 = float(np.nextafter(np.float32(1), np.float32(0)))
    b = p._batimento(500, y0, 1.0, 1.0)
    assert b is not None and b.n_pico == 500 - A and b.fracao == 0.0
