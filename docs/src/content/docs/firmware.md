---
title: Firmware
description: O que roda na STM32 fora do PDS.
---

Código que usa HAL, em `Core/Inc` e `Core/Src` (fora de `pds/`).

| Parte | Responsável | Estado |
|---|---|---|
| Leitura do MAX30102 (I2C1, FIFO, INT no PB5) | João | a fazer |
| Serial pro PC (USART1 a 921600 com DMA, adaptador USB-serial) | João | configurada no `.ioc` |
| Fonte falsa (PhysioNet em flash) | André | a fazer |
| Timer, filas e laço principal (TIM2 a 100 Hz já configurado) | André | a fazer |
| Display OLED (I2C3) | Celso | a fazer |

## Pinagem

| Sinal | Pino |
|---|---|
| Sensor SCL / SDA (I2C1) | PB6 / PB7 |
| Sensor INT (EXTI5) | PB5 |
| Display SCL / SDA (I2C3) | PA8 / PB4 |
| Serial TX / RX (USART1) | PA9 / PA10 (TX da placa → RX do adaptador) |
| Cristal HSE 25 MHz | PH0 / PH1 (já soldado na Black Pill) |

## Clock

HSE 25 MHz → PLL (/25, ×192, /2) → **SYSCLK 96 MHz**. APB1 a 48 MHz
(timers a 96 MHz), APB2 a 96 MHz. O TIM2 gera a interrupção de 100 Hz:
96 MHz ÷ 9600 ÷ 100.

## Interrupções

| Interrupção | Pra quê |
|---|---|
| EXTI9_5 (PB5, borda de descida, pull-up) | INT do MAX30102: FIFO com amostras |
| TIM2 (100 Hz) | processamento periódico da cadeia |
| DMA2 Stream 7 + USART1 | envio pela serial sem travar a CPU |

## Regras

- Um PR de cada vez mexe no `.ioc`.
- Depois de regenerar no CubeMX, conferir que nada em `Core/*/pds/` mudou.
