"""Vetores de referência do módulo fft: o NumPy é o gabarito da FFT do CMSIS.

Cada caso é uma entrada real de n pontos e o espectro de potência |X[k]|^2, k = 0
a n/2, dividido por n^2 pra ficar numa escala em que a tolerância absoluta serve
(o pico de uma senoide de amplitude 1 vale 0,25). O teste em C
(testes/fft/teste_fft.c) roda fft_potencia() sobre a mesma entrada, divide por
n^2 e compara.

Casos:
  n256, n512, n1024  duas senoides (1,2 e 2,5 Hz) e ruído, sem janela
  ppg1024            8 s do filtrado de s1_sit: média fora, janela de Hann,
                     amplitude normalizada e zero-padding até 1024, como o espectral usa

Uso (da pasta analise/):  uv run python -m analise.fft_vetores
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from analise import FS_HZ, vetores

TOL = 1e-5  # absoluta, sobre a potência dividida por n^2
SEMENTE = 25


def potencia(entrada: np.ndarray) -> np.ndarray:
    """|X[k]|^2 / n^2, k = 0 a n/2, em float32 (o gabarito da FFT do C)."""
    x = entrada.astype(np.float64)
    return (np.abs(np.fft.rfft(x)) ** 2 / len(x) ** 2).astype(np.float32)


def sinal(n: int) -> np.ndarray:
    rng = np.random.default_rng(SEMENTE + n)
    t = np.arange(n) / FS_HZ
    x = (
        np.sin(2 * np.pi * 1.2 * t)
        + 0.5 * np.sin(2 * np.pi * 2.5 * t)
        + 0.1 * rng.standard_normal(n)
    )
    return x.astype(np.float32)


def ppg1024() -> np.ndarray:
    from analise import fonte_falsa, physionet

    f = fonte_falsa.gera(physionet.carrega("s1_sit"), 30.0, 60.0)
    janela = f.filtrado_ir[: 8 * FS_HZ].astype(np.float64)
    janela = (janela - janela.mean()) * np.hanning(len(janela) + 2)[1:-1]
    janela /= np.abs(janela).max()  # amplitude 1, como os outros casos (a tolerância é absoluta)
    return np.pad(janela, (0, 1024 - len(janela))).astype(np.float32)


def casos() -> dict[str, tuple[np.ndarray, str]]:
    return {
        "n256": (sinal(256), "duas senoides e ruído, 256 pontos"),
        "n512": (sinal(512), "duas senoides e ruído, 512 pontos"),
        "n1024": (sinal(1024), "duas senoides e ruído, 1024 pontos"),
        "ppg1024": (ppg1024(), "8 s do s1_sit com Hann e zero-padding até 1024"),
    }


def gera_vetores(testes: Path | None = None) -> list[Path]:
    saidas = []
    for nome, (entrada, descricao) in casos().items():
        extra = {"testes": testes} if testes else {}
        saidas.append(
            vetores.gera_vetor(
                "fft",
                nome,
                {"entrada": entrada, "potencia": potencia(entrada)},
                tol=TOL,
                descricao=descricao,
                **extra,
            )
        )
    return saidas


if __name__ == "__main__":
    for caminho in gera_vetores():
        print(caminho)
