"""Carregador do PhysioNet: Pulse Transit Time PPG Dataset.

https://physionet.org/content/pulse-transit-time-ppg/1.0.0/

22 pessoas x 3 atividades (sit, walk, run), MAX30101 a 500 Hz no dedo
indicador, com ECG de referência e as marcas de pico R conferidas à mão
(arquivo .atr). O MAX30101 é o MAX30102 com um LED verde a mais: mesmo ADC e
mesmo front-end, então o sinal tem a mesma cara do nosso.

Canais usados: pleth_1 (vermelho) e pleth_2 (IR), os dois da ponta do dedo
(falange distal), como no nosso sensor. A descrição do dataset se contradiz
sobre qual é qual; a razão das razões decide: com pleth_1 como vermelho a
SpO2 dá ~97%, trocado dá ~63%.

O download fica em analise/dados/physionet/ (no .gitignore) e só acontece na
primeira vez.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlretrieve

import numpy as np
import wfdb

URL = "https://physionet.org/files/pulse-transit-time-ppg/1.0.0"
REGISTRO_PADRAO = "s1_sit"
PASTA_PADRAO = Path(__file__).resolve().parents[2] / "dados" / "physionet"

CANAL_VERMELHO = "pleth_1"
CANAL_IR = "pleth_2"
CANAL_ECG = "ecg"


@dataclass(frozen=True)
class Registro:
    """Um trecho do dataset, pronto pra cadeia de PDS."""

    nome: str
    fs_hz: int
    """Taxa do PPG e do ECG, em Hz (500 no dataset)."""
    ir: np.ndarray
    """IR em contagens do ADC, com DC."""
    vermelho: np.ndarray
    """Vermelho em contagens do ADC, com DC."""
    ecg: np.ndarray
    """ECG em mV, só pra conferir."""
    picos_ecg: np.ndarray
    """Índices (a fs_hz) dos picos R do ECG, as marcas de batimento."""

    @property
    def duracao_s(self) -> float:
        return len(self.ir) / self.fs_hz

    @property
    def t(self) -> np.ndarray:
        """Tempo de cada amostra, em segundos."""
        return np.arange(len(self.ir)) / self.fs_hz

    @property
    def t_picos_ecg(self) -> np.ndarray:
        """Instante de cada batimento do ECG, em segundos."""
        return self.picos_ecg / self.fs_hz

    def recorta(self, inicio_s: float, fim_s: float) -> Registro:
        """Trecho entre inicio_s e fim_s. Os picos ficam relativos ao início."""
        a = round(inicio_s * self.fs_hz)
        b = round(fim_s * self.fs_hz)
        picos = self.picos_ecg[(self.picos_ecg >= a) & (self.picos_ecg < b)] - a
        return Registro(
            nome=self.nome,
            fs_hz=self.fs_hz,
            ir=self.ir[a:b],
            vermelho=self.vermelho[a:b],
            ecg=self.ecg[a:b],
            picos_ecg=picos,
        )


def registros() -> list[str]:
    """Nomes dos 66 registros (s1_sit, s1_walk, s1_run, s2_sit...)."""
    return [f"s{i}_{atividade}" for i in range(1, 23) for atividade in ("sit", "walk", "run")]


def baixa(nome: str = REGISTRO_PADRAO, pasta: Path = PASTA_PADRAO) -> Path:
    """Baixa .hea, .dat e .atr do registro, se ainda não estiverem na pasta."""
    pasta.mkdir(parents=True, exist_ok=True)
    for ext in ("hea", "dat", "atr"):
        arquivo = pasta / f"{nome}.{ext}"
        if not arquivo.exists():
            urlretrieve(f"{URL}/{arquivo.name}", arquivo)
    return pasta


def carrega(nome: str = REGISTRO_PADRAO, pasta: Path = PASTA_PADRAO) -> Registro:
    """Lê um registro (baixando na primeira vez) e devolve IR, vermelho, ECG e picos."""
    baixa(nome, pasta)
    return le_local(nome, pasta)


def le_local(nome: str, pasta: Path) -> Registro:
    """Lê um registro já baixado, sem acessar a rede."""
    caminho = str(pasta / nome)
    sinais = wfdb.rdrecord(caminho, channel_names=[CANAL_ECG, CANAL_VERMELHO, CANAL_IR])
    anotacoes = wfdb.rdann(caminho, "atr")

    # O .dat guarda 12 bits comprimidos; ganho e offset do cabeçalho (unidade
    # "NU") reconstroem a contagem do ADC de 18 bits em p_signal. É nessa
    # escala que o nosso sensor entrega.
    p = sinais.p_signal

    return Registro(
        nome=nome,
        fs_hz=int(sinais.fs),
        ir=p[:, 2],
        vermelho=p[:, 1],
        ecg=p[:, 0],
        picos_ecg=np.asarray(anotacoes.sample, dtype=np.int64),
    )
