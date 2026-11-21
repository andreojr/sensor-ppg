import numpy as np
import pytest

from analise import vetores


def test_float_volta_igual():
    """O literal C de cada float32 é o mesmo float32 de volta."""
    x = np.array([0.1, 1.0, -3.5e-7, 1e20, 123456.789], dtype=np.float32)
    texto = vetores.header("filtro", "caso", {"x": x}, tol=1e-5)
    corpo = texto.split("caso_x[5] = {")[1].split("};")[0]
    lidos = [np.float32(v.strip().removesuffix("f")) for v in corpo.split(",") if v.strip()]
    assert np.array_equal(lidos, x)


def test_formato():
    texto = vetores.header("picos", "trecho_1", {"n_pico": [3, 105], "bpm": [72.0]}, tol=0.5)
    assert "#ifndef VETOR_PICOS_TRECHO_1_H" in texto
    assert "#define TRECHO_1_TOL 0.5f" in texto
    assert "#define TRECHO_1_N_PICO_N 2u" in texto
    assert "static const int32_t trecho_1_n_pico[2] = {" in texto
    assert "static const float trecho_1_bpm[1] = {" in texto
    assert "72.0f" in texto


@pytest.mark.parametrize("arrays, tol", [
    ({"x": [np.nan]}, 0.1),
    ({"x": [np.inf]}, 0.1),
    ({"X": [1.0]}, 0.1),
    ({"x": [2**40]}, 0.1),
    ({}, 0.1),
    ({"x": [1.0]}, -1.0),
])
def test_rejeita(arrays, tol):
    with pytest.raises(ValueError):
        vetores.header("filtro", "caso", arrays, tol)


def test_rejeita_nome_de_caso():
    with pytest.raises(ValueError):
        vetores.header("filtro", "1caso", {"x": [1.0]}, 0.1)


def test_grava_no_lugar_certo(tmp_path):
    caminho = vetores.gera_vetor("hrv", "caso", {"x": [1.0]}, tol=0.1, testes=tmp_path)
    assert caminho == tmp_path / "hrv" / "vetores" / "caso.h"
    assert "hrv/caso" in caminho.read_text(encoding="utf-8")


def test_exemplo_em_dia(tmp_path):
    """O exemplo versionado é o que o gerador produz hoje."""
    novo = vetores.gera_exemplo(testes=tmp_path).read_text(encoding="utf-8")
    versionado = (vetores.TESTES / "comum" / "vetores" / "exemplo.h").read_text(encoding="utf-8")
    assert novo == versionado, "rode: uv run python -m analise.vetores"
