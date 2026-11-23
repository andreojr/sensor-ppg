# Laço principal: sensor, cadeia, display e fiscal (#17)

Data: 23/11/2026. Issue: #17 ("Timer, filas e laço principal com medição de
ciclos"). Prazo da issue: 27/11; apresentação: 30/11.

## Por quê

Os sete módulos de PDS da v0.3 (decimação, filtro, picos, HRV no tempo,
qualidade, espectral, respiração) já rodam juntos na placa, mas **grudados na
leitura do sensor**: o `main.c` lê a FIFO do MAX30102 e passa cada amostra pela
cadeia inteira na hora, dentro da mesma função (`decima()`), junto com a serial.
Não há fila, o TIM2 está configurado e nunca é ligado, ninguém preenche o
`ppg_resultados_t` que o display vai ler, e só se mede o custo de cada módulo,
não o da cadeia nem o da volta do laço.

A #17 pede: "cadeia chama o processa de cada módulo a 100 Hz sem estouro de fila;
ciclos por amostra medidos". A decisão de 22/11 (`firmware.md`, "Laço simples,
sem RTOS") fixou o formato: **laço simples com duas filas pequenas, sem RTOS**,
display por páginas de ~3 ms por volta, porque depois do INT do sensor só cabem
~37,5 ms de bloqueio.

O André precisa conseguir **explicar e defender** o desenho na banca: o mais
simples que cumpra a issue, com números medidos como prova.

## Objetivos

- `main.c` só liga o hardware e chama `app_init()` e `app_laco()`.
- O laço é um **superloop com tarefas cooperativas**: cada tarefa faz pouco e
  devolve o controle, nunca espera nada.
- A cadeia de PDS vira um módulo sem HAL (`cadeia`), testável no PC.
- O `ppg_resultados_t` é preenchido pela cadeia e lido pelo display.
- O TIM2 a 100 Hz vira **régua de tempo**: prova com números que a cadeia
  acompanha os 100 Hz e que a fila não estoura.
- Medidas com o DWT: cada módulo, a cadeia por amostra e a volta do laço.
- Os resultados (BPM, HRV, respiração, espectral, qualidade, tela) saem
  **iguais** aos da versão atual: reorganizar não muda nenhum número.

## Fora do escopo

- RTOS, DMA na I2C, I2C1 a 400 kHz, SpO2 (#125), LF/HF (#115).
- Mudar o `ppg.h` (precisa do ok do grupo) ou o `.ioc`.
- Mudar qualquer módulo de `pds/` existente.
- O driver e as telas do display (#121, #122, do Celso): aqui só se define o
  ponto de encaixe.
- Suporte de dedo, ergonomia, hardware (ressalva da apresentação).

## Anti-objetivos (falharia mesmo "funcionando")

- O TIM2 **marcar o passo** da cadeia (ver Abordagens: os relógios divergem).
- Qualquer tarefa bloquear o laço por mais que o necessário (ler a FIFO, uma
  página do display, as amostras da fila).
- Saída dos módulos diferente da versão atual sem explicação.
- Conflito difícil com o #122: o encaixe do display tem que ser uma chamada.

## Abordagens consideradas

1. **Sensor dita o ritmo, fila de 100 Hz, TIM2 de régua (escolhida).** O INT
   avisa, o laço lê a FIFO, decima na hora e põe as amostras de 100 Hz numa
   fila; a cadeia esvazia a fila; o display manda uma página. O TIM2 só conta.
   Simples, sem deriva, cumpre a issue com prova medida.
2. **Manter a cadeia dentro da leitura e só acrescentar medidas.** Menor PR, mas
   não tem a fila que a issue pede e mistura ler e processar.
3. **TIM2 marca o passo (plano de setembro, PR #86).** O sensor tem oscilador
   próprio (400 Hz) e o TIM2 conta pelo cristal; uma diferença de 1% faz a fila
   ganhar ou perder 1 amostra por segundo e estourar (ou secar) em segundos.
   Corrigir isso é mais código sem ganho. Descartada.

Um parecer independente (subagente, a partir só da spec) chegou à abordagem 1,
com a fila de amostras já decimadas e a cadeia em módulo próprio; o André
aprovou com o ajuste de que a cadeia não chama o display (ela é sem HAL).

## O desenho

```
 MAX30102 (400 Hz, relógio próprio, FIFO de 32, INT com 17)
   │ INT (EXTI PB5): só levanta a bandeira
   ▼
 app_laco()  ── roda sem parar, cada tarefa curta:
   1. sensor_tarefa()   bandeira ou PB5 baixo → lê a FIFO (~10 ms a 100 kHz)
                        → decimação (400 → 100 Hz) → FILA (16 × ppg_amostra_t)
   2. cadeia_tarefa()   enquanto a fila tem amostra: cadeia_processa()
                        → atualiza a FICHA (ppg_resultados_t)
                        → display_amostra(filtrado.ir)  [anel da onda, #121]
                        → linhas de resultado na serial
   3. display_tarefa()  display_servico(&ficha, HAL_GetTick())  [1 página, #122]
   4. monitor_tarefa()  a cada 100 tiques do TIM2 (1 s): taxa, fila, perdidas;
                        a cada 10 s: ciclos
   5. serial_envia()    (já existe: despacha o buffer por DMA)

 TIM2 (100 Hz, cristal): a interrupção só soma 1 num contador.
```

### Arquivos

| Arquivo | Camada | O que faz |
|---|---|---|
| `Core/Src/main.c` | CubeMX | `app_init()` antes do laço, `app_laco()` dentro; mais nada nos blocos `USER CODE` |
| `Core/Src/app.c`, `Core/Inc/app.h` | app (HAL) | init de tudo, ordem das tarefas, callbacks do EXTI e do TIM2 |
| `Core/Src/sensor.c`, `Core/Inc/sensor.h` | app (HAL) | ler a FIFO, tratar perdidas, decimar, encher a fila |
| `Core/Inc/pds/cadeia/cadeia.h`, `Core/Src/pds/cadeia/cadeia.c` | pds (sem HAL) | a cadeia de módulos, a regra do BPM confiável, a ficha, os ciclos por módulo |
| `Core/Src/monitor.c`, `Core/Inc/monitor.h` | app (HAL) | TIM2, DWT, relatórios `#` na serial |
| `Core/Src/display.c` | app (HAL) | do Celso (#122); aqui não muda |

A fila sensor → cadeia é um anel simples de `ppg_amostra_t` (16 posições), no
`sensor.c` ou num `fila.h` pequeno; escolha do builder.

### Fila sensor → cadeia

- Guarda amostras **já decimadas** (100 Hz). Uma leitura da FIFO dá no máximo
  32 cruas = 8 decimadas; 16 posições é o dobro.
- O laço esvazia a fila inteira a cada volta (a folga é grande; ver Ciclos).
- **Se encher:** descarta a amostra nova e conta (`fila_cheia`). Com a fila
  esvaziada toda volta, isso só acontece se algo travar o laço; o contador é a
  prova de que não aconteceu.
- As perdidas do **sensor** (FIFO de 32 cheia) seguem como hoje: a decimação
  recebe a última amostra no lugar de cada perdida, para o `n` seguir alinhado
  com o tempo do sensor; o total vai para o monitor.

### A cadeia (`pds/cadeia/`)

Segue o molde do `ppg.h` (estado numa struct de quem chama, sem malloc, sem
global, sem HAL):

```c
bool cadeia_init(cadeia_t *c, cadeia_relogio_t relogio); /* relogio: NULL no PC */
void cadeia_processa(cadeia_t *c, const ppg_amostra_t *bruto, cadeia_saida_t *s);
```

- `cadeia_t` guarda o estado de filtro, picos, HRV, qualidade (e a fila do HRV),
  espectral e respiração, a ficha `ppg_resultados_t` e os ciclos por módulo.
- `relogio` é um ponteiro para função que devolve o contador de ciclos (na placa,
  o DWT; no PC, NULL = não mede). Assim a cadeia mede cada módulo sem incluir
  HAL.
- `cadeia_saida_t` diz o que aconteceu nesta amostra, para o `app` mandar pela
  serial e pro display: o filtrado; se saiu batimento (e qual, com o BPM do
  picos); se saiu espectral, respiração, julgamento da qualidade (e o `mostra`
  da tela); e as saídas do HRV desta amostra (podem ser várias: a fila do HRV
  solta até `QUALIDADE_FILA` batimentos de uma vez).
- **Ordem e regras: exatamente as de hoje** (`decima()` no `main.c` da
  c6727a2), para os números saírem iguais: filtro → picos (com batimento:
  `picos_bpm`, `qualidade_batimento_usavel` do julgamento de antes,
  `qualidade_fila_poe`, o velho que transborda vai pro HRV) → espectral →
  respiração → qualidade (julgou: guarda o julgamento, `qualidade_fila_tira`
  até esvaziar e manda cada um pro HRV, `qualidade_bpm_confiavel`).
- **A ficha:** `ultimo_batimento`, `bpm_picos` (com `valido` = o resultado de
  `qualidade_bpm_confiavel`, ou seja, o display recebe o BPM já filtrado pela
  regra), `bpm_espectral`, `hrv`, `respiracao`, `qualidade`. `spo2` fica
  `valido = false` até a #125.
- *Decisão do builder (Claude):* a regra roda quando a qualidade julga (1 vez
  por segundo), como a linha `t,` de hoje. Entre dois julgamentos, o
  `bpm_picos.valido` da ficha **mantém a última decisão da regra**; o número
  (`bpm`) acompanha o último batimento. A cadeia guarda o BPM cru do picos à
  parte e é ele que entra na regra (a ficha nunca realimenta a regra). Pior
  caso: o número de um batimento novo aparece até 1 s antes de a regra o
  reavaliar, mas a regra já confere a idade do batimento.
- O `ciclos_t` (média e máximo) sai do `bancada.h` (que inclui HAL) para um
  header sem HAL, usado pela cadeia e pelo `bancada.c`.

### TIM2: régua de tempo

- `HAL_TIM_Base_Start_IT(&htim2)` no `app_init()`; o callback só incrementa um
  contador `volatile`.
- A cada 100 tiques (1 s de cristal), o monitor relata e zera:
  `# laco: amostras X fila_max Y fila_cheia Z perdidas W`.
  - `amostras` ≈ 100 prova os 100 Hz (no tempo do sensor; o desvio do
    oscilador dele aparece aqui, ex. 99 ou 101).
  - `fila_max`, `fila_cheia`, `perdidas`: prova de que nada estourou.
- O `firmware.md` é corrigido: o TIM2 deixa de ser "processamento periódico da
  cadeia" e vira "régua de tempo do monitor", com o porquê (dois relógios).

### Ciclos (DWT)

- **Por módulo:** como hoje (`ciclos_t`, média e máximo), agora dentro da cadeia
  via `relogio`; a decimação medida no `sensor.c`.
- **Cadeia por amostra:** uma chamada de `cadeia_processa` inteira.
- **Volta do laço:** do início ao fim de `app_laco()`, e o maior intervalo entre
  duas leituras da FIFO (o que precisa caber nos 37,5 ms depois do INT).
- Relato a cada 10 s, no formato `# <nome>: ciclos med X max Y (orcamento Z)`.

**Orçamento (corrige a issue, que fala em 3 000 por amostra: esse é o da
qualidade sozinha, `qualidade.md`):**

| Medida | Orçamento | Esperado (soma das medidas dos módulos) |
|---|---|---|
| Cadeia, média por amostra de 100 Hz | soma dos orçamentos dos módulos (~61 000) | ~24 000 (2,5% da CPU) |
| Cadeia, pior amostra | 960 000 (um período, 10 ms) | ~930 000 se o espectro da respiração (~800 mil) e a FFT (~100 mil) caírem na mesma amostra: **apertado** |
| Maior intervalo entre leituras da FIFO | 37,5 ms depois do INT (~80 ms entre leituras) | ~42,5 ms normal; pior volta estimada ~15 ms de trabalho |

Os orçamentos dos módulos foram medidos no Debug; os da cadeia também (o build
da apresentação deve ser conferido, como diz o `fft.md`).

**Se estourar:** a pior amostra passar de 960 mil não perde nada se a volta
couber (a fila absorve): só registrar e documentar. Se o intervalo entre
leituras passar do limite (aparecem `perdidas`), medir em Release e, se não
bastar, pedir aos donos da respiração e do espectral que defasem o cálculo de
um em relação ao do outro. Não cortar módulo.

### Serial

- **Padrão:** os resultados (`p,`, `e,`, `h,`, `r,`, `t,`), o **bruto a 100 Hz
  (`b,`)** e as linhas `#` do monitor. Mesmo formato de hoje. O `b,` fica no
  padrão (decisão do André, 23/11) porque o `captura --qualidade` (#130) julga
  a qualidade no PC a partir dele; custa ~100 linhas curtas por segundo
  (~3 KB/s), e o monitor mostra quanto em ciclos.
- **`-DSERIAL_COMPLETA=ON` no CMake:** acrescenta as cruas (`n,ir,vermelho`, 400
  Hz) e o `f,`, para captura e conferência contra o Python. Usado na validação
  do PR.
- O cabeçalho `#` do início diz qual modo está ligado.

### Display (encaixe com o #122)

- `display_amostra(filtrado.ir)` chamado pelo `app` a cada amostra da cadeia (a
  cadeia não chama o display: ela é sem HAL).
- `display_servico(&ficha, HAL_GetTick())` uma vez por volta.
- Telas de boot/erro (até ~25 ms) só antes do laço.
- Enquanto o #122 não entra, `display_tarefa()` existe e não faz nada (ou fica
  atrás de um `#ifdef`); quem entrar depois faz o rebase.

## Testes (fluxo da casa)

1. **Python:** um `analise/cadeia.py` (ou função) que encadeia os módulos Python
   que já existem, na mesma ordem, e gera um vetor de referência a partir de um
   trecho do PhysioNet (bruto a 100 Hz).
2. **PC:** `testes/cadeia/` passa o mesmo bruto em `cadeia_processa` e compara
   com o Python: batimentos, BPM, BPM confiável, HRV, espectral, respiração e
   qualidade. Entra no `ctest` como os outros; o `guarda_sem_hal` cobre o novo
   módulo.
3. **Placa (fonte falsa):** `-DBANCADA_CADEIA=ON` roda o mesmo vetor na placa,
   confere as saídas e mede ciclos (módulos, cadeia).
4. **Placa com o sensor:** 5 a 10 min com o dedo, `-DSERIAL_COMPLETA=ON`:
   `perdidas` = 0, `fila_cheia` = 0, `amostras` ≈ 100 por segundo, pior volta e
   pior intervalo entre leituras; e o `--confere` dos módulos contra o Python
   batendo como antes.
5. **Regressão** (*decisão do builder*): gravar uma captura com a versão
   c6727a2 (que já manda as cruas por padrão) e, **no PC**, reproduzir as cruas
   de 400 Hz pela decimação + `cadeia_processa`. As linhas de resultado (`p,`,
   `e,`, `h,`, `r,`, `t,`) têm que sair iguais às que a placa antiga mandou
   (mesmo código em float32: igual de fato). A ordem entre tipos de linha
   dentro de uma mesma amostra pode mudar; compara-se por tipo. Esse replay
   entra como ferramenta de PC (script ou executável de teste), não como
   bancada.

*Critério C × Python no `testes/cadeia/`* (*decisão do builder*): saídas
discretas iguais (quantidade e `n_pico` dos batimentos, `rr_valido`, `valido`,
`usavel`, `mostra`, `rr_usado`); números com a tolerância que cada módulo já
usa no `confere.h`. Divergência discreta é investigada; se a causa for
float32 × float64 num caso de fronteira, documenta-se e escolhe-se outro
trecho, nunca se afrouxa a regra.

O display (`display_amostra`, `display_servico`) ainda não existe na `main`:
enquanto o #122 não entra, o `app` usa funções vazias com a mesma assinatura do
#122.

Nada na placa sem o OK do André.

## Combinar com o Celso (#121, #122)

- O formato acima: `display_amostra` por amostra, `display_servico` por volta,
  ficha só de leitura.
- A regra do BPM: a ficha já traz `bpm_picos.valido` com a regra completa (`qualidade_bpm_confiavel`);
  a regra própria do `oled_telas.c` (`bpm_picos.valido && (!q.valido || q.usavel)`)
  fica redundante. Ele decide se simplifica.
- Ordem de merge: quem entra primeiro, e quem faz o rebase do `main.c`/`app.c`.

## Deixado ao builder

- Onde mora o anel da fila (no `sensor.c` ou num header próprio).
- Nomes internos, formato exato das linhas `#` novas.
- Como estruturar o vetor de referência e o teste no PC, desde que compare com
  o Python.
- Dividir em commits pequenos; o PR fica abaixo de 2 000 linhas sem contar
  gerado.
