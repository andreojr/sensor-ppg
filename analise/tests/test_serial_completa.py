import pytest

from analise import decimacao, filtro, serial_completa


def test_carrega_sem_o_arquivo_explica(tmp_path):
    with pytest.raises(SystemExit, match="SERIAL_COMPLETA"):
        serial_completa.carrega(tmp_path / "x_filtrado.csv")


def test_carrega_so_cabecalho_explica(tmp_path):
    (tmp_path / "x.csv").write_text("n,ir,vermelho\n")
    with pytest.raises(SystemExit, match="vazio.*SERIAL_COMPLETA"):
        serial_completa.carrega(tmp_path / "x.csv")


def test_confere_com_firmware_padrao_explica(tmp_path):
    # O que a captura grava com o firmware padrão: CSV principal só com o cabeçalho,
    # _bruto.csv com dados e nenhum _filtrado.csv.
    (tmp_path / "x.csv").write_text("n,ir,vermelho\n")
    (tmp_path / "x_bruto.csv").write_text("n,ir,vermelho\n0,1.0,2.0\n1,1.0,2.0\n")
    for modulo in (decimacao, filtro):
        with pytest.raises(SystemExit, match="SERIAL_COMPLETA"):
            modulo.main(["--confere", str(tmp_path / "x.csv")])
