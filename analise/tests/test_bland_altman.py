import numpy as np

from analise import bland_altman as ba


def test_viés_e_limites_de_concordancia():
    ecg = np.array([60.0, 70.0, 80.0, 90.0])
    c = ba.Concordancia.de(ecg + np.array([1.0, 3.0, 1.0, 3.0]), ecg)
    assert c.n == 4
    assert np.isclose(c.vies, 2.0)
    assert np.isclose(c.dp, np.std([1, 3, 1, 3], ddof=1))
    assert np.isclose(c.superior - c.vies, ba.Z95 * c.dp)
    assert np.isclose(c.vies - c.inferior, ba.Z95 * c.dp)


def test_ignora_pares_sem_medida():
    c = ba.Concordancia.de(np.array([61.0, np.nan, 82.0]), np.array([60.0, 70.0, 80.0]))
    assert c.n == 2
    assert np.isclose(c.vies, 1.5)


def test_poucos_pares_dao_nan():
    c = ba.Concordancia.de(np.array([61.0]), np.array([60.0]))
    assert c.n == 1 and np.isnan(c.vies)


def test_registro_limpo_concorda(tmp_path):
    pares = ba.pares_registro("s1_sit")
    cadeia, ecg = pares["bpm_picos"]
    assert abs(cadeia - ecg) < 3.0
    dados = {k: np.array([v]) for k, v in pares.items()} | {"registro": np.array(["s1_sit"])}
    assert ba.figura(dados, tmp_path / "ba.png").exists()
