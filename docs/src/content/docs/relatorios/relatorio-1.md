---
title: 1º relatório parcial
description: Estado do projeto em 05/10/2026, escopo ampliado e próximos passos.
sidebar:
  order: 1
---

**ENGG54, Laboratório Integrado III, UFBA, 2026.2.**
André Júnior, Celso Bomfim e João Luís da Cruz. Entregue em 05/10/2026.

[Baixar o relatório em PDF](/relatorios/relatorio-1.pdf), versão entregue no Moodle.

## 1. Contexto e motivação

O projeto é um oxímetro de dedo cujo processamento de sinal é todo nosso:
um sensor MAX30102 entrega a luz refletida pelo dedo em dois comprimentos
de onda (vermelho e infravermelho), uma STM32F411 processa esse sinal em
tempo real e um display OLED mostra os resultados.

O sensor já faz a conversão analógico-digital (ADC de 18 bits, dentro do
chip) e o cancelamento da luz ambiente. Fora isso, o que ele entrega é cru:
um número de 0 a 262143 por canal, dominado por um nível constante (DC)
em torno de 70 mil a 140 mil contagens. O pulso cardíaco é uma oscilação de
0,2% a 2% em cima desse nível, invisível a olho nu no sinal bruto. Extrair
dele batimento, variabilidade, oxigenação e respiração é um problema de
Processamento Digital de Sinais (PDS), e é isso que justifica o semestre.

## 2. Escopo: da proposta ao plano atual

A proposta de 14/09 previa remover o DC, aplicar um passa-faixa, detectar
picos e mostrar o BPM. Em 28/09 fizemos uma análise offline em dados
públicos (o spike) para saber se isso bastava para três pessoas num
semestre. Não bastava: com passa-faixa e picos, o BPM saiu em 77,1 contra
77,0 do eletrocardiograma (ECG) de referência, numa tarde. Por outro lado,
um detector de picos ingênuo errou batimentos e dobrou a medida de
variabilidade (SDNN de 141 ms onde o esperado era cerca de 40 ms). O
problema fácil é o BPM; o difícil é tudo o que depende do instante exato de
cada batimento.

Com isso, o escopo foi ampliado. Nada do que a proposta prometeu mudou
(sensor fixo, dedo em repouso, sem compras além das previstas, sem filtro
adaptativo, sem acelerômetro). Mudam os resultados e o cronograma.

| # | Item | PDS envolvido |
|---|---|---|
| **Piso** | | |
| 1 | Anti-aliasing e decimação próprios (sensor a 400 Hz, saída a 100 Hz) | amostragem, aliasing, FIR passa-baixas, comparação com a média interna do sensor |
| 2 | Remoção de DC e passa-faixa 0,5 a 4 Hz | IIR × FIR, resposta em frequência, atraso de fase |
| 3a | BPM por detecção de picos | limiar adaptativo, rejeição de batimento falso |
| 3b | BPM pelo espectro (FFT) | janelamento, resolução espectral × atraso |
| 4 | HRV no tempo | interpolação do pico, SDNN e RMSSD |
| 7 | Detector de sinal ruim (dedo mal posicionado) | relação sinal-ruído, estatística por janela |
| **Alvo** | | |
| 4 | HRV na frequência | LF/HF |
| 5 | SpO2 | separação AC/DC nos dois canais, razão das razões |
| 6 | Frequência respiratória | filtro de banda muito baixa (0,1 a 0,5 Hz), demodulação de amplitude |

**Piso** é o que o grupo se compromete a entregar; **alvo** é o que tenta
entregar. O item 1 merece destaque: o sensor sabe fazer média interna de
amostras, mas essa média é um filtro ruim (lóbulo lateral a -13 dB).
Desligamos a média, lemos o sensor a 400 Hz e fazemos o anti-aliasing e a
redução de taxa nós mesmos, comparando o resultado com o do sensor.

> **Escopo desta entrega.** A ampliação acima é uma decisão do grupo e ainda
> não foi discutida com o professor. Este relatório a apresenta como o plano
> em vigor e pede a confirmação ou os ajustes do professor. O que a proposta
> chamou de "filtragem única" como risco é atacado pelos itens 1 e 7.

## 3. Arquitetura

```
MAX30102 ──► decimacao ──► bruto (com DC) ──┬──► filtro ──► filtrado ──┬──► picos ──► hrv
 400 Hz                       100 Hz        │                          └──► espectral
                                            ├──► qualidade
                                            ├──► spo2
                                            └──► respiracao
```

Cada caixa é um módulo de PDS em C puro, sem dependência da biblioteca da
STM32 (HAL), o que permite compilar e testar tudo no PC com `gcc`. O
display e o laço principal leem só uma struct de resultados.

O que amarra os módulos é a **interface** `ppg.h`, combinada entre os
três antes de qualquer módulo existir. Mudar essa interface exige o ok dos
três. As decisões da versão 1 (PR #99):

- Uma só taxa nas saídas da cadeia: 100 Hz. A taxa do sensor (400 Hz na
  placa, 500 Hz no dado público) é parâmetro da decimação, não da
  interface.
- Dois pontos de saída: **bruto** (com DC, para SpO2, qualidade e
  respiração) e **filtrado** (0,5 a 4 Hz, para picos e espectro).
- Unidade única: contagens do ADC de 18 bits, em `float`.
- O filtro declara o seu atraso, para o detector de picos corrigir o
  instante do batimento.
- O batimento leva o instante com fração de amostra (pico interpolado) e
  uma flag de intervalo válido. Sem isso o HRV a 100 Hz não tem precisão.
- Cada módulo tem `init` e `processa`, sem alocação dinâmica e sem estado
  global.

## 4. O que foi feito até 04/10

A tabela abaixo resume as entregas da primeira semana, com os números
medidos em cada uma.

| Data | Entrega | Números |
|---|---|---|
| 28/09 | Análise offline (spike) em dados públicos; plano dos 7 itens; divisão em três frentes | BPM 77,1 × 77,0 do ECG; HRV precisa de 50 Hz ou mais, ou de pico interpolado |
| 28/09 a 01/10 | Repositório público com CI (firmware ARM, testes do PDS no PC, lint e testes Python, regras de PR, site de documentação, release por tag) e GitHub Project com cards automáticos | main protegida; 1 aprovação de code owner; limite de 400 linhas por PR; doc do módulo obrigatória |
| 02/10 | Configuração da placa: clock de 96 MHz, serial a 921600 com DMA, interrupção do sensor, timer de 100 Hz (PR #86) | |
| 03/10 | Leitura do MAX30102 pela I2C a 400 Hz, 18 bits, FIFO com interrupção, sinal cru enviado ao PC (PR #98, João) | 399,4 amostras/s medidas; 0 perdidas em 20 s; IR ~130 mil e vermelho ~137 mil com o dedo, ~1500 sem dedo |
| 04/10 | Interface `ppg.h` v1 (PR #99, em revisão) | ver seção 3 |
| 04/10 | Carregador do dado público PhysioNet, com IR, vermelho, ECG e marcas de pico R (PR #100, em revisão) | registro s1_sit: 508 s, 613 batimentos; do ECG: 72,4 bpm, SDNN 46,9 ms, RMSSD 30,5 ms |
| 05/10 | Gerador da fonte falsa (issue #15, PR #101, em revisão): trechos do PhysioNet em arrays C para a flash e vetores para os testes no PC | 10 s a 400 Hz; 60 s bruto e filtrado a 100 Hz; marcas do ECG |

Dois achados que valem registro:

- **Sensor segurando o barramento.** Se a placa reseta no meio de uma
  leitura I2C, o sensor fica segurando a linha de dados e a inicialização
  falha. O firmware agora envia até 9 pulsos de clock antes de iniciar,
  para destravar. Aconteceu duas vezes nos testes.
- **Canal vermelho e infravermelho trocados.** A descrição do dado público
  se contradiz sobre qual canal é qual. A razão das razões (base do SpO2)
  decide: com um canal como vermelho a SpO2 dá 97% (o registro mede 98%);
  trocado, dá 63%. No nosso sensor o vermelho também saiu um pouco acima
  do infravermelho, o que vamos conferir com a forma de onda.

## 5. Método de trabalho

**Três frentes em paralelo.** João (A: decimação, filtro, respiração e a
leitura do sensor), André (B: HRV, qualidade, fonte falsa, laço principal,
infraestrutura e relatórios) e Celso (C: picos, espectro, SpO2 e display).
Cada frente tem um revisor fixo em rodízio (A revisado por C, B por A, C
por B), então cada pessoa conhece a fundo duas frentes.

**Ninguém espera o código de ninguém**, por duas razões:

1. A interface foi fechada antes dos módulos.
2. A **fonte falsa**: trechos do dado público gravados na flash da STM32
   (sinal bruto, sinal já filtrado e as marcas de batimento do ECG),
   tocados amostra por amostra como se fossem o sensor. Quem faz picos
   testa na placa sem esperar o filtro; quem faz HRV usa as marcas do ECG
   até os picos ficarem prontos.

**Cada item passa por cinco passos, um PR cada:** protótipo em Python
validado contra o ECG; porte para C; teste no PC comparando o C com os
vetores do Python; placa com a fonte falsa; sensor real.

**Validação sem comprar nada.** O dado público (Pulse Transit Time PPG
Dataset, PhysioNet) tem o mesmo front-end do nosso sensor, a 500 Hz, com
ECG sincronizado. Ele é o gabarito de BPM e HRV. Para SpO2 e respiração,
usamos um oxímetro emprestado se houver, e respiração no ritmo de um
metrônomo.

## 6. Próximos passos até o 2º relatório (26/10)

| Frente | Até 26/10 |
|---|---|
| A (João) | Protótipo e porte da decimação (item 1) e do filtro (item 2); comparação com a média interna do sensor; sinal filtrado do sensor real no PC |
| B (André) | Fonte falsa rodando na placa; timer, filas e laço principal; protótipo do HRV no tempo (SDNN, RMSSD) validado contra o ECG; esboço do detector de qualidade |
| C (Celso) | Protótipo e porte da detecção de picos (3a) com pico interpolado; BPM na placa com a fonte falsa; primeira tela no OLED |

Marcos: a release `v0.1` ("Relatório 1"), com o sinal bruto e a interface,
e a `v0.2` em 26/10, com BPM na placa.

## 7. Riscos

- **Sinal da protoboard pior que o do dado público.** O clipe de dedo do
  PhysioNet tem pressão controlada; o nosso não. Se o sinal real for muito
  ruidoso, o detector de qualidade (item 7) ganha peso e a respiração (item
  6) sai do alvo. A leitura do sensor já funciona, então essa comparação é
  a primeira coisa a fazer.
- **Dependência entre picos e HRV.** O HRV precisa dos instantes dos
  picos. A fonte falsa cobre isso durante o desenvolvimento com as marcas
  do ECG; a dependência só aparece na integração final.
- **Tempo.** São cerca de 67 h por pessoa estimadas para o semestre. O
  cronograma do BPM foi adiantado em relação à proposta justamente para
  sobrar tempo para o restante.

## Referências

- MAXIM INTEGRATED. *MAX30102: High-Sensitivity Pulse Oximeter and
  Heart-Rate Sensor for Wearable Health*. Datasheet, Rev. 0, 2015.
- MEHRGARDT, P. et al. *Pulse Transit Time PPG Dataset* (version 1.0.0).
  PhysioNet, 2022. https://physionet.org/content/pulse-transit-time-ppg/1.0.0/
- O PDF entregue no Moodle foi gerado em LaTeX a partir deste texto.
