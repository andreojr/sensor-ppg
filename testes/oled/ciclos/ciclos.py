# /// script
# requires-python = ">=3.12"
# dependencies = ["unicorn", "capstone"]
# ///
"""Custo de desenhar cada tela do display num Cortex-M4F, sem a placa: compila pro ARM, emula e conta.

O que faz:
  1. Compila o módulo oled/ (o mesmo código do firmware) pro Cortex-M4F com as flags do Release
     (-Os, FPU de hardware), junto com o bench_oled.c.
  2. Roda o código ARM no emulador Unicorn (baseado no QEMU): desenha cada tela e conta as
     instruções executadas.
  3. Estima os ciclos com um modelo simples do Cortex-M4F (ver custo() abaixo).
  4. Mostra quantas páginas do SSD1306 mudam de um quadro pro seguinte, que é o que decide
     quanto tempo o I2C fica ocupado (cada página são ~3 ms a 400 kHz).

O que NÃO mede: tempo real na placa. O modelo não conhece a espera da flash (o STM32F411 a
96 MHz tem 3 estados de espera, que o cache ART esconde em parte) nem a sobreposição de
instruções do pipeline: trate os ciclos como estimativa; a contagem de instruções é exata.

Uso (da raiz do repositório; precisa do arm-none-eabi-gcc no PATH):
  uv run testes/oled/ciclos/ciclos.py
"""

from __future__ import annotations

import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs
from unicorn import UC_ARCH_ARM, UC_HOOK_CODE, UC_HOOK_INTR, UC_MODE_MCLASS, UC_MODE_THUMB, Uc
from unicorn.arm_const import UC_ARM_REG_C1_C0_2, UC_ARM_REG_FPEXC, UC_ARM_REG_SP

RAIZ = Path(__file__).resolve().parents[3]
AQUI = Path(__file__).resolve().parent
MHZ = 96  # SYSCLK do firmware
FLAGS = ["-mcpu=cortex-m4", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard", "-mthumb", "-Os",
         "-ffunction-sections", "-fdata-sections", "-std=gnu11", "-ffp-contract=off"]
INCLUDES = [f"-I{RAIZ / 'Core' / 'Inc' / 'pds'}"]
FONTES = [RAIZ / "Core/Src/pds/oled/oled.c", RAIZ / "Core/Src/pds/oled/oled_telas.c",
          AQUI / "bench_oled.c"]
TELAS = ["principal", "resumo", "alvo", "sem dedo", "sinal ruim"]


def gcc(*args: str) -> None:
    subprocess.run(["arm-none-eabi-gcc", *args], check=True)


def compila(saida: Path) -> tuple[bytes, dict[str, int]]:
    objetos = []
    for fonte in FONTES:
        obj = saida / (fonte.stem + ".o")
        gcc(*FLAGS, *INCLUDES, "-c", str(fonte), "-o", str(obj))
        objetos.append(str(obj))
    elf = saida / "bench.elf"
    # A libm (floorf) pede a libc enxuta do firmware.
    gcc("-mcpu=cortex-m4", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard", "-mthumb",
        "--specs=nano.specs", "--specs=nosys.specs", "-nostartfiles", "-Wl,--gc-sections",
        f"-Wl,-T,{AQUI / 'm.ld'}", "-Wl,--undefined=entra_desenha", "-Wl,--undefined=entra_paginas",
        "-o", str(elf), *objetos, "-lm", "-lc", "-lgcc")
    imagem = saida / "bench.bin"
    subprocess.run(["arm-none-eabi-objcopy", "-O", "binary", str(elf), str(imagem)], check=True)
    nm = subprocess.check_output(["arm-none-eabi-nm", str(elf)], text=True)
    simbolos = {p[2]: int(p[0], 16) for p in (l.split() for l in nm.splitlines()) if len(p) == 3}
    return imagem.read_bytes(), simbolos


def custo(mn: str, ops: str) -> int:
    """Ciclos de uma instrução no Cortex-M4F (modelo simplificado do manual da ARM).

    1 ciclo na maioria; 2 pra load/store simples; 1 + n pros de vários registradores; 3 pra
    multiplica-e-soma de ponto flutuante; 14 pra VDIV/VSQRT; o ramo tomado entra à parte (+2).
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


def novo(imagem: bytes) -> Uc:
    uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    uc.mem_map(0, 0x40000)
    uc.mem_map(0x20000000, 0x20000)
    uc.mem_write(0, imagem)
    # A FPU do Cortex-M4 sai desligada; o firmware liga no SystemInit. Aqui, direto.
    uc.reg_write(UC_ARM_REG_C1_C0_2, 0xF00000)
    uc.reg_write(UC_ARM_REG_FPEXC, 0x40000000)
    return uc


class Contador:
    """Conta as instruções e os ciclos das execuções em que `ligado` é True.

    O gancho é instalado UMA vez e só a contagem liga e desliga: o Unicorn guarda os blocos já
    traduzidos, e um gancho montado e desmontado a cada execução deixa blocos sem contador, o
    que faz as execuções seguintes contarem só o que é novo.
    """

    def __init__(self, uc: Uc, md: Cs) -> None:
        self.md = md
        self.ligado = False
        self.instrucoes = 0
        self.ciclos = 0
        self.prox: int | None = None
        self.cache: dict[int, tuple[str, str, int]] = {}
        self.chegou = False
        uc.hook_add(UC_HOOK_CODE, self._gancho)
        uc.hook_add(UC_HOOK_INTR, self._bkpt)

    def _gancho(self, uc: Uc, endereco: int, tamanho: int, _: object) -> None:
        if not self.ligado:
            return
        if endereco not in self.cache:
            ins = next(self.md.disasm(bytes(uc.mem_read(endereco, tamanho)), endereco))
            self.cache[endereco] = (ins.mnemonic, ins.op_str, custo(ins.mnemonic, ins.op_str))
        if self.prox is not None and endereco != self.prox:
            self.ciclos += 2  # ramo tomado: o pipeline se reabastece
        self.prox = endereco + tamanho
        self.instrucoes += 1
        self.ciclos += self.cache[endereco][2]

    def _bkpt(self, uc: Uc, numero: int, _: object) -> None:
        self.chegou = True
        uc.emu_stop()

    def roda(self, uc: Uc, entrada: int, contar: bool) -> dict[str, int]:
        self.ligado, self.instrucoes, self.ciclos, self.prox, self.chegou = contar, 0, 0, None, False
        # O bench termina num BKPT em vez de retornar, então a pilha não volta sozinha.
        uc.reg_write(UC_ARM_REG_SP, 0x20020000)
        uc.emu_start(entrada | 1, 0x30000, count=20_000_000)  # |1: modo Thumb
        if not self.chegou:
            sys.exit("a execução não chegou ao BKPT: medida inválida")
        return {"instrucoes": self.instrucoes, "ciclos": self.ciclos}


def main() -> None:
    if shutil.which("arm-none-eabi-gcc") is None:
        sys.exit("arm-none-eabi-gcc não está no PATH (Arm GNU Toolchain)")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    with tempfile.TemporaryDirectory() as pasta:
        imagem, sim = compila(Path(pasta))
    uc = novo(imagem)
    ctr = Contador(uc, md)
    ctr.roda(uc, sim["entra_init"], False)

    def le(nome: str) -> int:
        return struct.unpack("<I", bytes(uc.mem_read(sim[nome], 4)))[0]

    def escreve(nome: str, v: int) -> None:
        uc.mem_write(sim[nome], struct.pack("<I", v))

    if le("ok") != 1:
        sys.exit("oled_init não rodou")
    print(f"imagem ARM: {len(imagem)} bytes\n")
    print(f"{'tela':<11} | {'instruções':>10} | {'ciclos (modelo)':>15} | {'tempo a 96 MHz':>14} | "
          f"{'págs. do 1º quadro':>18} | {'págs. do quadro seguinte':>24}")
    for c, nome in enumerate(TELAS):
        escreve("cenario", c)
        escreve("empurra", 0)
        ctr.roda(uc, sim["entra_paginas"], False)  # esvazia o que ficou do cenário anterior
        st = ctr.roda(uc, sim["entra_desenha"], True)
        ctr.roda(uc, sim["entra_paginas"], False)
        primeiro = le("paginas")
        escreve("empurra", 5)  # 20 quadros por segundo a 100 Hz: 5 amostras novas por quadro
        ctr.roda(uc, sim["entra_desenha"], False)
        ctr.roda(uc, sim["entra_paginas"], False)
        seguinte = le("paginas")
        print(f"{nome:<11} | {st['instrucoes']:>10,} | {st['ciclos']:>15,} | "
              f"{st['ciclos'] / MHZ:>11.0f} us | {primeiro:>18} | {seguinte:>24}")


if __name__ == "__main__":
    main()
