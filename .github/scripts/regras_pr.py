"""Regras de PR do sensor-ppg (ver CONTRIBUTING.md).

1. Até LIMITE_LINHAS linhas alteradas, sem contar arquivo gerado.
2. Documentação junto com o código:
   - Core/*/pds/<módulo>/        -> docs/src/content/docs/modulos/<módulo>.md(x)
   - Core/Inc/pds/comum/ppg.h    -> docs/src/content/docs/interface.md
   - *.ioc ou firmware nosso     -> docs/src/content/docs/firmware.md
     (firmware nosso = arquivos em Core/Inc e Core/Src fora de pds/, menos os
     que o CubeMX gera: main, stm32f4xx_*, syscalls, sysmem, system_stm32f4xx)

Uso: python3 regras_pr.py <base> <head>
"""

import re
import subprocess
import sys

LIMITE_LINHAS = 400

# Não contam no tamanho do PR.
GERADOS = (
    re.compile(r"^Drivers/"),
    re.compile(r"^cmake/stm32cubemx/"),
    re.compile(r"^Core/(Inc|Src)/(main|stm32f4xx_\w+|syscalls|sysmem|system_stm32f4xx)\.[ch]$"),
    re.compile(r"^startup_.*\.s$"),
    re.compile(r"^.*\.ld$"),
    re.compile(r"^\.mxproject$"),
    re.compile(r"^.*\.ioc$"),
    re.compile(r"^testes/.*/vetores/"),
    re.compile(r"^analise/uv\.lock$"),
    re.compile(r"^docs/package-lock\.json$"),
)

MODULO = re.compile(r"^Core/(?:Inc|Src)/pds/([^/]+)/")
DOC = re.compile(r"^docs/src/content/docs/modulos/([^/]+)\.mdx?$")
SEM_DOC = {"comum"}  # a interface é documentada à parte (interface.md)

DOCS = "docs/src/content/docs/"
INTERFACE = re.compile(r"^Core/Inc/pds/comum/ppg\.h$")
IOC = re.compile(r"^[^/]*\.ioc$")
FIRMWARE_NOSSO = re.compile(r"^Core/(Inc|Src)/(?!pds/)[^/]+\.[ch]$")
GERADO_CUBEMX = re.compile(r"^Core/(Inc|Src)/(main|stm32f4xx_\w+|syscalls|sysmem|system_stm32f4xx)\.[ch]$")


def alteracoes(base: str, head: str) -> list[tuple[int, str]]:
    saida = subprocess.run(
        ["git", "diff", "--numstat", f"{base}...{head}"],
        check=True, capture_output=True, text=True,
    ).stdout
    linhas = []
    for linha in saida.splitlines():
        adic, rem, caminho = linha.split("\t", 2)
        if " => " in caminho:  # renomeado: fica o nome novo
            caminho = re.sub(r"\{[^}]* => ([^}]*)\}", r"\1", caminho).split(" => ")[-1]
        n = 0 if adic == "-" else int(adic) + int(rem)  # "-" = binário
        linhas.append((n, caminho))
    return linhas


def checa(linhas: list[tuple[int, str]]) -> list[str]:
    erros = []

    contadas = [(n, c) for n, c in linhas if not any(g.match(c) for g in GERADOS)]
    total = sum(n for n, _ in contadas)
    if total > LIMITE_LINHAS:
        maiores = sorted(contadas, reverse=True)[:5]
        lista = "\n".join(f"    {n:5d}  {c}" for n, c in maiores)
        erros.append(
            f"PR com {total} linhas alteradas (limite {LIMITE_LINHAS}). "
            f"Divida em PRs menores. Maiores arquivos:\n{lista}"
        )

    caminhos = [c for _, c in linhas]
    modulos = {m.group(1) for c in caminhos if (m := MODULO.match(c))} - SEM_DOC
    docs = {m.group(1) for c in caminhos if (m := DOC.match(c))}
    for mod in sorted(modulos - docs):
        erros.append(
            f"O módulo '{mod}' mudou, mas a doc dele não: atualize "
            f"docs/src/content/docs/modulos/{mod}.md"
        )

    def mudou_doc(nome: str) -> bool:
        return any(re.match(rf"^{DOCS}{nome}\.mdx?$", c) for c in caminhos)

    if any(INTERFACE.match(c) for c in caminhos) and not mudou_doc("interface"):
        erros.append(f"O ppg.h mudou, mas a doc da interface não: atualize {DOCS}interface.md")

    firmware = [c for c in caminhos
                if IOC.match(c) or (FIRMWARE_NOSSO.match(c) and not GERADO_CUBEMX.match(c))]
    if firmware and not mudou_doc("firmware"):
        erros.append(
            f"O firmware mudou ({', '.join(firmware[:3])}), mas a doc não: "
            f"atualize {DOCS}firmware.md"
        )
    return erros


def main() -> int:
    base, head = sys.argv[1], sys.argv[2]
    linhas = alteracoes(base, head)
    erros = checa(linhas)
    if erros:
        for e in erros:
            print(f"::error::{e}" if "\n" not in e else e)
        return 1
    total = sum(n for n, c in linhas if not any(g.match(c) for g in GERADOS))
    print(f"ok: {total} linhas contadas, doc dos módulos em dia")
    return 0


if __name__ == "__main__":
    sys.exit(main())
