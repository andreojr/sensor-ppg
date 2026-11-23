"""A cadeia de referência (analise.cadeia) é a soma dos módulos, na ordem da placa."""

import re
from pathlib import Path

import numpy as np
import pytest

from analise import cadeia, espectral, filtro, picos, qualidade, respiracao, vetores

FS = 100


def sinal(dur_s: float = 90.0, bpm: float = 72.0) -> tuple[np.ndarray, np.ndarray]:
    """PPG sintético no nível do sensor: pulso gaussiano e respiração a 15 rpm (com
    entalhe dicrótico o picos vê batimento duplo e o BPM nunca fica válido)."""
    t = np.arange(round(dur_s * FS)) / FS
    fase = (t * bpm / 60.0) % 1.0
    pulso = np.exp(-(((fase - 0.2) / 0.07) ** 2))
    resp = 1.0 + 0.003 * np.sin(2 * np.pi * 0.25 * t)
    ir = 130_000.0 * resp + 600.0 * pulso
    vm = 137_000.0 * resp + 500.0 * pulso
    return ir.astype(np.float32), vm.astype(np.float32)


@pytest.fixture(scope="module")
def caso():
    ir, vm = sinal()
    return ir, vm, cadeia.roda(ir, vm)


def test_batimentos_iguais_ao_picos(caso):
    ir, _, s = caso
    esperados, _ = picos.detecta(filtro.filtra(ir))
    assert len(s.batimentos) > 50
    assert [b.n_pico for b in s.batimentos] == [b.n_pico for b in esperados]
    assert [b.rr_valido for b in s.batimentos] == [b.rr_valido for b in esperados]


def test_hrv_usa_a_fila(caso):
    ir, vm, s = caso
    n = np.arange(len(ir))
    bruto = np.column_stack([n, ir, vm])
    filtrado = np.column_stack([n, filtro.filtra(ir), filtro.filtra(vm)])
    entrou = qualidade.rr_entrou_no_hrv(bruto, filtrado)
    assert len(s.hrv) > 50
    assert {h.n_pico: h.rr_usado for h in s.hrv} == entrou


def test_tela_segue_a_regra(caso):
    ir, vm, s = caso
    julgamentos = qualidade.roda(ir, vm)
    assert [t.n for t in s.tela] == [j.n for j in julgamentos]
    assert any(t.mostra for t in s.tela)
    # O último batimento que já tinha SAÍDO do picos em cada n (sai depois do n_pico).
    p, ultimo, ate = picos.Picos(), {}, None
    for n, x in enumerate(filtro.filtra(ir)):
        if p.processa(float(x), n) is not None:
            ate = (p.ultimo.n_pico, *p.bpm)
        ultimo[n] = ate
    for t, j in zip(s.tela, julgamentos, strict=True):
        u = ultimo[t.n]
        esperado = qualidade.bpm_confiavel(j.usavel, u is not None and u[1], u is not None, t.n,
                                           u[0] if u else 0)
        assert t.mostra == esperado, t.n
        assert t.bpm == (u[2] if t.mostra else 0.0)


def test_espectral_e_respiracao_iguais_aos_modulos(caso):
    ir, _, s = caso
    esperado = espectral.estima(filtro.filtra(ir))
    assert [(e.n, e.valido, e.bpm) for e in s.espectral] == [(e.n, e.valido, e.bpm) for e in esperado]
    resp = respiracao.estima(ir)
    assert [(r.n, r.valido, r.rpm) for r in s.respiracao] == [
        (int(i), bool(v), float(rpm)) for i, v, rpm, _ in resp]


def test_vetor_em_dia():
    """O Python de hoje, na entrada gravada no vetor, dá a saída gravada (sem PhysioNet)."""
    caminho = vetores.TESTES / "cadeia" / "vetores" / "physionet.h"
    a = _le_vetor(caminho)
    s = cadeia.roda(a["ir"].astype(np.float32), a["vermelho"].astype(np.float32))
    for nome, valores in cadeia.arrays(s).items():
        assert np.allclose(a[nome], np.asarray(valores, dtype=np.float32), rtol=1e-6), nome


def _le_vetor(caminho: Path) -> dict[str, np.ndarray]:
    texto = caminho.read_text(encoding="utf-8")
    caso = caminho.stem
    arrays = {}
    for nome, corpo in re.findall(rf"static const \w+ {caso}_(\w+)\[\d+\] = \{{(.*?)\}};",
                                  texto, re.DOTALL):
        arrays[nome] = np.array([float(v.rstrip("f")) for v in corpo.split(",") if v.strip()])
    return arrays


# ---- Replay: a cadeia refeita no PC a partir do bruto da placa -------------------

LINHAS_PLACA = (
    "b,0,100.00,200.00\n"
    "p,120,0.2500,1,812.50,1,73.85\n"
    "h,120,1,41.50,30.25,1\n"
    "e,800,1,72.10\n"
    "r,2400,15.20,1\n"
    "t,99,1,7385\n"
)
TIPOS = {"picos": 0, "hrv": 0, "espectral": 0, "respiracao": 0, "tela": 0}


def _captura(pasta: Path, linhas: str) -> Path:
    """Grava os CSVs que o analise.captura gravaria com essas linhas da placa."""
    from analise import captura

    destino = pasta / "cap.csv"
    captura.grava(cadeia._Texto(linhas), destino)
    return destino


def test_compara_replay_igual(tmp_path):
    destino = _captura(tmp_path, LINHAS_PLACA)
    assert cadeia.compara_replay(destino, LINHAS_PLACA) == TIPOS


def test_compara_replay_decisao_diferente(tmp_path):
    destino = _captura(tmp_path, LINHAS_PLACA)
    trocado = LINHAS_PLACA.replace("p,120,0.2500,1,", "p,120,0.2500,0,")
    assert cadeia.compara_replay(destino, trocado)["picos"] == 1


def test_compara_replay_numero_na_tolerancia(tmp_path):
    # O bruto da linha b, tem 2 casas: o número refeito pode mudar um pouco.
    destino = _captura(tmp_path, LINHAS_PLACA)
    perto = LINHAS_PLACA.replace("812.50", "812.55").replace("0.2500", "0.2560")
    assert cadeia.compara_replay(destino, perto)["picos"] == 0
    longe = LINHAS_PLACA.replace("812.50", "813.50")
    assert cadeia.compara_replay(destino, longe)["picos"] == 1


def test_compara_replay_conta_o_que_falta_na_captura(tmp_path):
    destino = _captura(tmp_path, LINHAS_PLACA)
    assert cadeia.compara_replay(destino, LINHAS_PLACA + "t,199,0,0\n")["tela"] == 1


def test_compara_replay_pre_reset_com_mesmo_n(tmp_path):
    # Antes do reset, uma tela no mesmo n: vale a de depois (a última no arquivo).
    destino = _captura(tmp_path, "t,99,0,0\np,120,0.1000,0,0.00,0,0.00\n" + LINHAS_PLACA)
    assert cadeia.compara_replay(destino, LINHAS_PLACA) == TIPOS


def test_compara_replay_formato_diferente(tmp_path):
    destino = _captura(tmp_path, LINHAS_PLACA)
    cadeia_ponto(destino, "hrv").write_text(
        "n_pico,valido,sdnn_ms,rmssd_ms\n120,1,41.5,30.25\n", encoding="utf-8")
    assert cadeia.compara_replay(destino, LINHAS_PLACA)["hrv"] == 1


def _bruto(pasta: Path, linhas: str) -> Path:
    destino = pasta / "cap.csv"
    destino.write_text("n,ir,vermelho\n", encoding="utf-8")
    cadeia_ponto(destino, "bruto").write_text("n,ir,vermelho\n" + linhas, encoding="utf-8")
    return destino


def test_bruto_desde_o_reset_corta_e_preenche(tmp_path):
    destino = _bruto(tmp_path, "4000,9,9\n4001,9,9\n0,1.5,2.5\n1,3.0,4.0\n3,5.0,6.0\n")
    # A linha 2 a serial perdeu: entra a anterior repetida (como a placa faz com as perdidas).
    assert cadeia.bruto_desde_o_reset(destino) == [
        (0, 1.5, 2.5), (1, 3.0, 4.0), (2, 3.0, 4.0), (3, 5.0, 6.0)]


def test_bruto_desde_o_reset_ignora_linha_embaralhada(tmp_path):
    # "419,..." que chegou como "19,..." (visto na captura da #17): o n volta sem ser
    # reset (não vem 20 depois), então é lixo; e um salto além de SALTO_MAX também.
    linhas = "".join(f"{n},{n},{n}\n" for n in range(418)) + "19,7,7\n418,1,1\n9999,5,5\n419,2,2\n"
    destino = _bruto(tmp_path, linhas)
    assert [r[0] for r in cadeia.bruto_desde_o_reset(destino)] == list(range(420))


def test_bruto_desde_o_reset_sem_reset_recusa(tmp_path):
    destino = _bruto(tmp_path, "7,1,2\n8,1,2\n")
    with pytest.raises(ValueError, match="reset"):
        cadeia.bruto_desde_o_reset(destino)


def test_main_sem_nada_pra_comparar_falha(tmp_path, capsys, monkeypatch):
    cruas = tmp_path / "cap.csv"
    cruas.write_text("n,ir,vermelho\n0,1,2\n", encoding="utf-8")
    monkeypatch.setattr(cadeia, "replay", lambda *_: {})
    cadeia.main(["--replay", str(cruas)])
    assert "FALHOU" in capsys.readouterr().out


def cadeia_ponto(destino: Path, ponto: str) -> Path:
    from analise import captura

    return captura.destino_ponto(destino, ponto)
