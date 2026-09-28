---
title: sensor-ppg
description: Processamento digital de sinais de fotopletismografia em tempo real.
---

Projeto da disciplina ENGG54 (Laboratório Integrado III, UFBA, 2026.2):
estimar frequência cardíaca, variabilidade dos batimentos, oxigenação e
respiração a partir de um sensor óptico de dedo, **com todo o processamento
feito por nós**, rodando em tempo real numa STM32.

> Projeto de alunos da disciplina. Não é um site oficial da UFBA.

## Hardware

| Peça | Papel |
|---|---|
| MAX30102 (I2C1) | LEDs vermelho e infravermelho + ADC de 18 bits. Entrega o sinal cru. |
| STM32F411 (Black Pill) | Roda a cadeia de PDS amostra a amostra. |
| OLED SSD1306 (I2C3) | Mostra a onda e os resultados. |

Dedo em repouso, sensor fixo na protoboard.

## A cadeia de processamento

```
MAX30102 ──► decimacao ──► bruto (com DC) ──┬──► filtro ──► filtrado ──┬──► picos ──► hrv
                                            │                          └──► espectral
                                            ├──► qualidade
                                            ├──► spo2
                                            └──► respiracao
```

Cada caixa é um módulo em `Core/*/pds/<módulo>/`, com uma página em
[Módulos de PDS](modulos/decimacao/).

## Equipe

| Frente | Quem | Módulos |
|---|---|---|
| A: filtragem | João | decimacao, filtro, respiracao |
| B: HRV | André | hrv, qualidade |
| C: batimento | Celso | picos, espectral, spo2 |

## Marcos

| Data | Entrega |
|---|---|
| 05/10 | 1º relatório parcial |
| 26/10 | 2º relatório parcial |
| 23 ou 30/11 | Apresentação final |
