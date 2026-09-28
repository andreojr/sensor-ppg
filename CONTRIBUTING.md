# Como trabalhamos

## Frentes e módulos

Cada integrante é dono de uma frente, e cada frente tem alguns módulos de
`Core/*/pds/`. Quem é dono de qual módulo está no
[`.github/CODEOWNERS`](.github/CODEOWNERS). Cada frente também tem um
**revisor fixo**, em rodízio: cada um conhece a fundo a sua frente e a que
revisa.

As três frentes andam **em paralelo**. Ninguém espera o código de ninguém,
porque todos dependem só de duas coisas:

1. **A interface** em `Core/Inc/pds/comum/ppg.h`: taxa de 100 Hz, amostra
   bruta (com DC) e filtrada, atraso do filtro e structs de resultado.
2. **A fonte falsa**: trechos do PhysioNet gravados na placa (bruto, filtrado
   e marcas de batimento do ECG), tocados como se fossem o sensor.

**Mudar o `ppg.h` precisa do ok dos outros dois**, combinado antes de abrir o
PR.

## Fluxo de cada item

Cada passo é um PR próprio:

1. **Protótipo em Python** (`analise/`), validado no PhysioNet com o ECG como
   gabarito.
2. **Porte pra C** em `Core/Inc/pds/<módulo>/` e `Core/Src/pds/<módulo>/`.
3. **Teste no PC** (`testes/<módulo>/`): a saída do C bate com os vetores de
   referência gerados pelo Python.
4. **Na placa com a fonte falsa.**
5. **Integração com o sensor real.**

## Regras do PDS

- **Nada em `pds/` inclui HAL nem `main.h`.** Só C padrão. O teste no PC não
  enxerga a HAL: se incluir, o CI quebra.
- Includes relativos à raiz `pds`: `#include "comum/ppg.h"`,
  `#include "filtro/filtro.h"`.
- Sem `malloc` e sem variável global. O estado do módulo fica numa struct que
  quem chama aloca:

  ```c
  typedef struct { /* estado */ } filtro_t;
  void filtro_init(filtro_t *f);
  void filtro_processa(filtro_t *f, const ppg_amostra_t *entrada,
                       ppg_amostra_t *saida);
  ```

- Nome das funções: `<módulo>_init`, `<módulo>_processa`, `<módulo>_<coisa>`.

## Branches e PRs

- A `main` é protegida: ninguém faz push direto, nem o dono do repositório.
- **Toda branch nasce de uma issue**, com o número dela no nome:
  `<label>/<nº da issue>-<descrição-curta>`. **O prefixo é o label da
  issue.** Em PDS, o módulo vai logo depois do número.

  | Label | Quando | Exemplo de branch |
  |---|---|---|
  | `pds` | módulo de PDS (`Core/*/pds/<módulo>/`) | `pds/42-filtro-butterworth` |
  | `comum` | a interface `ppg.h` | `comum/4-ppg-h-v1` |
  | `firmware` | código da STM32 com HAL e o `.ioc` | `firmware/6-ioc-usart-timer` |
  | `analise` | Python: ferramentas, validação, coleta | `analise/9-carregador-physionet` |
  | `testes` | testes do PDS no PC e vetores | `testes/22-vetores` |
  | `docs` | site, relatórios, apresentação | `docs/14-relatorio-1` |
  | `ci` | CI, regras de PR, automação | `ci/90-cache-do-build` |

  Pelo terminal:

  ```bash
  gh issue develop 42 --name pds/42-filtro-butterworth --checkout
  ```

  Ou pelo botão "Create a branch" na página da issue: troque o nome sugerido
  pra `<label>/<nº>-<descrição>`.
- **No PR, escreva `Closes #42`** na descrição (tem que ser em inglês:
  `Closes`, `Fixes` ou `Resolves`). É isso que liga o PR à issue e fecha a
  issue no merge.
- **PR pequeno:** até ~400 linhas alteradas, sem contar arquivo gerado
  (`Drivers/`, `cmake/stm32cubemx/`, código gerado do CubeMX, vetores de
  referência).
- **Aprovação:** 1 aprovação, que precisa ser de code owner. PR no seu
  módulo: quem aprova é o seu revisor fixo. PR no módulo de outra pessoa: o
  dono ou o revisor fixo daquele módulo aprova. Commit novo derruba a
  aprovação.
- **CI verde** é obrigatório.
- **Documentação junto com o código.** O CI exige:

  | Se o PR muda | Também muda |
  |---|---|
  | `Core/*/pds/<módulo>/` | `docs/src/content/docs/modulos/<módulo>.md` |
  | `Core/Inc/pds/comum/ppg.h` | `docs/src/content/docs/interface.md` |
  | o `.ioc`, ou firmware nosso em `Core/` fora de `pds/` | `docs/src/content/docs/firmware.md` |

  Os arquivos que o CubeMX gera (`main.c`, `stm32f4xx_*`...) não entram na
  regra sozinhos, mas uma mudança no `.ioc` que os regenera entra. É das
  páginas que saem os relatórios.
- As regras de tamanho e de documentação são checadas pelo CI
  (`.github/scripts/regras_pr.py`); dá pra rodar antes do push:
  `python3 .github/scripts/regras_pr.py origin/main HEAD`.
- **Prazo de revisão:** 48 h. Se não der, avise no grupo.
- Merge por **squash**. O título do PR vira a mensagem do commit.

## Versões (releases)

Uma versão por marco: `v0.1` no relatório 1, `v0.2` no relatório 2, `v1.0` na
apresentação final. Na véspera, com a `main` atualizada:

```bash
git tag v0.1 -m "Relatório 1"
git push origin v0.1
```

O CI compila o firmware, roda os testes e publica a release com o `.bin`, o
`.hex` e o `.elf`, e a lista dos PRs do período separada por tipo. O tipo sai do
label do PR, que é colocado sozinho a partir do prefixo da branch.

## `.ioc` (CubeMX)

Conflito no `.ioc` é difícil de resolver. **Um PR de cada vez mexe nele.**
Avise no grupo antes de abrir o CubeMX. Depois de regenerar, confira que nada
em `Core/*/pds/` mudou.

## Gestão

- **Tasks:** GitHub Projects do repositório. Uma issue por task. O card anda
  sozinho:

  | Quando | Status |
  |---|---|
  | issue criada | A fazer |
  | branch criada com o nº da issue | Em andamento |
  | PR aberto com `Closes #N` | Em revisão |
  | review pedindo mudanças | Em andamento |
  | PR mergeado | Feito |
 Marcos: relatório 1 (05/10), relatório 2 (26/10),
  apresentação final (23 ou 30/11).
- **Compromissos com hora** (aulas, orientação, reuniões): agenda do Google
  compartilhada do grupo.
