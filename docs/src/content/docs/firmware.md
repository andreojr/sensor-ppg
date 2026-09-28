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

## Configuração do CubeMX

O que está no `sensor-ppg.ioc` e **por quê**. Quem mexer no `.ioc` confere
esta lista antes de gerar o código.

### Clock (Clock Configuration)

Primeiro, em **System Core → RCC**: High Speed Clock (HSE) = **Crystal/Ceramic
Resonator**. Os pinos PH0/PH1 ficam reservados pro cristal de 25 MHz, que já
vem soldado na placa: não ligar nada neles.

| Campo | Valor | Por quê |
|---|---|---|
| Input frequency (HSE) | 25 | cristal da Black Pill |
| PLL Source Mux | HSE | o oscilador interno (HSI) é impreciso |
| /M | 25 | 1 MHz na entrada do PLL |
| ×N | 192 | 192 MHz no VCO |
| /P | 2 | **SYSCLK 96 MHz**: folga pro PDS (FFT, filtros) |
| System Clock Mux | PLLCLK | |
| AHB | /1 | HCLK 96 MHz |
| APB1 | /2 | 48 MHz (o limite do APB1 é 50); timers do APB1 a 96 MHz |
| APB2 | /1 | 96 MHz (USART1 fica aqui) |

Se o clock mudar, **o baud rate da USART1 e o TIM2 mudam junto**: recalcular.

### USART1 (Connectivity)

| Campo | Valor | Por quê |
|---|---|---|
| Mode | Asynchronous | |
| Pinos | PA9 = TX, PA10 = RX | TX da placa no RX do adaptador USB-serial, GND em comum |
| Baud rate | 921600, 8N1 | 400 Hz × 2 canais em texto não cabe em 115200. A 96 MHz o erro é 0,16%; a 16 MHz seria 2,12% (perde bytes) |
| DMA | USART1_TX, DMA2 Stream 7, Memory To Peripheral, Normal, incremento só na memória, Byte/Byte | o DMA envia o buffer e a CPU segue lendo o sensor e rodando o PDS |
| NVIC | USART1 global interrupt | avisa o fim do envio por DMA |

### PB5: INT do MAX30102 (System Core → GPIO)

| Campo | Valor | Por quê |
|---|---|---|
| Mode | External Interrupt, **Falling edge** | o INT do sensor é ativo em nível baixo |
| Pull | **Pull-up** | o INT é dreno aberto |
| NVIC | EXTI line[9:5] interrupts | |

### TIM2: processamento a 100 Hz (Timers)

| Campo | Valor | Por quê |
|---|---|---|
| Clock Source | Internal Clock | |
| Prescaler | 9599 | 96 MHz ÷ 9600 = 10 kHz |
| Counter Period | 99 | 10 kHz ÷ 100 = **100 Hz** (`PPG_FS_HZ`) |
| NVIC | TIM2 global interrupt | |

### Avisos amarelos no CubeMX

Triângulo amarelo em I2C1, USART1, RCC, TIM1, TIM4, SDIO, SPI3 é esperado:
algum modo alternativo daquele periférico usa um pino já ocupado (ex.: o alerta
SMBus do I2C1 é o PB5). Só é problema se ficar **vermelho** ou se o modo de um
periférico em uso mudar sozinho.

### Project Manager

Toolchain **CMake**. O código nosso fica fora de `Core/*/pds/` ou dentro dos
blocos `USER CODE`, que o CubeMX preserva.

## Regras

- Um PR de cada vez mexe no `.ioc`.
- Depois de regenerar no CubeMX, conferir que nada em `Core/*/pds/` mudou.
