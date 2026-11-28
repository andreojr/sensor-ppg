"""A conferência do OLED contra a serial e a gravação do log (sem placa)."""

import io
from pathlib import Path

import numpy as np
import pytest
from matplotlib.image import imread

from analise import grava_log, oled
from analise import oled_confere as oc
from analise import tela_terminal as tt

CASOS = oled.casos()
RAIZ = Path(__file__).resolve().parents[2]
LOG_REAL = RAIZ / "analise" / "dados" / "oled_passo5_20261124.log"
ASSETS = RAIZ / "docs" / "src" / "assets"
CAMPO_BPM = "principal: BPM grande (t,)"


def resumo(picos="72", fft="71", sdnn="48 MS", rmssd="35 MS", lf="6.0", spo2="97", resp="16"):
    return oled.tela_resumo(
        [
            ("BPM PICOS", picos),
            ("BPM FFT", fft),
            ("SDNN", sdnn),
            ("RMSSD", rmssd),
            ("LF/HF", lf),
            ("QUALIDADE", "82%"),
        ],
        "2/3",
        spo2,
        resp,
    )


def alvo(spo2="97", resp="16"):
    return oled.tela_alvo(spo2, resp, "72", "82%", CASOS["alvo"][1])


def linhas_d(fb: oled.Fb, t: float) -> list[tuple[float, str]]:
    mem = fb.paginas()
    return [(t, tt.linha_d(p, mem[p * 128 : (p + 1) * 128])) for p in range(8)]


RESULTADOS_BONS = {
    "t": "t,1,1,7200",
    "p": "p,10,0.5,1,833,1,72.0",
    "e": "e,1,1,71.0",
    "h": "h,10,1,48.2,35.1,60",
    "l": "l,1,1,6.044",
    "s": "s,1,1,97.2,0.5",
    "r": "r,1,16.0,1",
}


def sessao(
    ciclos: int = 3,
    duracoes: tuple[float, float, float] = (8.0, 4.0, 4.0),
    telas=None,
    linhas: dict[str, str] | None = None,
    avisos: bool = True,
) -> list[tuple[float, str]]:
    """Principal, resumo e alvo repetidos. A placa manda as linhas de resultado uma vez por
    segundo, um pouco depois do começo do segundo. `linhas` troca o texto de um tipo."""
    r = {**RESULTADOS_BONS, **(linhas or {})}
    telas = telas or [CASOS["principal"][0], resumo(), alvo()]
    ev: list[tuple[float, str]] = []
    t = 0.0
    for _ in range(ciclos):
        for fb, duracao in zip(telas, duracoes, strict=True):
            ev += linhas_d(fb, t + 0.1)
            t += duracao
    ev += linhas_d(telas[0], t + 0.1)  # um quadro a mais, só pra o fim da última tela contar
    for seg in range(int(t) + 1):
        ev += [(seg + 0.5, s) for s in r.values()]
        if avisos:  # os avisos de 1 s da placa
            ev.append((seg + 0.6, "# laco: amostras 100 fila_max 5 fila_cheia 0 perdidas 0"))
            ev.append((seg + 0.6, "# tela: d_descartadas 0"))
    return sorted(ev, key=lambda e: e[0])


def conta(ev: list[tuple[float, str]]) -> oc.Relatorio:
    r = oc.confere(ev)
    assert r is not None
    return r


def escreve(pasta: Path, ev: list[tuple[float, str]], nome: str = "s.log") -> Path:
    p = pasta / nome
    p.write_text("".join(f"{t:.3f}\t{s}\n" for t, s in ev))
    return p


def sai_com(pasta: Path, ev, capsys, *args: str) -> tuple[int, str]:
    capsys.readouterr()
    codigo = oc.main([str(escreve(pasta, ev)), *args])
    return codigo, capsys.readouterr().out


# ---------- o caso certo ----------


def test_caso_certo_bate_100_por_cento_e_passa():
    r = conta(sessao())
    assert set(r.campos) == set(oc.CAMPOS_ESPERADOS)
    for nome, c in r.campos.items():
        assert c.ok == c.total > 0, nome
    assert r.falhas() == []
    assert r.passou()


def test_main_sai_com_zero_no_caso_certo(tmp_path, capsys):
    codigo, saida = sai_com(tmp_path, sessao(), capsys, "--png", str(tmp_path / "png"))
    assert codigo == 0
    assert "100.0%" in saida
    assert (tmp_path / "png" / "oled_alvo.png").exists()


# ---------- rodízio ----------


def test_rodizio_reconhecido():
    r = conta(sessao())
    assert r.sequencia[:6] == ["principal", "resumo", "alvo"] * 2
    mediana = {k: v[0] for k, v in r.duracao_por_tela.items()}
    assert mediana == {"principal": 8.0, "resumo": 4.0, "alvo": 4.0}
    assert r.rodizio_ok
    assert r.nominais == {"principal": (2, 2), "resumo": (3, 3), "alvo": (3, 3)}


def test_rodizio_4_8_8_sai_com_1(tmp_path, capsys):
    codigo, saida = sai_com(tmp_path, sessao(duracoes=(4.0, 8.0, 8.0)), capsys)
    assert codigo == 1
    assert "rodízio: a duração" in saida


def test_trecho_de_6_s_reprova():
    # 2 s de diferença: fora de 0,5 s (e dentro de uma tolerância frouxa de 2 s)
    assert not oc.duracao_confere({"principal": [8.0, 8.0], "resumo": [6.0, 6.0]})
    assert oc.duracao_confere({"principal": [8.0], "resumo": [4.4], "alvo": [3.6]})
    assert oc.duracao_confere({"principal": [8.4]})  # a fronteira é 0,5 s
    assert oc.duracao_confere({"principal": [8.5]})
    assert not oc.duracao_confere({"principal": [8.6]})
    assert not oc.duracao_confere({"principal": [7.4]})
    assert not oc.duracao_confere({})


def test_ordem_do_rodizio():
    def seg(*telas):
        return [[k, i, i] for i, k in enumerate(telas)]

    assert oc.ordem_confere(seg("principal", "resumo", "alvo", "principal", "resumo"))
    assert oc.ordem_confere(seg("principal", "resumo", "principal"))  # alvo sem valor
    assert oc.ordem_confere(seg("principal", "sinal_ruim", "alvo"))  # SINAL RUIM interrompe
    assert not oc.ordem_confere(seg("principal", "alvo"))
    assert not oc.ordem_confere(seg("principal", "resumo", "alvo", "resumo"))
    assert not oc.ordem_confere(seg("alvo", "resumo"))


def test_ordem_trocada_sai_com_1(tmp_path, capsys):
    ev = sessao(telas=[CASOS["principal"][0], alvo(), resumo()])  # principal, alvo, resumo
    codigo, saida = sai_com(tmp_path, ev, capsys)
    assert codigo == 1
    assert "a ordem" in saida


def test_sinal_ruim_e_tela_propria_e_o_bpm_grande_dela_e_conferido():
    ruim = CASOS["sinal_ruim"][0]
    ev = linhas_d(ruim, 0.1) + linhas_d(ruim, 10.1)

    def com_t(linha_t):
        return sorted(ev + [(s + 0.5, linha_t) for s in range(11)], key=lambda e: e[0])

    r = conta(com_t("t,1,0,0"))  # a placa não mostra BPM: a tela tem "--"
    assert r.sequencia == ["sinal_ruim"]
    assert r.campos[CAMPO_BPM].fracao == 1.0
    r = conta(com_t("t,1,1,7200"))  # a placa diz 72, mas a tela tem "--"
    assert r.campos[CAMPO_BPM].ok == 0


# ---------- integridade e código de saída ----------


@pytest.mark.parametrize(
    "extra, trecho",
    [
        ([(2.0, "b,1,1.0,1.0"), (2.1, "b,3,1.0,1.0")], "saltos no contador"),
        ([(2.0, "lixo no meio")], "linhas estragadas"),
        ([(2.0, "d,3,xyz")], "d, estragadas"),
        ([(2.0, "# laco: amostras 100 fila_max 5 fila_cheia 0 perdidas 2")], "amostras perdidas"),
        ([(2.0, "# tela: d_descartadas 5")], "descartadas"),
        ([(2.0, "p,10,0.5,1")], "linhas estragadas"),  # faltam campos
    ],
)
def test_cada_problema_de_integridade_sai_com_1(tmp_path, capsys, extra, trecho):
    ev = sorted(sessao() + extra, key=lambda e: e[0])
    codigo, saida = sai_com(tmp_path, ev, capsys)
    assert codigo == 1
    assert trecho in saida


def test_descartadas_dentro_do_limite_passam(tmp_path, capsys):
    ev = sessao() + [(2.0, "# tela: d_descartadas 5")]
    ev.sort(key=lambda e: e[0])
    assert sai_com(tmp_path, ev, capsys)[0] == 1
    assert sai_com(tmp_path, ev, capsys, "--max-descartadas", "0.2")[0] == 0


def test_log_so_com_d_e_t_sai_com_1(tmp_path, capsys):
    ev = [(t, s) for t, s in sessao() if s.startswith(("d,", "t,"))]
    codigo, saida = sai_com(tmp_path, ev, capsys)
    assert codigo == 1
    assert "campo sem conferência: resumo: BPM PICOS" in saida


def test_sem_quadros_nao_ha_o_que_conferir(tmp_path, capsys):
    assert oc.confere([(0.0, "b,1,1.0,1.0")]) is None
    assert oc.main([str(escreve(tmp_path, [(0.0, "# so comentario")]))]) == 1


def test_campo_abaixo_do_minimo_sai_com_1(tmp_path, capsys):
    ev = sessao(linhas={"p": "p,10,0.5,1,833,1,75.0"})  # a tela diz 72
    codigo, saida = sai_com(tmp_path, ev, capsys)
    assert codigo == 1
    assert "resumo: BPM PICOS" in saida and "mínimo" in saida


def test_linha_d_estragada_e_contada():
    ev = sessao()
    ev.insert(5, (0.2, "d,3,xyz"))  # curta e sem hexadecimal
    ev.insert(9, (0.3, "d,9," + "ab" * 128))  # página 9 não existe
    ev.insert(12, (0.4, "d,1," + "AB" * 128))  # maiúscula é recusada
    r = conta(ev)
    assert r.integridade.d_estragadas == 3
    assert r.integridade.d_validas == 8 * 10  # 9 trocas de tela + o último quadro
    assert r.integridade.estragadas == 0
    assert any("d, estragadas" in f for f in r.falhas())
    assert all(c.fracao == 1.0 for c in r.campos.values())  # os quadros bons seguem certos


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


def test_linhas_truncadas_nao_derrubam_e_contam_como_estragadas():
    # p, e t, com menos campos, e demais; # laco sem "perdidas"; # tela sem número
    ev = [
        (0.0, "p,1,0.5,1"),
        (0.1, "t,1,1"),
        (0.2, "t,1,1,7200,5"),
        (0.3, "h,1,1,2.0"),
        (0.4, "# laco: amostras 100 fila_max 5"),
        (0.5, "# tela: d_descartadas"),
        (0.6, "e,1,1,71.0"),  # esta está certa
    ]
    i = oc.mede_integridade(ev)
    assert i.estragadas == 6
    h = oc.Historico(ev)
    assert h.tempos["e"] == [0.6]
    assert "p" not in h.tempos and "t" not in h.tempos
    assert oc.candidatos_principal(h, 0.5) == set()  # sem IndexError


def test_le_log_conta_linha_sem_tab_ou_vazia(tmp_path):
    p = tmp_path / "s.log"
    p.write_text("0.100\tb,1,1.0,1.0\n\nsem tab\nabc\tb,2,1.0,1.0\n0.200\t\n0.300\t# ok\n")
    eventos, ruins = oc.le_log(p)
    assert eventos == [(0.1, "b,1,1.0,1.0"), (0.3, "# ok")]
    assert ruins == 4
    assert oc.mede_integridade(eventos, ruins).estragadas == 4


def test_sem_os_avisos_de_1_s_nao_passa(tmp_path, capsys):
    # sem "# laco" e "# tela", "0 perdidas" e "0 descartadas" seriam vazios
    codigo, saida = sai_com(tmp_path, sessao(avisos=False), capsys)
    assert codigo == 1
    assert "avisos # laco" in saida and "avisos # tela" in saida
    # só metade da sessão com aviso também reprova
    ev = [(t, s) for t, s in sessao() if not (s.startswith(("# laco", "# tela")) and t > 24)]
    falhas = conta(ev).falhas()
    assert any("# laco" in f for f in falhas) and any("# tela" in f for f in falhas)
    assert conta(sessao()).falhas() == []


def test_b_com_contador_repetido_ou_que_volta_conta_salto():
    def saltos(*ns):
        return oc.mede_integridade([(i * 0.01, f"b,{n},1.0,1.0") for i, n in enumerate(ns)]).b_saltos

    assert saltos(1, 2, 3, 4) == 0
    assert saltos(1, 1, 2) == 1  # repetido
    assert saltos(1, 2, 3, 2, 3) == 1  # volta
    assert saltos(1, 2, 4) == 1  # pulou


def test_minimo_por_campo_e_a_fronteira():
    r = conta(sessao())
    r.campos[CAMPO_BPM] = oc.Campo(ok=94, total=100)
    assert any(CAMPO_BPM in f for f in r.falhas(0.95))
    assert not any(CAMPO_BPM in f for f in r.falhas(0.90))
    r.campos[CAMPO_BPM] = oc.Campo(ok=95, total=100)
    assert r.falhas(0.95) == []  # exatamente no mínimo passa


def test_le_log_com_tempo_inf_ou_nan(tmp_path):
    p = tmp_path / "s.log"
    p.write_text("inf\tb,1,1.0,1.0\nnan\t# x\n-inf\t# y\n0.5\t# ok\n")
    eventos, ruins = oc.le_log(p)
    assert eventos == [(0.5, "# ok")]
    assert ruins == 3


def test_resp_grande_do_alvo_nenhum_par_difere_so_nas_linhas_8_a_15():
    # por isso a caixa de 16 linhas do RESP (e a do BPM e da SpO2 grandes) não precisa de teste
    # próprio pra metade de baixo: se um par assim existisse, esta conta o acharia
    def topo(txt):
        fb = oled.Fb()
        fb.text_r(100, 0, txt, 2)
        return fb.p[:16, 72:101]

    n = {t: topo(t) for t in map(str, range(100))}
    pares = [
        (a, b)
        for a in n
        for b in n
        if (n[a][:8] == n[b][:8]).all() and not (n[a] == n[b]).all()
    ]
    assert pares == []


# ---------- arredondamento, valores inválidos e teto ----------


def test_textos_numero_meio_pra_cima_e_empate():
    assert oc.textos_numero(72.4, 999) == {"72"}
    assert oc.textos_numero(72.6, 999) == {"73"}
    assert oc.textos_numero(72.5, 999) == {"72", "73"}  # x,50: os dois lados valem
    assert oc.textos_numero(72.50, 999) == {"72", "73"}
    assert oc.textos_numero(72.496, 999) == {"72", "73"}  # a linha só tem 2 casas
    assert oc.textos_numero(72.504, 999) == {"72", "73"}
    assert oc.textos_numero(72.494, 999) == {"72"}
    assert oc.textos_numero(72.506, 999) == {"73"}
    assert oc.textos_numero(0.5, 999) == {"0", "1"}


def test_textos_numero_invalido_e_teto():
    assert oc.textos_numero(-1.0, 999) == {"--"}
    assert oc.textos_numero(float("nan"), 999) == {"--"}
    assert oc.textos_numero(150.0, 99) == {"99"}  # resp passa de 99
    assert oc.textos_numero(150.0, 999) == {"150"}
    assert oc.textos_numero(1500.0, 999) == {"999"}
    assert oc.textos_numero(100.4, 100) == {"100"}
    assert oc.textos_numero(98.5, 99) == {"98", "99"}  # o teto não passa de 99 no empate


def test_lf_hf_formato_x_ponto_y():
    assert oc.texto_lf_hf(6.044) == {"6.0"}
    assert oc.texto_lf_hf(6.287) == {"6.3"}
    assert oc.texto_lf_hf(0.95) == {"0.9", "1.0"}  # x,x5 é empate
    assert oc.texto_lf_hf(14.0) == {"14.0"}
    assert oc.texto_lf_hf(-1.0) == {"--"}


def campo(r, nome):
    return r.campos[nome]


def test_empate_no_bpm_picos_aceita_os_dois_lados():
    for tela_txt in ("72", "73"):
        ev = sessao(telas=[CASOS["principal"][0], resumo(picos=tela_txt), alvo()],
                    linhas={"p": "p,10,0.5,1,833,1,72.50"})
        assert campo(conta(ev), "resumo: BPM PICOS (p,)").fracao == 1.0, tela_txt
    ev = sessao(telas=[CASOS["principal"][0], resumo(picos="74"), alvo()],
                linhas={"p": "p,10,0.5,1,833,1,72.50"})
    assert campo(conta(ev), "resumo: BPM PICOS (p,)").ok == 0


def test_valor_invalido_vira_dois_tracos_no_resumo_e_no_alvo():
    ev = sessao(
        telas=[
            CASOS["principal"][0],
            resumo(picos="--", fft="--", sdnn="--", rmssd="--", lf="--", spo2="--", resp="--"),
            alvo(spo2="--", resp="--"),
        ],
        linhas={
            "p": "p,10,0.5,0,0.0,0,0.0",
            "e": "e,1,0,0.0",
            "h": "h,10,0,0.0,0.0,0",
            "l": "l,1,0,0.000",
            "s": "s,1,0,0.0,0.0",
            "r": "r,1,0.0,0",
        },
    )
    r = conta(ev)
    for nome, c in r.campos.items():
        if nome != CAMPO_BPM:
            assert c.ok == c.total > 0, nome


def test_tela_com_numero_e_placa_dizendo_invalido_nao_bate():
    ev = sessao(linhas={"s": "s,1,0,0.0,0.0", "r": "r,1,0.0,0", "l": "l,1,0,0.000"})
    r = conta(ev)
    for nome in ("resumo: SPO2~ (s,)", "resumo: RESP (r,)", "alvo: SPO2 grande (s,)",
                 "alvo: RESP grande (r,)", "resumo: LF/HF (l,)"):
        assert campo(r, nome).ok == 0, nome


def test_lf_hf_no_resumo_confere_o_formato():
    assert campo(conta(sessao()), "resumo: LF/HF (l,)").fracao == 1.0
    errado = sessao(telas=[CASOS["principal"][0], resumo(lf="6.3"), alvo()])
    assert campo(conta(errado), "resumo: LF/HF (l,)").ok == 0
    ok = sessao(
        telas=[CASOS["principal"][0], resumo(lf="6.3"), alvo()], linhas={"l": "l,1,1,6.287"}
    )
    assert campo(conta(ok), "resumo: LF/HF (l,)").fracao == 1.0


def test_troca_de_um_digito_na_tela_e_detectada():
    errada = oled.tela_principal("73", True, 4, CASOS["principal"][1])
    r = conta(sessao(telas=[errada, resumo(), alvo()]))
    assert campo(r, CAMPO_BPM).ok == 0
    assert campo(r, "resumo: SDNN (h,)").fracao == 1.0
    assert not r.passou()


@pytest.mark.parametrize(
    "tipo, trocado",
    [
        ("p", "p,10,0.5,1,833,1,75.0"),
        ("e", "e,1,1,77.0"),
        ("h", "h,10,1,52.0,35.1,60"),
        ("s", "s,1,1,91.0,0.5"),
        ("r", "r,1,12.0,1"),
        ("l", "l,1,1,3.100"),
    ],
)
def test_troca_do_valor_de_uma_linha_de_resultado_e_detectada(tipo, trocado):
    r = conta(sessao(linhas={tipo: trocado}))
    assert any(c.fracao < 0.5 for c in r.campos.values())
    assert not r.passou()


@pytest.mark.parametrize(
    "tipo, trocado, campos",
    [
        ("p", "p,10,0.5,1,833,1,82.0", ["resumo: BPM PICOS (p,)"]),  # só a dezena: 72 -> 82
        ("e", "e,1,1,81.0", ["resumo: BPM FFT (e,)"]),
        ("h", "h,10,1,58.2,45.1,60", ["resumo: SDNN (h,)", "resumo: RMSSD (h,)"]),
        ("s", "s,1,1,87.2,0.5", ["resumo: SPO2~ (s,)", "alvo: SPO2 grande (s,)"]),
        ("r", "r,1,26.0,1", ["resumo: RESP (r,)", "alvo: RESP grande (r,)"]),
    ],
)
def test_so_a_dezena_diferente_tambem_e_detectada(tipo, trocado, campos):
    r = conta(sessao(linhas={tipo: trocado}))
    for nome in campos:
        assert campo(r, nome).ok == 0, nome
    assert not r.passou()


def test_teto_de_resp_99_e_de_spo2_100_no_resumo_e_no_alvo():
    ev = sessao(
        telas=[CASOS["principal"][0], resumo(spo2="100", resp="99"), alvo(spo2="100", resp="99")],
        linhas={"s": "s,1,1,105.0,0.5", "r": "r,1,150.0,1"},
    )
    r = conta(ev)
    for nome in ("resumo: SPO2~ (s,)", "resumo: RESP (r,)", "alvo: SPO2 grande (s,)",
                 "alvo: RESP grande (r,)"):
        assert campo(r, nome).fracao == 1.0, nome


def test_bpm_grande_do_ultimo_batimento_invalido_vira_dois_tracos():
    sem = oled.tela_principal("--", False, 4, CASOS["principal"][1])
    ev = sessao(telas=[sem, resumo(), alvo()],
                linhas={"t": "t,1,1,7200", "p": "p,10,0.5,1,0.0,0,0.0"})
    assert campo(conta(ev), CAMPO_BPM).fracao == 1.0


def test_bpm_grande_com_t_dizendo_mostra_0_nao_aceita_numero():
    # o display nunca mostra número quando o último t, disse 0, mesmo com p, válido
    ev = sessao(linhas={"t": "t,1,0,0", "p": "p,10,0.5,1,833,1,72.0"})
    assert campo(conta(ev), CAMPO_BPM).ok == 0


# ---------- as janelas ----------


def test_valor_de_15_s_atras_nao_vale():
    ev = [
        (5.0, "t,1,1,7200"),
        (5.0, "s,1,1,97.2,0.5"),
        (5.0, "r,1,16.0,1"),
        (5.0, "p,1,0.5,1,833,1,72.0"),
        (20.0, "t,2,1,9000"),
        (20.0, "s,2,1,91.0,0.5"),
        (20.0, "r,2,12.0,1"),
        (20.0, "p,2,0.5,1,833,1,90.0"),
    ]
    h = oc.Historico(ev)
    assert oc.candidatos_principal(h, 20.2) == {"90"}
    assert h.ultimas("t", 20.2) == [[2, 1, 9000]]
    assert h.ultimas("s", 20.2) == [[2, 1, 91.0, 0.5]]
    assert h.ultimas("r", 20.2) == [[2, 12.0, 1]]
    assert oc.candidatos_principal(h, 5.2) == {"72"}
    # e, pelo fim: uma linha que chega depois do quadro só vale até FRENTE_S
    assert h.ultimas("t", 19.4) == []
    assert h.ultimas("t", 19.65) == [[2, 1, 9000]]


def test_t_s_e_r_com_2_s_de_idade_nao_valem_e_com_1_s_valem():
    velho = [(8.0, "t,1,1,7200"), (8.0, "s,1,1,97.2,0.5"), (8.0, "r,1,16.0,1"),
             (8.0, "p,1,0.5,1,833,1,72.0")]
    h = oc.Historico(velho)
    assert oc.candidatos_principal(h, 10.1) == set()
    assert h.ultimas("s", 10.1) == [] and h.ultimas("r", 10.1) == []
    assert oc.candidatos_principal(h, 9.0) == {"72"}  # 1 s de idade
    assert h.ultimas("s", 9.0) != [] and h.ultimas("r", 9.0) != []
    # e na conferência: tela com número, mas a única linha t, tem 2 s de idade: não bate
    ev = linhas_d(CASOS["principal"][0], 10.1) + linhas_d(CASOS["principal"][0], 20.1)
    ev += [(8.0, "t,1,1,7200")] + [(float(k) + 0.5, "t,1,0,0") for k in range(15, 21)]
    r = conta(sorted(ev, key=lambda e: e[0]))
    assert r.campos[CAMPO_BPM].ok < r.campos[CAMPO_BPM].total


def test_p_de_2_s_atras_nao_entra_nos_candidatos_do_bpm_grande():
    h = oc.Historico([(8.0, "p,1,0.5,1,833,1,90.0"), (9.5, "t,1,1,7200")])
    assert oc.candidatos_principal(h, 10.0) == {"72"}
    h = oc.Historico([(9.0, "p,1,0.5,1,833,1,90.0"), (9.5, "t,1,1,7200")])
    assert oc.candidatos_principal(h, 10.0) == {"72", "90"}


def test_resumo_mostra_o_ultimo_valor_mesmo_antigo_mas_so_as_ultimas():
    ev = (
        [(float(i), f"h,{i},1,{40 + i}.0,30.0,60") for i in range(10)]
        + [(float(i), f"p,{i},0.5,1,833,1,{70 + i}.0") for i in range(10)]
        + [(float(i), f"e,{i},1,{70 + i}.0") for i in range(10)]
        + [(float(i), f"l,{i},1,{1 + i}.000") for i in range(10)]
    )
    h = oc.Historico(ev)
    assert [d[0] for d in h.ultimas("h", 100.0)] == [7, 8, 9]  # as 3 últimas
    assert [d[0] for d in h.ultimas("p", 100.0)] == [7, 8, 9]
    assert [d[0] for d in h.ultimas("e", 100.0)] == [8, 9]
    assert [d[0] for d in h.ultimas("l", 100.0)] == [8, 9]


def test_tela_velha_nao_bate_com_resultado_novo_no_log():
    # a tela mostra SpO2 97 e RESP 16, mas depois de 15 s a placa diz outra coisa
    ev = sessao(ciclos=2)
    novos = [(t + 15.0, s) for t, s in ev if s.startswith(("s,", "r,"))]
    ev = [(t, s) for t, s in ev if not s.startswith(("s,", "r,"))] + [
        (t, s.replace("97.2", "91.0").replace("16.0", "12.0")) for t, s in novos
    ]
    ev.sort(key=lambda e: e[0])
    r = conta(ev)
    assert campo(r, "alvo: SPO2 grande (s,)").fracao < 0.5


# ---------- classificação das telas e dos pixels ----------


def test_classifica_as_telas_dos_casos():
    for nome in ("principal", "alvo", "sem_dedo", "sinal_ruim"):
        assert oc.classifica(oc.pixels(CASOS[nome][0].paginas())) == nome, nome
    assert oc.classifica(oc.pixels(resumo().paginas())) == "resumo"
    assert oc.classifica(oc.pixels(CASOS["inicio"][0].paginas())) == "outra"


def test_sinal_ruim_limiares_das_linhas_16_e_23():
    def tela(l23, l16):
        p = np.zeros((64, 128), np.uint8)
        p[23, :l23] = 1
        p[16, :l16] = 1
        return p

    assert oc.classifica(tela(128, 128)) == "sinal_ruim"  # a faixa quase cheia
    assert oc.classifica(tela(121, 61)) == "sinal_ruim"
    assert oc.classifica(tela(120, 61)) != "sinal_ruim"
    assert oc.classifica(tela(121, 60)) != "sinal_ruim"
    assert oc.classifica(tela(128, 0)) != "sinal_ruim"  # uma linha de onda não é a faixa


def test_pixels_e_o_contrario_de_paginas():
    fb = CASOS["principal"][0]
    assert (oc.pixels(fb.paginas()) == fb.p).all()


# ---------- PNGs ----------


def test_png_sai_colorido_e_com_o_tamanho_certo(tmp_path):
    r = oc.confere(sessao(), tmp_path)
    assert r is not None and r.pngs == ["principal", "resumo", "alvo"]
    img = imread(tmp_path / "oled_principal.png")
    assert img.shape[:2] == (64 * oc.ESCALA_PNG, 128 * oc.ESCALA_PNG)
    px = (img[..., :3] * 255).round().astype(int)
    aceso_cima = CASOS["principal"][0].p[: tt.CORTE_AMARELO_PX] == 1
    aceso_baixo = CASOS["principal"][0].p[tt.CORTE_AMARELO_PX :] == 1
    assert aceso_cima.any() and aceso_baixo.any()
    assert {tuple(c) for c in px.reshape(-1, 3)} == {(0, 0, 0), (255, 215, 0), (0, 175, 255)}
    e = oc.ESCALA_PNG
    y, x = np.argwhere(aceso_cima)[0]
    assert tuple(px[y * e, x * e]) == (255, 215, 0)
    y, x = np.argwhere(aceso_baixo)[0]
    assert tuple(px[(y + tt.CORTE_AMARELO_PX) * e, x * e]) == (0, 175, 255)


def test_o_quadro_do_png_e_escolhido_de_forma_deterministica():
    def amostras(*marcas):
        return [(t, np.full((64, 128), i, np.uint8)) for i, t in enumerate(marcas)]

    am = amostras(10.0, 130.0, 131.0, 140.0, 150.0)
    ti = [(t, "alvo") for t, _ in am]
    # bons: só o de 140 s; o de 130 s é depois de 120 s mas não é bom
    bons = [False, False, False, True, True]
    assert oc.escolhe_quadro(am, ti, bons, "alvo")[0] == 140.0
    # sem nenhum bom: o primeiro depois de 120 s
    assert oc.escolhe_quadro(am, ti, [False] * 5, "alvo")[0] == 130.0
    # a tela só apareceu antes de 120 s: o primeiro dela
    assert oc.escolhe_quadro(am[:1], ti[:1], [True], "alvo")[0] == 10.0
    assert oc.escolhe_quadro(am, ti, bons, "resumo") is None


def bons_por_tela(ev):
    am = oc.amostra_quadros(oc.remonta_quadros(ev))
    ti = [(t, oc.classifica(p)) for t, p in am]
    _, bons = oc.confere_numeros(am, ti, oc.Historico(ev))
    out = {}
    for (_, k), b in zip(ti, bons, strict=True):
        out.setdefault(k, []).append(b)
    return out


def test_quadro_bom_exige_todos_os_campos_com_um_valor_so():
    bons = bons_por_tela(sessao())
    assert all(any(v) for v in bons.values())  # no caso certo as três telas têm quadro bom
    # com 72,50 na linha do p, o PICOS e o BPM grande têm dois valores possíveis: não é "bom"
    bons = bons_por_tela(sessao(linhas={"p": "p,10,0.5,1,833,1,72.50"}))
    assert not any(bons["resumo"]) and not any(bons["principal"])
    assert any(bons["alvo"])
    # um campo "--" também não é bom (SpO2 inválida no alvo)
    bons = bons_por_tela(sessao(telas=[CASOS["principal"][0], resumo(), alvo(spo2="--")],
                                linhas={"s": "s,1,0,0.0,0.0"}))
    assert not any(bons["alvo"])


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


def test_grava_log_pode_descartar_a_primeira_linha_cortada():
    fonte = SerialFalsa([b"ppg,1,2\n", b"b,1,2.0,3.0\n"])
    relogio = iter([0.0, 0.1, 0.2, 5.0]).__next__
    saida = io.StringIO()
    assert grava_log.grava(fonte, saida, 1.0, relogio, descarta_primeira=True) == 1
    assert "ppg" not in saida.getvalue() and "b,1,2.0,3.0" in saida.getvalue()


def test_log_gravado_volta_igual_pelo_le_log(tmp_path):
    ev = sessao(ciclos=1)
    lido, ruins = oc.le_log(escreve(tmp_path, ev))
    assert ruins == 0
    assert len(lido) == len(ev)
    assert lido[0] == (round(ev[0][0], 3), ev[0][1])


# ---------- o log real (fora do git) ----------


@pytest.fixture(scope="module")
def log_real():
    if not LOG_REAL.exists():
        pytest.skip("analise/dados/ está fora do git: sem o log real da sessão de 24/11")
    return oc.le_log(LOG_REAL)


def test_log_real_da_integracao_final(log_real):
    eventos, ruins = log_real
    r = conta_com_ruins(eventos, ruins)
    i = r.integridade
    assert (i.linhas, i.estragadas, i.d_estragadas) == (78534, 0, 0)
    assert (i.b_saltos, i.laco_perdidas, i.d_descartadas) == (0, 0, 10)
    assert r.rodizio_ok
    assert r.segundos_por_tela["sinal_ruim"] == 52  # o SINAL RUIM ganha do rodízio
    c = r.campos
    assert (c[CAMPO_BPM].ok, c[CAMPO_BPM].total) == (901, 905)
    for nome, campo_ in c.items():
        if nome != CAMPO_BPM:
            assert campo_.ok == campo_.total, nome
    assert r.passou()


def conta_com_ruins(eventos, ruins):
    r = oc.confere(eventos, log_ruins=ruins)
    assert r is not None
    return r


def test_pngs_das_docs_sao_os_que_o_comando_gera_do_log_real(log_real, tmp_path):
    eventos, ruins = log_real
    assert oc.confere(eventos, tmp_path, ruins) is not None
    for tela in ("principal", "resumo", "alvo"):
        gerado = imread(tmp_path / f"oled_{tela}.png")
        commitado = imread(ASSETS / f"oled_{tela}.png")
        assert gerado.shape == commitado.shape, tela
        assert (gerado == commitado).all(), tela
