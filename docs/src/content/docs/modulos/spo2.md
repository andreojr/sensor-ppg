---
title: SpO2
description: "Oxigenação pela razão das razões (vermelho/infravermelho): uma estimativa, sem calibração."
sidebar:
  order: 8
---

| | |
|---|---|
| Frente | C · Celso |
| Item do plano | 5 (Alvo) |
| Entrada | bruto (com DC, os dois canais) |
| Saída | ppg_spo2_t |
| Código | `Core/*/pds/spo2/` |
| Protótipo | `analise/src/analise/spo2.py` |

**O quê:** oxigenação pela razão das razões (vermelho/infravermelho). **É uma estimativa:** a curva
é a reta usual de livro e **não foi calibrada com um oxímetro de referência**. Serve para ver a
tendência e a ordem de grandeza (95 a 100% em pessoas saudáveis), não como medida clínica.

## Estado

| Passo | Situação |
|---|---|
| 1. Python (`analise/src/analise/spo2.py`) | feito, validado em 15 registros do PhysioNet (estabilidade e plausibilidade) |
| 2. C (`Core/*/pds/spo2/`) | feito, idêntico ao Python (erro 0) |
| 3. Teste no PC (`testes/spo2/`) | feito: 2 vetores e os casos de comportamento |
| 4. Placa com a fonte falsa | feito na placa (24/11/2026, `-DBANCADA_SPO2=ON`): 33 de 33 saídas, 0 fora da tolerância, erro 0; ciclos por amostra med 131 / max 1 532 (Release) e 420 / 3 822 (Debug), orçamento 9 600 |
| 5. Sensor real | offline nas capturas de 22 e 23/11 (abaixo); falta a captura com o firmware novo (linha `s,...` na serial) |

Esta página é atualizada em todo PR que mexe no módulo.

## Método

Recebe o **bruto** (com DC) dos dois canais, uma amostra por vez, a 100 Hz. A hemoglobina com e sem
oxigênio absorve o vermelho e o infravermelho de jeitos diferentes, e a **razão das razões** mede isso:

1. **AC e DC por canal.** Cada canal passa por um passa-altas de 1ª ordem (média exponencial,
   `ALFA = 0,02`, corte ~0,3 Hz): `dc = dc + ALFA * (x - dc)` e `ac = x - dc`. É a mesma ideia do
   módulo qualidade. Tira o DC e a deriva, e deixa só o que pulsa.
2. **Janela de 8 s, uma saída por segundo.** Cada segundo (bloco) acumula a soma de `x` e de `ac²` e guarda
   a maior amostra dos dois canais; a janela são os últimos 8 blocos. O **DC** é a média de `x`; o **AC** é o
   RMS (a raiz da média de `ac²`), que não depende de achar picos nem de o pulso ter boa forma.
3. **R = (AC_vermelho / DC_vermelho) / (AC_ir / DC_ir)**, e **SpO2 = 110 − 25·R**, limitada a 0 a 100%.
4. **`valido`**: a janela encheu; o DC dos dois canais passa de 10 000 contagens em **cada segundo** da janela
   (tem dedo o tempo todo); o DC não varia mais que 1,5× entre os segundos; nenhuma amostra de nenhum canal chega
   a 250 000 (a saturação, abaixo); o AC do IR é maior que zero; e R está entre 0,2 e 1,6 (a faixa que a
   fisiologia permite: 105% a 70%). Inválido sai com `spo2_pct = 0`, como o `picos_bpm()` (o display mostra `--`).

**R entre 0,2 e 0,4 sai válido e cortado em 100%.** A reta dá 105% a 100% nessa faixa; o módulo aceita a janela
(o R está na faixa) e limita a SpO2 em 100%. Não é raro: no `s1_walk` o R médio é 0,399, e 28 das 53 janelas saem
"100%" por esse corte (8 de 53 no `s4_sit`, 11 de 53 no `s4_walk`). Fica assim de propósito (o `R_MIN` não mudou):
sem calibração não dá pra dizer se esses R baixos são a reta errada ou o sinal, e 100% é plausível para quem
é saudável. Mas um "100%" na tela pode ser um R abaixo do que a reta cobre, não uma medida de 100%.

**Saturação.** Com o dedo apertado ou o LED forte, o DC sobe perto do topo do ADC de 18 bits (262 143) e o pulso é
cortado: o AC encolhe, o R sai errado e nada mais na janela avisa (o DC é alto e estável). Por isso cada bloco de
1 s guarda a maior amostra dos dois canais (um `float` por bloco, sem buffer de amostras), e a janela é inválida se
algum bloco chega a **250 000** contagens, o mesmo limite do módulo qualidade (`QUALIDADE_SATURA`, ~95% do topo;
`SPO2_SATURA` no C). Basta um segundo saturado em um canal para invalidar as 8 janelas que o contêm. Os
registros do PhysioNet (no nível do sensor) não chegam perto disso: os vetores e a validação não mudaram.

**O AC é o RMS de um passa-altas de 1ª ordem, sem passa-baixa.** Tudo acima de ~0,3 Hz entra no AC: o pulso,
mas também o ruído de banda larga do sensor e o movimento. O ruído soma energia ao AC dos dois canais e puxa o
R: quanto mais ele pesa, mais o R reflete a razão entre os ruídos relativos dos canais, e não a oxigenação. Um passa-faixa (por exemplo, 0,5 a 5 Hz) ou
usar o filtrado do `filtro` para o AC é uma opção futura; hoje a defesa é a qualidade (só mostrar com
`usavel`).

**Por que a defesa do DC por segundo.** A primeira versão olhava só o DC médio da janela. Quando o dedo sai
**no meio** da janela, o degrau do DC vira um AC enorme nos dois canais com razão ~1, o R fica perto de 1 e o
módulo devolvia `valido = true` com SpO2 ~85%: um valor plausível e errado. O teste pegou isso, e a defesa
(DC alto em todos os segundos e estável) corrigiu. Nos 15 registros reais, ela não rejeita nada (100% válidos).

O módulo **não** olha movimento nem ruído: quem decide se o trecho presta é o módulo `qualidade`, que já está
na `main`. O display (`oled_escolhe()`) troca a tela inteira para **SEM DEDO** ou **SINAL RUIM** quando a qualidade
julga sem dedo ou `!usavel`, então a SpO2 só aparece com sinal usável. Ressalva: a janela da SpO2 tem 8 s e a
qualidade fica usável antes de a janela inteira ser de sinal bom; logo que a tela volta, o valor ainda inclui
alguns segundos de antes.

**Parâmetros:** janela de 8 s e passo de 1 s (uma saída por segundo, como o espectral); `ALFA = 0,02`; reta
`110 − 25·R` (a linear usual). Uma curva quadrática, como a dos exemplos da Maxim, é a outra opção comum e não
foi testada: sem referência, não há como escolher entre as duas.

**Vetores de teste:** `uv run python -m analise.spo2` (em `analise/`) grava `testes/spo2/vetores/` com o bruto
e a saída do Python: `s1_sit` (40 s limpos) e `sem_dedo` (25 s do `s1_sit` e depois 15 s com DC de 1 500, com
janelas válidas, inválidas e as de transição).

## Validação

**O PhysioNet não traz SpO2 de referência** (o gabarito dele é o ECG, que não mede oxigenação), então **não há
"erro contra a referência"**, e a #27 já prevê isso ("marcado como estimado se não houver oxímetro de
referência"). O que dá para conferir sem oxímetro, em 5 pessoas × (sentado, andando, correndo), 60 s de cada
registro a partir de 30 s do bruto da fonte falsa (`uv run python -m analise.spo2_validacao`):

| Atividade | R médio | Desvio do R, janelas a cada 1 s (mediana) | Desvio do R, janelas sem sobreposição (mediana e máx.) | SpO2 estimada (média e faixa) | Janelas válidas |
|---|---|---|---|---|---|
| sentado | 0,487 | 0,012 | 0,011 (0,041) | 97,8% (96,4 a 99,3) | 100% |
| andando | 0,438 | 0,010 | 0,011 (0,077) | 99,0% (97,7 a 99,9) | 100% |
| correndo | 0,562 | 0,028 | 0,034 (0,067) | 95,9% (94,4 a 97,6) | 100% |

- **R estável entre janelas** (o critério da #27). As saídas saem a cada 1 s sobre 8 s de dados, então duas
  seguidas dividem 7 s e variam pouco por construção: desvio de 0,004 a 0,077 por registro, mediana de 0,01 a
  0,03. O critério de verdade é entre janelas **sem sobreposição** (8 s, passo de 8 s: 7 janelas por registro de
  60 s): desvio de 0,003 a 0,077 por registro, mediana de 0,011 a 0,034. Dá praticamente o mesmo, então a
  estabilidade não é efeito da sobreposição. Um desvio de 0,077 no R é ~1,9 ponto de SpO2 pela reta.
- **Valores plausíveis** para pessoas saudáveis: 94 a 100%.
- **Canais trocados:** com vermelho e IR invertidos, R vira ~1/R (perto de 2), fora da faixa: **0% das janelas
  ficam válidas** sentado e andando. Correndo, 18% em média e **até 45% num registro** (`s1_run`; 19% no `s2_run`,
  28% no `s4_run`): com movimento, o R dos canais trocados cai pra dentro da faixa em quase metade das janelas.
  A atribuição dos canais faz diferença, e o `R_MAX` protege contra LEDs trocados no sensor parado, **não** com
  movimento; aí depende de a qualidade marcar o trecho como não usável.

**Nas capturas do nosso sensor (offline).** Passando as 8 capturas de 22 e 23/11 (`*_bruto.csv`) pelo
`analise.spo2`, só nas janelas que a qualidade (calculada na ordem de canais da captura) diz usáveis, em 6 das 8
capturas (nas outras 2 nenhuma janela é usável): com os canais na ordem que o firmware mandava, o R mediano por
captura deu 1,86 a 2,68 e só 0 a 1 janela por captura saiu válida (SpO2 em torno de 50%, impossível em repouso).
Trocando só os canais da SpO2, o R mediano por captura deu 0,37 a 0,54 e todas as janelas usáveis saíram válidas,
com a SpO2 mediana por captura de 96,6 a 100%. Calculando também a qualidade com os canais trocados (o que o
firmware novo faz), as janelas usáveis mudam um pouco: o R mediano por captura vai de 0,40 a 0,77 (o 0,77, 90,7%,
é de uma captura com só 2 janelas usáveis) e há janelas isoladas até 82%. Medianas por captura, não por janela.
Conferido na placa: no nosso módulo os LEDs vêm trocados (com o LED1 apagado, a luz vermelha continua acesa).
O driver passou a desfazer a troca (ver [Firmware](../../firmware/)), e a SpO2 depende dessa correção.

**O que isso NÃO prova.**

- **Não prova que o valor está certo.** Só que ele é plausível, estável e coerente. A reta de livro dá ~97% aqui, e
  isso bate com o que se espera de gente saudável, mas é a mesma suposição que usamos para escolher qual canal é
  qual (a doc do dataset se contradiz; o R decidiu).
- **O movimento mexe no R.** A mesma pessoa dá 99,9% andando e 94,4% correndo (`s1`), e não há motivo fisiológico
  para uma diferença dessas. É movimento corrompendo o AC. Daí a regra de só mostrar com `qualidade.usavel`.
- **Calibração:** pra ter exatidão, é preciso um oxímetro de referência com o sensor real e ajustar a curva (e
  provavelmente os coeficientes dependem do módulo MAX30102 e de como o dedo apoia).
- O `ppg.h` não tem um campo "estimado" em `ppg_spo2_t`, e mudá-lo precisa do ok dos outros dois. Por isso o
  "estimado" fica fora do contrato: nesta página, no comentário do `spo2.h`, no cabeçalho da serial e no
  display, onde o rótulo sai como `SPO2~` (o `~` é a marca de estimada; veja [OLED](../oled/)).

## Em C

`spo2_t` guarda o DC de cada canal, o bloco em andamento e os últimos 8 blocos, cada um com a maior amostra
(**208 B de RAM**, sem `malloc`).
`spo2_processa()` devolve `true` uma vez por segundo, a partir da amostra 800. Amostra com NaN ou infinito é
descartada. O C faz as mesmas contas do Python, na mesma ordem e em `float`: no teste (`testes/spo2/teste_spo2.c`,
sobre os dois vetores, 33 saídas cada) o resultado sai **idêntico (erro 0)**; reiniciar dá o mesmo resultado. O
teste falha de verdade: trocar a curva (110 − 24·R) reprova 33 pontos, e tirar a defesa do DC deixa 15 janelas com
valor errado de até 85,8 de diferença.

Casos de comportamento: o R conhecido (0,4 a 1,4) e a reta, primeira saída na amostra 800 e uma por segundo, canais
trocados, R abaixo do mínimo, sem dedo, sem pulso (sem divisão por zero), dedo que sai no meio, DC que cai pela
metade, NaN, SpO2 acima de 100% limitada a 100 (tirar o corte reprova), IR ou vermelho saturado e um segundo só
saturado (tirar a guarda reprova os três).

Na cadeia (`testes/cadeia/`), o vetor de 90 s do PhysioNet também confere as 83 saídas da SpO2 (`n`, `valido`,
`spo2`, `r`) e a ficha (`cadeia_resultados()->spo2` igual à última saída): passar o filtrado em vez do bruto ou
não atualizar a ficha reprova o teste. O `analise.cadeia --replay` compara as linhas `s,` da placa.

## Custo

Firmware compilado com o `arm-none-eabi-gcc` 16.2.0, sem avisos. Release (`-Os`), sobre a `main` (o resumo do
linker):

| | Flash | RAM |
|---|---|---|
| `main` | 60.084 B | 40.152 B |
| com o SpO2 na cadeia | 61.264 B (**+1.180 B**) | 40.392 B (**+240 B**) |
| com a bancada (`-DBANCADA_SPO2=ON`) | 94.272 B (o vetor de 32 KB) | 40.600 B |

**Ciclos** (código ARM emulado, modelo simples do Cortex-M4F, **sem** a espera da flash; `uv run
testes/spo2/ciclos/ciclos.py`, precisa do `arm-none-eabi-gcc`): média de **197 ciclos por amostra** e pior caso
de **1.701** (17,7 µs), a amostra que fecha o segundo, contra o orçamento de 9 600 (1% da CPU por amostra). As saídas
do código ARM emulado também batem com as do Python (33 de 33).

## Pendente

- **Rodar com o sensor real** no firmware com os LEDs corrigidos e ver as linhas `s,...` (passo 5, #78).
- **Calibrar com um oxímetro de referência.** Sem isso o resultado continua "estimado".
- **Passa-faixa no AC** (ou o AC do filtrado), para o ruído de banda larga e o movimento puxarem menos o R.
