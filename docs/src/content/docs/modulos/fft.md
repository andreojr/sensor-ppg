---
title: FFT
description: "FFT real do CMSIS-DSP atrás de uma função fina, pro espectral."
sidebar:
  order: 10
---

| | |
|---|---|
| Frente | C · Celso |
| Item do plano | FFT na placa (#25), usada pelo `espectral` |
| Entrada | n amostras reais (`float`), n = 256, 512 ou 1024 |
| Saída | potência `|X[k]|²`, k = 0 a n/2 |
| Código | `Core/*/pds/fft/` |
| Biblioteca | CMSIS-DSP v1.16.2, em `Drivers/CMSIS/DSP/` |
| Gabarito | NumPy (`analise/src/analise/fft_vetores.py`) |

**O quê:** o `espectral` precisa do espectro do sinal pra achar a frequência do
pulso. A FFT (transformada rápida de Fourier) decompõe o sinal em "quanto de cada
frequência existe nele". Em vez de escrever uma, usamos a do CMSIS-DSP, a
biblioteca da ARM que já vem otimizada pro Cortex-M4 da placa, e escondemos ela
atrás de uma função nossa de três linhas de uso.

## Estado

| Passo | Situação |
|---|---|
| CMSIS-DSP no projeto (só a FFT, versão fixa) | feito |
| Função fina `fft_init` / `fft_potencia` | feito |
| Teste no PC contra o NumPy | feito |
| Firmware compila com ela, sem avisos novos | feito (Debug e Release) |
| Flash e RAM medidos | feito |
| Ciclos | estimados por emulação e **medidos na placa** (DWT) |
| Rodar na STM32 dentro do orçamento (#25) | feito: o espectral inteiro, pior caso de ~101 300 ciclos (10,6% de um período de amostra) |

## Uso

```c
#include "fft/fft.h"

fft_t f;                 /* o estado fica com quem chama: sem malloc, sem global */
float x[1024];           /* a janela, n amostras reais */
float trabalho[1024];    /* área de trabalho, n floats */

fft_init(&f, 1024);      /* uma vez; false se o tamanho não está compilado */
/* ... preenche x ... */
fft_potencia(&f, x, trabalho);
/* x[0] a x[512] agora é |X[k]|², a potência na frequência k * fs / n */
```

`fft_potencia` **sobrescreve** `x` e `trabalho`. A FFT não é normalizada (igual à
do NumPy). O `espectral` inclui só `fft/fft.h`, nunca um cabeçalho do CMSIS: se a
FFT mudar um dia, só o `fft.c` muda. `fft.c` é o único arquivo nosso que enxerga
o CMSIS.

## Decisões

**CMSIS-DSP copiado pro repositório, só a FFT, versão fixa (v1.16.2).** Sem o
pacote do CubeMX (mexeria no `.ioc`), sem baixar na hora do build (dependeria de
rede) e sem biblioteca pré-compilada. São 8 fontes e 10 cabeçalhos, sem alteração,
com a licença Apache 2.0. A lista e o motivo de cada arquivo estão em
`Drivers/CMSIS/DSP/README.md`. Os 4,9 MB do `arm_common_tables.c` são texto das
tabelas de todos os tamanhos; o linker só leva as que usamos (ver "Flash").

**Por que a v1.16.2 e não a mais nova (1.18):** o projeto tem o CMSIS-Core 5.6, e a
série 1.16 é a última que funciona com ele. A partir da 1.17 o CMSIS-DSP passa a
exigir o CMSIS 6.

**Tamanhos 256, 512 e 1024, ligados por padrão.** Cada um traz as suas tabelas pra
flash, então só entram os que o `espectral` pode usar. Pra mudar: `-DFFT_COM_2048=1`,
`-DFFT_COM_256=0` etc. O tamanho precisa ser potência de 2 e pelo menos tão grande
quanto a janela (8 s a 100 Hz = 800 amostras pede 1024).

**A inicialização é chamada pelo nome do tamanho** (`arm_rfft_fast_init_1024_f32`),
nunca pela genérica `arm_rfft_fast_init_f32(S, n)`. A genérica tem um `switch` que
referencia as tabelas de todos os tamanhos, e o linker não consegue descartar o que
está referenciado. Esta versão do CMSIS-DSP não tem mais o `-DARM_DSP_CONFIG_TABLES`
(dá erro de compilação), então esse é o jeito.

**Estado opaco.** O `fft_t` guarda a instância do CMSIS num vetor de bytes, e o
`fft.c` confere em tempo de compilação (`_Static_assert`) que cabe. Assim o
`fft.h` não inclui nada do CMSIS.

**Formato da saída do CMSIS.** `arm_rfft_fast_f32` entrega os números empacotados:
`[Re0, Re(n/2), Re1, Im1, Re2, Im2, ...]` (o primeiro e o do meio são reais puros e
dividem espaço). `fft_potencia` desempacota e devolve só `|X[k]|²`, já no lugar de
`x`.

## Experimento: o mesmo CMSIS compila no PC?

**Sim.** Os 8 arquivos compilam com `gcc` no PC, sem nenhum aviso, com
`-D__GNUC_PYTHON__`. Esse é o modo "host" do `arm_math_types.h`: sem ele, o cabeçalho
inclui o `cmsis_compiler.h`, que usa instruções do ARM e não compila num
PC. Então o teste do passo 3 roda a **mesma FFT que roda na placa**, e não uma
substituta. A tolerância é a do `float32`, e não a de uma FFT diferente.

## Teste no PC

`testes/fft/teste_fft.c` roda `fft_potencia` sobre 4 entradas e compara com a
potência do NumPy (em `float64`), dividida por n² pra ficar numa escala em que
a tolerância absoluta serve (o pico de uma senoide de amplitude 1 vale 0,25):

| Caso | Pontos | Maior erro | Tolerância |
|---|---|---|---|
| duas senoides e ruído | 256 | 3,7e-9 | 1e-5 |
| idem | 512 | 4,5e-8 | 1e-5 |
| idem | 1024 | 1,5e-8 | 1e-5 |
| 8 s do `s1_sit` com Hann e zero-padding | 1024 | 4,7e-10 | 1e-5 |

Também confere que `fft_init` recusa tamanhos que não estão compilados (0, 300,
1000, 4096). O teste falha de verdade com a conta errada: trocando `re² + im²`
por `re² − im²` no `fft.c`, ele reprova com os valores à mostra. Os vetores são
gerados por `uv run python -m analise.fft_vetores` (em `analise/`).

O primeiro caso do PPG reprovou por um motivo que vale registrar: com a amplitude
do sinal em centenas de contagens, a potência chega a ~400, e o erro natural do
`float32` (~1e-7 **relativo**) passa de 1e-5 em valor **absoluto**. A FFT estava certa;
o caso passou a usar a entrada normalizada pra amplitude 1, como os outros.

## Flash e RAM

**Quando o espectral entrou** (antes da cadeia da #17; Release, `arm-none-eabi-gcc` 16.2.0, sem aviso):
o firmware fica em **49.980 B de flash e 33.828 B de RAM**, contra 23.864 B e 19.132 B
da `main` (com a respiração, #110): **+26.116 B de flash e +14.696 B de RAM** pelo espectral e pela FFT
juntos. Os 14.680 B do `espectral_t` são quase toda a RAM. As tabelas de 256 e 512 pontos
também entram (o `fft_init` aceita os três tamanhos), embora o espectral só use 1024.

**Medida da FFT sozinha** (histórica, antes de o espectral entrar na cadeia, com o
`arm-none-eabi-gcc` 14.2.1 e a `main` de então): uma função temporária (fora do
repositório) chama `fft_init` dos 3 tamanhos e um `fft_potencia` de cada, com dois
buffers de 1024 `float`:

| Build | Flash (`main`) | Flash (com a FFT) | Diferença | RAM (`main`) | RAM (com a FFT) | Diferença |
|---|---|---|---|---|---|---|
| Release (`-Os`) | 17.828 B | 38.216 B | **+20.388 B** (≈ 19,9 KB) | 13.320 B | 21.728 B | **+8.408 B** |
| Debug (`-O0`) | 29.136 B | 56.392 B | +27.256 B | 13.320 B | 21.728 B | +8.408 B |

O chip tem 512 KB de flash e 128 KB de RAM: a FFT acrescenta **~3,9% da flash**
(Release; o firmware inteiro fica em 7,3%) e **~6,4% da RAM**.

- **RAM, +8.408 B:** 2 × 1024 × 4 B = 8.192 B dos dois buffers (`x` e `trabalho`)
  mais 3 × 72 B = 216 B dos três `fft_t`. Com um só tamanho (1024), são 8.192 B + 72 B.
  Isso é a RAM **fixa**. A **pilha** que a FFT usa enquanto roda é pequena: pelo
  `-fstack-usage` (arquivos `.su` do build Release), a cadeia mais funda é
  `fft_potencia` (16 B) → `arm_rfft_fast_f32` (32 B) → `arm_cfft_f32` (120 B) →
  `arm_radix8_butterfly_f32` (152 B), ou seja, **320 B**. É uma análise estática: não há
  recursão, mas ela não conta o que a interrupção que chamar a FFT já tiver na pilha.
- **Flash, +20.388 B no Release:** 16.528 B de tabelas + 3.814 B de código (e mais
  um pouco do nosso `fft.c`). No `.map`, **só 9 tabelas** ficaram: as dos três tamanhos
  ligados. As de 4096 pontos, `float64`, `q15` e `q31` foram descartadas.

| Tabela | Bytes |
|---|---|
| `twiddleCoef_rfft_1024` | 4.096 |
| `twiddleCoef_512` | 4.096 |
| `twiddleCoef_rfft_512` | 2.048 |
| `twiddleCoef_256` | 2.048 |
| `twiddleCoef_rfft_256` | 1.024 |
| `twiddleCoef_128` | 1.024 |
| `armBitRevIndexTable512` | 896 |
| `armBitRevIndexTable256` | 880 |
| `armBitRevIndexTable128` | 416 |
| **Total** | **16.528** |

Cada tamanho custa as tabelas dele (a FFT real de n pontos usa a complexa de n/2):
1024 pontos são 9.088 B, 512 são 4.976 B e 256 são 2.464 B. Se o `espectral` usar só
1024, dá pra desligar os outros dois (`-DFFT_COM_256=0 -DFFT_COM_512=0`) e economizar
7.440 B de flash.

> **Cuidado ao medir no PC:** no Windows o linker (formato PE) **não** descartou as
> tabelas grandes (o executável de teste ficou com todas, uns 120 KB). No ARM (formato
> ELF) descartou. O número que vale é o do firmware, e vem do `.map`.

## Ciclos

A placa roda a 96 MHz e amostra a 100 Hz, então o orçamento é de
**960.000 ciclos por amostra**. A FFT roda uma vez por passo do espectral (a cada 1 s,
ou seja, a cada 100 amostras), então na prática o limite é ela caber dentro de **um**
período de amostra se rodar no laço principal sem travar o resto.

Sem a placa, a medida possível é **emular o código ARM** e contar as instruções
executadas. `testes/fft/ciclos/ciclos.py` compila o `fft.c` e o CMSIS pra Cortex-M4F
(`-Os`, FPU de hardware), roda no emulador Unicorn, **confere que a saída bate com o
NumPy** (erro ≤ 2,3e-7 relativo ao pico) e conta:

| Pontos | Instruções executadas | Ciclos (modelo) | % do orçamento de 1 amostra | Em tempo a 96 MHz |
|---|---|---|---|---|
| 256 | 12.795 | ~21.300 | 2,2% | 0,22 ms |
| 512 | 27.624 | ~45.550 | 4,7% | 0,47 ms |
| 1024 | 51.375 | ~84.550 | 8,8% | 0,88 ms |

Rodar: `uv run testes/fft/ciclos/ciclos.py` (precisa do `arm-none-eabi-gcc` no PATH). Os
números acima são do `arm-none-eabi-gcc` 16.2.0; outra versão do compilador gera outro
código e muda um pouco a contagem (com o 14.2.1, a de 1024 deu 50.466). Como no firmware,
o `-ffp-contract=off` vale só pros fontes do `pds` (o CMSIS pode fundir multiplicação e soma).

**O que é exato e o que é estimativa.** A contagem de instruções é exata (cada uma que
o processador executaria, no código que o compilador gerou). Os ciclos vêm de um
modelo simples do Cortex-M4F: 1 ciclo na maioria das instruções, 2 pra load/store,
3 pra multiplica-e-soma de ponto flutuante (VFMA), 14 pra divisão, e +2 a cada
desvio tomado. **Não** modela a espera da flash (a 96 MHz o STM32F411 tem 3 estados
de espera, que o cache ART esconde em parte) nem a sobreposição de instruções do
pipeline. O valor real na placa pode ser maior (pela flash) ou menor (pelo pipeline);
com folga de mais de 10× no orçamento, a conclusão de que **cabe** não depende disso.
**Na placa** (`DWT->CYCCNT`, bancada do espectral, Release): o espectral inteiro tem pior
caso de **~101 300 ciclos** (1,06 ms), contra ~107 400 do modelo; a média por amostra
deu 951 no vetor e ~1 070 em regime com o sensor. O modelo errou pra cima ~6%.

**O espectral inteiro** (`espectral_processa()` amostra a amostra sobre os 60 s do `s2_walk`,
`uv run testes/fft/ciclos/ciclos.py espectral`): as 53 saídas saem iguais às do Python, e o
custo é de **~1 058 ciclos por amostra em média** (orçamento 9 600) e **~107 406 no pior caso**,
a amostra em que sai a FFT (orçamento 960 000; 11,2% de um período de amostra, 1,12 ms a
96 MHz). A FFT de 1024 pontos é ~84 550 desses; o resto é copiar a janela, tirar a média,
aplicar o Hann e achar o pico.

Os números são do **Release (`-Os`)**. O Debug (`-O0`) é bem mais lento, então
o orçamento deve ser conferido no build que vai pra apresentação.

## Decisões pendentes

- **Decidir o tamanho** (256, 512 ou 1024) e desligar os outros: depende da janela
  do `espectral` (8 s, 800 amostras, pede 1024).
- **Onde a FFT roda:** hoje no laço principal, dentro do `espectral_processa()` (a
  interrupção só marca que há amostra). Cabe com folga num período de amostra (10,6%
  medido); uma interrupção de baixa prioridade só valeria se o laço apertar.
