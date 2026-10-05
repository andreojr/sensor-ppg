"""Vetores de referência dos testes em C.

O protótipo em Python gera a saída esperada de um módulo e grava um header C em
testes/<módulo>/vetores/<caso>.h. O teste em C inclui o header, roda o módulo
na mesma entrada e compara com testes/confere.h.

Formato do header (um por caso):

    #define <CASO>_TOL 1e-05f                 tolerância absoluta da comparação
    #define <CASO>_<ARRAY>_N 500u             tamanho de cada array
    static const float <caso>_<array>[500] = { ... };      (float32)
    static const int32_t <caso>_<array>[12] = { ... };     (inteiros e bool)

Gerar de novo o exemplo de testes/comum/vetores/: uv run python -m analise.vetores
"""

import re
from collections.abc import Mapping
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike

TESTES = Path(__file__).resolve().parents[3] / "testes"

_NOME = re.compile(r"^[a-z][a-z0-9_]*$")
_POR_LINHA = 8


def _checa_nome(tipo: str, nome: str) -> None:
    if not _NOME.match(nome):
        raise ValueError(f"{tipo} '{nome}' inválido: use minúsculas, dígitos e _")


def _valores(arr: np.ndarray) -> tuple[str, list[str]]:
    """Tipo C e os valores formatados como literais C."""
    if arr.dtype.kind in "biu":
        if arr.size and (arr.min() < -(2**31) or arr.max() >= 2**31):
            raise ValueError("inteiro fora da faixa de int32_t")
        return "int32_t", [str(int(v)) for v in arr]
    if arr.dtype.kind != "f":
        raise ValueError(f"tipo não suportado: {arr.dtype}")
    f32 = arr.astype(np.float32)
    if not np.all(np.isfinite(f32)):
        raise ValueError("NaN ou infinito não cabe num vetor de referência")
    # str(np.float32) é a menor representação que volta ao mesmo float32.
    return "float", [str(v) + "f" for v in f32]


def header(modulo: str, caso: str, arrays: Mapping[str, ArrayLike], tol: float,
           descricao: str = "") -> str:
    """Texto do header C de um caso."""
    _checa_nome("módulo", modulo)
    _checa_nome("caso", caso)
    if not arrays:
        raise ValueError("nenhum array")
    if not tol >= 0:
        raise ValueError("tol tem que ser >= 0")

    guarda = f"VETOR_{modulo}_{caso}_H".upper()
    linhas = [
        "/*",
        f" * Vetor de referência: {modulo}/{caso}.",
        *([f" * {descricao}"] if descricao else []),
        " * Gerado por analise/src/analise/vetores.py. Não edite à mão.",
        " */",
        f"#ifndef {guarda}",
        f"#define {guarda}",
        "",
        "#include <stdint.h>",
        "",
        f"#define {caso.upper()}_TOL {np.float32(tol)!s}f",
    ]
    for nome, valores in arrays.items():
        _checa_nome("array", nome)
        arr = np.asarray(valores).ravel()
        tipo, literais = _valores(arr)
        ident = f"{caso}_{nome}"
        linhas += [
            "",
            f"#define {ident.upper()}_N {arr.size}u",
            f"static const {tipo} {ident}[{max(arr.size, 1)}] = {{",
        ]
        for i in range(0, len(literais), _POR_LINHA):
            linhas.append("    " + ", ".join(literais[i:i + _POR_LINHA]) + ",")
        linhas.append("};")
    linhas += ["", f"#endif /* {guarda} */", ""]
    return "\n".join(linhas)


def gera_vetor(modulo: str, caso: str, arrays: Mapping[str, ArrayLike], tol: float,
               descricao: str = "", testes: Path = TESTES) -> Path:
    """Grava testes/<modulo>/vetores/<caso>.h e devolve o caminho."""
    destino = testes / modulo / "vetores" / f"{caso}.h"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(header(modulo, caso, arrays, tol, descricao), encoding="utf-8",
                       newline="\n")
    return destino


def arrays_exemplo() -> dict[str, np.ndarray]:
    """Caso de exemplo: senoide de 1,2 Hz a FS_HZ e o dobro dela."""
    from analise import FS_HZ

    n = np.arange(2 * FS_HZ)
    entrada = np.sin(2 * np.pi * 1.2 * n / FS_HZ).astype(np.float32)
    return {"entrada": entrada, "esperado": 2 * entrada, "indices": n[::FS_HZ]}


def gera_exemplo(testes: Path = TESTES) -> Path:
    return gera_vetor("comum", "exemplo", arrays_exemplo(), tol=1e-6, testes=testes,
                      descricao="Prova de ida e volta do formato: esperado = 2 * entrada.")


if __name__ == "__main__":
    print(gera_exemplo())
