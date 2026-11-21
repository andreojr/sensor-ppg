# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy", "unicorn", "capstone"]
# ///
"""Custo da FFT do CMSIS num Cortex-M4F, sem a placa: compila pro ARM, emula e conta.

O que faz:
  1. Compila o fft.c e o CMSIS-DSP (os mesmos arquivos do firmware) pro Cortex-M4F
     com as flags do Release (-Os, FPU de hardware), junto com o bench.c.
  2. Roda o código ARM no emulador Unicorn (baseado no QEMU) pra cada tamanho de
     FFT, com um sinal conhecido.
  3. Confere que a saída é a mesma do NumPy (se não for, a medida não vale).
  4. Conta as instruções executadas e estima os ciclos com um modelo simples do
     Cortex-M4F (ver custo() abaixo).

O que NÃO mede: tempo real na placa. O modelo não conhece a espera da flash
(o STM32F411 a 96 MHz tem 3 estados de espera, que o cache ART esconde em parte)
nem a sobreposição de instruções do pipeline. Trate os ciclos como estimativa; a
contagem de instruções é exata. A medida de verdade é com o contador de ciclos da
placa (DWT->CYCCNT).

Uso (da raiz do repositório; precisa do arm-none-eabi-gcc no PATH):
  uv run testes/fft/ciclos/ciclos.py
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_HOOK_INTR, UC_MODE_MCLASS, UC_MODE_THUMB, Uc
from unicorn.arm_const import UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_SP

RAIZ = Path(__file__).resolve().parents[3]
AQUI = Path(__file__).resolve().parent
DSP = RAIZ / "Drivers" / "CMSIS" / "DSP"
FS_HZ = 100  # igual a PPG_FS_HZ
TAMANHOS = (256, 512, 1024)
ORCAMENTO = 96_000_000 // FS_HZ  # ciclos por amostra: 96 MHz / 100 Hz

FLAGS = ["-mcpu=cortex-m4", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard", "-mthumb", "-Os",
         "-ffunction-sections", "-fdata-sections", "-std=gnu11"]
INCLUDES = [f"-I{DSP / 'Include'}", f"-I{RAIZ / 'Drivers' / 'CMSIS' / 'Include'}",
            f"-I{RAIZ / 'Core' / 'Inc' / 'pds'}"]


def gcc(*args: str) -> None:
    subprocess.run(["arm-none-eabi-gcc", *args], check=True)


def compila(saida: Path) -> tuple[bytes, dict[str, int]]:
    objetos = []
    fontes = [*sorted((DSP / "Source").glob("*/*.c")), RAIZ / "Core/Src/pds/fft/fft.c", AQUI / "bench.c"]
    for fonte in fontes:
        obj = saida / (fonte.stem + ".o")
        extra = ["-w"] if DSP in fonte.parents else []
        gcc(*FLAGS, *extra, *INCLUDES, "-c", str(fonte), "-o", str(obj))
        objetos.append(str(obj))
    elf = saida / "bench.elf"
    gcc("-mcpu=cortex-m4", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard", "-mthumb", "-nostdlib",
        "-nostartfiles", "-Wl,--gc-sections", f"-Wl,-T,{AQUI / 'm.ld'}", "-Wl,--undefined=entra_fft",
        "-o", str(elf), *objetos, "-lgcc")
    imagem = saida / "bench.bin"
    subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", str(elf), str(imagem)], check=True)
    nm = subprocess.check_output(["arm-none-eabi-nm", str(elf)], text=True)
    simbolos = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return imagem.read_bytes(), simbolos


def custo(mn: str, ops: str) -> int:
    """Ciclos de uma instrução no Cortex-M4F (modelo simplificado do manual da ARM).

    1 ciclo na maioria; 2 pra load/store simples; 1 + n pros de vários registradores;
    3 pra multiplica-e-soma de ponto flutuante (VFMA e parentes); 14 pra VDIV/VSQRT.
    O ramo tomado entra à parte (+2, o pipeline se reabastece).
    """
    if mn.startswith(("vdiv", "vsqrt")):
        return 14
    if mn.startswith(("vfma", "vfms", "vfnma", "vfnms", "vmla", "vmls", "vnmla", "vnmls")):
        return 3
    if mn.startswith(("vldm", "vstm", "vpush", "vpop", "ldm", "stm", "push", "pop")):
        return 1 + max(1, ops.count(",") + 1 - 1)
    if mn.startswith(("ldr", "str", "vldr", "vstr")):
        return 2
    if mn.startswith(("sdiv", "udiv")):
        return 6
    return 1


def novo(imagem: bytes, simbolos: dict[str, int], n: int) -> Uc:
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    uc.mem_map(0, 0x40000)
    uc.mem_map(0x20000000, 0x20000)
    uc.mem_write(0, imagem)
    uc.reg_write(UC_ARM_REG_SP, 0x20020000)
    # A FPU do Cortex-M4 sai desligada; o firmware liga no SystemInit. Aqui, direto.
    uc.reg_write(UC_ARM_REG_C1_C0_2, 0xF00000)
    uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
    uc.mem_write(simbolos["n_cfg"], struct.pack("<I", n))
    return uc


def roda(uc: Uc, entrada: int, contar: bool, md: Cs) -> dict[str, int]:
    st = {"instrucoes": 0, "ciclos": 0, "ramos": 0, "fp": 0, "mem": 0}
    prox: list[int | None] = [None]
    cache: dict[int, tuple[str, str, int]] = {}

    def gancho(uc: Uc, endereco: int, tamanho: int, _: object) -> None:
        if endereco not in cache:
            ins = next(md.disasm(bytes(uc.mem_read(endereco, tamanho)), endereco))
            cache[endereco] = (ins.mnemonic, ins.op_str, custo(ins.mnemonic, ins.op_str))
        mn, ops, c = cache[endereco]
        if prox[0] is not None and endereco != prox[0]:
            st["ciclos"] += 2
            st["ramos"] += 1
        prox[0] = endereco + tamanho
        st["instrucoes"] += 1
        st["ciclos"] += c
        st["fp"] += mn.startswith("v") and not mn.startswith(("vldr", "vstr", "vpush", "vpop", "vldm", "vstm", "vmov"))
        st["mem"] += mn.startswith(("ldr", "str", "vldr", "vstr", "ldm", "stm", "push", "pop", "vpush", "vpop", "vldm", "vstm"))

    h = uc.hook_add(UC_HOOK_CODE, gancho) if contar else None
    chegou: list[int] = []
    uc.hook_add(UC_HOOK_INTR, lambda u, n, _: (chegou.append(1), u.emu_stop()))
    uc.emu_start(entrada | 1, 0x30000, count=5_000_000)  # |1: modo Thumb
    if h is not None:
        uc.hook_del(h)
    if not chegou:
        sys.exit("a execução não chegou ao BKPT: medida inválida")
    return st


def sinal(n: int) -> np.ndarray:
    """O mesmo sinal de analise.fft_vetores.sinal: duas senoides e ruído."""
    rng = np.random.default_rng(25 + n)
    t = np.arange(n) / FS_HZ
    x = np.sin(2 * np.pi * 1.2 * t) + 0.5 * np.sin(2 * np.pi * 2.5 * t) + 0.1 * rng.standard_normal(n)
    return x.astype(np.float32)


def main() -> None:
    if shutil.which("arm-none-eabi-gcc") is None:
        sys.exit("arm-none-eabi-gcc não está no PATH (Arm GNU Toolchain)")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    with tempfile.TemporaryDirectory() as pasta:
        imagem, simbolos = compila(Path(pasta))

    print(f"imagem ARM: {len(imagem)} bytes (código + tabelas), orçamento {ORCAMENTO:,} ciclos por amostra\n")
    print(f"{'n':>5} | {'instruções':>10} | {'ciclos (modelo)':>15} | {'% do orçamento':>14} | "
          f"{'ramos':>6} | {'FP':>6} | {'mem':>6} | erro vs NumPy")
    for n in TAMANHOS:
        uc = novo(imagem, simbolos, n)
        roda(uc, simbolos["entra_init"], False, md)
        if struct.unpack("<I", bytes(uc.mem_read(simbolos["ok"], 4)))[0] != 1:
            sys.exit(f"fft_init({n}) recusou o tamanho")
        x = sinal(n)
        uc.mem_write(simbolos["x"], x.tobytes())
        st = roda(uc, simbolos["entra_fft"], True, md)
        obtido = np.frombuffer(bytes(uc.mem_read(simbolos["x"], 4 * (n // 2 + 1))), dtype=np.float32)
        esperado = np.abs(np.fft.rfft(x.astype(np.float64))) ** 2
        erro = float(np.max(np.abs(obtido - esperado)) / esperado.max())
        if erro > 1e-5:
            sys.exit(f"n={n}: a saída do código ARM não bate com o NumPy (erro {erro:.1e})")
        print(f"{n:>5} | {st['instrucoes']:>10,} | {st['ciclos']:>15,} | "
              f"{100 * st['ciclos'] / ORCAMENTO:>13.1f}% | {st['ramos']:>6,} | {st['fp']:>6,} | "
              f"{st['mem']:>6,} | {erro:.1e}")


if __name__ == "__main__":
    main()
