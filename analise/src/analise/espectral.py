"""Protótipo do módulo espectral: BPM pelo pico da FFT, em janela deslizante.

Entrada: filtrado (0,5 a 4 Hz, média zero) a FS_HZ, uma amostra por vez. A cada
HOP_S, com a janela cheia, sai um ppg_bpm_t.

Método, a cada passo:
  1. Última janela de JANELA_S segundos, menos a média.
  2. Janela de Hann (sem ela, o corte da janela espalha o pico pelo espectro).
  3. Zero-padding até NFFT pontos: não dá informação nova, mas interpola o
     espectro e deixa o pico mais fácil de localizar.
  4. Maior pico de potência na banda BANDA_HZ.
  5. Interpolação parabólica em volta do pico: a frequência sai com precisão
     bem melhor que a distância entre bins.
  6. Válido só se o pico concentra potência suficiente (PROMINENCIA): dentro da
     banda, o pico e seus vizinhos imediatos têm pelo menos essa fração do total.

Resolução e atraso (estudado em espectral_validacao.py): a resolução de frequência é 1 / JANELA_S, e o BPM
medido é o da janela inteira, ou seja, vem com atraso de cerca de JANELA_S / 2.

Validação contra o ECG: uv run python -m analise.espectral_validacao
Vetores de referência pro teste em C (testes/espectral/vetores/), da pasta analise/:

    uv run python -m analise.espectral
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from analise import FS_HZ

JANELA_S = 8.0
HOP_S = 1.0
NFFT = 1024
BANDA_HZ = (0.7, 3.5)  # 42 a 210 bpm
PROMINENCIA = 0.3  # fração mínima da potência da banda no pico e vizinhos
TOL_VETOR = 1e-3  # tolerância dos floats no teste em C (bpm e prominência)


@dataclass(frozen=True)
class Bpm:
    """ppg_bpm_t mais o instante: n é a amostra em que a janela terminou.

    bpm é 0 quando valido é False.
    """

    n: int
    valido: bool
    bpm: float
    prominencia: float


class Espectral:
    def __init__(
        self,
        janela_s: float = JANELA_S,
        hop_s: float = HOP_S,
        nfft: int = NFFT,
        banda_hz: tuple[float, float] = BANDA_HZ,
        prominencia: float = PROMINENCIA,
    ) -> None:
        self.n_janela = round(janela_s * FS_HZ)
        self.hop = round(hop_s * FS_HZ)
        self.nfft = nfft
        if self.n_janela > nfft:
            raise ValueError("a janela tem mais amostras que a FFT")
        self.prominencia = prominencia
        self.hann = np.hanning(self.n_janela + 2)[1:-1].astype(np.float32)
        freqs = np.fft.rfftfreq(nfft, 1 / FS_HZ)
        self.k0 = int(np.searchsorted(freqs, banda_hz[0]))
        self.k1 = int(np.searchsorted(freqs, banda_hz[1]))
        self.reinicia()

    def reinicia(self) -> None:
        """espectral_init."""
        self.buffer = np.zeros(self.n_janela, dtype=np.float32)  # circular
        self.n = 0

    def processa(self, x: float) -> Bpm | None:
        """espectral_processa: devolve o BPM a cada hop, com a janela cheia."""
        self.buffer[self.n % self.n_janela] = x
        self.n += 1
        if self.n < self.n_janela or (self.n - self.n_janela) % self.hop:
            return None
        # Janela em ordem do tempo: a mais antiga primeiro.
        inicio = self.n % self.n_janela
        janela = np.roll(self.buffer, -inicio)
        return self._estima(janela)

    def _estima(self, janela: np.ndarray) -> Bpm:
        janela = (janela - janela.mean()) * self.hann
        espectro = np.abs(np.fft.rfft(janela, self.nfft)) ** 2
        banda = espectro[self.k0 : self.k1]
        if banda.sum() <= 0:
            return Bpm(self.n - 1, False, 0.0, 0.0)

        k = self.k0 + int(np.argmax(banda))
        k = min(max(k, 1), len(espectro) - 2)
        vizinhos = espectro[k - 1 : k + 2]
        prominencia = float(vizinhos.sum() / banda.sum())

        # Vértice da parábola por (k-1, k, k+1), no log da amplitude.
        a, b, c = np.log(np.maximum(vizinhos, 1e-30)) / 2
        den = a - 2 * b + c
        d = 0.5 * (a - c) / den if den != 0 else 0.0
        f_hz = (k + d) * FS_HZ / self.nfft
        valido = prominencia >= self.prominencia
        # Inválido sai com bpm 0, como o picos_bpm(): o display mostra "--".
        return Bpm(self.n - 1, valido, 60.0 * f_hz if valido else 0.0, prominencia)


def estima(filtrado: np.ndarray, **parametros) -> list[Bpm]:
    """Roda o módulo num trecho e devolve todos os BPM."""
    e = Espectral(**parametros)
    return [r for x in filtrado if (r := e.processa(x)) is not None]


CASOS = (
    ("s1_sit", "limpo, sentado"),
    ("s2_walk", "artefato de movimento: pico fraco, valido = false"),
)
VETOR_DURACAO_S = 60.0


def gera_vetores(testes: Path | None = None) -> list[Path]:
    """Grava testes/espectral/vetores/<caso>.h: entrada e o que o C tem que devolver."""
    from analise import fonte_falsa, physionet, vetores

    saidas = []
    for nome, descricao in CASOS:
        f = fonte_falsa.gera(physionet.carrega(nome), 30.0, VETOR_DURACAO_S)
        entrada = f.filtrado_ir.astype(np.float32)
        r = estima(entrada)
        arrays = {
            "entrada": entrada,
            "valido": [x.valido for x in r],
            "bpm": [x.bpm for x in r],
            "prominencia": [x.prominencia for x in r],
        }
        extra = {"testes": testes} if testes else {}
        saidas.append(
            vetores.gera_vetor(
                "espectral",
                nome,
                arrays,
                tol=TOL_VETOR,
                descricao=f"{nome} ({descricao}): {VETOR_DURACAO_S:g} s do filtrado_ir.",
                **extra,
            )
        )
    return saidas


if __name__ == "__main__":
    for caminho in gera_vetores():
        print(caminho)
