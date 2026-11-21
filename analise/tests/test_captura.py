import io
import re
from pathlib import Path

import matplotlib
import pandas as pd

from analise import captura, plota

matplotlib.use("Agg")

MAX30102_H = Path(__file__).resolve().parents[2] / "Core/Inc/max30102.h"


def test_taxa_igual_ao_firmware():
    """A taxa do sensor no Python tem que ser a mesma do firmware."""
    texto = MAX30102_H.read_text(encoding="utf-8")
    fs_c = int(re.search(r"#define MAX30102_FS_HZ (\d+)u", texto).group(1))
    assert captura.SENSOR_FS_HZ == fs_c


def test_le_linha():
    assert captura.le_linha("12,130000,140000\n") == (12, 130000, 140000)
    assert captura.le_linha("# MAX30102 400 Hz: n,ir,vermelho") is None
    assert captura.le_linha("30000,14") is None  # cortada
    assert captura.le_linha("a,b,c") is None


def test_grava_csv_e_detecta_saltos(tmp_path):
    serial_falsa = io.BytesIO(
        b"0,13,999\n"  # pedaço de linha de antes de abrir a porta
        b"# MAX30102 400 Hz: n,ir,vermelho\n"
        b"5,100,200\n"
        b"6,101,201\n"
        b"# perdidas: 3\n"
        b"10,102,202\n"
        b"11,103,203\n"
    )
    destino = tmp_path / "x.csv"
    resumo = captura.grava(serial_falsa, destino, segundos=0.1)

    df = pd.read_csv(destino)
    assert list(df.columns) == list(captura.COLUNAS)
    assert df["n"].tolist() == [0, 5, 6, 10, 11]
    assert resumo.amostras == 5
    assert resumo.saltos == [(0, 5), (6, 10)]
    assert resumo.perdidas == 4 + 3
    assert resumo.comentarios == ["# MAX30102 400 Hz: n,ir,vermelho", "# perdidas: 3"]


def test_plota_gera_png(tmp_path):
    csv = tmp_path / "x.csv"
    csv.write_text("n,ir,vermelho\n100,1,2\n101,3,4\n102,5,6\n", encoding="utf-8")
    df = plota.carrega(csv)
    assert df["t"].tolist() == [0, 1 / captura.SENSOR_FS_HZ, 2 / captura.SENSOR_FS_HZ]

    png = tmp_path / "x.png"
    plota.main([str(csv), "--png", str(png)])
    assert png.stat().st_size > 0
