"""O espelho do display: das linhas "d," da placa até o desenho no terminal (sem placa)."""

import io
import re
import time

import pytest

from analise import captura, oled
from analise import tela_terminal as tt

HEXA = "ab" * 128


def linhas_d(fb: oled.Fb) -> list[str]:
    mem = fb.paginas()
    return [tt.linha_d(p, mem[p * 128 : (p + 1) * 128]) for p in range(8)]


class Tty(io.StringIO):
    """Saída que finge ser um terminal."""

    def isatty(self) -> bool:
        return True


def sem_cores(texto: str) -> list[str]:
    """As linhas do quadro sem os códigos de cor (só os caracteres desenhados)."""
    return [re.sub(r"\033\[[0-9;]*m", "", linha) for linha in texto.split("\n")]


def cores_do_quadro(texto: str) -> list[str]:
    """O código de cor que abre cada linha do quadro."""
    return [re.match(r"\033\[[0-9;]*m", linha).group() for linha in texto.split("\n")]


def espelho(**kw) -> tuple[tt.Espelho, io.StringIO]:
    saida = Tty()
    return tt.Espelho(saida=saida, intervalo=0, **kw), saida


@pytest.mark.parametrize("caso", list(oled.casos()))
def test_tela_remontada_igual_a_do_oled(caso):
    fb = oled.casos()[caso][0]
    e, _ = espelho()
    for linha in linhas_d(fb):
        assert e.linha(linha)
    assert e.completa()
    assert e.memoria == fb.paginas()


@pytest.mark.parametrize("caso", list(oled.casos()))
def test_desenho_tem_o_tamanho_certo_e_os_pixels(caso):
    fb = oled.casos()[caso][0]
    mem = fb.paginas()
    blocos = tt.desenha_blocos(mem)
    assert len(blocos) == 32 and all(len(linha) == 128 for linha in blocos)
    braille = tt.desenha_braille(mem)
    assert len(braille) == 16 and all(len(linha) == 64 for linha in braille)
    # cada pixel do Fb aparece no meio-bloco certo
    for y in range(0, 64, 2):
        for x in range(128):
            esperado = " ▀▄█"[int(fb.p[y, x]) + 2 * int(fb.p[y + 1, x])]
            assert blocos[y // 2][x] == esperado
    # e o braille tem a mesma quantidade de pixels acesos
    acesos = sum((ord(c) - 0x2800).bit_count() for linha in braille for c in linha)
    assert acesos == int(fb.p.sum())


def test_pixel_bit_zero_e_a_linha_de_cima():
    mem = bytearray(1024)
    mem[0] = 0b00000001  # página 0, coluna 0, linha 0
    mem[128 + 5] = 0b10000000  # página 1, coluna 5, linha 15
    assert tt.pixel(bytes(mem), 0, 0) == 1 and tt.pixel(bytes(mem), 0, 1) == 0
    assert tt.pixel(bytes(mem), 5, 15) == 1
    blocos = tt.desenha_blocos(bytes(mem))
    assert blocos[0][0] == "▀" and blocos[7][5] == "▄"


def test_braille_um_ponto_e_tudo_aceso():
    mem = bytearray(1024)
    mem[0] = 1
    assert tt.desenha_braille(bytes(mem))[0][0] == "⠁"
    assert tt.desenha_braille(b"\xff" * 1024)[3] == "⣿" * 64


def test_redesenha_no_mesmo_lugar_sem_rolar():
    e, saida = espelho()
    e.linha("d,0," + HEXA)
    e.linha("d,1," + HEXA)
    texto = saida.getvalue()
    assert texto.startswith(tt.INICIO + tt.TOPO)  # limpa só no primeiro desenho
    assert texto.count(tt.INICIO) == 1
    assert texto.count(tt.TOPO) == 2  # um cursor ao topo por desenho
    assert texto.split(tt.TOPO)[1].count("\n") == 31  # 32 linhas, sem \n no fim: não rola
    assert "\033[?1049h" in tt.INICIO and "\033[?1049l" in tt.FIM  # tela alternativa
    e.fecha()
    assert saida.getvalue().endswith(tt.FIM)


def test_braille_desenha_16_linhas():
    e, saida = espelho(braille=True)
    e.linha("d,0," + HEXA)
    assert saida.getvalue().split(tt.TOPO)[1].count("\n") == 15


def test_terminal_pequeno_nao_desenha_e_avisa():
    saida = Tty()
    e = tt.Espelho(saida=saida, intervalo=0, terminal=(100, 40))
    e.linha("d,0," + HEXA)
    e.fecha()
    assert saida.getvalue() == ""
    assert e.recebidas == 1
    assert "100x40" in e.aviso() and "128x32" in e.aviso()
    assert "só o CSV" in e.aviso()
    assert tt.Espelho(saida=Tty(), braille=True, terminal=(64, 16)).aviso() is None
    assert tt.Espelho(saida=Tty(), terminal=(128, 32)).aviso() is None
    assert tt.Espelho(saida=Tty(), braille=True, terminal=(63, 16)).aviso() is not None
    assert tt.Espelho(saida=Tty(), terminal=(128, 31)).aviso() is not None


def test_saida_que_nao_e_terminal_nao_escreve_escapes():
    saida = io.StringIO()  # isatty() é False
    e = tt.Espelho(saida=saida, intervalo=0, terminal=(80, 24))
    assert "não é um terminal" in e.aviso()  # e não o aviso de 80x24
    e.inicia()
    e.linha("d,0," + HEXA)
    e.fecha()
    assert saida.getvalue() == "" and e.recebidas == 1


def test_inicia_mostra_a_espera_que_some_com_a_primeira_pagina():
    for braille, linhas in ((False, 32), (True, 16)):
        e, saida = espelho(braille=braille)
        e.inicia()
        texto = saida.getvalue()
        assert tt.ESPERA in texto and texto.count("\n") == linhas - 1
        e.linha("d,0," + HEXA)
        ultimo = saida.getvalue().split(tt.TOPO)[-1]
        assert tt.ESPERA not in ultimo


def test_rajada_de_8_paginas_fecha_a_tela_no_tick_mesmo_sem_linha_nova(tmp_path):
    fb = oled.casos()["principal"][0]
    entrada = [b"b,0,1,2\n"] + [(x + "\n").encode() for x in linhas_d(fb)]

    class Fonte:
        def readline(self) -> bytes:
            if entrada:
                return entrada.pop(0)
            time.sleep(0.03)  # timeout da porta: linha vazia
            return b""

    saida = Tty()
    e = tt.Espelho(saida=saida, intervalo=0.1)
    captura.grava(Fonte(), tmp_path / "x.csv", segundos=0.5, espelho=e)
    texto = saida.getvalue()
    # a 1ª página desenhou na hora; as outras 7 ficaram seguradas e saíram em tick
    assert texto.count(tt.TOPO) >= 2
    ultimo = texto.split(tt.TOPO)[-1]
    assert ultimo.split("\n")[0].count("█") + ultimo.count("▀") > 0
    assert tt.desenha_blocos(fb.paginas()) == sem_cores(ultimo.removesuffix(tt.FIM))


def test_intervalo_segura_o_redesenho():
    saida = Tty()
    e = tt.Espelho(saida=saida, intervalo=3600)
    e.linha("d,0," + HEXA)  # o primeiro desenha
    e.linha("d,1," + HEXA)  # o segundo espera
    assert saida.getvalue().count(tt.TOPO) == 1
    e.fecha()  # o que ficou pendente sai no fim
    assert saida.getvalue().count(tt.TOPO) == 2


def test_pagina_repetida_igual_nao_redesenha():
    e, saida = espelho()
    e.linha("d,3," + HEXA)
    e.linha("d,3," + HEXA)
    assert saida.getvalue().count(tt.TOPO) == 1


@pytest.mark.parametrize(
    "linha",
    [
        "d,8," + HEXA,  # página fora de 0 a 7
        "d,-1," + HEXA,
        "d,x," + HEXA,
        "d,0," + HEXA[:-2],  # tamanho errado
        "d,0," + HEXA + "00",
        "d,0," + "zz" * 128,  # não é hexadecimal
        "d,0,",
        "d,0",
        "d,0," + HEXA + ",1",  # campo a mais
        "x,0," + HEXA,
        "d,0," + HEXA[:-1],  # cortada no meio
        "d,0," + HEXA[:100] + " " + HEXA[101:],  # espaço no meio (mesmo tamanho)
        "d,0," + HEXA[:100] + "\t" + HEXA[101:],  # tab no meio
        "d,0," + HEXA[:-2] + " 1",  # espaço faria o fromhex ignorar
        "d,0," + HEXA.upper(),  # o contrato é minúsculo
    ],
)
def test_linha_invalida_e_ignorada(linha):
    assert tt.le_pagina(linha) is None
    e, saida = espelho()
    assert not e.linha(linha)
    assert e.recebidas == 0 and saida.getvalue() == ""


def test_linha_da_placa_e_hex_minusculo():
    assert tt.linha_d(0, bytes([0xAB]) * 128) == "d,0," + HEXA


def test_captura_alimenta_o_espelho_e_o_csv_nao_muda(tmp_path):
    fb = oled.casos()["principal"][0]
    entrada = (
        b"b,0,100,200\n"
        + "\n".join(linhas_d(fb)).encode()
        + b"\nd,9,"
        + HEXA.encode()
        + b"\nd,0,zz\n"
        + b"b,1,101,201\n"
    )
    e, _ = espelho()
    resumo = captura.grava(io.BytesIO(entrada), tmp_path / "x.csv", segundos=0.1, espelho=e)
    assert e.memoria == fb.paginas()
    assert resumo.paginas_tela == 8
    assert resumo.invalidas == 2
    assert resumo.por_ponto == {"bruto": 2}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.csv", "x_bruto.csv"]


def test_captura_sem_espelho_ignora_as_linhas_d(tmp_path):
    entrada = ("d,0," + HEXA + "\nd,8," + HEXA + "\n5,1,2\n").encode()
    resumo = captura.grava(io.BytesIO(entrada), tmp_path / "x.csv", segundos=0.1)
    assert resumo.amostras == 1 and resumo.paginas_tela == 1 and resumo.invalidas == 1


@pytest.mark.parametrize("braille,linhas,amarelas", [(False, 32, 8), (True, 16, 4)])
def test_cor_de_cada_linha_amarelo_em_cima_azul_embaixo(braille, linhas, amarelas):
    e, saida = espelho(braille=braille)
    e.linha("d,0," + HEXA)
    quadro = saida.getvalue().split(tt.TOPO)[1]
    assert all(linha.endswith("\033[0m") for linha in quadro.split("\n"))  # zera as cores
    cores = cores_do_quadro(quadro)
    assert cores == [tt.COR_AMARELO] * amarelas + [tt.COR_AZUL] * (linhas - amarelas)
    assert tt.COR_AMARELO == "\033[38;5;220;40m" and tt.COR_AZUL == "\033[38;5;39;40m"


@pytest.mark.parametrize("caso", list(oled.casos()))
@pytest.mark.parametrize("braille", [False, True])
def test_cores_nao_mudam_os_caracteres(caso, braille):
    fb = oled.casos()[caso][0]
    e, saida = espelho(braille=braille)
    for linha in linhas_d(fb):
        e.linha(linha)
    esperado = tt.desenha_braille(fb.paginas()) if braille else tt.desenha_blocos(fb.paginas())
    assert sem_cores(saida.getvalue().split(tt.TOPO)[-1]) == esperado


def test_quadro_de_espera_fica_numa_cor_so():
    e, saida = espelho()
    e.inicia()
    assert set(cores_do_quadro(saida.getvalue().split(tt.TOPO)[1])) == {tt.CORES}
