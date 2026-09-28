---
title: Firmware
description: O que roda na STM32 fora do PDS.
---

Código que usa HAL, em `Core/Inc` e `Core/Src` (fora de `pds/`).

| Parte | Responsável | Estado |
|---|---|---|
| Leitura do MAX30102 (I2C1, FIFO, INT no PB5) | João | a fazer |
| USB CDC (sinal bruto pro PC) | João | a fazer |
| Fonte falsa (PhysioNet em flash) | André | a fazer |
| Timer, filas e laço principal | André | a fazer |
| Display OLED (I2C3) | Celso | a fazer |

## Pinagem

| Sinal | Pino |
|---|---|
| Sensor SCL / SDA (I2C1) | PB6 / PB7 |
| Sensor INT (EXTI5) | PB5 |
| Display SCL / SDA (I2C3) | PA8 / PB4 |

## Regras

- Um PR de cada vez mexe no `.ioc`.
- Depois de regenerar no CubeMX, conferir que nada em `Core/*/pds/` mudou.
