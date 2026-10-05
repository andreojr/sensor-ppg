---
title: "1º relatório: fala de 5 min"
description: Roteiro da apresentação de 05/10/2026, com tempo por bloco e os slides.
sidebar:
  order: 2
---

Cinco minutos é pouco: cerca de 620 palavras faladas (4:45 a 130 palavras por minuto, o que deixa folga). Um tema por slide,
um número por frase. O que não cabe fica no relatório escrito.

## Roteiro

| Tempo | Bloco | O que dizer |
|---|---|---|
| 0:00 a 0:35 | **O problema** (slide 1) | O sensor entrega luz refletida pelo dedo em dois comprimentos de onda, já digitalizada em 18 bits. O pulso é 0,2% a 2% de um nível constante enorme; o gráfico é do nosso sensor, medido hoje (0,4%). Tudo o que interessa (batimento, variabilidade, oxigenação, respiração) está escondido aí e é PDS puro tirar isso em tempo real numa STM32. |
| 0:35 a 1:35 | **Por que ampliamos o escopo** (slide 2) | A proposta era BPM. Testamos em dado público com ECG de referência: passa-faixa e picos deram 77,1 contra 77,0 bpm numa tarde. Mas um detector de picos ingênuo dobrou o SDNN, e hoje perdeu 3 de 18 batimentos no nosso sensor. O fácil é o BPM; o difícil é o instante exato de cada batimento. Daí os 7 itens, com piso e alvo. Destaque pro item 1: desligamos a média interna do sensor e fazemos o anti-aliasing nós mesmos. |
| 1:35 a 2:20 | **Arquitetura e interface** (slide 3) | A cadeia: sensor a 400 Hz, decimação pra 100 Hz, bruto e filtrado, módulos. Cada módulo é C puro, testável no PC. O contrato é o `ppg.h`, fechado antes dos módulos: taxa única, dois pontos de saída, pico com fração de amostra. Mudar exige o ok dos três. |
| 2:20 a 3:25 | **O que está pronto** (slide 4) | Repositório com CI e revisão obrigatória. Leitura do sensor a 400 Hz sem perder amostra (399,4/s, 0 perdidas em 20 s), e hoje o pulso apareceu no sinal real (0,4% a 0,7% do DC). Carregador do dado público com o gabarito do HRV (72,4 bpm, SDNN 46,9 ms). Dois achados: o sensor trava o barramento se a placa reseta no meio da leitura, e os canais vermelho e infravermelho vêm trocados na descrição do dataset; a razão das razões (SpO2 97% × 63%) desempata, e no nosso sensor a ordem foi conferida desligando um LED de cada vez. |
| 3:25 a 4:10 | **Como trabalhamos** (slide 5) | Três frentes em paralelo, cada uma com revisor fixo. Ninguém espera ninguém por causa da interface e da fonte falsa: trechos do dado público na flash, tocados como se fossem o sensor, com as marcas de batimento do ECG. Cada item: Python validado no ECG, C, teste no PC, placa com fonte falsa, sensor real. |
| 4:10 a 4:45 | **Até 26/10 e riscos** (slide 6) | Decimação e filtro (João), fonte falsa na placa e HRV no tempo (André), picos com BPM na placa e display (Celso). Risco principal: o sinal da protoboard ser pior que o do dado público. Primeira medida, hoje: com o dedo parado o pulso aparece limpo; mexendo, o artefato passa do tamanho do pulso. Se persistir, qualidade ganha peso e respiração sai do alvo. |

## Slides (conteúdo, não design)

1. **O problema.** Um gráfico do sinal cru do nosso sensor (DC enorme,
   pulso quase invisível) ao lado do mesmo trecho sem o DC. Uma frase: "o pulso é 0,2
   a 2% do sinal".
2. **Escopo: proposta × plano.** Duas colunas. Esquerda: DC, passa-faixa,
   picos, BPM. Direita: os 7 itens, com piso e alvo marcados. Embaixo, os
   dois números que justificam: 77,1 × 77,0 bpm e SDNN 141 × 40 ms.
3. **Arquitetura.** O diagrama da cadeia, com as taxas (400 Hz, 100 Hz) e
   os dois pontos de saída. Uma caixa ao lado: "ppg.h: o contrato".
4. **Feito até aqui.** Tabela de 6 linhas: repositório e CI; placa e sensor
   (399,4/s, 0 perdidas); pulso no sensor real (0,4% a 0,7% do DC); interface
   v1; dado público e gabarito (72,4 bpm, 46,9 ms); fonte falsa. Um canto para os dois achados.
5. **Método.** Três frentes e o rodízio de revisão. O desenho da fonte
   falsa: PhysioNet na flash entrando no lugar do sensor. Os cinco passos
   de cada item.
6. **Próximos passos e riscos.** Uma linha por frente até 26/10. Um risco.

## Quem fala o quê

<!-- Sugestão, já com o ok de João e Celso: cada um fala do que
fez (João o slide 4 da leitura do sensor; Celso ...). -->

## Perguntas prováveis

- *Por que não usar a média interna do sensor?* Porque ela é um filtro de
  média móvel, com lóbulo lateral a -13 dB: deixa passar aliasing. E porque
  fazer o anti-aliasing nós mesmos é o item de PDS mais rico do projeto.
- *Por que 100 Hz?* Abaixo de 50 Hz o RMSSD erra 50% no dado público. 100
  Hz dá folga, e com o pico interpolado a precisão não depende só da taxa.
- *Como validam sem equipamento?* Dado público com ECG sincronizado para
  BPM e HRV; metrônomo para respiração; oxímetro emprestado para SpO2.
- *E se o sinal da protoboard for ruim?* É o risco principal e já dá para
  medir: a leitura do sensor funciona. O detector de qualidade existe por
  isso.
