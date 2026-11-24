# /// script
# requires-python = ">=3.12"
# dependencies = ["unicorn", "capstone"]
# ///
"""Custo do spo2 num Cortex-M4F, sem a placa: compila pro ARM, emula, confere com o Python e conta.

O que faz:
  1. Compila o módulo spo2/ (o mesmo código do firmware) pro Cortex-M4F com as flags do Release
     (-Os, FPU de hardware), junto com o bench_spo2.c.
  2. Roda o código ARM no emulador Unicorn (baseado no QEMU) sobre as 4 000 amostras do vetor
     sem_dedo (40 s), uma chamada por amostra.
  3. Confere cada saída (valido e spo2) com a do vetor, que veio do Python: se não bater, a medida não vale.
  4. Conta as instruções e estima os ciclos com um modelo simples do Cortex-M4F (ver custo()).

O que NÃO mede: tempo real na placa. O modelo não conhece a espera da flash (o STM32F411 a 96 MHz
tem 3 estados de espera, que o cache ART esconde em parte) nem a sobreposição de instruções do
pipeline: trate os ciclos como estimativa; a contagem de instruções é exata.

Uso (da raiz do repositório; precisa do arm-none-eabi-gcc no PATH):
  uv run testes/spo2/ciclos/ciclos.py
"""

from __future__ import annotations

import re
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
ORCAMENTO = 9600  # 1% da CPU por amostra a 100 Hz: 96 MHz / 100 Hz / 100
FLAGS = ["-mcpu=cortex-m4", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard", "-mthumb", "-Os",
         "-ffunction-sections", "-fdata-sections", "-std=gnu11", "-ffp-contract=off"]
INCLUDES = [f"-I{RAIZ / 'Core' / 'Inc' / 'pds'}", f"-I{RAIZ / 'testes'}"]
FONTES = [RAIZ / "Core/Src/pds/spo2/spo2.c", AQUI / "bench_spo2.c"]
VETOR = RAIZ / "testes/spo2/vetores/sem_dedo.h"


def gcc(*args: str) -> None:
    subprocess.run(["arm-none-eabi-gcc", *args], check=True)


def compila(saida: Path) -> tuple[bytes, dict[str, int]]:
    objetos = []
    for fonte in FONTES:
        obj = saida / (fonte.stem + ".o")
        gcc(*FLAGS, *INCLUDES, "-c", str(fonte), "-o", str(obj))
        objetos.append(str(obj))
    elf = saida / "bench.elf"
    # A libm (sqrtf) pede a libc enxuta do firmware.
    gcc("-mcpu=cortex-m4", "-mfpu=fpv4-sp-d16", "-mfloat-abi=hard", "-mthumb",
        "--specs=nano.specs", "--specs=nosys.specs", "-nostartfiles", "-Wl,--gc-sections",
        f"-Wl,-T,{AQUI / 'm.ld'}", "-Wl,--undefined=entra_amostra",
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
    traduzidos, e um gancho montado e desmontado a cada execução deixa blocos sem contador.
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


def le_vetor(nome: str) -> list[float]:
    """Um array de testes/spo2/vetores/sem_dedo.h (o vetor do teste no PC)."""
    texto = VETOR.read_text(encoding="utf-8")
    m = re.search(rf"sem_dedo_{nome}\[\d+\] = \{{(.*?)\}};", texto, re.DOTALL)
    return [float(v.strip().removesuffix("f")) for v in m.group(1).split(",") if v.strip()]


def main() -> None:
    if shutil.which("arm-none-eabi-gcc") is None:
        sys.exit("arm-none-eabi-gcc não está no PATH (Arm GNU Toolchain)")
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    with tempfile.TemporaryDirectory() as pasta:
        imagem, sim = compila(Path(pasta))
    uc = novo(imagem)
    ctr = Contador(uc, md)

    def le(nome: str, fmt: str = "<I") -> float:
        return struct.unpack(fmt, bytes(uc.mem_read(sim[nome], 4)))[0]

    ctr.roda(uc, sim["entra_init"], False)
    if le("ok") != 1:
        sys.exit("spo2_init não rodou")

    esp_valido, esp_spo2 = le_vetor("valido"), le_vetor("spo2")
    n_amostras = len(le_vetor("ir"))
    soma = maior = maior_saida = saidas = fora = 0
    pior = 0.0
    for i in range(n_amostras):
        uc.mem_write(sim["indice"], struct.pack("<I", i))
        st = ctr.roda(uc, sim["entra_amostra"], True)
        soma += st["ciclos"]
        maior = max(maior, st["ciclos"])
        if le("saiu"):
            maior_saida = max(maior_saida, st["ciclos"])
            fora += int(le("valido")) != int(esp_valido[saidas])
            pior = max(pior, abs(le("spo2_pct", "<f") - esp_spo2[saidas]))
            saidas += 1
    media = soma // n_amostras
    print(f"imagem ARM: {len(imagem)} bytes (código e o vetor do sem_dedo)\n")
    print(f"amostras: {n_amostras}, saídas: {saidas} (esperado {len(esp_valido)})")
    print(f"saídas com valido diferente do Python: {fora}; maior diferença de spo2: {pior:.1e}")
    print(f"ciclos por amostra (modelo): média {media:,} | pior caso {maior:,} | "
          f"na amostra que fecha o segundo {maior_saida:,} (orçamento {ORCAMENTO:,}: "
          f"{'OK' if max(media, maior) <= ORCAMENTO else 'FALHOU'})")
    print(f"pior caso = {maior / MHZ:.1f} us a 96 MHz")
    if saidas != len(esp_valido) or fora or pior > 1e-2:
        sys.exit("o spo2 no ARM não bate com o Python")


if __name__ == "__main__":
    main()
