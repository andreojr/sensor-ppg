"""Gerador da fonte falsa: um trecho do PhysioNet nos formatos da cadeia.

A fonte falsa é o "CD de teste" do grupo: um sinal real de PPG, gravado junto
com o ECG, cortado nos pontos da cadeia do ppg.h. Com ela cada módulo é
testado sem esperar o módulo anterior, e o resultado tem gabarito (o ECG).

Quatro saídas, do mesmo trecho de s1_sit:

  sensor_400hz    o que o nosso sensor entrega: IR e vermelho inteiros, a
                  400 Hz (reamostrados dos 500 Hz do dataset). Entrada da
                  decimação.
  bruto_100hz     saída da decimação: 100 Hz, com DC. Decimado pelo scipy
                  (FIR, fase zero), que é a referência da decimação nossa.
  filtrado_100hz  saída do filtro: passa-faixa 0,5 a 4 Hz pelo scipy, fase
                  zero (atraso 0). Referência do filtro nosso.
  batimentos      marcas de pico R do ECG, como ppg_batimento_t: n_pico a
                  100 Hz e rr_ms. Fazem o papel do módulo picos/ até ele
                  existir, e são o gabarito do BPM e do HRV.

Os picos são do ECG, não do PPG: a onda de pulso chega ao dedo uns 200 a
300 ms depois do pico R. Pra BPM e HRV só os intervalos importam, então tanto
faz; pra comparar o instante do pico do PPG com o ECG, lembrar desse atraso.

Uso (da pasta analise/):

  uv run python -m analise.fonte_falsa            vetores em testes/comum/vetores/
  uv run python -m analise.fonte_falsa --c PASTA  também os arrays C em PASTA

Os vetores são texto, uma amostra por linha, colunas separadas por espaço,
primeira linha com os nomes. Os arrays C são const float/uint32_t pra flash.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import signal

from analise import FS_HZ, physionet

FS_SENSOR_HZ = 400
INICIO_S = 30.0  # pula o começo da gravação
DURACAO_S = 60.0
DURACAO_SENSOR_S = 10.0  # o trecho a 400 Hz é só pra decimação; não precisa de 60 s
MARGEM_S = 5.0  # filtrado com sobra dos dois lados, depois cortada: sem transiente nas bordas
BANDA_HZ = (0.5, 4.0)
ORDEM_FILTRO = 2

RAIZ = Path(__file__).resolve().parents[3]
PASTA_VETORES = RAIZ / "testes" / "comum" / "vetores"


@dataclass(frozen=True)
class FonteFalsa:
    registro: str
    inicio_s: float
    sensor_ir: np.ndarray
    sensor_vermelho: np.ndarray
    bruto_ir: np.ndarray
    bruto_vermelho: np.ndarray
    filtrado_ir: np.ndarray
    filtrado_vermelho: np.ndarray
    n_pico: np.ndarray
    rr_ms: np.ndarray


def gera(
    r: physionet.Registro, inicio_s: float = INICIO_S, duracao_s: float = DURACAO_S
) -> FonteFalsa:
    # Recorta com margem; os filtros de fase zero (filtfilt) têm transiente nas
    # bordas, e a margem é descartada no fim.
    margem = min(MARGEM_S, inicio_s)
    largo = r.recorta(inicio_s - margem, inicio_s + duracao_s + margem)
    trecho = r.recorta(inicio_s, inicio_s + duracao_s)

    # 500 -> 400 Hz: reamostragem polifásica (sobe 4, desce 5). O sensor
    # entrega inteiros de 18 bits.
    n_sensor = round(DURACAO_SENSOR_S * r.fs_hz)
    sensor = [
        np.clip(np.round(signal.resample_poly(x[:n_sensor], FS_SENSOR_HZ, r.fs_hz)), 0, 2**18 - 1)
        for x in (trecho.ir, trecho.vermelho)
    ]

    # 500 -> 100 Hz: FIR anti-aliasing de fase zero e decimação por 5. A média
    # sai antes e volta depois, pra não vazar DC pelas bordas do FIR.
    fator = r.fs_hz // FS_HZ
    assert fator * FS_HZ == r.fs_hz, "a taxa do dataset tem que ser múltipla de 100 Hz"
    corte = slice(round(margem * FS_HZ), round(margem * FS_HZ) + round(duracao_s * FS_HZ))
    bruto_largo = [
        signal.resample_poly(x - x.mean(), 1, fator) + x.mean() for x in (largo.ir, largo.vermelho)
    ]
    bruto = [x[corte] for x in bruto_largo]

    # Passa-faixa 0,5 a 4 Hz, fase zero (filtfilt): atraso 0, média zero.
    sos = signal.butter(ORDEM_FILTRO, BANDA_HZ, btype="band", fs=FS_HZ, output="sos")
    filtrado = [signal.sosfiltfilt(sos, x - x.mean())[corte] for x in bruto_largo]

    # Picos do ECG na grade de 100 Hz. rr_ms do primeiro é 0 (não há anterior).
    n_pico = np.round(trecho.t_picos_ecg * FS_HZ).astype(np.uint32)
    rr_ms = np.concatenate([[0.0], np.diff(trecho.t_picos_ecg) * 1000.0])

    return FonteFalsa(
        registro=r.nome,
        inicio_s=inicio_s,
        sensor_ir=sensor[0],
        sensor_vermelho=sensor[1],
        bruto_ir=bruto[0],
        bruto_vermelho=bruto[1],
        filtrado_ir=filtrado[0],
        filtrado_vermelho=filtrado[1],
        n_pico=n_pico,
        rr_ms=rr_ms,
    )


def escreve_vetores(f: FonteFalsa, pasta: Path = PASTA_VETORES) -> list[Path]:
    """Um arquivo texto por saída, com cabeçalho. Lidos pelos testes em C."""
    pasta.mkdir(parents=True, exist_ok=True)
    cab = f"# {f.registro} de {f.inicio_s:g} s. Gerado por analise.fonte_falsa; não editar à mão.\n"
    arquivos = {
        "sensor_400hz.txt": (
            "n ir vermelho",
            np.column_stack([np.arange(len(f.sensor_ir)), f.sensor_ir, f.sensor_vermelho]),
            "%d %d %d",
        ),
        "bruto_100hz.txt": (
            "n ir vermelho",
            np.column_stack([np.arange(len(f.bruto_ir)), f.bruto_ir, f.bruto_vermelho]),
            "%d %.3f %.3f",
        ),
        "filtrado_100hz.txt": (
            "n ir vermelho",
            np.column_stack([np.arange(len(f.filtrado_ir)), f.filtrado_ir, f.filtrado_vermelho]),
            "%d %.3f %.3f",
        ),
        "batimentos.txt": ("n_pico rr_ms", np.column_stack([f.n_pico, f.rr_ms]), "%d %.1f"),
    }
    escritos = []
    for nome, (colunas, dados, fmt) in arquivos.items():
        caminho = pasta / nome
        with caminho.open("w", encoding="utf-8") as arq:
            arq.write(cab)
            arq.write(f"{colunas}\n")
            np.savetxt(arq, dados, fmt=fmt)
        escritos.append(caminho)
    return escritos


def _array_c(nome: str, tipo: str, valores: np.ndarray, fmt: str, por_linha: int = 8) -> str:
    linhas = [
        "    " + ", ".join(fmt % v for v in valores[i : i + por_linha]) + ","
        for i in range(0, len(valores), por_linha)
    ]
    return f"const {tipo} {nome}[{len(valores)}] = {{\n" + "\n".join(linhas) + "\n};\n"


def escreve_c(f: FonteFalsa, pasta: Path) -> tuple[Path, Path]:
    """fonte_dados.h e fonte_dados.c: arrays const pra flash. Quem liga é o firmware (#16)."""
    pasta.mkdir(parents=True, exist_ok=True)
    cab = (
        f"/* Gerado por analise.fonte_falsa a partir de {f.registro} ({f.inicio_s:g} s).\n"
        " * Não editar à mão: rode `uv run python -m analise.fonte_falsa --c <pasta>`. */\n"
    )
    h = pasta / "fonte_dados.h"
    c = pasta / "fonte_dados.c"
    h.write_text(
        cab
        + "#ifndef FONTE_DADOS_H\n#define FONTE_DADOS_H\n\n#include <stdint.h>\n\n"
        + f"#define FONTE_SENSOR_FS_HZ {FS_SENSOR_HZ}u\n"
        + f"#define FONTE_SENSOR_N {len(f.sensor_ir)}u\n"
        + f"#define FONTE_N {len(f.bruto_ir)}u\n"
        + f"#define FONTE_BATIMENTOS_N {len(f.n_pico)}u\n\n"
        + "/* Como o sensor entrega: contagens do ADC a FONTE_SENSOR_FS_HZ. */\n"
        + "extern const uint32_t fonte_sensor_ir[FONTE_SENSOR_N];\n"
        + "extern const uint32_t fonte_sensor_vermelho[FONTE_SENSOR_N];\n\n"
        + "/* Saída da decimação (com DC) e do filtro (0,5 a 4 Hz), a PPG_FS_HZ. */\n"
        + "extern const float fonte_bruto_ir[FONTE_N];\n"
        + "extern const float fonte_bruto_vermelho[FONTE_N];\n"
        + "extern const float fonte_filtrado_ir[FONTE_N];\n"
        + "extern const float fonte_filtrado_vermelho[FONTE_N];\n\n"
        + "/* Picos R do ECG: n a PPG_FS_HZ e intervalo até o anterior (0 no primeiro). */\n"
        + "extern const uint32_t fonte_batimento_n[FONTE_BATIMENTOS_N];\n"
        + "extern const float fonte_batimento_rr_ms[FONTE_BATIMENTOS_N];\n\n"
        + "#endif /* FONTE_DADOS_H */\n",
        encoding="utf-8",
    )
    c.write_text(
        cab
        + '#include "fonte_dados.h"\n\n'
        + _array_c("fonte_sensor_ir", "uint32_t", f.sensor_ir, "%du")
        + _array_c("fonte_sensor_vermelho", "uint32_t", f.sensor_vermelho, "%du")
        + _array_c("fonte_bruto_ir", "float", f.bruto_ir, "%.2ff")
        + _array_c("fonte_bruto_vermelho", "float", f.bruto_vermelho, "%.2ff")
        + _array_c("fonte_filtrado_ir", "float", f.filtrado_ir, "%.3ff")
        + _array_c("fonte_filtrado_vermelho", "float", f.filtrado_vermelho, "%.3ff")
        + _array_c("fonte_batimento_n", "uint32_t", f.n_pico, "%du")
        + _array_c("fonte_batimento_rr_ms", "float", f.rr_ms, "%.1ff"),
        encoding="utf-8",
    )
    return h, c


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--registro", default=physionet.REGISTRO_PADRAO)
    p.add_argument("--inicio", type=float, default=INICIO_S, help="início do trecho, em s")
    p.add_argument("--vetores", type=Path, default=PASTA_VETORES, help="pasta dos vetores de texto")
    p.add_argument("--c", type=Path, default=None, help="pasta pra fonte_dados.h e .c (opcional)")
    args = p.parse_args(argv)

    f = gera(physionet.carrega(args.registro), args.inicio)
    for caminho in escreve_vetores(f, args.vetores):
        print(caminho)
    if args.c:
        for caminho in escreve_c(f, args.c):
            print(caminho, f"({caminho.stat().st_size // 1024} KiB de texto)")

    flash = (2 * len(f.sensor_ir) + 2 * len(f.n_pico)) * 4 + 4 * len(f.bruto_ir) * 4
    print(
        f"{f.registro}: {len(f.bruto_ir) / FS_HZ:g} s a {FS_HZ} Hz, {len(f.sensor_ir) / FS_SENSOR_HZ:g} s a "
        f"{FS_SENSOR_HZ} Hz, {len(f.n_pico)} batimentos; ~{flash // 1024} KiB na flash"
    )


if __name__ == "__main__":
    main()
