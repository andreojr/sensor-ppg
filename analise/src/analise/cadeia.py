"""Referência da cadeia inteira (pds/cadeia/ no C), amostra a amostra.

Entra o bruto (saída da decimação, a 100 Hz, com DC) e saem as mesmas coisas
que a placa manda pela serial: batimentos (p,), BPM espectral (e,), HRV (h,),
respiração (r,) e o BPM que a tela mostra (t,). Os módulos são os do Python
que já existem; aqui só a ordem e as regras do laço, iguais às do C:

    filtro -> picos -> espectral -> respiração -> qualidade

- Batimento: guarda o BPM cru do picos e entra na fila do HRV com o julgamento
  da qualidade "de antes"; fila cheia solta o mais antigo direto pro HRV, com o
  RR de fora.
- Julgamento da qualidade: esvazia a fila no HRV (o RR entra se o picos aceitou
  e os julgamentos de antes e de agora dizem usável) e decide o BPM da tela
  (qualidade.bpm_confiavel).

Uso:
    uv run python -m analise.cadeia --vetores   # gera testes/cadeia/vetores/physionet.h
    uv run python -m analise.cadeia --replay dados/captura.csv

--replay passa as cruas de uma captura (feita com as cruas ligadas, apertando o
reset da placa depois de começar a captura) pelo replay_cadeia (o C da cadeia, no PC) e confere, linha a linha, se
os resultados batem com o que a placa mandou. É a prova de que reorganizar o
firmware não mudou nenhum número.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import numpy as np

from analise import espectral, filtro, hrv, picos, qualidade, respiracao

FS_HZ = 100
VETOR_INICIO_S = 60
VETOR_DURACAO_S = 90
TOL_VETOR = 0.01  # a maior entre as dos vetores do picos e do hrv (rr_ms, bpm, sdnn, rmssd)


class Bat(NamedTuple):
    """Linha p,: o batimento e o BPM cru do picos naquele instante."""

    n_pico: int
    fracao: float
    rr_valido: bool
    rr_ms: float
    bpm_valido: bool
    bpm: float


class Esp(NamedTuple):
    """Linha e,."""

    n: int
    valido: bool
    bpm: float


class Hrv(NamedTuple):
    """Linha h,."""

    n_pico: int
    valido: bool
    sdnn: float
    rmssd: float
    rr_usado: bool


class Resp(NamedTuple):
    """Linha r,."""

    n: int
    valido: bool
    rpm: float


class Tela(NamedTuple):
    """Linha t,: o BPM do picos só se a qualidade e o picos concordam (0 se não)."""

    n: int
    mostra: bool
    bpm: float


@dataclass
class Saidas:
    batimentos: list[Bat] = field(default_factory=list)
    espectral: list[Esp] = field(default_factory=list)
    hrv: list[Hrv] = field(default_factory=list)
    respiracao: list[Resp] = field(default_factory=list)
    tela: list[Tela] = field(default_factory=list)


def roda(ir: np.ndarray, vm: np.ndarray) -> Saidas:
    """Passa o bruto (n = 0, 1, 2, ...) pela cadeia e devolve tudo o que saiu."""
    ir = np.asarray(ir, dtype=np.float64)
    vm = np.asarray(vm, dtype=np.float64)
    f_ir = filtro.filtra(ir)
    p, h, q, fila = picos.Picos(), hrv.Hrv(), qualidade.Qualidade(), qualidade.Fila()
    e, r = espectral.Espectral(), respiracao.Estimador()
    s = Saidas()
    julg: tuple[int, bool] | None = None   # (n, usavel) do último julgamento
    ultimo: Bat | None = None             # último batimento, com o BPM cru

    def para_hrv(b: picos.Batimento, entra: bool) -> None:
        saida = h.processa(hrv.Batimento(True, b.n_pico, b.fracao, entra, b.rr_ms))
        if saida is not None:
            s.hrv.append(Hrv(b.n_pico, saida.valido, saida.sdnn_ms, saida.rmssd_ms, entra))

    for n in range(len(ir)):
        b = p.processa(float(f_ir[n]), n)
        if b is not None:
            bpm_valido, bpm = p.bpm
            ultimo = Bat(b.n_pico, b.fracao, b.rr_valido, b.rr_ms, bpm_valido, bpm)
            s.batimentos.append(ultimo)
            antes = julg is not None and qualidade.batimento_usavel(julg[1], True, julg[0], n)
            velho = fila.poe(b, antes)
            if velho is not None:
                para_hrv(velho, False)

        bpm_e = e.processa(float(f_ir[n]))
        if bpm_e is not None:
            s.espectral.append(Esp(bpm_e.n, bpm_e.valido, bpm_e.bpm))

        saiu, valido, rpm, _ = r.processa(float(ir[n]))
        if saiu:
            s.respiracao.append(Resp(n, valido, rpm))

        j = q.processa(n, float(ir[n]), float(vm[n]))
        if j is not None:
            julg = (n, j.usavel)
            for bat, entra in fila.tira(j.usavel):
                para_hrv(bat, entra)
            mostra = qualidade.bpm_confiavel(
                j.usavel, ultimo is not None and ultimo.bpm_valido, ultimo is not None, n,
                ultimo.n_pico if ultimo is not None else 0)
            s.tela.append(Tela(n, mostra, ultimo.bpm if mostra and ultimo else 0.0))
    return s


def arrays(s: Saidas) -> dict[str, np.ndarray]:
    """As saídas em colunas, com os nomes do vetor do teste em C."""
    def col(itens, campo, tipo):
        return np.array([getattr(i, campo) for i in itens], dtype=tipo)

    return {
        "bat_n_pico": col(s.batimentos, "n_pico", np.int32),
        "bat_fracao": col(s.batimentos, "fracao", np.float32),
        "bat_rr_valido": col(s.batimentos, "rr_valido", np.int32),
        "bat_rr_ms": col(s.batimentos, "rr_ms", np.float32),
        "bat_bpm_valido": col(s.batimentos, "bpm_valido", np.int32),
        "bat_bpm": col(s.batimentos, "bpm", np.float32),
        "esp_n": col(s.espectral, "n", np.int32),
        "esp_valido": col(s.espectral, "valido", np.int32),
        "esp_bpm": col(s.espectral, "bpm", np.float32),
        "hrv_n_pico": col(s.hrv, "n_pico", np.int32),
        "hrv_valido": col(s.hrv, "valido", np.int32),
        "hrv_sdnn": col(s.hrv, "sdnn", np.float32),
        "hrv_rmssd": col(s.hrv, "rmssd", np.float32),
        "hrv_rr_usado": col(s.hrv, "rr_usado", np.int32),
        "resp_n": col(s.respiracao, "n", np.int32),
        "resp_valido": col(s.respiracao, "valido", np.int32),
        "resp_rpm": col(s.respiracao, "rpm", np.float32),
        "tela_n": col(s.tela, "n", np.int32),
        "tela_mostra": col(s.tela, "mostra", np.int32),
        "tela_bpm": col(s.tela, "bpm", np.float32),
    }


def vetor_physionet(nome: str = "s1_sit") -> dict[str, np.ndarray]:
    """90 s de s1_sit a partir de 60 s, no nível do nosso sensor (como a qualidade)."""
    ir, vm = qualidade.registro_100hz(nome)
    a, b = VETOR_INICIO_S * FS_HZ, (VETOR_INICIO_S + VETOR_DURACAO_S) * FS_HZ
    ir, vm = qualidade.no_sensor(ir[a:b], vm[a:b])
    ir, vm = ir.astype(np.float32), vm.astype(np.float32)
    return {"ir": ir, "vermelho": vm, **arrays(roda(ir, vm))}


def gera_vetores(testes: Path | None = None) -> list[Path]:
    from analise import vetores

    testes = testes or vetores.TESTES
    return [
        vetores.gera_vetor("cadeia", "physionet", vetor_physionet(), tol=TOL_VETOR, testes=testes,
                           descricao=f"s1_sit de {VETOR_INICIO_S} a "
                                     f"{VETOR_INICIO_S + VETOR_DURACAO_S} s, no nível do sensor."),
    ]


# Tipo de linha -> CSV que o analise.captura grava ao lado do principal.
PONTOS_REPLAY = ("bruto", "filtrado", "picos", "hrv", "espectral", "respiracao", "tela")
REPLAY_BIN = Path(__file__).resolve().parents[3] / "build" / "testes" / "replay_cadeia"


class _Texto:
    """Fonte do analise.captura a partir de um texto (acaba com KeyboardInterrupt)."""

    def __init__(self, texto: str) -> None:
        self.linhas = iter(texto.splitlines())

    def readline(self) -> bytes:
        try:
            return next(self.linhas).encode()
        except StopIteration:
            raise KeyboardInterrupt from None


def _le_csv(caminho: Path) -> list[tuple[float, ...]]:
    with caminho.open(encoding="utf-8") as f:
        linhas = list(csv.reader(f))[1:]
    return [tuple(float(v) for v in ln) for ln in linhas]


def _depois_do_reset(linhas: list[tuple[float, ...]]) -> list[tuple[float, ...]]:
    """As linhas depois do último reset (o n da 1ª coluna volta), como picos.depois_do_reset."""
    voltas = [i for i in range(1, len(linhas)) if linhas[i][0] < linhas[i - 1][0]]
    return linhas[voltas[-1]:] if voltas else linhas


def compara_replay(captura: Path, linhas: str) -> dict[str, int]:
    """Linhas diferentes por tipo, entre os CSVs da captura e as linhas refeitas no PC.

    Só os tipos que a captura tem, e só depois do último reset da placa. A última linha de cada tipo pode faltar na captura
    (ela para no meio de uma amostra), então uma linha a mais no fim não conta."""
    from analise import captura as cap

    with tempfile.TemporaryDirectory() as pasta:
        refeito = Path(pasta) / "replay.csv"
        cap.grava(_Texto(linhas), refeito)
        diferencas = {}
        for ponto in PONTOS_REPLAY:
            original = cap.destino_ponto(captura, ponto)
            if not original.exists():
                continue
            a = _depois_do_reset(_le_csv(original))
            novo = cap.destino_ponto(refeito, ponto)
            b = _depois_do_reset(_le_csv(novo)) if novo.exists() else []
            comum = min(len(a), len(b))
            erradas = sum(1 for x, y in zip(a[:comum], b[:comum], strict=True)
                          if len(x) != len(y) or not np.allclose(x, y, rtol=0, atol=1e-9))
            diferencas[ponto] = erradas + max(0, abs(len(a) - len(b)) - 1)
    return diferencas


def replay(captura: Path, binario: Path = REPLAY_BIN) -> dict[str, int]:
    """Roda o replay_cadeia nas cruas da captura e compara (ver compara_replay).

    A captura tem que pegar o reset da placa (um n = 0): o estado dos módulos depende
    de tudo desde o boot. Comece a captura e aperte o reset."""
    with captura.open(encoding="utf-8") as f:
        tem_reset = any(ln.startswith("0,") for ln in f)
    if not tem_reset:
        raise ValueError(f"{captura}: a captura não pegou o reset da placa (nenhum n = 0); "
                         "comece a captura e aperte o reset")
    with captura.open("rb") as entrada:
        texto = subprocess.run([str(binario)], stdin=entrada, capture_output=True, check=True,
                               text=True).stdout
    return compara_replay(captura, texto)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--vetores", action="store_true", help="gera o vetor do teste em C")
    p.add_argument("--replay", type=Path, metavar="CAPTURA",
                   help="confere a captura contra o C da cadeia no PC")
    p.add_argument("--bin", type=Path, default=REPLAY_BIN,
                   help="o replay_cadeia (cmake --build build/testes)")
    args = p.parse_args(argv)
    if args.replay:
        diferencas = replay(args.replay, args.bin)
        for ponto, n in diferencas.items():
            print(f"{ponto}: {n} linhas diferentes")
        if not diferencas:
            print("nada pra comparar: a captura não tem as linhas de resultado")
        print("OK" if diferencas and not any(diferencas.values()) else "FALHOU")
        return
    if args.vetores:
        for caminho in gera_vetores():
            print(caminho)
        return
    p.print_help()


if __name__ == "__main__":
    main()
