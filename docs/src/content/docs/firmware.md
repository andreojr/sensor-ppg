---
title: Firmware
description: O que roda na STM32 fora do PDS.
---

Código que usa HAL, em `Core/Inc` e `Core/Src` (fora de `pds/`).

| Parte | Responsável | Estado |
|---|---|---|
| Leitura do MAX30102 (I2C1, FIFO, INT no PB5) | João | feita: `max30102.c` |
| Serial pro PC (USART1 a 921600 com DMA, adaptador USB-serial) | João | feita: `serial.c`, manda o sinal cru e as saídas da cadeia (bruto, filtrado, batimentos, HRV, BPM do espectral e respiração) |
| Decimação na placa (400 → 100 Hz) e ciclos (DWT) | João | feita: `main.c` e `bancada.c`; ver [Decimação](../modulos/decimacao/) |
| Filtro na placa (bruto → filtrado) | João | feito: `main.c` e `bancada.c`; ver [Filtro](../modulos/filtro/) |
| Picos na placa (filtrado → batimentos e BPM) | Celso / André | feito: `main.c` e `bancada.c`; ver [Picos](../modulos/picos/) |
| HRV na placa (batimentos → SDNN e RMSSD) | André | feito: `main.c`, linhas `h,`, bate com o Python na placa; ver [HRV](../modulos/hrv/) |
| Espectral na placa (filtrado → BPM pela FFT) | Celso | feito: `main.c`, linhas `e,`, bate com o Python na placa; ver [Espectral](../modulos/espectral/) e [FFT](../modulos/fft/) |
| Respiração na placa (bruto → rpm, 1 por segundo) | João | feita: `main.c` e `bancada.c`; ver [Respiração](../modulos/respiracao/) |
| Bancada do HRV na placa (`-DBANCADA_HRV=ON`) | André | feita: `bancada_hrv.c`, passou na placa; ver [HRV](../modulos/hrv/) |
| Bancada da qualidade na placa (`-DBANCADA_QUALIDADE=ON`) | André | feita: `bancada_qualidade.c`, passou na placa (55/55, pior caso 2 149 ciclos no Debug); ver [Qualidade](../modulos/qualidade/) |
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

Resistores (pull-up). O módulo do MAX30102 puxa SDA, SCL e INT para **1,8 V**,
bem no limite do que o STM32 a 3,3 V lê como 1 (~1,8 V). No INT isso dava
interrupção falsa: o clock do I2C acoplava no fio e a EXTI disparava a cada
pulso do SCL (~80 mil por segundo, medido na placa), e o laço lia a FIFO a cada
~2 ms em vez de esperar as 17 amostras. Por isso:

| Pino | Ligação | Por quê |
|---|---|---|
| SDA (B7) | 2 kΩ pro 3V3 | dreno aberto: STM32 e sensor puxam o SDA, o resistor sobe |
| INT (B5) | 2 kΩ pro 3V3 | leva o nível alto pra ~2,8 V, longe do limite: acabam as interrupções falsas |
| SCL (B6) | sem resistor | **push-pull**: só o STM32 dirige o clock (o sensor não estica o SCL), então o próprio pino sobe e desce |

O CubeMX só deixa os pinos do I2C em dreno aberto; o push-pull do SCL fica no
`USER CODE` do `I2C1_MspInit` (`stm32f4xx_hal_msp.c`) e no `destrava_i2c1()`.
O SDA continua em dreno aberto: se os dois lados pudessem empurrar o SDA, um
pra 1 e outro pra 0, seria curto.

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
# decimacao 100 Hz: b,n,ir,vermelho
# filtro 100 Hz, atraso 100: f,n,ir,vermelho
# picos: p,n_pico,fracao,rr_valido,rr_ms,bpm_valido,bpm
# espectral: e,n,bpm_valido,bpm
# hrv: h,n_pico,valido,sdnn,rmssd,rr_usado
# respiracao 1 Hz: r,n,rpm,valido
# tela 1 Hz: t,n,mostra,bpm x100
0,112034,98765
1,112040,98771
...
b,0,112036.41,98768.02
f,0,0.00,0.00
...
p,1234,0.2500,1,812.50,1,73.85
h,1234,1,48.27,33.10,1
r,99,0.00,0
...
e,799,1,73.85
...
t,1199,1,6420
...
# decimacao: ciclos med ... max ... (orcamento 2400)
# filtro: ciclos med ... max ... (orcamento 19200)
# picos: ciclos med ... max ... (orcamento 9600)
# espectral: ciclos med ... (orcamento 9600) max ... (orcamento 960000)
# hrv: ciclos med ... max ... (orcamento 20000)
# respiracao: ciclos med ... max ... (orcamento 9600)
# qualidade: ciclos med ... max ... (orcamento 3000)
```

- `n` é o índice da amostra a 400 Hz desde o boot. Se o sensor descartar
  amostras, sai uma linha `# perdidas: K` e o `n` pula K. Com isso o PC confere
  que nada se perdeu: os `n` têm que vir em sequência.
- `ir` e `vermelho` são as contagens cruas do ADC (0 a 262143), com DC.
- Linhas que começam com `b,` são o **bruto a 100 Hz** que a placa decimou
  (`decimacao_processa()`), com 2 casas: uma a cada 4 amostras do sensor,
  com o `n` a 100 Hz. A saída `n` é o instante da amostra `4n` do sensor e
  sai 60 ms depois dela. Amostra perdida entra na decimação como a última
  repetida, e o `n` do bruto não pula.
- Linhas que começam com `f,` são o **filtrado** (`filtro_processa()`, 0,5
  a 4 Hz, média zero), uma por linha `b,`, com o mesmo `n`. O sinal está
  atrasado de `PPG_ATRASO_AMOSTRAS` (100 amostras = 1 s) e vale depois dos
  primeiros 2 s.
- Linhas que começam com `p,` são os **batimentos** (`picos_processa()` sobre
  o filtrado), uma por batimento: `n_pico` (já sem o atraso do filtro),
  `fracao` (4 casas), `rr_valido` (0/1), `rr_ms`, `bpm_valido` (0/1) e `bpm`
  (`picos_bpm()`, 2 casas). Cada uma sai 300 ms depois do pico no `n` do
  filtrado (o candidato pendente), ou seja, ~1,3 s depois do pulso de verdade
  (mais 1 s do atraso do filtro).
- Logo depois de cada `p,`, uma linha `h,` com a saída do HRV
  (`hrv_processa()` sobre o mesmo batimento): `n_pico`, `valido` (0/1, só
  com 45 s de RR aceitos na janela e 20 diferenças), SDNN e RMSSD em ms com 2 casas,
  e `rr_usado` (0/1): 0 quando a qualidade disse que o trecho não dá pra usar e o RR
  desse batimento ficou de fora do HRV (ver [HRV](../modulos/hrv/)).
- Linhas que começam com `e,` são o **BPM do espectral** (`espectral_processa()` sobre o
  filtrado), uma por segundo, a partir de 8 s de sinal (a janela da FFT): `n` (o do
  filtrado em que a janela terminou), `bpm_valido` (0/1) e `bpm` (2 casas, 0 quando
  inválido). O `n` conta o atraso do filtro, como nas linhas `f,`.
- Linhas que começam com `r,` são a **respiração** (`respiracao_processa()`):
  uma por segundo, com o `n` do bruto que fechou a estimativa, as respirações
  por minuto e `valido` (0 ou 1). Nos primeiros 60 s (a janela enchendo), sai
  `valido` 0.
- A cada 10 s, `# decimacao: ...`, `# filtro: ...`, `# picos: ...`,
  `# espectral: ...`, `# hrv: ...`, `# qualidade: ...` e
  `# respiracao: ciclos med X max Y` medem cada `_processa()`
  com o contador de ciclos do núcleo (DWT). Os orçamentos são 1% da CPU pra
  decimação (96 MHz / 400 Hz / 100 = 2400 ciclos por amostra do sensor), 2%
  pro filtro (19 200 ciclos por amostra a 100 Hz), 1% pro picos (9 600), 1%
  pra respiração (9 600, em média; o espectro roda numa amostra por segundo)
  e 20 000 ciclos por batimento pro HRV (o da bancada do HRV). O espectral tem
  dois orçamentos: **média** de 9 600 ciclos por amostra (1%) e **pior caso** de
  960 000 (a amostra em que sai a FFT, uma por segundo, tem que caber num período de
  amostra: 96 MHz / 100 Hz); `# espectral: ...` mostra os dois.
- Linhas que começam com `#` são comentário. Se o sensor não responder no
  boot, sai `# erro: MAX30102 nao respondeu na I2C1` e a placa para. Se a
  taxa do sensor não tiver filtro de decimação, sai
  `# erro: decimacao sem filtro para essa taxa do MAX30102` e a placa para.

São no máximo uns 25 bytes × 400 Hz + 2 × 30 bytes × 100 Hz ≈ 16 kB/s, cerca
de 17% dos ~92 kB/s da serial. O envio usa DMA com buffer duplo: o laço preenche um buffer de 3 KiB
(cabe a pior leitura: FIFO cheia, linhas `b,` e `f,` e o resumo dos ciclos) enquanto o DMA manda o outro.

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
| 2 kΩ, um em cada | B7 (SDA) → 3V3 e B5 (INT) → 3V3; o SCL fica sem resistor |
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

Pra gravar em CSV e plotar, dentro de `analise/` (o CSV vai pra
`analise/dados/`, que não entra no git). No fim, a captura mostra a taxa medida
e quantas amostras se perderam. As linhas `b,`, `f,`, `p,`, `h,`, `e,` e `r,` vão pra
`<nome>_bruto.csv`, `<nome>_filtrado.csv`, `<nome>_picos.csv`, `<nome>_hrv.csv`,
`<nome>_espectral.csv` e `<nome>_respiracao.csv`, e cada
`--confere` compara o módulo da placa com o do Python no mesmo sinal:

```bash
uv run python -m analise.captura COM3 --segundos 30
uv run python -m analise.plota dados/sensor_<data>_<hora>.csv
uv run python -m analise.decimacao --confere dados/sensor_<data>_<hora>.csv
uv run python -m analise.filtro --confere dados/sensor_<data>_<hora>.csv
uv run python -m analise.respiracao --confere dados/sensor_<data>_<hora>.csv
```

| Sintoma | Causa provável |
|---|---|
| `# erro: MAX30102 nao respondeu na I2C1` | VIN, GND, SCL ou SDA soltos (o SCL solto é o mais comum) |
| Só o cabeçalho, nenhuma amostra | INT não ligado no B5 |
| Caracteres sem sentido | baud errado (tem que ser 921600) |
| Nada chega | RX do adaptador fora do A9, ou sem GND comum |

### Bancada da decimação (fonte falsa)

Com `-DBANCADA_DECIMACAO=ON`, na partida a placa toca a fonte falsa a 400 Hz
(o vetor de `testes/decimacao/vetores/sensor_400hz.h`, ~40 KB na flash) na
decimação, confere com a saída do Python e mede os ciclos. Sai pela serial,
antes das amostras:

```bash
cmake --preset Debug -DBANCADA_DECIMACAO=ON
cmake --build --preset Debug
```

```text
# bancada decimacao: 994 saidas (esperado 994), 0 fora da tolerancia, erro max 8 milesimos
# bancada decimacao: ciclos por amostra med ... max ... (orcamento 2400): OK
```

A opção fica guardada no cache do CMake: volte com `-DBANCADA_DECIMACAO=OFF`.

### Bancada do filtro (fonte falsa)

Igual, com `-DBANCADA_FILTRO=ON`: os 60 s do bruto da fonte falsa (o vetor de
`testes/filtro/vetores/bruto_100hz.h`, ~96 KB na flash) passam pelo filtro e
são conferidos com o Python. As bancadas podem ser ligadas juntas.

```text
# bancada filtro: 6000 saidas, 0 fora da tolerancia, erro max 0 milesimos
# bancada filtro: ciclos por amostra med ... max ... (orcamento 19200): OK
```

### Bancada do picos (fonte falsa)

Com `-DBANCADA_PICOS=ON`: os 40 s do filtrado do `s3_sit` (o vetor de
`testes/picos/vetores/s3_sit.h`) passam pelo picos e são conferidos com o
Python. Pode ser ligada junto com as outras.

```text
# bancada picos: 47 batimentos (esperado 47), 0 fora da tolerancia, erro max ... milesimos
# bancada picos: ciclos por amostra med ... max ... (orcamento 9600): OK
```

### Bancada do espectral (fonte falsa)

Com `-DBANCADA_ESPECTRAL=ON`: os 60 s do filtrado do `s2_walk` (o vetor de
`testes/espectral/vetores/s2_walk.h`, ~24 KB na flash, com saídas válidas e inválidas)
passam pelo espectral e são conferidos com o Python (`valido` exato; `bpm` e prominência
com tolerância de 0,001). Confere também os dois orçamentos de ciclos. Pode ser ligada
junto com as outras.

```text
# bancada espectral: 53 saidas (esperado 53), 0 fora da tolerancia, erro max ... milesimos
# bancada espectral: ciclos por amostra med ... (orcamento 9600), max ... (orcamento 960000): OK
```

**Na placa** (22/11/2026, Release): 53 saídas, 0 fora da tolerância, e o DWT mediu
**951 ciclos por amostra em média e 101 323 no pior caso** (a amostra da FFT, 1,06 ms).
A emulação (`uv run testes/fft/ciclos/ciclos.py espectral`) estimava ~1 060 e ~107 400.

### Bancada da respiração

Com `-DBANCADA_RESPIRACAO=ON`: 5 min do bruto do `s1_sit` (o vetor de
`testes/respiracao/vetores/s1_sit.h`, ~120 KB na flash), porque os 60 s da
fonte falsa só enchem uma janela. Decimação, filtro e respiração juntas
ocupam ~300 KB de flash. Com todas as bancadas ligadas juntas, a flash passa de 400 KB
(dos 512 KB do chip): ligue só as que for usar.

```text
# bancada respiracao: 299 estimativas (esperado 299), 0 diferentes, erro max 0 milesimos de rpm
# bancada respiracao: ciclos por amostra med ... max ... (orcamento 9600): OK
```

### O BPM que a tela mostraria (linha `t,`)

A qualidade roda sempre no laço (não só com a bancada). Uma vez por segundo,
a cada saída dela, sai `t,n,mostra,bpm x100`: `mostra` = 1 só quando a
qualidade diz que o sinal dá pra usar, o picos diz que o ritmo é regular e o
último batimento tem no máximo 3 s (`qualidade_bpm_confiavel()`, ver
[Qualidade](../modulos/qualidade/)); aí `bpm` é o BPM do picos em
centésimos, senão 0. É o que o display vai ler. `analise.captura` grava em
`<nome>_tela.csv`.

### Bancada da qualidade (`bancada_qualidade.c`)

Com `-DBANCADA_QUALIDADE=ON`, a placa, logo depois de `serial_init()` e antes
do sensor, toca o vetor `bordas` (o mesmo de `testes/qualidade/vetores/`,
~73 KB na flash) no `qualidade_processa()`, confere com a saída do Python e
mede os ciclos por amostra: duas linhas `# bancada qualidade: ...`. Depois,
no laço, cada amostra do bruto decimado passa pela qualidade e, uma vez por
segundo, sai uma linha `q,n,dedo,usavel,indice,motivo,dc,pi,aspereza,razao,ritmo`
(inteiros escalados, ver `bancada_qualidade.h`), que o `analise.captura`
grava em `<nome>_qualidade.csv`. Sem a opção, não entram o vetor nem a linha `q,`
(a qualidade em si roda sempre no laço, e a linha `t,` também sai sempre).
Procedimento e orçamento em [Qualidade](../modulos/qualidade/).

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

### I2C3: display OLED (Connectivity)

| Campo | Valor | Por quê |
|---|---|---|
| I2C Speed Mode | **Fast Mode**, 400000 | um quadro inteiro do SSD1306 (1024 bytes) leva ~23 ms a 400 kHz e ~92 ms a 100 kHz. Depois do INT do sensor só cabem 37,5 ms de bloqueio do laço; 30 ms foram medidos na placa sem perda |
| Fast Mode Duty Cycle | Tlow/Thigh = 2 | padrão |
| Pinos | PA8 = SCL, PB4 = SDA | |

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

## Bancada do HRV (`bancada_hrv.c`)

Com `-DBANCADA_HRV=ON` no CMake, a placa, logo depois de `serial_init()` e
antes do sensor, toca as marcas de batimento da fonte falsa (`s1_sit`, o
mesmo vetor de `testes/hrv/vetores/`) no `hrv_processa()`, confere com a
saída do Python e mede os ciclos por batimento com o contador do núcleo
(DWT). O resultado sai em duas linhas `# bancada hrv: ...`. Sem a opção, nada
disso entra no firmware. Procedimento e orçamento em [HRV](../modulos/hrv/).

## Regras

- Um PR de cada vez mexe no `.ioc`.
- Depois de regenerar no CubeMX, conferir que nada em `Core/*/pds/` mudou.
