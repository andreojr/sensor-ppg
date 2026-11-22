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
  6. Válido só se o pico é máximo local (maior ou igual aos dois vizinhos) e
     concentra potência suficiente (PROMINENCIA): o pico e seus vizinhos
     imediatos têm pelo menos essa fração do total da banda.

Resolução e atraso (estudado em espectral_validacao.py): a resolução de frequência é 1 / JANELA_S, e o BPM
medido é o da janela inteira, ou seja, vem com atraso de cerca de JANELA_S / 2.

Validação contra o ECG: uv run python -m analise.espectral_validacao
Vetores de referência pro teste em C (testes/espectral/vetores/), da pasta analise/:

    uv run python -m analise.espectral

Na placa (passo 5): captura com o analise.captura e confere o BPM da placa (linhas
"e,") com o Python sobre o mesmo filtrado e com o RR médio do picos na janela:

    uv run python -m analise.espectral --confere dados/sensor_<data>_<hora>.csv
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from analise import FS_HZ

JANELA_S = 8.0
HOP_S = 1.0
NFFT = 1024
BANDA_HZ = (0.7, 3.5)  # 42 a 210 bpm nominal; válido na prática de ~44 a ~208
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
        vizinhos = espectro[k - 1 : k + 2]
        # Na borda, um vizinho fica fora da banda: entra também no total, pra
        # prominência não passar de 1.
        total = banda.sum()
        if k == self.k0:
            total += vizinhos[0]
        if k == self.k1 - 1:
            total += vizinhos[2]
        prominencia = float(vizinhos.sum() / total)
        # O maior bin da banda só é pulso se for pico de verdade: na borda, o
        # vizinho de fora pode ser maior (um componente fora da banda vazando).
        # Sem isso, a parábola extrapola pra fora da banda e sai um BPM errado.
        maximo_local = bool(vizinhos[1] >= vizinhos[0] and vizinhos[1] >= vizinhos[2])

        # Vértice da parábola por (k-1, k, k+1), no log da amplitude.
        a, b, c = np.log(np.maximum(vizinhos, 1e-30)) / 2
        den = a - 2 * b + c
        d = 0.5 * (a - c) / den if den != 0 else 0.0
        f_hz = (k + d) * FS_HZ / self.nfft
        valido = maximo_local and prominencia >= self.prominencia
        # Inválido sai com bpm 0, como o picos_bpm(): o display mostra "--".
        return Bpm(self.n - 1, valido, 60.0 * f_hz if valido else 0.0, prominencia)


def estima(filtrado: np.ndarray, **parametros) -> list[Bpm]:
    """Roda o módulo num trecho e devolve todos os BPM."""
    e = Espectral(**parametros)
    return [r for x in filtrado if (r := e.processa(x)) is not None]


CASOS = (
    ("s1_sit", "limpo, sentado"),
    ("s2_walk", "artefato de movimento: BPM errado em parte das saídas"),
    ("borda", "sintético: silêncio e senoides perto das bordas da banda"),
)
VETOR_DURACAO_S = 60.0
# Caso "borda": 10 s de silêncio (banda sem potência) e 10 s de cada senoide.
# 0,55 e 3,6 Hz ficam fora da banda e vazam pro bin da borda (inválido); 0,8 e
# 3,3 Hz ficam dentro, perto da borda (válido). 3,8 Hz é a limitação conhecida:
# o pico verdadeiro está longe da borda e sobra na banda só o lóbulo lateral da
# Hann, que é pico local com prominência alta (sai válido, ~195 bpm).
BORDA_HZ = (0.55, 0.8, 3.3, 3.6, 3.8)


def entrada_borda() -> np.ndarray:
    n = np.arange(10 * FS_HZ)
    trechos = [np.zeros(len(n))]
    trechos += [100.0 * np.sin(2 * np.pi * f * n / FS_HZ) for f in BORDA_HZ]
    return np.concatenate(trechos).astype(np.float32)


def gera_vetores(testes: Path | None = None) -> list[Path]:
    """Grava testes/espectral/vetores/<caso>.h: entrada e o que o C tem que devolver."""
    from analise import fonte_falsa, physionet, vetores

    saidas = []
    for nome, descricao in CASOS:
        if nome == "borda":
            entrada = entrada_borda()
        else:
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
                descricao=f"{nome} ({descricao}): {len(entrada) / FS_HZ:g} s de entrada.",
                **extra,
            )
        )
    return saidas


def confere_placa(
    filtrado: np.ndarray,
    espectral_placa: np.ndarray,
    picos_placa: np.ndarray | None = None,
    atraso: int = 100,
) -> dict:
    """Compara o BPM da placa com o Python sobre o mesmo filtrado (e com o picos).

    filtrado: colunas n, ir, vermelho (o _filtrado.csv). espectral_placa: n,
    bpm_valido, bpm (o _espectral.csv). picos_placa: n_pico, ..., rr_ms, ... (o
    _picos.csv), opcional. Só entram as saídas com as 800 amostras da janela na
    captura (uma linha perdida na serial tira as janelas que a contêm). A placa
    manda o filtrado com 2 casas, então o BPM bate até ~0,01, não exato.
    atraso: PPG_ATRASO_AMOSTRAS, pra pôr a janela no tempo do n_pico do picos.
    """
    e = Espectral()
    ir = dict(zip(filtrado[:, 0].astype(int), filtrado[:, 1].astype(np.float32), strict=True))
    v_dif, bpm_dif, contra_picos, bpm_placa = 0, 0.0, [], []
    n_janelas = 0
    for n, valido, bpm in espectral_placa:
        idx = range(int(n) - e.n_janela + 1, int(n) + 1)
        if not all(k in ir for k in idx):
            continue
        n_janelas += 1
        py = e._estima(np.array([ir[k] for k in idx], dtype=np.float32))
        v_dif += int(bool(valido) != py.valido)
        bpm_dif = max(bpm_dif, abs(float(bpm) - float(py.bpm)))
        if not valido:
            continue
        bpm_placa.append(float(bpm))
        if picos_placa is not None:
            fim = n - atraso
            dentro = picos_placa[
                (picos_placa[:, 0] > fim - e.n_janela)
                & (picos_placa[:, 0] <= fim)
                & (picos_placa[:, 2] == 1)
            ]
            if len(dentro) >= 3:
                contra_picos.append(float(bpm) - 60000.0 / dentro[:, 3].mean())
    return {
        "saidas": len(espectral_placa),
        "janelas": n_janelas,
        "valido_diferente": v_dif,
        "bpm_dif_max": bpm_dif,
        "bpm_placa": np.array(bpm_placa),
        "contra_picos": np.array(contra_picos),
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--confere", type=Path, help="CSV da captura (com _filtrado, _espectral e _picos ao lado)"
    )
    args = ap.parse_args(argv)
    if not args.confere:
        for caminho in gera_vetores():
            print(caminho)
        return
    lado = args.confere.with_name
    arq = lado(args.confere.stem + "_espectral.csv")
    if not arq.exists():
        raise SystemExit(f"sem {arq.name}: a placa não mandou nenhuma linha e, (8 s de captura?)")
    arq_picos = lado(args.confere.stem + "_picos.csv")
    r = confere_placa(
        np.loadtxt(lado(args.confere.stem + "_filtrado.csv"), delimiter=",", skiprows=1),
        np.loadtxt(arq, delimiter=",", skiprows=1, ndmin=2),
        np.loadtxt(arq_picos, delimiter=",", skiprows=1, ndmin=2) if arq_picos.exists() else None,
    )
    print(f"{r['saidas']} saídas da placa, {r['janelas']} com a janela inteira na captura")
    print(
        f"placa x Python: valido diferente em {r['valido_diferente']}, maior diferença de bpm {r['bpm_dif_max']:.3f}"
    )
    b = r["bpm_placa"]
    if len(b):
        print(f"bpm válido da placa: mediana {np.median(b):.1f} (de {b.min():.1f} a {b.max():.1f})")
    c = r["contra_picos"]
    if len(c):
        print(
            f"espectral - picos (60 / RR médio na janela): {len(c)} janelas, "
            f"mediana |dif| {np.median(np.abs(c)):.2f} bpm, máx {np.abs(c).max():.2f}"
        )
    ok = r["janelas"] > 0 and r["valido_diferente"] == 0 and r["bpm_dif_max"] < 0.05
    print("OK" if ok else "FALHOU")


if __name__ == "__main__":
    main()
