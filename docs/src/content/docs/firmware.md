---
title: Firmware
description: O que roda na STM32 fora do PDS.
---

Código que usa HAL, em `Core/Inc` e `Core/Src` (fora de `pds/`).

| Parte | Responsável | Estado |
|---|---|---|
| Leitura do MAX30102 (I2C1, FIFO, INT no PB5) | João | feita: `max30102.c` |
| Serial pro PC (USART1 a 460800 com DMA, adaptador USB-serial) | João | feita: `serial.c`; o texto das linhas em `pds/cadeia/linhas.c`. Padrão: bruto e resultados; `-DSERIAL_COMPLETA=ON` acrescenta o sinal cru e o filtrado |
| Decimação na placa (400 → 100 Hz) e ciclos (DWT) | João | feita: `sensor.c` e `bancada.c`; ver [Decimação](../modulos/decimacao/) |
| Filtro na placa (bruto → filtrado) | João | feito: `pds/cadeia/` e `bancada.c`; ver [Filtro](../modulos/filtro/) |
| Picos na placa (filtrado → batimentos e BPM) | Celso / André | feito: `pds/cadeia/` e `bancada.c`; ver [Picos](../modulos/picos/) |
| HRV na placa (batimentos → SDNN e RMSSD) | André | feito: `pds/cadeia/`, linhas `h,`, bate com o Python na placa; ver [HRV](../modulos/hrv/) |
| LF/HF na placa (batimentos → LF/HF, a cada 5 s) | André | ligado na cadeia: `pds/cadeia/`, linhas `l,`, conta espalhada em 17 amostras; capturado com o sensor (24/11): `--replay` com 0 diferenças, LF/HF de 6,03 a 11,05 na respiração lenta; ver [HRV](../modulos/hrv/#na-cadeia-a-cada-5-s-espalhado) |
| Espectral na placa (filtrado → BPM pela FFT) | Celso | feito: `pds/cadeia/`, linhas `e,`, bate com o Python na placa; ver [Espectral](../modulos/espectral/) e [FFT](../modulos/fft/) |
| Respiração na placa (bruto → rpm, 1 por segundo) | João | feita: `pds/cadeia/` e `bancada.c`; ver [Respiração](../modulos/respiracao/) |
| SpO2 na placa (bruto → SpO2 **estimada**) | Celso | bancada passou na placa (24/11: 33/33, erro 0); sensor real (24/11): 361 de 361 válidas, mediana 98,6 a 98,9%: `pds/cadeia/`, `bancada.c`, linhas `s,`; ver [SpO2](../modulos/spo2/) |
| Bancada do HRV na placa (`-DBANCADA_HRV=ON`) | André | feita: `bancada_hrv.c`, passou na placa; ver [HRV](../modulos/hrv/) |
| Bancada da qualidade na placa (`-DBANCADA_QUALIDADE=ON`) | André | feita: `bancada_qualidade.c`, passou na placa (55/55, pior caso 2 149 ciclos no Debug); ver [Qualidade](../modulos/qualidade/) |
| Bancada do LF/HF na placa (`-DBANCADA_HRV_FREQ=ON`) | André | rodou na placa (23/11 e 24/11): 0 fora da tolerância; conta espalhada 0 diferentes em 62 contas, pior passo 136 137 ciclos em Release e 187 285 em Debug (orçamentos 160 000 e 320 000); ver [HRV](../modulos/hrv/) |
| Fonte falsa (PhysioNet em flash) | André | feita: os vetores do PhysioNet das bancadas (`-DBANCADA_*`) |
| Timer, filas e laço principal (#17) | André | feito e medido na placa (23/11): `app.c`, `sensor.c`, `monitor.c`, `pds/cadeia/`. Ver [Laço principal](#laço-principal) e [Cadeia](../modulos/cadeia/) |
| Display OLED (I2C3, SSD1306) | Celso | `display.c` (chip) e `pds/oled/` (telas), chamados pelo `app.c`; ver [Display OLED](#display-oled-displayc) e [OLED](../modulos/oled/) |

## Pinagem

| Sinal | Pino |
|---|---|
| Sensor SCL / SDA (I2C1) | PB6 / PB7 |
| Sensor INT (EXTI5) | PB5 |
| Display SCL / SDA (I2C3) | PA8 / PB4 |
| Buzzer ativo (GPIO saída, nível alto soa) | PB14 |
| Serial TX / RX (USART1) | PA9 / PA10 (TX da placa → RX do adaptador) |
| Cristal HSE 25 MHz | PH0 / PH1 (já soldado na Black Pill) |

## Clock

HSE 25 MHz → PLL (/25, ×192, /2) → **SYSCLK 96 MHz**. APB1 a 48 MHz
(timers a 96 MHz), APB2 a 96 MHz. O TIM2 gera a interrupção de 100 Hz:
96 MHz ÷ 9600 ÷ 100. Ela é a **régua de tempo** do laço (ver [Laço principal](#laço-principal)).

## Interrupções

| Interrupção | Pra quê |
|---|---|
| EXTI9_5 (PB5, borda de descida, pull-up) | INT do MAX30102: FIFO com amostras |
| TIM2 (100 Hz) | régua de tempo: só conta; o monitor relata a cada 1 s se a cadeia acompanhou os 100 Hz (não marca o passo da cadeia: quem marca é o sensor) |
| DMA2 Stream 7 + USART1 | envio pela serial sem travar a CPU |

## Leitura do MAX30102 (`max30102.c`)

Endereço I2C 0x57, na I2C1 a 100 kHz. No boot, o `max30102_init()` confere o
PART_ID (0x15), reseta o sensor e configura:

| Registrador | Valor | Por quê |
|---|---|---|
| MODE_CONFIG (0x09) | 0x03, modo SpO2 | vermelho e IR alternados |
| SPO2_CONFIG (0x0A) | 0x2F | ADC em 4096 nA, **400 Hz** (`MAX30102_FS_HZ`), pulso de 411 µs (18 bits) |
| FIFO_CONFIG (0x08) | 0x0F | sem média no sensor (a decimação é nossa), sem rollover, INT com 17 amostras na FIFO |
| LED1_PA / LED2_PA (0x0C / 0x0D) | 0x24 | 7,2 mA nos dois LEDs (LED1 é o IR e LED2 o vermelho no nosso módulo, abaixo) |
| INT_ENABLE1 (0x02) | 0x80 | só o A_FULL (FIFO quase cheia) |

**LEDs trocados no nosso módulo.** No módulo verde "MAX30100/30102" que usamos, o LED1 (o
"vermelho" do datasheet) é o infravermelho, e o LED2 é o vermelho. Conferido na placa em
24/11/2026: com o LED1 apagado (LED1_PA = 0), a luz vermelha continua acesa. Por isso a leitura
desfaz a troca (`MAX30102_LEDS_TROCADOS` em `max30102.c`, 1 por padrão; para um módulo certo,
mude para 0), e o resto do firmware recebe `ir` e `vermelho` de verdade, como o `ppg.h` pede.

Como se notou: com a ordem antiga, a razão das razões da SpO2 nas capturas de 22 e 23/11 dava
R de 1,9 a 2,7 (SpO2 em torno de 50%, impossível em repouso); com os canais trocados, R de
0,37 a 0,54 (SpO2 de 97 a 100%). Passando essas capturas pela cadeia do Python com os canais
trocados, o BPM fica igual, o BPM confiável sai igual ou mais vezes em todas (ex.: 48 → 73 de 120
linhas `t,` numa captura) e o HRV válido fica praticamente igual ou sobe (40 → 39 na pior).

O teste de 05/10 do relatório 1 (desligar um LED de cada vez) mostrou só que o LED1 cai na
primeira coluna do FIFO, como o datasheet diz; ele não olhava a cor do LED. Por isso a troca
só apareceu com a SpO2.

**Capturas de antes de 24/11 têm `ir` e `vermelho` trocados** (as colunas das linhas `b,` e
das cruas). O `--replay` continua valendo (ele passa o bruto da própria captura pela cadeia),
mas qualquer análise que dependa de qual canal é qual (a SpO2, por exemplo) precisa trocar as
colunas antes.

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

460800 8N1, texto, uma linha por amostra. O texto das linhas sai de
`pds/cadeia/linhas.c` (sem HAL: o replay no PC escreve o mesmo). Dois modos:

- **Padrão:** o bruto (`b,`), os resultados (`p,` `h,` `e,` `r,` `s,` `t,` `l,`) e as
  linhas `#`. É o que a aplicação usa; o `captura --qualidade` julga a qualidade no
  PC a partir do `b,`.
- **`-DSERIAL_COMPLETA=ON`:** acrescenta as cruas a 400 Hz (`n,ir,vermelho`) e o
  filtrado (`f,`), pra captura e conferência contra o Python (`--confere` dos
  módulos e `analise.cadeia --replay`).
- **`-DSERIAL_TELA=ON`:** independente das outras duas: acrescenta as linhas `d,` com as páginas do
  display (ver [Espelho do display](#espelho-do-display--dserial_telaon)).

```text
# sensor-ppg: laco principal, serial completa
# MAX30102 400 Hz: n,ir,vermelho (so na completa)
# decimacao 100 Hz: b,n,ir,vermelho
# filtro 100 Hz, atraso 100: f,n,ir,vermelho (so na completa)
# picos: p,n_pico,fracao,rr_valido,rr_ms,bpm_valido,bpm
# espectral: e,n,bpm_valido,bpm
# hrv: h,n_pico,valido,sdnn,rmssd,rr_usado
# respiracao 1 Hz: r,n,rpm,valido
# spo2 (ESTIMADA, reta 110 - 25 R, sem calibracao): s,n,valido,spo2,r
# tela 1 Hz: t,n,mostra,bpm x100
# lf/hf a cada 5 s: l,n,valido,lf_hf
# laco 1 Hz (TIM2): amostras, fila_max, fila_cheia, perdidas
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
s,799,1,96.36,0.546
t,1199,1,6420
...
l,537,0,0.000
...
# laco: amostras 100 fila_max 5 fila_cheia 0 perdidas 0
...
# decimacao: ciclos med ... max ... (orcamento 2400)
# filtro: ciclos med ... max ... (orcamento 19200)
# picos: ciclos med ... max ... (orcamento 9600)
# espectral: ciclos med ... (orcamento 9600) max ... (orcamento 960000)
# hrv: ciclos med ... max ... (orcamento 20000)
# lf/hf: ciclos med ... (orcamento 9600) max ... (orcamento 320000)
# respiracao: ciclos med ... max ... (orcamento 9600)
# spo2: ciclos med ... max ... (orcamento 9600)
# qualidade: ciclos med ... max ... (orcamento 3000)
# cadeia: ciclos med ... (orcamento 70200) max ... (orcamento 960000)
# volta: ciclos med ... max ... (orcamento 3600000)
# leitura: maior intervalo ... ms (limite 80)
# taxa: 100.02 amostras/s em 10 s (TIM2)
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
- Até ~1 s depois de cada `p,` (o batimento espera o julgamento da qualidade), uma linha `h,` com a saída do HRV
  (`hrv_processa()` sobre o mesmo batimento): `n_pico`, `valido` (0/1, só
  com 45 s de RR aceitos na janela e 20 diferenças), SDNN e RMSSD em ms com 2 casas,
  e `rr_usado` (0/1): 1 se o RR entrou no HRV, 0 se ficou de fora (trecho que a qualidade
  disse não usável, ou RR recusado pelo picos; ver [Qualidade](../modulos/qualidade/)).
- Linhas que começam com `e,` são o **BPM do espectral** (`espectral_processa()` sobre o
  filtrado), uma por segundo, a partir de 8 s de sinal (a janela da FFT): `n` (o do
  filtrado em que a janela terminou), `bpm_valido` (0/1) e `bpm` (2 casas, 0 quando
  inválido). O `n` conta o atraso do filtro, como nas linhas `f,`.
- Linhas que começam com `l,` são o **LF/HF** do HRV (`hrv_freq.h`), uma a cada
  5 s: `n` (a amostra em que a conta terminou, `n % 500 == 37`), `valido` (0/1, só
  com 270 s de RR usados na janela de 300 s, ~4,5 min depois de pôr o dedo) e
  `lf_hf` (3 casas, 0 quando inválido, no máximo 999.999 para não estourar o `long` da
  formatação; o `r` da linha `s,` tem o mesmo teto). A janela termina no último batimento que
  foi pro HRV. A conta é espalhada em 17 amostras (ver
  [HRV](../modulos/hrv/#na-cadeia-a-cada-5-s-espalhado)).
- Linhas que começam com `r,` são a **respiração** (`respiracao_processa()`):
  uma por segundo, com o `n` do bruto que fechou a estimativa, as respirações
  por minuto e `valido` (0 ou 1). Nos primeiros 60 s (a janela enchendo), sai
  `valido` 0.
- A cada 1 s do TIM2, `# laco: ...` (ver [Laço principal](#laço-principal)).
- A cada 10 s, `# decimacao: ...`, `# filtro: ...`, `# picos: ...`,
  `# espectral: ...`, `# hrv: ...`, `# lf/hf: ...`, `# qualidade: ...`, `# spo2: ...` e
  `# respiracao: ciclos med X max Y` medem cada `_processa()`
  com o contador de ciclos do núcleo (DWT). Os orçamentos são 1% da CPU pra
  decimação (96 MHz / 400 Hz / 100 = 2400 ciclos por amostra do sensor), 2%
  pro filtro (19 200 ciclos por amostra a 100 Hz), 1% pro picos (9 600), 1%
  pra respiração (9 600, em média; o espectro roda numa amostra por segundo)
  e 20 000 ciclos por batimento pro HRV (o da bancada do HRV; inclui a guarda do
  RR no LF/HF, `hrv_freq_guarda`, que é uma fila circular: escreve o RR e anda o
  início, sem mover vetor nenhum; medido na placa em 24/11, no máximo 170 ciclos em
  Release e 624 em Debug, com orçamento próprio de 2 000 na bancada do LF/HF). O LF/HF tem média de 9 600 por amostra e pior amostra de 320 000 em
  Debug (160 000 em Release): o pior passo da conta espalhada. O espectral tem
  dois orçamentos: **média** de 9 600 ciclos por amostra (1%) e **pior caso** de
  960 000 (a amostra em que sai a FFT, uma por segundo, tem que caber num período de
  amostra: 96 MHz / 100 Hz); `# espectral: ...` mostra os dois. Depois vêm a
  cadeia inteira por amostra, a volta do laço e o maior intervalo entre duas
  leituras da FIFO (ver [Laço principal](#laço-principal)).
- Uma linha `s,` por segundo (a partir de 8 s de sinal), com a **SpO2 estimada** (`spo2_processa()` sobre o
  **bruto**, não o filtrado): `n` (o do bruto em que a janela terminou), `valido` (0/1), `spo2` em % com 2 casas
  (0 quando inválida) e o `r` (a razão das razões) com 3 casas. Sem calibração com oxímetro, é uma estimativa:
  serve para a tendência e a ordem de grandeza. Só confie com o sinal bom.
- Linhas que começam com `#` são comentário. Se o display não responder no
  boot, sai `# aviso: display nao respondeu na I2C3: segue sem ele` e a placa segue sem ele.
  Se o sensor não responder no
  boot, sai `# erro: MAX30102 nao respondeu na I2C1` e a placa para. Se a
  taxa do sensor não tiver filtro de decimação, sai
  `# erro: decimacao sem filtro para essa taxa do MAX30102` e a placa para.

No padrão são ~30 bytes × 100 Hz ≈ 3 kB/s mais os resultados. Na completa, no
máximo uns 25 bytes × 400 Hz + 2 × 30 bytes × 100 Hz ≈ 16 kB/s, cerca de 35% dos
~46 kB/s da serial a 460800. O envio usa DMA com buffer duplo: o laço preenche um buffer de 3 KiB
(cabe a pior leitura: FIFO cheia, linhas `b,` e `f,` e o resumo dos ciclos) enquanto o DMA manda o outro.

### Espelho do display (`-DSERIAL_TELA=ON`)

Opção de compilação, **desligada por padrão** (sem ela o firmware sai igual ao de antes). Com ela, cada
página que o `display.c` manda com sucesso ao OLED sai também pela serial, numa linha `d,` (o PC remonta a
tela e desenha no terminal; ver a issue #141):

```text
d,<página>,<256 caracteres hexadecimais minúsculos>
```

- `<página>` vai de 0 a 7. Os 256 caracteres são os 128 bytes da página, da coluna 0 à 127, na ordem da
  memória do SSD1306: cada byte é uma coluna e o bit 0 é a linha de cima da página. A linha tem 261 bytes
  com o `\n`. O texto sai de `oled_linha_tela()` (`pds/oled/`, sem HAL, testada no PC).
- Só sai a página que mudou (a que foi pro chip), do mesmo jeito que o I2C. A cada ~10 s
  (`DISPLAY_ESPELHO_MS`) o `display.c` marca as 8 páginas como não enviadas (`oled_invalida()`), e elas vão de
  novo ao chip e à serial, uma por volta do laço (~24 ms de I2C no total, 8 linhas), pra quem liga o PC no
  meio fechar uma tela inteira.
- A linha entra no buffer pelo `serial_escreve()` e nunca espera: se não couber, a linha é descartada, a
  página fica certa no OLED e volta no próximo reenvio.
- **Custo na serial:** 261 B = 5,7 ms de fio a 460800. O reenvio é pouco (8 × 261 B a cada 10 s, ~0,2 kB/s).
  O que pesa é a onda: o teto é 6 páginas por quadro a 20 quadros por segundo, ~31 kB/s (68% dos ~46 kB/s); a
  média medida da onda é ~3,9 páginas por quadro, ~20 kB/s. Isso vem além das linhas de sempre. Por isso o buffer da serial é de **4 KiB** nesse modo (3 KiB sem a opção): no
  tempo que o DMA leva pra mandar um buffer cheio (~67 ms) juntam-se até ~2,3 KB de linhas `d,`, e uma leitura
  pesada (até ~1,8 KB) pode cair em cima. RAM a mais: +2 KiB, só com a opção. Esse número é conta, não
  medida: o quanto a tela atrapalha a captura (linhas `b,` perdidas) fica para a validação na placa (#144).
- **As amostras têm prioridade:** a linha `d,` só entra no buffer se sobrarem ~1,9 KB livres depois dela (o
  pior bloco de amostras, `serial_cabe()`); senão cai só a `d,` e a página volta no reenvio de 10 s. Cada
  linha `d,` descartada é contada e sai a cada segundo, junto do `# laco`, como `# tela: d_descartadas N`
  (só com a opção). No boot, `envia_tudo()` despacha o buffer ao fim (as 3 telas de início escrevem ~3,7 KB).
- **Sem display ativo** (o `display_init` falhou, ou a I2C falhou 3 vezes seguidas e o display se desligou)
  não saem `d,` nem reenvio: o PC fica com a última tela.
- O Python lê a `d,` (PR #146, #142) e mostra a tela no terminal com
  `uv run python -m analise.captura <porta> --tela` (ver
  [Espelho no terminal](../modulos/oled/#espelho-no-terminal---tela)). Sem `--tela`, as `d,` são lidas e
  descartadas, sem contar como linhas inválidas. `--tela` não anda junto com `--qualidade`.

### Por que 460800

Medido em 23/11/2026 (firmware da v0.4.0, Release, serial padrão, adaptador
CH340 (driver ch341), 3 min cada, contando no PC as linhas `b,` que faltaram e as que chegaram
cortadas):

| Baud | Dedo | `b,` faltando | Linhas estragadas |
|---|---|---|---|
| 921600 | sem | 0 | 1 |
| 921600 | com | 18 | 14 |
| 460800 | com | 0 | 0 |

A placa contou 0 amostras perdidas nas três: a perda era só no fio. O dedo encosta no
módulo do sensor, que divide o terra com a placa e o adaptador, e põe ruído na linha
da serial. A 921600 cada bit dura ~1 µs e um pico de ruído vira bit errado: o
adaptador descarta o byte e a linha chega cortada no meio. A 460800 o bit dura o
dobro e a mesma captura não perdeu nada. Ainda sobra banda: a serial padrão usa ~3 kB/s
e a completa até ~16 kB/s, de ~46 kB/s (acima).

## Display OLED (`display.c`)

SSD1306 na I2C3 (SCL no PA8, SDA no PB4, Fast Mode a 400 kHz, já configurado). O código tem duas
partes: o módulo [`oled/`](../modulos/oled/) desenha numa memória de imagem de 1024 bytes (C puro, testado no
PC) e o `display.c` fala com o chip pela HAL, mandando só as páginas que mudaram.

Ligação (conferida na placa em 23/11/2026): VDD em 3V3, GND em G, SCK em A8, SDA em B4 (os nomes são os
do módulo). O módulo tem os pull-ups na plaquinha e funciona a 3,3 V, no mesmo nível da placa.

| Item | Valor | Tipo |
|---|---|---|
| Controlador e ligação | SSD1306, I2C3, PA8 / PB4 | fato (`.ioc`) |
| Endereço | 0x3C (`DISPLAY_ENDERECO`; alguns módulos usam 0x3D) | fato (medido: é o único endereço na I2C3) |
| Resolução | 128 × 64 | fato (confirmada por quem tem o módulo) |
| Orientação | segmentos e linhas remapeados; `-DDISPLAY_ORIENTACAO_NORMAL=0` desfaz | fato (texto em pé na placa) |
| Envio | uma página (128 bytes, 3,1 ms medidos a 400 kHz) por volta do laço principal, nunca no TIM2 | decisão |
| Quadros | 20 por segundo (`DISPLAY_QUADRO_MS = 50`) | decisão |

- **Boot:** o display liga logo depois da serial e mostra a inicialização (uma linha por etapa: `MAX30102`,
  `DECIMACAO`, `FILTRO`). Se o sensor ou a decimação falham, mostra a tela de erro antes de a placa parar.
  A tela de inicialização fica no ar ao menos 2 s (`DISPLAY_AGUARDE_MS`).
- **Display ausente:** `display_init` devolve `false` (o chip não respondeu em `DISPLAY_ENDERECO`), avisa na
  serial e o resto da placa segue. Depois de 3 falhas seguidas de envio o display se desliga **até o próximo
  reset** (a I2C3 é reiniciada a cada falha, mas isso não solta um escravo que segura o SDA; só o display usa
  a I2C3). Antes de cada envio o `display.c` espera o barramento livre por no máximo ~2 ms (a HAL esperaria
  25 ms fixos pelo BUSY), e cada `HAL_I2C_Mem_Write` tem 5 ms de prazo. Pior caso de uma página que falha
  (não medido): ~2 + ~2 + 5 ≈ 10 ms, contra 3,1 ms de uma página boa, no máximo 3 vezes seguidas.
- **Resultados:** o `app.c` passa a ficha da cadeia (`cadeia_resultados()`) e a onda filtrada
  (`display_amostra()`, uma amostra por saída da cadeia, 100 Hz). O BPM segue a regra do BPM confiável:
  aparece só quando `bpm_picos.valido`, que a cadeia liga com `qualidade_bpm_confiavel()` (a mesma decisão
  da linha `t,`), senão `--`. A SpO2 (**estimada**) aparece quando `spo2.valido` (a última saída do
  `spo2_processa()`, a mesma da linha `s,`), senão `--`; com a qualidade julgando sem dedo ou `!usavel`, a tela
  inteira vira SEM DEDO ou SINAL RUIM.

### Bancada do display (demonstração)

Com `-DBANCADA_DISPLAY=ON` a placa, logo depois da serial e **sem precisar do sensor**, percorre as telas com dados de
mentira, num ciclo de 30 s: 0 a 20 s sinal bom (SpO2 e respiração entram aos 10 s), 20 a 25 s sinal ruim com
movimento na onda, 25 a 30 s sem dedo. **Não volta** (é só a demonstração). A cada 5 s manda quanto tempo o laço ficou
bloqueado numa chamada do display, pra conferir a folga do sensor:

```text
# bancada display: chamada do laco med ... us max ... us (folga do sensor 37500 us): OK
```

**Medido na placa (23/11/2026, I2C3 a 400 kHz, módulo 0x3C):**

| Firmware | Pior chamada do display | Volta mais longa | Maior intervalo entre leituras | Perdidas |
|---|---|---|---|---|
| Demonstração (`-DBANCADA_DISPLAY=ON`, Debug) | 4,8 ms (desenhar o resumo) | — | — (sem sensor) | — |
| Cadeia + display, Debug, sem dedo, 30 s | — | 18,6 ms | 43 ms | 0 |
| Cadeia + display, Release, sem dedo, 30 s | — | 14,0 ms | 42 ms | 0 |
| Cadeia + display, Release, com dedo, 90 s | — | 19,2 ms | 45 ms | 0 |

Os limites são 37,5 ms (folga do sensor depois do INT) e 80 ms (FIFO inteira); a fila não passou de 5 de 16.
Com o dedo, a serial disse "BPM confiável" em 82 das 90 linhas `t,` (79 a 95 bpm) e o OLED mostrou o
número (86 BPM na foto da conferência), com a onda de pico pra cima: a inversão de sinal está certa.

## Rodar na placa e ver a leitura

O que precisa no PC:

- Arm GNU Toolchain **11 ou mais novo**, CMake e Ninja no PATH. O GCC 10
  (o do Chocolatey é o 10.3) não linka: o `.ld` do CubeMX 6.18 usa `READONLY`.
- STM32CubeProgrammer, que traz o driver do ST-LINK. A extensão STM32Cube do
  VS Code também instala.
- Adaptador USB-serial de 3,3 V que aguente 460800 (CH340, CP2102, FT232). O
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

Pra ver a leitura, abra um terminal serial a 460800 na porta do adaptador:
`python -m serial.tools.miniterm COM3 460800` (pyserial), ou o Serial Monitor
do VS Code com `"vscode-serial-monitor.customBaudRates": [460800]` nas
configurações. Nas linhas `b,` (bruto), sem dedo IR e vermelho ficam na casa
de 1 000; com o dedo, passam de 100 000 e oscilam ~1% com o pulso.

**O que a serial manda.** No firmware padrão (o da release), só o bruto a 100 Hz
(`b,`), os resultados (`p,`, `h,`, `e,`, `r,`, `s,`, `t,`, `l,`) e as linhas `#`. O sinal cru
a 400 Hz (`n,ir,vermelho`) e o filtrado (`f,`) só saem com
`-DSERIAL_COMPLETA=ON`, e são eles que os `--confere` da decimação, do filtro,
do picos e do HRV precisam.

Pra gravar em CSV e plotar, dentro de `analise/` (o CSV vai pra
`analise/dados/`, que não entra no git). No fim, a captura mostra a taxa medida
e quantas linhas se perderam (pelos saltos no `n` das cruas ou, sem elas, das `b,`). As linhas `b,`, `f,`, `p,`, `h,`, `e,`, `r,`, `s,` e `l,` vão pra
`<nome>_bruto.csv`, `<nome>_filtrado.csv`, `<nome>_picos.csv`, `<nome>_hrv.csv`,
`<nome>_espectral.csv`, `<nome>_respiracao.csv`, `<nome>_spo2.csv` e `<nome>_lfhf.csv`, e cada
`--confere` compara o módulo da placa com o do Python no mesmo sinal:

```bash
cmake --preset Debug -DSERIAL_COMPLETA=ON   # cruas e f, para os --confere
cmake --build --preset Debug
STM32_Programmer_CLI -c port=SWD -w build/Debug/sensor-ppg.elf -v -rst
uv run python -m analise.captura COM3 --segundos 30
uv run python -m analise.plota dados/sensor_<data>_<hora>.csv
uv run python -m analise.decimacao --confere dados/sensor_<data>_<hora>.csv
uv run python -m analise.filtro --confere dados/sensor_<data>_<hora>.csv
uv run python -m analise.respiracao --confere dados/sensor_<data>_<hora>.csv
```

Antes de uma captura que vai valer (o passo 5 de um módulo), use
`--qualidade`: enquanto grava, a captura passa as linhas `b,` pela qualidade
do Python (a mesma conta do C, ver [Qualidade](../modulos/qualidade/)) e diz, uma
vez por segundo, se o sinal está usável. Ajeite o dedo até ver `USAVEL` em
verde por alguns segundos seguidos; se aparecer `placa reiniciou`, conte o
tempo do roteiro a partir dali. Uma linha `b,` que a serial perde entra como a anterior
repetida (a placa não perdeu a amostra); sem isso, a qualidade do Python recomeçava do
zero a cada perda e mostrava ~5 s de "sem ritmo" que a placa não via. Na captura da
v0.4.0 (abaixo), foram 10 quedas de usável para "sem ritmo" antes e 3 depois, as 3
reais (dedo assentando, movimento e a amplitude do pulso caindo).

```bash
uv run python -m analise.captura COM3 --segundos 60 --qualidade
```

```text
   2.0 s  nao usavel: sem dedo  (pi 0.00%)
   9.0 s  nao usavel: sem ritmo  (pi 0.84%)
  12.0 s  USAVEL  (1 seguidos)
  13.0 s  USAVEL  (2 seguidos)
```

O tempo é o do sinal (desde a 1ª linha `b,`). Os motivos são os bits da
qualidade: `sem dedo`, `saturado (aperte menos)`, `pulso fraco`, `movimento`,
`ruido` e `sem ritmo`; sem motivo e ainda não usável é `esperando 3 janelas
boas`. O `pi` é o índice de perfusão (altura do pulso / DC): abaixo de
0,05% é dedo sem pulso; acima de 5%, movimento. Precisa das linhas `b,` (o
firmware manda por padrão).

| Sintoma | Causa provável |
|---|---|
| `# erro: MAX30102 nao respondeu na I2C1` | VIN, GND, SCL ou SDA soltos (o SCL solto é o mais comum) |
| Só o cabeçalho, nenhuma amostra | INT não ligado no B5 |
| Caracteres sem sentido | baud errado (tem que ser 460800; até a v0.4.0 era 921600) |
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
ocupam ~300 KB de flash. As 5 bancadas de módulo juntas ocupam ~360 KB (Release), e com a da cadeia ~440 KB;
com todas as 8 (somando HRV e qualidade) a flash estoura os 512 KB do chip e o
firmware não linka: ligue só as que for usar.

```text
# bancada respiracao: 299 estimativas (esperado 299), 0 diferentes, erro max 0 milesimos de rpm
# bancada respiracao: ciclos por amostra med ... max ... (orcamento 9600): OK
```
### Bancada do spo2 (fonte falsa)

Com `-DBANCADA_SPO2=ON`: os 40 s do bruto do vetor `sem_dedo` (`testes/spo2/vetores/sem_dedo.h`, ~32 KB na flash,
com janelas válidas, inválidas e de transição) passam pelo spo2 e são conferidos com o Python (`valido` exato; `spo2`
e `r` com tolerância de 0,001). Confere também o orçamento de ciclos. Pode ser ligada junto com as outras.

```text
# bancada spo2: 33 saidas (esperado 33), 0 fora da tolerancia, erro max ... milesimos
# bancada spo2: ciclos por amostra med ... max ... (orcamento 9600): OK
```

**Medido na placa (24/11/2026):** 33 de 33 saídas, 0 fora da tolerância, erro 0; ciclos por amostra med 131 e
max 1 532 em Release, 420 e 3 822 em Debug (orçamento 9 600). O emulador do PC dá 197 e 1 701 (sem a espera da
flash). Com o sensor real (24/11): 361 de 361 saídas válidas, mediana 98,6 a 98,9%. Ver [SpO2](../modulos/spo2/).

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
| Baud rate | 460800, 8N1 | a serial completa (cruas a 400 Hz + `f,`, até ~16 kB/s) não cabe em 115200 (11,5 kB/s). A 96 MHz o erro é 0,16%. Era 921600 até a v0.4.0: perdia bytes com o dedo no sensor (ver "Por que 460800") |
| DMA | USART1_TX, DMA2 Stream 7, Memory To Peripheral, Normal, incremento só na memória, Byte/Byte | o DMA envia o buffer e a CPU segue lendo o sensor e rodando o PDS |
| NVIC | USART1 global interrupt | avisa o fim do envio por DMA |

### PB14: buzzer (System Core → GPIO)

GPIO_Output, push-pull, sem pull, velocidade baixa, nível inicial baixo, label `BUZZER`.
Buzzer **ativo** (oscilador interno) ligado direto no pino: nível alto soa.

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

### TIM2: régua de 100 Hz (Timers)

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

Com `-DBANCADA_HRV_FREQ=ON`, o mesmo para o LF/HF: toca o vetor
`freq_s1_sit` no `hrv_freq_processa()`, confere a conta espalhada (a da cadeia)
a cada 10 batimentos, mede o pior `hrv_freq_guarda` e manda quatro linhas
`# bancada lf/hf: ...`. Os orçamentos
são por perfil (Release ou Debug, pelo `__OPTIMIZE__`). As duas opções podem ser
ligadas juntas. O `hrv_freq_t` da bancada (~16,4 KiB) fica `static`, fora da
pilha, além do da cadeia.

## Laço principal

O `main.c` (CubeMX) só liga o hardware, destrava a I2C1 e chama `app_init()` uma
vez e `app_laco()` pra sempre. A aplicação é um **superloop com tarefas
cooperativas**: cada volta chama as tarefas em ordem, e cada uma faz pouco e
devolve o controle, nunca espera nada. É isso que garante ler o sensor a tempo.

```text
 MAX30102 (400 Hz, relógio próprio, FIFO de 32, INT com 17)
   │ INT (EXTI PB5): só levanta a bandeira
   ▼
 app_laco()  (app.c), a cada volta:
   1. sensor_tarefa()   (sensor.c) bandeira ou PB5 baixo → lê a FIFO (~10 ms)
                        → decimação (400 → 100 Hz) → FILA (16 amostras)
   2. cadeia            esvazia a fila: cadeia_processa() (pds/cadeia/)
                        → ficha ppg_resultados_t, linhas na serial, onda pro display
   3. display           display_servico(): uma página (~3 ms) com a ficha
   4. buzzer            buzzer_servico(): bipe por batimento, tom sem batimento
   5. monitor_tarefa()  (monitor.c) a cada 1 s de TIM2: # laco; a cada 10 s: ciclos
   6. serial_envia()    despacha o buffer por DMA

 TIM2 (100 Hz, cristal): a interrupção só soma 1 num contador.
```

**Quem marca o passo é o sensor, não o TIM2.** O MAX30102 conta o tempo com um
oscilador próprio, e o TIM2 conta pelo cristal da placa. Os dois nunca batem
exatamente: se o TIM2 mandasse processar uma amostra a cada 10 ms, uma diferença de
1% faria a fila ganhar ou perder uma amostra por segundo e estourar (ou secar) em
segundos. Por isso o TIM2 é a **régua**: a cada 100 tiques (1 s de cristal) a placa
manda

```text
# laco: amostras 100 fila_max 5 fila_cheia 0 perdidas 0
```

- `amostras`: quantas saíram da cadeia naquele segundo. Oscila de 96 a 104 mesmo com
  tudo certo: as amostras chegam em lotes de 4 ou 5 (17 cruas a cada 42,5 ms), e a
  janela de 1 s do TIM2 corta os lotes onde calhar. O número que prova os 100 Hz é a
  **média**, que sai a cada 10 s: `# taxa: 100.02 amostras/s em 600 s (TIM2)` (no
  tempo do sensor; se o oscilador dele for 1% rápido, sai ~101).
- `fila_max`: o maior enchimento da fila (de 16) no segundo. Normal: 4 ou 5.
- `fila_cheia`: amostras descartadas por fila cheia. Sanidade: com a fila esvaziada a
  cada leitura, não acontece (o pior caso é 16, ver abaixo).
- `perdidas`: amostras que o sensor descartou por FIFO cheia. **Tem que ser 0** (fora
  do primeiro segundo depois das bancadas, em que a FIFO encheu enquanto elas rodavam).
  Junto com `# leitura: maior intervalo`, é a prova de que o laço leu o sensor a tempo.

**A fila** guarda amostras **já decimadas** (`ppg_amostra_t`, `pds/cadeia/fila.h`).
Uma leitura normal traz 17 cruas = 4 ou 5 decimadas. O pior caso é o boot, depois
das bancadas: 32 cruas mais 31 perdidas (o máximo que o sensor conta, que entram como
a última repetida) = 63 cruas, até 16 decimadas. Por isso 16 posições. Cheia, a
amostra nova é descartada e contada. A FIFO do sensor é quem segura as amostras
enquanto o processador está ocupado: depois do INT ainda cabem 15 (37,5 ms).

**O display** lê só a ficha `ppg_resultados_t`, que a cadeia sobrescreve (número só
interessa o mais recente), e recebe a onda filtrada amostra a amostra
(`display_amostra()`, o anel de 256 do módulo `oled/`); a `display_servico()` manda
no máximo uma página por volta (ver [Display OLED](#display-oled-displayc)).

### Ciclos e orçamento

O DWT mede cada módulo, a cadeia inteira por amostra e a volta do laço. O
orçamento de "3 000 ciclos por amostra" da #17 é o da qualidade sozinha; o da
cadeia é a soma dos orçamentos dos módulos. O HRV roda dentro da medida da cadeia,
mas fica fora da soma: só calcula a cada batimento (orçamento de 20 000 ciclos, ~1
por segundo, ou ~200 por amostra na média).

| Medida | Orçamento | Por quê |
|---|---|---|
| Cadeia (`# cadeia`), média por amostra de 100 Hz | 70 200 | filtro 19 200 + picos 9 600 + espectral 9 600 + respiração 9 600 + SpO2 9 600 + qualidade 3 000 + LF/HF 9 600 (a decimação, 2 400 por amostra do sensor, é medida à parte no `sensor.c`); era 51 000 antes da SpO2 e do LF/HF |
| LF/HF (`# lf/hf`), pior amostra | 320 000 (Debug) / 160 000 (Release) | o pior passo da conta espalhada (8 das 109 frequências), nas amostras de `n % 500` de 21 a 37, longe da de `n` terminado em 99 |
| Cadeia, pior amostra | 960 000 | um período (10 ms); a respiração (~0,8 milhão) e a FFT (~0,41 milhão) calculam o espectro **sempre na mesma amostra**, uma vez por segundo (a de `n` terminado em 99): estoura (ver abaixo) |
| Volta do laço (`# volta`) | 3 600 000 (37,5 ms) | a folga do sensor depois do INT |
| Maior intervalo entre leituras da FIFO (`# leitura`) | 80 ms | 32 amostras a 400 Hz; normal ~42,5 ms |

**Se estourar:** passar de 960 000 numa amostra não perde nada se a volta couber (a
fila absorve): só registrar. Se aparecerem `perdidas`, medir em Release e, se não
bastar, defasar o espectro da respiração em relação ao da FFT (hoje os dois saem na
mesma amostra, a cada segundo). Não cortar módulo. A bancada da cadeia segue a mesma
regra: o max acima de 960 000 não reprova, só sai registrado na linha final.

**Medidas na placa (23/11/2026, Debug, `-DBANCADA_CADEIA=ON -DSERIAL_COMPLETA=ON`,
dedo no sensor, 3 min depois do reset):**

| Medida | Placa | Orçamento |
|---|---|---|
| `# cadeia` média por amostra | 25 357 | 51 000 |
| `# cadeia` pior amostra | 1 229 429 | 960 000 (estoura) |
| `# volta` pior volta | 2 491 743 (26 ms) | 3 600 000 (37,5 ms) |
| `# leitura` maior intervalo | 42 ms | 80 ms |
| `# laco` fila_max / fila_cheia / perdidas | 5 / 0 / 0 | 16 / 0 / 0 |
| `# taxa` | 99,9 amostras/s | 100 |

A pior amostra estoura porque a respiração (798 840) e o espectral (409 906)
calculam o espectro na mesma amostra, o que acontece uma vez por segundo. Pela regra
acima, isso só é registrado: a volta coube em 26 ms, a fila chegou a 5 de 16 e nada
se perdeu. Na bancada (vetor do PhysioNet na partida) a cadeia bateu com o Python em
478 saídas, 0 fora da tolerância.

**O firmware da release na placa** (23/11/2026, o `sensor-ppg.hex` da release v0.4.0:
Release, sem bancada, serial padrão; dedo no sensor, ~3 min depois do reset):

| Medida | Release | Orçamento | Debug (acima) |
|---|---|---|---|
| `# cadeia` média por amostra | 4 270 a 8 409 | 51 000 | 25 357 |
| `# cadeia` pior amostra | 423 476 | 960 000 (cabe) | 1 229 429 (estoura) |
| respiração / espectral, pior amostra | 308 575 / 99 870 | | 798 840 / 409 906 |
| `# volta` pior volta | 1 535 236 (16 ms) | 3 600 000 (37,5 ms) | 2 491 743 (26 ms) |
| `# leitura` maior intervalo | 42 ms | 80 ms | 42 ms |
| `# laco` fila_max / fila_cheia / perdidas | 5 / 0 / 0 (182 s) | 16 / 0 / 0 | 5 / 0 / 0 |
| `# taxa` | 99,79 amostras/s em 180 s | 100 | 99,9 |

Cada módulo ficou no seu orçamento (médias: decimação 357, filtro 2 694, picos 159,
qualidade 937, espectral 1 090, respiração 3 176; HRV 4 475 no pior batimento). Em
Release, a pior amostra cabe no período. A pior volta (16 ms) é a amostra do espectro
somada à leitura da FIFO pela I2C1 a 100 kHz.

O `--replay` dessa captura deu 0 diferenças no espectral, na respiração, no HRV e nas
telas. No picos, 35 de 276 batimentos têm a mesma decisão (`rr_valido`, `bpm_valido`) e
só a fração do pico (até 0,28 amostra) e o `rr_ms` (até 3 ms) diferentes, todos perto de
uma das 27 linhas `b,` que chegaram ao PC cortadas ou coladas (ex.
`b,6526,130487.20,12799`). São bytes perdidos no meio da linha, no fio até o PC (a
placa, quando descarta, descarta a linha inteira): ruído do dedo na serial a 921600,
que sumiu a 460800 (ver [Por que 460800](#por-que-460800)).

**A pilha completa na placa** (24/11/2026, já com o LF/HF e a SpO2 na cadeia e os LEDs
corrigidos). Duas medidas:

- **Bancada, sem dedo** (`-DBANCADA_HRV_FREQ=ON -DBANCADA_CADEIA=ON`): a cadeia bateu
  com o Python em 496 saídas, 0 fora da tolerância. Em Release, `# cadeia` med 6 663
  e max 424 454 (orçamentos 70 200 e 960 000); o `# bancada lf/hf` da cadeia, med 113
  e max 2 037 (só o `comeca`: o vetor de 90 s não cobre). Em Debug, med 20 745 e max
  1 252 992 (o max acima de 960 000 só é registrado, como antes). Fila_max 5 e
  perdidas 0 nos dois. A bancada do LF/HF da mesma gravação está em
  [HRV](../modulos/hrv/#3-placa-com-a-fonte-falsa-1).
- **Sensor real** (firmware padrão Release, dedo pressionado com a mão, 370 s desde o
  reset, repouso e depois respiração lenta):

| Medida | Placa | Orçamento |
|---|---|---|
| `# lf/hf` média / pior amostra | 2 437 / 125 579 | 9 600 / 160 000 |
| `# cadeia` média / pior amostra | 11 141 / 425 314 | 70 200 / 960 000 |
| `# volta` pior volta | 1 840 415 (19 ms) | 3 600 000 (37,5 ms) |
| `# leitura` maior intervalo | 46 ms | 80 ms |
| `# laco` fila_max / perdidas | 5 / 0 | 16 / 0 |
| `# taxa` | 99,83 amostras/s em 370 s | 100 |

O `--replay` dessa captura deu 0 linhas diferentes em todas as saídas (picos, hrv,
espectral, respiração, SpO2, tela e lfhf). O BPM mediano do picos foi ~94, e a tela
mostrou o BPM em 168 de 179 e em 178 de 188 segundos. O LF/HF medido está em
[HRV](../modulos/hrv/#lfhf-na-frequência).

**O que não foi medido na placa** (ressalvas da v0.4.0):

- O `rr_usado` do HRV no firmware da release: o `hrv --confere` precisa do filtrado,
  que só sai com `-DSERIAL_COMPLETA=ON` (conferido na v0.3, PR #129).
- A linha final da bancada da cadeia nessa medida não foi guardada (só "478 saídas, 0
  fora da tolerância"). Com o critério de então, ela teria saído `FALHOU` pelo max; o critério
  mudou depois (na pré-release da v0.4.0: o max acima de 960 000 só é registrado) e o
  novo rodou na placa em 24/11/2026 com a pilha completa (496 saídas, 0 fora; no Debug o max de
  1 252 992 só foi registrado, ver "A pilha completa na placa").
- Uma linha que a placa não consegue pôr no buffer da serial (cheio) é descartada sem
  contagem; no PC isso aparece como linha perdida, igual a uma perda no adaptador.
- O `--replay` só confere numa direção: cada linha refeita no PC tem que existir na
  captura, mas uma linha a mais na placa não seria vista.

### Testar

- **PC:** `ctest` roda o `teste_cadeia` (90 s do PhysioNet contra a referência em
  Python, `analise/src/analise/cadeia.py`), o `teste_linhas`, o `teste_fila` e o
  `teste_replay`.
- **Placa, fonte falsa:** `-DBANCADA_CADEIA=ON` passa o mesmo vetor pela cadeia na
  partida e mede os ciclos. Em 90 s o LF/HF nunca cobre os 270 s: a linha
  `# bancada lf/hf` dali mede só o `hrv_freq_comeca`, não o pior passo (esse vem
  de `-DBANCADA_HRV_FREQ=ON`).
- **Placa, sensor:** comece a captura e aperte o reset;
  `uv run python -m analise.cadeia --replay dados/<captura>.csv` refaz no PC, a
  partir do bruto que a placa mandou, todas as linhas de resultado e confere que são
  iguais às da placa (ver [Cadeia → Replay](../modulos/cadeia/#replay-a-prova-de-que-nada-mudou)).

Flash/RAM (Release): 52 724 / 35 288 B antes do laço novo, 54 284 / 37 032 B
depois (135 KB de flash com a bancada da cadeia). Em Debug, 78 788 / 37 040 B.

Com o display, a SpO2 e o LF/HF na cadeia (medido pelo linker em 24/11/2026, sem bancada):
Release 63 472 B de flash e 57 264 B de RAM; Debug 94 152 e 57 272. O LF/HF
acrescentou 16 872 B de RAM (o `hrv_freq_t` dentro do `cadeia_t`, que agora tem
~41 KB) e ~2 KB de flash em Release (antes dele, já com a SpO2: 61 264 / 40 392 B).
Com `-DBANCADA_CADEIA=ON`: Release 144 832 / 57 632 B, Debug 176 828 / 57 640 B. A F411
tem 512 KB de flash e 128 KB de RAM.

### Buzzer (`buzzer.c`, `buzzer_logica.c`, #152)

Feedback sonoro como monitor hospitalar, no PB14 (buzzer ativo, nível alto soa, ligado direto):

- **bipe curto** (`BUZZER_BIPE_MS` = 80 ms) a cada batimento detectado (`cadeia_saida_t.bateu`);
- **tom contínuo** só com o **dedo no sensor** e batimento perdido: faz `BUZZER_PERDA_MS` = 3 s sem batimento
  (o RR de 40 bpm é 1,5 s) ou a qualidade julgou o sinal não usável com dedo presente
  (`valido && dedo_presente && !usavel`). Os batimentos de sinal ruim são ignorados (podem ser ruído);
- **dedo retirado** (`valido && !dedo_presente`): tom por `BUZZER_SEM_DEDO_MS` = 3 s e depois **cala**, sem
  repetir. Fica mudo até o dedo voltar e o primeiro batimento rearmar o monitor;
- o tom contínuo **para** no primeiro batimento com sinal usável, que já dá o bipe;
- **mudo** até o primeiro batimento (placa ligada sem dedo não apita) e se um dos três parâmetros for 0.

Reaproveita os sinais da cadeia, sem módulo de PDS novo. Não bloqueia: o tempo vem de
`HAL_GetTick()` e `buzzer_servico()` só escreve o pino quando o nível muda (custo desprezível, sem
mudar o orçamento da volta). A regra (`buzzer_logica.c`, C puro, sem HAL, fora de `pds/`) é testada no PC
(`testes/buzzer/teste_buzzer.c`). O bipe sai ~1,3 s depois do pulso de verdade (atraso do filtro mais o
candidato pendente do picos), como as linhas `p,`. **Testado na placa (bipe por batimento, tom contínuo e silêncio sem dedo).**

## Recuperação de falhas

Três recuperações automáticas, para a placa voltar sozinha de um travamento durante a medida. Elas **não consertam a causa elétrica provável** (ruído, mau contato, reset no meio de uma transferência): só recuperam. Nenhuma linha nova na serial.

| Recuperação | Quando age | O que faz | Limite |
|---|---|---|---|
| I2C3 (`destrava_i2c3`, `display.c`) | No `display_init` e a cada falha de envio ao display | `HAL_I2C_DeInit`, 9 pulsos no SCL (PA8) com o SDA (PB4) solto e um STOP, e depois o `HAL_I2C_Init`. Leva ~0,2 ms (espera por laço curto, sem `HAL_Delay`), cabe numa volta do laço (a mais longa é ~16 ms, limite 37,5 ms). | O OLED pode segurar o SDA em baixo no meio de um byte e um reset do microcontrolador não solta o chip (medido: BUSY da I2C3 preso, SDA=0, SCL=1, sem erro da HAL). Se o chip travar de outro jeito, o display se desliga depois de 3 falhas seguidas e tenta religar (`display_init` de novo) a cada 2 s, sem travar o laço (~17 ms por tentativa com o chip ausente, ~28 ms uma vez quando ele volta). Um OLED que perde a energia e volta responde com ACK sem a configuração: não é detectado, só um reset resolve. |
| Sensor (`recupera`, `sensor.c`) | Sem amostras por 1000 ms | `max30102_init` de novo (reset e configuração completa, acende os LEDs). Se falhar, reinicia a I2C1 e tenta de novo 1 s depois, sem desistir. | A cadeia de PDS não é reiniciada: o trecho sem sinal sai como qualidade ruim. Se o SDA da I2C1 ficar preso pelo sensor, `DeInit`/`Init` não solta (a `destrava_i2c1` do `main.c` só roda no boot). |
| Watchdog independente (IWDG, `main.c`) | Se o laço principal parar de voltar por ~2 s | Reinicia o microcontrolador. LSI ~32 kHz, prescaler /64, recarga 1000. Alimentado depois do `app_laco()`. | Ligado direto nos registradores (só em blocos `USER CODE`, sobrevive à regeneração do CubeMX), depois do `app_init`: o boot não é coberto. Parado no debugger. As bancadas (`BANCADA_*`) rodam no `app_init`, antes dele. |

## Laço simples, sem RTOS

**Decisão:** a cadeia roda num laço principal simples, com uma fila pequena
(sensor para cadeia); o display lê a ficha `ppg_resultados_t`, sem fila. Não usamos RTOS: o curso não exige, e
a medida na placa mostrou que ele não faz falta.

**A pergunta:** se o display travar o laço por ~30 ms, o sensor perde amostras?
O MAX30102 guarda até 32 amostras (80 ms a 400 Hz) e avisa pelo INT com 17, o que
deixa **37,5 ms** de folga depois do aviso. A bancada do bloqueio parou o laço de
propósito (espera ativa, sem ler o sensor) e mediu o maior intervalo entre duas
leituras da FIFO com o DWT.

Medido na placa (22/11/2026, 30 s por configuração, I2C3 a 400 kHz, resistor de
2 kΩ no INT), **0 amostras perdidas em todas**:

| Bloqueio / período | Maior intervalo entre leituras | Amostras na FIFO no pior caso (de 32) |
|---|---|---|
| 0 ms (linha de base) | 42,6 ms | 17 |
| 3 ms a cada 10 ms (uma página do display) | 42,6 ms | 17 |
| 30 ms a cada 50 ms (quadro inteiro) | 46,7 a 50 ms | 18 a 20 |
| 30 ms a cada 20 ms (pior caso) | 72,6 ms | 29 |

**Como ler:**

- Um quadro inteiro de ~30 ms cabe, mas **apertado**: no pior caso sobram 3 vagas
  (~7,5 ms). Bloqueios acima de ~37 ms depois do aviso perdem amostras.
- Mandar **uma página (~3 ms) por volta do laço** não muda o intervalo: folga total.
  É o que o display usa.
- Isso vale com a I2C3 a **400 kHz**. A 100 kHz um quadro leva ~92 ms, passa dos
  80 ms da FIFO e perde amostras com certeza.

**Armadilha achada no caminho:** o INT do módulo fica em ~1,8 V (pull-up do módulo),
no limite do que o STM32 lê como 1, e o clock do I2C vazava nele (~80 mil
interrupções falsas por segundo, o que fazia o laço ler a FIFO a cada ~2 ms).
Afastar os fios só reduziu pela metade, e trocar o pino (B5 por A1) não mudou nada.
O que resolveu foi o resistor de 2 kΩ do INT para o 3V3 (ver "Resistores").

A bancada ficou na branch `firmware/experimento-bloqueio-display` (só local, não
entra na `main`); a decisão fica registrada aqui e na #17. O laço que saiu dela
está em [Laço principal](#laço-principal).

## Regras

- Um PR de cada vez mexe no `.ioc`.
- Depois de regenerar no CubeMX, conferir que nada em `Core/*/pds/` mudou.
