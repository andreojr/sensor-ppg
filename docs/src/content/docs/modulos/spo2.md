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
| 4. Placa com a fonte falsa | **código pronto, compila; falta rodar na placa** (`-DBANCADA_SPO2=ON`) |
| 5. Sensor real | **código pronto, compila; falta rodar com o sensor** (linha `s,...` na serial) |

Esta página é atualizada em todo PR que mexe no módulo.

## Método

Recebe o **bruto** (com DC) dos dois canais, uma amostra por vez, a 100 Hz. A hemoglobina com e sem
oxigênio absorve o vermelho e o infravermelho de jeitos diferentes, e a **razão das razões** mede isso:

1. **AC e DC por canal.** Cada canal passa por um passa-altas de 1ª ordem (média exponencial,
   `ALFA = 0,02`, corte ~0,3 Hz): `dc = dc + ALFA * (x - dc)` e `ac = x - dc`. É a mesma ideia do
   módulo qualidade. Tira o DC e a deriva, e deixa só o que pulsa.
2. **Janela de 8 s, uma saída por segundo.** Cada segundo (bloco) acumula a soma de `x` e de `ac²`; a
   janela são os últimos 8 blocos. O **DC** é a média de `x`; o **AC** é o RMS (a raiz da média de `ac²`),
   que não depende de achar picos nem de o pulso ter boa forma.
3. **R = (AC_vermelho / DC_vermelho) / (AC_ir / DC_ir)**, e **SpO2 = 110 − 25·R**, limitada a 0 a 100%.
4. **`valido`**: a janela encheu; o DC dos dois canais passa de 10 000 contagens em **cada segundo** da janela
   (tem dedo o tempo todo); o DC não varia mais que 1,5× entre os segundos; o AC do IR é maior que zero; e R está
   entre 0,2 e 1,6 (a faixa que a fisiologia permite: 105% a 70%). Inválido sai com `spo2_pct = 0`, como o
   `picos_bpm()` (o display mostra `--`).

**Por que a defesa do DC por segundo.** A primeira versão olhava só o DC médio da janela. Quando o dedo sai
**no meio** da janela, o degrau do DC vira um AC enorme nos dois canais com razão ~1, o R fica perto de 1 e o
módulo devolvia `valido = true` com SpO2 ~85%: um valor plausível e errado. O teste pegou isso, e a defesa
(DC alto em todos os segundos e estável) corrigiu. Nos 15 registros reais, ela não rejeita nada (100% válidos).

O módulo **não** olha movimento nem ruído: quem decide se o trecho presta é o módulo `qualidade`. O laço
principal só deve mostrar o SpO2 com `qualidade.usavel`.

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

| Atividade | R médio | Desvio do R dentro do registro (mediana) | SpO2 estimada (média e faixa) | Janelas válidas |
|---|---|---|---|---|
| sentado | 0,487 | 0,012 | 97,8% (96,4 a 99,3) | 100% |
| andando | 0,438 | 0,010 | 99,0% (97,7 a 99,9) | 100% |
| correndo | 0,562 | 0,028 | 95,9% (94,4 a 97,6) | 100% |

- **R estável entre janelas** (o critério da #27): desvio de 0,004 a 0,077 por registro, mediana de 0,01 a 0,03.
- **Valores plausíveis** para pessoas saudáveis: 94 a 100%.
- **Canais trocados:** com vermelho e IR invertidos, R vira ~1/R (perto de 2), fora da faixa: **0% das janelas
  ficam válidas** sentado e andando (e 18% correndo). A atribuição dos canais faz diferença, e o `R_MAX` protege
  contra LEDs trocados no sensor.

**O que isso NÃO prova.**

- **Não prova que o valor está certo.** Só que ele é plausível, estável e coerente. A reta de livro dá ~97% aqui, e
  isso bate com o que se espera de gente saudável, mas é a mesma suposição que usamos para escolher qual canal é
  qual (a doc do dataset se contradiz; o R decidiu).
- **O movimento mexe no R.** A mesma pessoa dá 99,9% andando e 94,4% correndo (`s1`), e não há motivo fisiológico
  para uma diferença dessas. É movimento corrompendo o AC. Daí a regra de só mostrar com `qualidade.usavel`.
- **Calibração:** pra ter exatidão, é preciso um oxímetro de referência com o sensor real e ajustar a curva (e
  provavelmente os coeficientes dependem do módulo MAX30102 e de como o dedo apoia).
- O `ppg.h` não tem um campo "estimado" em `ppg_spo2_t`, e mudá-lo precisa do ok dos outros dois. Por ora, o
  "estimado" está nesta página, no comentário do `spo2.h` e no cabeçalho da serial.

## Em C

`spo2_t` guarda o DC de cada canal, o bloco em andamento e os últimos 8 blocos (**~170 B de RAM**, sem `malloc`).
`spo2_processa()` devolve `true` uma vez por segundo, a partir da amostra 800. Amostra com NaN ou infinito é
descartada. O C faz as mesmas contas do Python, na mesma ordem e em `float`: no teste (`testes/spo2/teste_spo2.c`,
sobre os dois vetores, 33 saídas cada) o resultado sai **idêntico (erro 0)**; reiniciar dá o mesmo resultado. O
teste falha de verdade: trocar a curva (110 − 24·R) reprova 33 pontos, e tirar a defesa do DC deixa 15 janelas com
valor errado de até 85,8 de diferença.

Casos de comportamento: o R conhecido (0,4 a 1,4) e a reta, primeira saída na amostra 800 e uma por segundo, canais
trocados, R abaixo do mínimo, sem dedo, sem pulso (sem divisão por zero), dedo que sai no meio, DC que cai pela
metade e NaN.

## Custo

Firmware compilado com o `arm-none-eabi-gcc` 14.2.1, sem avisos. Release (`-Os`), sobre a `main`:

| | Flash | RAM |
|---|---|---|
| `main` | 21.796 B | 16.792 B |
| com o SpO2 na cadeia | 22.796 B (**+1.000 B**) | 16.984 B (**+192 B**) |
| com a bancada (`-DBANCADA_SPO2=ON`) | 55.948 B (o vetor de 32 KB) | 17.152 B |

**Ciclos** (código ARM emulado, modelo simples do Cortex-M4F, **sem** a espera da flash; `uv run
testes/spo2/ciclos/ciclos.py`, precisa do `arm-none-eabi-gcc`): média de **186 ciclos por amostra** e pior caso
de **1.559** (16 µs), a amostra que fecha o segundo, contra o orçamento de 9 600 (1% da CPU por amostra). As saídas
do código ARM emulado também batem com as do Python (33 de 33).

## Pendente

- **Rodar na placa** com a fonte falsa (`-DBANCADA_SPO2=ON`) e com o sensor real, e ver as linhas `s,...`.
- **Calibrar com um oxímetro de referência.** Sem isso o resultado continua "estimado".
- **Conferir a ordem dos LEDs** do módulo MAX30102 real (vermelho e IR podem vir trocados): o `R_MAX` derruba os
  valores se estiverem, mas o certo é conferir.
- **Mostrar só com `qualidade.usavel`** no laço principal, quando o módulo qualidade (PR aberto) for mergeado.
