"""A conferência do OLED contra a serial e a gravação do log (sem placa)."""

import io
from pathlib import Path

import numpy as np
import pytest

from analise import grava_log, oled
from analise import oled_confere as oc
from analise import tela_terminal as tt

CASOS = oled.casos()
LOG_REAL = Path(__file__).resolve().parents[1] / "dados" / "oled_passo5_20261124.log"

# resultados que a tela principal e o alvo de oled.casos() mostram: BPM 72, SpO2 97, resp 16
RESUMO = oled.tela_resumo(
    [
        ("BPM PICOS", "72"),
        ("BPM FFT", "71"),
        ("SDNN", "48 MS"),
        ("RMSSD", "35 MS"),
        ("LF/HF", "--"),
        ("QUALIDADE", "82%"),
    ],
    "2/2",
    "97",
    "16",
)


def linhas_d(fb: oled.Fb, t: float) -> list[tuple[float, str]]:
    mem = fb.paginas()
    return [(t, tt.linha_d(p, mem[p * 128 : (p + 1) * 128])) for p in range(8)]


def resultados(t: float, bpm: float = 72.0) -> list[tuple[float, str]]:
    """As linhas de resultado que combinam com as telas acima, um pouco antes de t."""
    t = t - 0.1
    return [
        (t, f"t,1,1,{round(bpm * 100)}"),
        (t, f"p,10,0.5,1,833,1,{bpm}"),
        (t, "e,1,1,71.0"),
        (t, "h,10,1,48.2,35.1,60"),
        (t, "s,1,1,97.2,0.5"),
        (t, "r,1,16.0,1"),
    ]


def sessao(ciclos: int = 3, bpm: float = 72.0) -> list[tuple[float, str]]:
    """Principal 8 s, resumo 4 s, alvo 4 s, repetido. A placa manda as linhas de resultado
    uma vez por segundo (um pouco antes do quadro)."""
    telas = [(CASOS["principal"][0], 8.0), (RESUMO, 4.0), (CASOS["alvo"][0], 4.0)]
    ev: list[tuple[float, str]] = []
    t = 0.0
    for _ in range(ciclos):
        for fb, duracao in telas:
            ev += linhas_d(fb, t + 0.1)
            t += duracao
    # um último quadro igual, só pra o fim da última tela contar
    ev += linhas_d(CASOS["principal"][0], t + 0.1)
    for seg in range(int(t) + 1):
        ev += resultados(seg + 0.5, bpm)
    return sorted(ev, key=lambda e: e[0])


def conta(ev: list[tuple[float, str]]) -> oc.Relatorio:
    r = oc.confere(ev)
    assert r is not None
    return r


def test_caso_certo_bate_100_por_cento():
    r = conta(sessao())
    assert r.campos  # algo foi conferido
    for nome, c in r.campos.items():
        assert c.ok == c.total > 0, nome
    assert set(r.campos) == {
        "principal: BPM grande (t,)",
        "resumo: BPM PICOS (p,)",
        "resumo: BPM FFT (e,)",
        "resumo: SDNN (h,)",
        "resumo: RMSSD (h,)",
        "resumo: SPO2~ (s,)",
        "resumo: RESP (r,)",
        "alvo: SPO2 grande (s,)",
        "alvo: RESP grande (r,)",
    }
    assert r.passou()


def test_rodizio_reconhecido():
    r = conta(sessao())
    assert r.sequencia[:6] == ["principal", "resumo", "alvo"] * 2
    mediana = {k: v[0] for k, v in r.duracao_por_tela.items()}
    assert mediana == {"principal": 8.0, "resumo": 4.0, "alvo": 4.0}
    assert r.rodizio_ok


def test_sinal_ruim_e_tela_propria_e_o_bpm_grande_dela_e_conferido():
    ruim = CASOS["sinal_ruim"][0]

    def sessao_ruim(linha_t: str) -> list[tuple[float, str]]:
        ev = linhas_d(ruim, 0.1) + linhas_d(ruim, 10.1)
        return sorted(ev + [(s + 0.5, linha_t) for s in range(11)], key=lambda e: e[0])

    r = conta(sessao_ruim("t,1,0,0"))  # a placa não mostra BPM: a tela tem "--"
    assert r.sequencia == ["sinal_ruim"]
    assert r.campos["principal: BPM grande (t,)"].fracao == 1.0
    r = conta(sessao_ruim("t,1,1,7200"))  # a placa diz 72, mas a tela tem "--"
    assert not r.passou()


def test_rodizio_fora_do_previsto_nao_passa():
    assert not oc.rodizio_confere({"principal": [3.0, 3.0], "resumo": [4.0]})
    assert not oc.rodizio_confere({})


def test_troca_de_um_digito_na_tela_e_detectada():
    # a tela principal mostra 73 quando a placa disse 72
    ev = sessao()
    errada = oled.tela_principal("73", True, 4, CASOS["principal"][1])
    ev = [(t, s) for t, s in ev if not s.startswith("d,")]  # tira todos os quadros
    t = 0.0
    novas: list[tuple[float, str]] = []
    for fb, duracao in [(errada, 8.0), (RESUMO, 4.0), (CASOS["alvo"][0], 4.0)] * 3:
        novas += linhas_d(fb, t + 0.1)
        t += duracao
    novas += linhas_d(errada, t + 0.1)
    r = conta(sorted(ev + novas, key=lambda e: e[0]))
    assert r.campos["principal: BPM grande (t,)"].ok == 0
    assert r.campos["resumo: SDNN (h,)"].fracao == 1.0
    assert not r.passou()


@pytest.mark.parametrize(
    "tipo, trocado",
    [
        ("p,", "p,10,0.5,1,833,1,75.0"),  # BPM PICOS 75 e BPM grande
        ("e,", "e,1,1,77.0"),
        ("h,", "h,10,1,52.0,35.1,60"),
        ("s,", "s,1,1,91.0,0.5"),
        ("r,", "r,1,12.0,1"),
    ],
)
def test_troca_do_valor_de_uma_linha_de_resultado_e_detectada(tipo, trocado):
    ev = [(t, trocado if s.startswith(tipo) else s) for t, s in sessao()]
    r = conta(ev)
    assert any(c.fracao < 0.5 for c in r.campos.values())
    assert not r.passou()


def test_linha_d_estragada_e_contada():
    ev = sessao()
    ev.insert(5, (0.2, "d,3,xyz"))  # curta e sem hexadecimal
    ev.insert(9, (0.3, "d,9," + "ab" * 128))  # página 9 não existe
    ev.insert(12, (0.4, "d,1," + "AB" * 128))  # maiúscula é recusada
    r = conta(ev)
    assert r.integridade.d_estragadas == 3
    assert r.integridade.d_validas == 8 * 10  # 9 trocas de tela + o último quadro
    assert r.integridade.estragadas == 0
    assert r.passou()  # as estragadas não derrubam os quadros bons


def test_integridade_conta_saltos_perdidas_e_estragadas():
    ev = [
        (0.0, "# sensor-ppg: laco principal"),
        (0.1, "b,1,100.0,50.0"),
        (0.2, "b,2,100.0,50.0"),
        (0.3, "b,4,100.0,50.0"),  # pulou o 3
        (0.4, "b,5,100.0"),  # cortada
        (0.5, "p,1,abc,2"),  # número que não é número
        (0.6, "lixo no meio"),
        (1.0, "# laco: amostras 100 fila_max 5 fila_cheia 0 perdidas 3"),
        (1.0, "# tela: d_descartadas 4"),
    ]
    i = oc.mede_integridade(ev)
    assert i.b_linhas == 3
    assert i.b_saltos == 1
    assert i.estragadas == 3
    assert i.laco_avisos == 1
    assert i.laco_perdidas == 3
    assert i.d_descartadas == 4


def test_sem_quadros_nao_ha_o_que_conferir():
    assert oc.confere([(0.0, "b,1,1.0,1.0")]) is None


def test_classifica_as_telas_dos_casos():
    for nome, esperado in [
        ("principal", "principal"),
        ("alvo", "alvo"),
        ("sem_dedo", "sem_dedo"),
        ("sinal_ruim", "sinal_ruim"),
    ]:
        p = oc.pixels(CASOS[nome][0].paginas())
        assert oc.classifica(p) == esperado, nome
    assert oc.classifica(oc.pixels(RESUMO.paginas())) == "resumo"
    assert oc.classifica(oc.pixels(CASOS["inicio"][0].paginas())) == "outra"


def test_pixels_e_o_contrario_de_paginas():
    fb = CASOS["principal"][0]
    assert (oc.pixels(fb.paginas()) == fb.p).all()


def test_png_sai_colorido_e_com_o_tamanho_certo(tmp_path):
    ev = sessao()
    amostras = oc.amostra_quadros(oc.remonta_quadros(ev))
    tipos = [(t, oc.classifica(p)) for t, p in amostras]
    salvas = oc.salva_pngs(amostras, tipos, tmp_path, a_partir_de=0.0)
    assert salvas == ["principal", "resumo", "alvo"]

    from matplotlib.image import imread

    img = imread(tmp_path / "oled_principal.png")
    assert img.shape[:2] == (64 * oc.ESCALA_PNG, 128 * oc.ESCALA_PNG)
    px = (img[..., :3] * 255).round().astype(int)
    aceso_cima = CASOS["principal"][0].p[: tt.CORTE_AMARELO_PX] == 1
    aceso_baixo = CASOS["principal"][0].p[tt.CORTE_AMARELO_PX :] == 1
    assert aceso_cima.any() and aceso_baixo.any()
    cores = {tuple(c) for c in px.reshape(-1, 3)}
    assert cores == {(0, 0, 0), (255, 215, 0), (0, 175, 255)}
    # o pixel aceso mais acima é amarelo e o mais abaixo é azul
    e = oc.ESCALA_PNG
    y_cima, x_cima = np.argwhere(aceso_cima)[0]
    assert tuple(px[y_cima * e, x_cima * e]) == (255, 215, 0)
    y_baixo, x_baixo = np.argwhere(aceso_baixo)[0]
    assert tuple(px[(y_baixo + tt.CORTE_AMARELO_PX) * e, x_baixo * e]) == (0, 175, 255)


def test_main_devolve_codigo_de_saida(tmp_path, capsys):
    bom = tmp_path / "bom.log"
    bom.write_text("".join(f"{t:.3f}\t{s}\n" for t, s in sessao()))
    assert oc.main([str(bom), "--png", str(tmp_path / "png"), "--desencontros"]) == 0
    assert "100.0%" in capsys.readouterr().out
    assert (tmp_path / "png" / "oled_alvo.png").exists()

    ruim = tmp_path / "ruim.log"
    ruim.write_text("".join(f"{t:.3f}\t{s}\n" for t, s in sessao(bpm=99.0)))
    # o BPM da placa (99) não é o da tela (72): falha
    assert oc.main([str(ruim)]) == 1
    assert "FALHOU" in capsys.readouterr().out

    vazio = tmp_path / "vazio.log"
    vazio.write_text("0.000\t# so comentario\n")
    assert oc.main([str(vazio)]) == 1


# ---------- grava_log ----------


class SerialFalsa:
    def __init__(self, linhas: list[bytes]) -> None:
        self.linhas = list(linhas)

    def readline(self) -> bytes:
        return self.linhas.pop(0) if self.linhas else b""


def test_grava_log_poe_horario_e_ignora_vazias():
    relogio = iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 5.0, 5.0]).__next__
    fonte = SerialFalsa([b"b,1,2.0,3.0\r\n", b"\r\n", b"# laco: ok\n", "d,0,\xe9".encode("latin-1")])
    saida = io.StringIO()
    n = grava_log.grava(fonte, saida, segundos=1.0, relogio=relogio)
    linhas = saida.getvalue().splitlines()
    assert n == len(linhas) == 3
    assert linhas[0].split("\t") == ["0.200", "b,1,2.0,3.0"]
    assert linhas[1].split("\t")[1] == "# laco: ok"
    assert linhas[2].split("\t")[1].startswith("d,0,")  # byte fora do ASCII não derruba


def test_log_gravado_volta_igual_pelo_le_log(tmp_path):
    ev = sessao(ciclos=1)
    p = tmp_path / "s.log"
    p.write_text("".join(f"{t:.3f}\t{s}\n" for t, s in ev))
    lido = oc.le_log(p)
    assert len(lido) == len(ev)
    assert lido[0] == (round(ev[0][0], 3), ev[0][1])


# ---------- o log real (fora do git) ----------


def test_log_real_da_integracao_final():
    if not LOG_REAL.exists():
        pytest.skip("analise/dados/ está fora do git: sem o log real da sessão de 24/11")
    r = conta(oc.le_log(LOG_REAL))
    i = r.integridade
    assert (i.linhas, i.estragadas, i.d_estragadas) == (78534, 0, 0)
    assert (i.b_saltos, i.laco_perdidas, i.d_descartadas) == (0, 0, 10)
    assert r.rodizio_ok
    assert r.segundos_por_tela["sinal_ruim"] == 52  # o SINAL RUIM ganha do rodízio
    c = r.campos
    assert (c["principal: BPM grande (t,)"].ok, c["principal: BPM grande (t,)"].total) == (897, 905)
    assert (c["resumo: BPM PICOS (p,)"].ok, c["resumo: BPM PICOS (p,)"].total) == (328, 337)
    for nome, campo in c.items():
        if nome not in ("principal: BPM grande (t,)", "resumo: BPM PICOS (p,)"):
            assert campo.ok == campo.total, nome
    assert r.passou()
