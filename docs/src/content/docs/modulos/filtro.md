---
title: Filtro
description: "Remoção de DC e passa-faixa 0,5 a 4 Hz."
sidebar:
  order: 2
---

| | |
|---|---|
| Frente | A · João |
| Item do plano | 2 (Piso) |
| Entrada | bruto (100 Hz, com DC) |
| Saída | filtrado (100 Hz, média zero, atrasado de `PPG_ATRASO_AMOSTRAS` = 100) |
| Código | `Core/*/pds/filtro/` |
| Protótipo | `analise/src/analise/filtro.py` |

**O quê:** remoção de DC e passa-faixa 0,5 a 4 Hz.

## Estado

| Passo | Estado |
|---|---|
| 1. Python, validado no PhysioNet | feito, com a comparação IIR × FIR |
| 2. C sem HAL | feito: `filtro.h`, `filtro.c`, `filtro_coef.h` (gerado) |
| 3. Teste no PC contra os vetores | feito: `testes/filtro/`, no CI |
| 4. Placa com a fonte falsa | código pronto (`-DBANCADA_FILTRO=ON`); falta rodar na placa |
| 5. Sensor real | código pronto (linhas `f,` na serial); falta capturar com o dedo |

## Método

### IIR × FIR: o efeito da fase no pico

A saída do filtro alimenta o `picos`, e o HRV depende do **instante** de cada
pico: o RMSSD típico é de 20 a 50 ms. O `ppg.h` corrige o atraso do filtro com
uma constante só, `PPG_ATRASO_AMOSTRAS`. Isso só funciona se o atraso for o
mesmo em todas as frequências, ou seja, com fase linear.

Foram comparados nos 22 registros `sit` do PhysioNet, com FC de 55 a 123 bpm
e 120 s cada, depois da nossa decimação:

- **FIR nosso**: fase linear, atraso de 100 amostras em todas as frequências.
- **IIR Butterworth** de ordem 2 e 4, causal: é o que caberia em poucas
  linhas e poucos ciclos.

A referência é o mesmo passa-faixa de fase zero (`filtfilt`) da fonte falsa:
o pico "certo", sem atraso nenhum.

| Filtro | Pico − pico de fase zero (ms), mediana (mín..máx entre registros) | Variação dentro do registro (ms) | IBI do PPG − RR do ECG, RMS (ms) |
|---|---|---|---|
| **FIR 201 (nosso)**, menos 100 amostras | **−2,9 (−10,3..1,4)** | **2,8** | **7,8** |
| IIR Butterworth 2 | 39,5 (−44,5..56,3) | 15,7 | 13,1 |
| IIR Butterworth 4 | −29,8 (−182,8..49,8) | 51,8 | 39,0 |

![Ganho dos três filtros e deslocamento do pico por registro contra a FC](../../../assets/filtro.png)

- No IIR, o pico **muda de lugar conforme a FC**. Abaixo do centro da
  banda ($\sqrt{0{,}5 \cdot 4} \approx 1{,}4$ Hz, ou 85 bpm), a fase do
  passa-faixa está adiantada e o pico sai antes. Acima, sai depois. A linha do
  gráfico é a previsão pela fundamental, $-\varphi(f)/(2\pi f)$: ela explica a
  tendência, mas não o valor exato. Os harmônicos do pulso são atrasados de
  forma diferente, e a onda se deforma (o pico vira outro ponto da onda).
  Não existe um `PPG_ATRASO_AMOSTRAS` que sirva pra todo mundo, e de
  −183 a +56 ms é bem mais que o RMSSD inteiro.
- Dentro do mesmo registro, a FC varia de batimento a batimento, então o pico
  do IIR também oscila (16 a 52 ms). Isso vai direto pro IBI e pro HRV.
- No FIR, o pico fica a poucos ms da referência em qualquer FC. O que sobra
  vem da diferença de ganho entre os dois, não da fase.

**Decisão: FIR de fase linear.** O custo é a latência de 1 s, que só atrasa
o display, e mais memória e ciclos que um IIR. As duas coisas cabem
(abaixo).

### Projeto do FIR

`scipy.signal.firwin`, janela de Hamming, 201 coeficientes, bordas de −6 dB
em 0,5 e 4 Hz (as mesmas da referência). Depois, a média dos coeficientes é
subtraída: **ganho em DC exatamente 0**, e é isso que remove o DC.

| Frequência | 0 | 0,05 Hz | 0,2 Hz | 0,5 Hz | 1 Hz | 2 Hz | 4 Hz | 6 Hz |
|---|---|---|---|---|---|---|---|---|
| Ganho (dB) | −∞ | −43 | −20 | −6 | −0,7 | 0,0 | −6 | −73 |

- **Por que janela, e não equiripple (Remez):** testado com 151 a 401
  coeficientes, o Remez deixa ~2 dB de ondulação na banda passante. Isso deforma
  o pulso, e o erro do IBI subiu pra 9,5 a 11,8 ms. A janela de Hamming tem a
  banda passante lisa.
- **Por que 201:** é o tamanho em que a deriva (0,05 a 0,2 Hz, respiração e
  movimento lento) cai de 20 a 43 dB. Com 101, a borda de baixo nem existe,
  porque a transição da janela é de ~3 Hz. Mais longo deixa mais latência e não
  melhora o pico.
- **Atraso:** $(201 - 1)/2 = 100$ amostras = 1 s, inteiro.
  `PPG_ATRASO_AMOSTRAS` passou de `0.0f` pra `100.0f`, e o `filtro.c`
  confere isso na compilação (`_Static_assert`).

### Implementação em C

```c
filtro_t f;                    /* ~3,2 KiB, de quem chama */
filtro_init(&f);
...
ppg_amostra_t filtrado;
filtro_processa(&f, &bruto, &filtrado);   /* sempre true; filtrado.n == bruto.n */
```

- Os coeficientes ficam em `filtro_coef.h`, gerado pelo Python
  (`uv run python -m analise.filtro --vetores`). O teste
  `test_coeficientes_e_vetor_em_dia` falha se ficar desatualizado.
- **Simetria:** $h_j = h_{N-1-j}$, então a soma vira
  $h_{100} x_{100} + \sum_{j<100} h_j (x_j + x_{N-1-j})$. São 101
  multiplicações por canal, e não 201.
- **Histórico duplicado:** a janela é sempre contínua, igual na decimação.
- **Começo sem transiente:** o histórico guarda o desvio da primeira amostra,
  e a parte antes da primeira amostra vale 0, ou seja, a própria primeira
  amostra. Como o ganho em DC é 0, o filtrado começa em 0, e não com um pico
  de ~100 mil. Ele vale depois de 201 amostras (2 s).

### A fonte falsa

O `filtrado_100hz` da fonte falsa agora é este FIR (antes era o `filtfilt`,
com atraso 0), atrasado de `PPG_ATRASO_AMOSTRAS` como na placa. Quem testa o
`picos` com a fonte falsa subtrai o atraso igual na cadeia de verdade. Os
picos do filtrado, menos 100 amostras, caem 0,13 s depois do R do ECG (p10 a
p90: 0,124 a 0,138 s), que é o tempo de trânsito do pulso até o dedo.

## Validação

### 1. Python no PhysioNet

`uv run python -m analise.filtro`, tabela acima. Contra o ECG, o IBI do PPG
filtrado erra 7,8 ms RMS (mediana dos 22 registros, 3130 pares de
batimentos). Isso fica na faixa do sinal antes do filtro (6,5 a 6,9 ms, ver
[Decimação](../decimacao/)), e o resto é a variação do tempo de trânsito do
pulso. Os IIR erram 13 e 39 ms.

### 2. C no PC

`testes/filtro/teste_filtro.c`, no CI (`pds-host`):

| Caso | Resultado |
|---|---|
| bruto da fonte falsa, 60 s (6000 amostras), contra o Python | maior erro 0,00008 contagens (tolerância 0,05) |
| `n` da saída igual ao da entrada | 6000 de 6000 |
| DC constante até 262143 | sai exatamente 0 |
| senoide de 1,5 Hz | ganho 1,006, atrasada de exatamente 100 amostras |
| 0,05 Hz e 6 Hz | ganho 0,007 e 0,0002 |
| `init` de novo | reinicia o histórico |

Trocar um índice da dobra da simetria faz 5918 das 6000 saídas falharem.

### 3. Placa com a fonte falsa

```bash
cmake --preset Debug -DBANCADA_FILTRO=ON
cmake --build --preset Debug
```

Na partida, a placa passa os 60 s do bruto da fonte falsa pelo filtro e
confere com o mesmo vetor do teste no PC:

```text
# bancada filtro: 6000 saidas, 0 fora da tolerancia, erro max 0 milesimos
# bancada filtro: ciclos por amostra med ... max ... (orcamento 19200): OK
```

**Orçamento:** 2% da CPU por amostra a 100 Hz, ou seja, 96 MHz / 100 Hz ×
2% = 19 200 ciclos. Pela contagem de instruções do laço em `-O0` (Debug),
~27 instruções por par de coeficientes. A estimativa é de ~7 500 ciclos por
amostra (101 iterações × 2 canais).

**Resultado na placa:** *(preencher com a saída da bancada)*

### 4. Sensor real

O firmware passa cada bruto pelo filtro e manda as duas linhas (`b,...` e
`f,...`). A captura grava `_bruto.csv` e `_filtrado.csv`, e o Python refaz o
filtro sobre o bruto da placa:

```bash
uv run python -m analise.captura COM3 --segundos 60
uv run python -m analise.filtro --confere dados/sensor_<data>_<hora>.csv
```

Sem ECG na placa, a referência disponível é o mesmo bruto filtrado com fase
zero. O `--confere` mostra o erro contra o Python (centésimos), quantos picos
casaram, o deslocamento deles contra a fase zero (tem que ficar em poucos ms,
como no PhysioNet) e o BPM. Com a placa simulada no PC (mesmo `filtro.c`,
fonte falsa a 400 Hz), deu 794 saídas, erro de 0,008 contagens e picos a
−1,4 ms da fase zero.

**Resultado com o sensor:** *(preencher com a saída do `--confere` e os ciclos)*
