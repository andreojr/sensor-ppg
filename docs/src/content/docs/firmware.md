---
title: Firmware
description: O que roda na STM32 fora do PDS.
---

Código que usa HAL, em `Core/Inc` e `Core/Src` (fora de `pds/`).

| Parte | Responsável | Estado |
|---|---|---|
| Leitura do MAX30102 (I2C1, FIFO, INT no PB5) | João | feita: `max30102.c` |
| Serial pro PC (USART1 a 921600 com DMA, adaptador USB-serial) | João | feita: `serial.c`, manda o sinal cru |
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

## Leitura do MAX30102 (`max30102.c`)

Endereço I2C 0x57, na I2C1 a 100 kHz. No boot, o `max30102_init()` confere o
PART_ID (0x15), reseta o sensor e configura:

| Registrador | Valor | Por quê |
|---|---|---|
| MODE_CONFIG (0x09) | 0x03, modo SpO2 | vermelho e IR alternados |
| SPO2_CONFIG (0x0A) | 0x2F | ADC em 4096 nA, **400 Hz** (`MAX30102_FS_HZ`), pulso de 411 µs (18 bits) |
| FIFO_CONFIG (0x08) | 0x0F | sem média no sensor (a decimação é nossa), sem rollover, INT com 17 amostras na FIFO |
| LED1_PA / LED2_PA (0x0C / 0x0D) | 0x24 | 7,2 mA no vermelho e no IR |
| INT_ENABLE1 (0x02) | 0x80 | só o A_FULL (FIFO quase cheia) |

Antes do init, o `destrava_i2c1()` (em `main.c`) solta o barramento. Se a placa
resetar no meio de uma leitura (F5, botão de reset, mau contato), o sensor fica
segurando o SDA em 0 esperando o resto do byte. A I2C1 vê o barramento ocupado
e o init falha. Até 9 pulsos no SCL, feitos por GPIO, terminam o byte, e um
STOP libera o barramento.

Sem rollover, se a FIFO encher o sensor descarta as amostras **novas** e conta
no OVF_COUNTER. Assim dá pra saber quantas se perderam.

Fluxo: o INT desce com 17 amostras (a cada 42,5 ms) e a EXTI só marca uma
flag. O laço principal lê INT_STATUS1 (o que solta o INT), os ponteiros da
FIFO e todas as amostras disponíveis numa leitura só do FIFO_DATA (6 bytes por
amostra: vermelho e depois IR, 18 bits cada). Ler 17 amostras leva uns 10 ms
na I2C a 100 kHz. Depois do INT ainda cabem 15 amostras (37,5 ms), então o
laço tem folga. O laço também olha o nível do PB5: se uma leitura falhar e o
INT ficar baixo, não vem outra borda de descida, e sem isso a leitura travaria.

## Serial pro PC (`serial.c`)

921600 8N1, texto, uma linha por amostra:

```text
# MAX30102 400 Hz: n,ir,vermelho
0,112034,98765
1,112040,98771
...
```

- `n` é o índice da amostra a 400 Hz desde o boot. Se o sensor descartar
  amostras, sai uma linha `# perdidas: K` e o `n` pula K. Com isso o PC confere
  que nada se perdeu: os `n` têm que vir em sequência.
- `ir` e `vermelho` são as contagens cruas do ADC (0 a 262143), com DC.
- Linhas que começam com `#` são comentário. Se o sensor não responder no
  boot, sai `# erro: MAX30102 nao respondeu na I2C1` e a placa para.

São no máximo uns 25 bytes × 400 Hz ≈ 10 kB/s, cerca de 11% dos ~92 kB/s da
serial. O envio usa DMA com buffer duplo: o laço preenche um buffer de 1 KiB
enquanto o DMA manda o outro.

## Rodar na placa e ver a leitura

O que precisa no PC:

- Arm GNU Toolchain **11 ou mais novo**, CMake e Ninja no PATH. O GCC 10
  (o do Chocolatey é o 10.3) não linka: o `.ld` do CubeMX 6.18 usa `READONLY`.
- STM32CubeProgrammer, que traz o driver do ST-LINK. A extensão STM32Cube do
  VS Code também instala.
- Adaptador USB-serial de 3,3 V que aguente 921600 (CH340, CP2102, FT232). O
  CH340 precisa do driver CH341SER, do site da WCH.

Ligações, com tudo desligado do USB:

| De | Para (Black Pill) |
|---|---|
| MAX30102 VIN / GND | 3V3 / G |
| MAX30102 SCL / SDA / INT | B6 / B7 / B5 |
| ST-LINK SWDIO / SWCLK / GND / 3.3V | DIO / SCK / G / 3V3 |
| Adaptador RX / GND | A9 / G (o VCC do adaptador fica solto) |

Compilar e gravar:

```bash
cmake --preset Debug
cmake --build --preset Debug
STM32_Programmer_CLI -c port=SWD -w build/Debug/sensor-ppg.elf -v -rst
```

Pra ver a leitura, abra um terminal serial a 921600 na porta do adaptador:
`python -m serial.tools.miniterm COM3 921600` (pyserial), ou o Serial Monitor
do VS Code com `"vscode-serial-monitor.customBaudRates": [921600]` nas
configurações. Sem dedo, IR e vermelho ficam na casa de 1 000; com o dedo,
passam de 100 000 e oscilam ~1% com o pulso.

| Sintoma | Causa provável |
|---|---|
| `# erro: MAX30102 nao respondeu na I2C1` | VIN, GND, SCL ou SDA soltos (o SCL solto é o mais comum) |
| Só o cabeçalho, nenhuma amostra | INT não ligado no B5 |
| Caracteres sem sentido | baud errado (tem que ser 921600) |
| Nada chega | RX do adaptador fora do A9, ou sem GND comum |

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
