"""A janela do espelho: as contas (cores, escala) e o desenho, sem abrir janela de verdade."""

import time

import pytest

from analise import captura, oled
from analise import tela_janela as tj
from analise import tela_terminal as tt


class CanvasFalso:
    def __init__(self):
        self.retangulos = []
        self.cores = {}
        self.chamadas = 0

    def create_rectangle(self, x0, y0, x1, y1, fill="", outline=""):
        self.retangulos.append((x0, y0, x1, y1))
        self.cores[len(self.retangulos) - 1] = fill
        return len(self.retangulos) - 1

    def itemconfigure(self, item, fill):
        self.chamadas += 1
        self.cores[item] = fill


@pytest.mark.parametrize(
    "monitor,esperado", [("hd", 4), ("fhd", 6), ("2k", 8), ("4k", 12)]
)
def test_escala_por_monitor(monitor, esperado):
    assert tj.escala(monitor) == esperado
    assert tj.escala(monitor) * 128 <= 0.4 * tj.RESOLUCOES[monitor][0]


def test_monitor_padrao_e_fhd():
    assert tj.MONITOR_PADRAO == "fhd"


def test_hex_das_cores_do_painel():
    assert tj.COR_AMARELO_HEX == "#ffd700" and tj.COR_AZUL_HEX == "#00afff"


def test_cor_de_cada_pixel_corte_em_16():
    mem = b"\xff" * 1024
    cores = tj.cores_dos_pixels(mem)
    assert all(c == "#ffd700" for linha in cores[: tt.CORTE_AMARELO_PX] for c in linha)
    assert all(c == "#00afff" for linha in cores[tt.CORTE_AMARELO_PX :] for c in linha)
    assert tj.cores_dos_pixels(bytes(1024))[0][0] == tj.PRETO


def test_pixel_aceso_na_cor_da_regiao():
    mem = bytearray(1024)
    mem[0] = 0b00000001  # (0, 0)
    mem[2 * 128 + 7] = 0b00000001  # página 2, coluna 7: linha 16
    cores = tj.cores_dos_pixels(bytes(mem))
    assert cores[0][0] == tj.COR_AMARELO_HEX and cores[16][7] == tj.COR_AZUL_HEX
    assert sum(c != tj.PRETO for linha in cores for c in linha) == 2


def test_desenho_cria_um_quadrado_por_pixel_e_so_muda_o_que_mudou():
    canvas = CanvasFalso()
    d = tj.Desenho(canvas, 6)
    assert len(canvas.retangulos) == 128 * 64
    assert canvas.retangulos[0] == (0, 0, 6, 6) and canvas.retangulos[-1] == (762, 378, 768, 384)
    fb = oled.casos()["principal"][0]
    d.pinta(fb.paginas())
    acesos = [c for c in canvas.cores.values() if c != tj.PRETO]
    assert len(acesos) == int(fb.p.sum())
    # pixel (x, y) é o item y * 128 + x
    y, x = (int(v[0]) for v in fb.p.nonzero())
    assert canvas.cores[y * 128 + x] == tj.cor_da_linha_px(y)


def test_desenho_segunda_pintura_apaga_e_so_troca_o_que_mudou():
    casos = oled.casos()
    a, b = casos["principal"][0].paginas(), casos["resumo"][0].paginas()
    canvas = CanvasFalso()
    d = tj.Desenho(canvas, 6)
    d.pinta(a)
    antes = canvas.chamadas
    d.pinta(b)
    cores_a, cores_b = tj.cores_dos_pixels(a), tj.cores_dos_pixels(b)
    esperado = [c for linha in cores_b for c in linha]
    assert [canvas.cores[i] for i in range(128 * 64)] == esperado  # inclui os que apagaram
    mudaram = sum(cores_a[y][x] != cores_b[y][x] for y in range(64) for x in range(128))
    assert 0 < mudaram < 128 * 64
    assert canvas.chamadas - antes == mudaram
    d.pinta(b)  # igual: nada a trocar
    assert canvas.chamadas - antes == mudaram


class RaizFalsa:
    def __init__(self):
        self.atualizacoes = 0
        self.fechada = False

    def protocol(self, nome, f):
        self.f = f

    def update(self):
        self.atualizacoes += 1

    def destroy(self):
        self.fechada = True


def janela_falsa(monkeypatch):
    raiz, canvas = RaizFalsa(), CanvasFalso()
    monkeypatch.setattr(tj, "abre_tk", lambda escala: (raiz, canvas))
    return tj.Janela("fhd", intervalo=0), raiz, canvas


def test_janela_espelho_pinta_e_fechar_encerra(monkeypatch):
    j, raiz, canvas = janela_falsa(monkeypatch)
    j.linha("d,0," + "ff" * 128)
    assert canvas.cores[0] == tj.COR_AMARELO_HEX
    antes = raiz.atualizacoes
    j.tick()
    assert raiz.atualizacoes == antes + 1 and not j.encerrado
    raiz.f()  # o usuário fecha a janela
    assert j.encerrado
    j.fecha()
    assert raiz.fechada


def test_captura_para_quando_a_janela_fecha(monkeypatch, tmp_path):
    j, raiz, _ = janela_falsa(monkeypatch)

    class Fonte:
        def readline(self):
            raiz.f()
            time.sleep(0.01)
            return b""

    r = captura.grava(Fonte(), tmp_path / "x.csv", segundos=5, espelho=j)
    assert r.segundos < 2


def test_erro_sem_ambiente_grafico(monkeypatch, capsys):
    def falha(escala):
        raise tj.ErroJanela("sem ambiente gráfico")

    monkeypatch.setattr(tj, "abre_tk", falha)
    with pytest.raises(SystemExit) as e:
        captura.main(["/dev/nada", "--janela"])
    assert "sem ambiente gráfico" in str(e.value) and "Traceback" not in str(e.value)


@pytest.mark.parametrize(
    "args", [["--janela", "--tela"], ["--janela", "--qualidade"], ["--janela", "--braille"]]
)
def test_janela_combinacoes_invalidas_dao_erro_antes_da_serial(args, capsys):
    with pytest.raises(SystemExit) as e:
        captura.main(["/dev/nada", *args])  # se abrisse a serial, o erro seria outro
    assert e.value.code == 2
    assert "usage" in capsys.readouterr().err


def test_fumaca_janela_de_verdade():
    try:
        j = tj.Janela("hd", intervalo=0)
    except tj.ErroJanela:
        pytest.skip("sem ambiente gráfico")
    j.linha("d,0," + "ff" * 128)
    j.tick()
    j.fecha()
    assert j.encerrado
