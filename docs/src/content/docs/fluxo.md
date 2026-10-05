---
title: Fluxo de trabalho
description: Como um item sai do Python e chega na placa.
---

O detalhe está no
[CONTRIBUTING.md](https://github.com/andreojr/sensor-ppg/blob/main/CONTRIBUTING.md).
Resumo:

## Cada item passa por 5 passos (um PR cada)

1. **Python** (`analise/`): protótipo validado no PhysioNet, com o ECG como
   gabarito.
2. **C** (`Core/*/pds/<módulo>/`): porte sem HAL.
3. **Teste no PC** (`testes/<módulo>/`): o C bate com os vetores gerados pelo
   Python.
4. **Placa com a fonte falsa**: trecho do PhysioNet tocado como se fosse o
   sensor.
5. **Sensor real**.

## Vetores de referência (passo 3)

O Python grava a entrada e a saída esperada de um módulo num header C, que o
teste em C inclui. Sem leitura de arquivo: o vetor é compilado junto.

```python
from analise.vetores import gera_vetor

gera_vetor("filtro", "trecho_1",
           {"entrada": bruto, "esperado": filtrado},  # float -> float, int/bool -> int32_t
           tol=1e-4)                                  # tolerância absoluta
# grava testes/filtro/vetores/trecho_1.h
```

O header traz, para cada array, `trecho_1_<array>[]` e o tamanho
`TRECHO_1_<ARRAY>_N`, além de `TRECHO_1_TOL`. O teste
(`testes/filtro/teste_filtro.c`) compara com `testes/confere.h`:

```c
#include "confere.h"
#include "vetores/trecho_1.h"

int main(void)
{
    float saida[TRECHO_1_ENTRADA_N];
    /* ... roda o módulo sobre trecho_1_entrada ... */
    return confere_float("filtrado", saida, trecho_1_esperado,
                         TRECHO_1_ESPERADO_N, TRECHO_1_TOL) ? 1 : 0;
}
```

- `confere_int` compara inteiros exatos (índices de pico, por exemplo).
- Os vetores são arquivos gerados: não contam no limite de linhas do PR. Não
  edite à mão; gere de novo pelo Python.
- Exemplo completo: `testes/comum/teste_vetores.c`, com o vetor gerado por
  `uv run python -m analise.vetores` (em `analise/`).

## Regras de PR

- A `main` é protegida: só entra por PR, com o CI verde.
- **1 aprovação de code owner.** No seu módulo, quem aprova é o seu revisor
  fixo (A é revisado por C, B por A, C por B).
- **Até ~400 linhas** alteradas, sem contar arquivo gerado.
- **Mudou um módulo, muda a página dele aqui** (`docs/src/content/docs/modulos/`).
- Merge por squash.

## Gestão

- **Tasks**: [GitHub Project](https://github.com/users/andreojr/projects/1),
  uma issue por task, com prazo e marco.
- **Compromissos com hora**: agenda compartilhada do grupo.
