"""Referência da cadeia inteira (pds/cadeia/ no C), amostra a amostra.

Entra o bruto (saída da decimação, a 100 Hz, com DC) e saem as mesmas coisas
que a placa manda pela serial: batimentos (p,), BPM espectral (e,), HRV (h,),
respiração (r,), SpO2 estimada (s,) e o BPM que a tela mostra (t,). Os módulos
são os do Python que já existem; aqui só a ordem e as regras do laço, iguais às
do C:

    filtro -> picos -> espectral -> respiração -> spo2 -> qualidade

- SpO2: roda sobre o bruto (com DC), IR e vermelho; não depende de nenhum outro
  módulo (quem decide se ela aparece na tela é a qualidade, fora da cadeia).

- Batimento: guarda o BPM cru do picos e entra na fila do HRV com o julgamento
  da qualidade "de antes"; fila cheia solta o mais antigo direto pro HRV, com o
  RR de fora.
- Julgamento da qualidade: esvazia a fila no HRV (o RR entra se o picos aceitou
  e os julgamentos de antes e de agora dizem usável) e decide o BPM da tela
  (qualidade.bpm_confiavel).

Uso:
    uv run python -m analise.cadeia --vetores   # gera testes/cadeia/vetores/physionet.h
    uv run python -m analise.cadeia --replay dados/captura.csv

--replay passa o bruto que a placa mandou (linhas b,, desde o reset: comece a captura
e aperte o reset) pelo replay_cadeia (o C da cadeia, no PC) e confere, linha a linha,
se os resultados batem com os da placa: decisões iguais e números dentro de
COLUNAS_NUMERO. Com uma captura da versão anterior, é a prova de que reorganizar o
firmware não mudou nenhum resultado. A entrada é o bruto, e não as cruas, porque a
serial perde ~0,1% das cruas a 400 Hz (e a placa usou a amostra verdadeira).
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

from analise import espectral, filtro, hrv, picos, qualidade, respiracao, spo2

FS_HZ = 100
VETOR_INICIO_S = 60
VETOR_DURACAO_S = 90
TOL_VETOR = 0.01  # a maior entre as dos vetores dos módulos (picos e hrv; a do spo2 é 1e-3)


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


class Oxi(NamedTuple):
    """Linha s,: a SpO2 estimada (0 se inválida) e o R da janela."""

    n: int
    valido: bool
    spo2: float
    r: float


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
    spo2: list[Oxi] = field(default_factory=list)
    tela: list[Tela] = field(default_factory=list)


def roda(ir: np.ndarray, vm: np.ndarray) -> Saidas:
    """Passa o bruto (n = 0, 1, 2, ...) pela cadeia e devolve tudo o que saiu."""
    ir = np.asarray(ir, dtype=np.float64)
    vm = np.asarray(vm, dtype=np.float64)
    f_ir = filtro.filtra(ir)
    p, h, q, fila = picos.Picos(), hrv.Hrv(), qualidade.Qualidade(), qualidade.Fila()
    e, r, o2 = espectral.Espectral(), respiracao.Estimador(), spo2.Spo2()
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

        oxi = o2.processa(float(ir[n]), float(vm[n]))  # o bruto, não o filtrado
        if oxi is not None:
            s.spo2.append(Oxi(n, oxi.valido, oxi.spo2, oxi.r))

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
        "spo2_n": col(s.spo2, "n", np.int32),
        "spo2_valido": col(s.spo2, "valido", np.int32),
        "spo2_pct": col(s.spo2, "spo2", np.float32),
        "spo2_r": col(s.spo2, "r", np.float32),
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


# Tipos comparados e, em cada um, as colunas de número (com a tolerância); as outras
# (n, válidos, rr_usado, mostra) têm que ser iguais. A tolerância cobre o bruto da
# linha b, ter 2 casas (a placa passa o valor inteiro na cadeia): na captura de
# regressão da #17, a maior diferença foi 0,06 ms num rr_ms.
COLUNAS_NUMERO = {
    "picos": {1: 0.01, 3: 0.1, 5: 0.1},   # fracao, rr_ms, bpm
    "hrv": {2: 0.1, 3: 0.1},              # sdnn, rmssd
    "espectral": {2: 0.1},                # bpm
    "respiracao": {1: 0.1},               # rpm
    # A linha s, tem a spo2 com 2 casas e o R com 3: um arredondamento que vira no último
    # dígito (mais a folga do float na diferença).
    "spo2": {2: 0.02, 3: 0.002},          # spo2, r
    "tela": {2: 0.1},                     # bpm
}
REPLAY_BIN = Path(__file__).resolve().parents[3] / "build" / "testes" / "replay_cadeia"
SALTO_MAX = 64  # um n que pula mais que isso (ou volta sem ser reset) é linha embaralhada


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


def _igual(ponto: str, a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    if len(a) != len(b):
        return False
    tol = COLUNAS_NUMERO[ponto]
    return all(abs(x - y) <= tol.get(i, 0.0) for i, (x, y) in enumerate(zip(a, b, strict=True)))


def compara_replay(captura: Path, linhas: str) -> dict[str, int]:
    """Linhas refeitas que não batem com a captura, por tipo.

    Cada linha refeita é procurada na captura pela 1ª coluna (n ou n_pico), na última
    vez que ela aparece (a de depois do reset). Conta como diferente se faltar na
    captura ou se uma decisão mudar ou um número passar da tolerância. Linhas da
    captura sem par no refeito (antes do reset, ou depois do fim do bruto) não contam."""
    from analise import captura as cap

    with tempfile.TemporaryDirectory() as pasta:
        refeito = Path(pasta) / "replay.csv"
        cap.grava(_Texto(linhas), refeito)
        diferencas = {}
        for ponto in COLUNAS_NUMERO:
            original = cap.destino_ponto(captura, ponto)
            if not original.exists():
                continue
            ultima = {int(r[0]): r for r in _le_csv(original)}
            novo = cap.destino_ponto(refeito, ponto)
            b = _le_csv(novo) if novo.exists() else []
            diferencas[ponto] = sum(1 for r in b
                                    if int(r[0]) not in ultima or not _igual(ponto, ultima[int(r[0])], r))
    return diferencas


def bruto_desde_o_reset(captura: Path) -> list[tuple[int, float, float]]:
    """O bruto (linhas b,) que a placa mandou, a partir do último reset.

    Linha que a serial perdeu entra como a anterior repetida (o que a placa faz com as
    perdidas do sensor); linha embaralhada (n fora de sequência) é descartada."""
    from analise import captura as cap

    caminho = cap.destino_ponto(captura, "bruto")
    linhas = _le_csv(caminho) if caminho.exists() else []
    n = [int(r[0]) for r in linhas]
    resets = [k for k in range(len(n)) if n[k] == 0 and (k + 1 == len(n) or n[k + 1] == 1)]
    if not resets:
        raise ValueError(f"{captura}: a captura não pegou o reset da placa (nenhum n = 0 no "
                         "bruto); comece a captura e aperte o reset")
    saida: list[tuple[int, float, float]] = []
    for r in linhas[resets[-1]:]:
        k = int(r[0])
        if saida and not saida[-1][0] < k <= saida[-1][0] + SALTO_MAX:
            continue
        while saida and k > saida[-1][0] + 1:
            saida.append((saida[-1][0] + 1, saida[-1][1], saida[-1][2]))
        saida.append((k, r[1], r[2]))
    return saida


def replay(captura: Path, binario: Path = REPLAY_BIN) -> dict[str, int]:
    """Passa o bruto da placa (desde o reset) pela cadeia em C no PC e compara."""
    entrada = "".join(f"{n},{ir!r},{vm!r}\n" for n, ir, vm in bruto_desde_o_reset(captura))
    texto = subprocess.run([str(binario), "--bruto"], input=entrada, capture_output=True,
                           check=True, text=True).stdout
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
        try:
            diferencas = replay(args.replay, args.bin)
        except (ValueError, OSError) as e:
            raise SystemExit(f"FALHOU: {e}") from None
        for ponto, n in diferencas.items():
            print(f"{ponto}: {n} linhas diferentes")
        if not diferencas:
            print("nada pra comparar: a captura não tem as linhas de resultado")
        ok = bool(diferencas) and not any(diferencas.values())
        print("OK" if ok else "FALHOU")
        raise SystemExit(0 if ok else 1)
    if args.vetores:
        for caminho in gera_vetores():
            print(caminho)
        return
    p.print_help()


if __name__ == "__main__":
    main()
