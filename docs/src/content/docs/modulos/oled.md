---
title: Display OLED
description: "As telas do display SSD1306 128x64: onda, BPM, qualidade e resultados."
sidebar:
  order: 11
---

| | |
|---|---|
| Frente | C · Celso |
| Item do plano | Display OLED (#26) |
| Entrada | `ppg_resultados_t` e as amostras do sinal filtrado |
| Saída | as páginas do SSD1306 que mudaram (128 bytes cada) |
| Código | `Core/*/pds/oled/` (o desenho) e `Core/Src/display.c` (o chip, pela HAL) |
| Gabarito | `analise/src/analise/oled.py`, porte do protótipo do design |

**O quê:** mostrar a onda do pulso e os números do `ppg_resultados_t` num OLED. O módulo
`oled/` desenha numa memória de imagem de 1024 bytes igual à do chip (C puro, sem HAL, testado
no PC). O `display.c` manda para o chip só as páginas que mudaram, uma por volta do laço.

## Estado

| Passo | Situação |
|---|---|
| Design das telas (protótipo interativo) | feito: 7 artboards |
| Referência em Python (`oled.py`) e vetores | feito |
| Módulo em C (`oled/`) e teste no PC, byte a byte | feito: 10 telas idênticas à referência |
| Driver do SSD1306 e integração no laço (`app.c`) | feito (Debug e Release, sem avisos) |
| Demonstração com dados de mentira (`-DBANCADA_DISPLAY=ON`) | feita, rodou na placa |
| Rodar na placa, com o módulo de verdade e o sensor | feito em 23/11: telas, BPM e onda conferidos, 0 amostras perdidas ([medidas](../../firmware/#display-oled-displayc)) |

Esta página é atualizada em todo PR que mexe no módulo.

## As telas

Cada pixel é 1 bit (sem cinza). A fonte é 5×7 em células de 6×8, só maiúsculas, algarismos e
`- . , : % / ! ? ( ) > = *` (o `*` é o coração): minúscula vira maiúscula e o que não está na
fonte vira `?`. Texto grande é a mesma fonte com cada pixel dobrado (12×16).

| Tela | Quando aparece | O que mostra |
|---|---|---|
| Principal | rodízio (8 s) | BPM grande, coração, 5 barras de qualidade e a onda (128 × 47, 2,56 s) |
| Resumo | rodízio (4 s) | BPM picos e FFT, SDNN, RMSSD, LF/HF, qualidade, SpO2 e respiração |
| Alvo | rodízio (4 s), só se SpO2 ou respiração têm valor | SpO2 e respiração grandes, BPM, sinal e a onda (128 × 32) |
| Sem dedo | `qualidade.valido` e `dedo_presente = false` | "SEM DEDO" e a instrução; ganha de todas |
| Sinal ruim | dedo presente e `usavel = false` | aviso invertido e a onda continua; ganha das do rodízio |
| Inicialização | boot | nome, uma linha por etapa (`...` ou `OK`) e "AGUARDE" |
| Erro | boot, se o sensor ou a decimação falham | "ERRO" invertido, o que falhou e o que fazer |

De onde vem cada número:

- **BPM:** `bpm_picos.bpm`, arredondado. Mostra `--` se `bpm_picos.valido` é falso ou, **com a
  qualidade válida**, se ela não for `usavel`. Na cadeia, `bpm_picos.valido` já é a regra do BPM
  confiável (`qualidade_bpm_confiavel()`, que exige `usavel`), então a segunda condição é só uma
  guarda redundante. O display **nunca mostra número quando o último `t,` disse 0**; pode mostrar `--`
  até ~1 s antes do `t,` (a cadeia apaga `bpm_picos.valido` num batimento com BPM inválido entre dois
  julgamentos, e só acende no julgamento). O **número** pode
  diferir do `t,` por até ~1 s: a tela acompanha o BPM do último batimento, e o `t,` o do último
  julgamento da qualidade (uma vez por segundo).
- **Barras:** `qualidade.indice` × 5; sem qualidade válida, nenhuma. Barra vazia é um traço de 1 px.
- **Coração:** acende quando `ultimo_batimento.n_pico` muda e apaga 150 ms depois.
- **Onda:** o IR filtrado, **com o sinal trocado** (`display_amostra` inverte): no IR, sangue a mais
  é luz a menos, então o pulso sairia de cabeça pra baixo. Conferido na placa: com a inversão, o pico
  aponta pra cima. O picos acha os máximos do IR **sem** inverter (os vales da onda desenhada), e
  marca o batimento ~1 s depois (o atraso do filtro mais a espera do candidato): o coração pisca fora
  de fase com o pico da onda na tela. Amostras que não são número (NaN) são descartadas antes da onda.
- **Resumo:** SDNN e RMSSD em ms inteiros; LF/HF em ponto fixo (14 vira `1.4`; o `printf` do
  nano.specs não imprime `float`); `--` onde o módulo ainda não tem valor.

A **onda** usa 2 amostras por coluna (a média das duas) e a mais nova fica na direita; antes de
encher, ela começa pela direita. A escala é automática (o mínimo e o máximo das colunas viram o fundo
e o topo, com 8% de folga) e **cresce na hora e encolhe 5% por quadro**, pra onda não "respirar" a cada batida.

## Decisões e suposições

O protótipo do design deixa algumas coisas em aberto; estas são as escolhas, todas fáceis de mudar:

| Item | Escolha | Tipo |
|---|---|---|
| Resolução | 128 × 64, confirmada por quem tem o módulo. A variante 128 × 32 do design **não foi feita** | fato |
| Endereço I2C | 0x3C (`DISPLAY_ENDERECO`; alguns módulos usam 0x3D) | fato (medido) |
| Orientação | segmentos e linhas remapeados (`A1`/`C8`); `-DDISPLAY_ORIENTACAO_NORMAL=0` desfaz | fato (conferida na placa) |
| Troca de telas | rodízio por tempo (8 s, 4 s, 4 s): o design não define um botão, e o `.ioc` não configura nenhum | decisão |
| Onda | com o sinal trocado, ver acima | fato (conferida na placa) |
| Quadros | 20 por segundo (`DISPLAY_QUADRO_MS = 50`), como no design | decisão |
| Envio | uma página (~3 ms) por volta do laço, nunca no TIM2 | decisão |
| Display ausente | `display_init` devolve `false`, avisa na serial e o resto segue; 3 falhas seguidas desligam o display | decisão |

## Testes

`testes/oled/teste_oled.c` compara **as 10 telas byte a byte** (1024 bytes cada) com a referência em
Python: fonte e primitivas, principal (com e sem valor), resumo, sem dedo, sinal ruim, início, os
dois erros e o alvo. A referência (`oled.py`) é um porte do `oled.js` do design, com as contas da onda em
`float32` e o arredondamento do JavaScript (o meio vai pra cima), pra não sair um pixel diferente.

Além disso, o teste confere o formato de página do SSD1306 (o bit 0 é a linha de cima), o recorte fora da
tela, minúscula e caractere desconhecido, o envio por página (só a página que mudou, em roda, e a
reinicialização), o rodízio e as prioridades, o coração (inclusive na volta do relógio de 32 bits), o BPM
`--` (com NaN e valores absurdos), a escala da onda (cresce na hora, encolhe 5%), a onda antes de
encher e o anel de amostras. Trocar a folga da onda (8% por 9%) reprova 5 telas; trocar o rodízio de
páginas reprova com mensagem clara.

**Limite desta conferência:** a referência é um porte do `oled.js`, não o `oled.js` rodando. Não tinha
`node` aqui, nem abri o protótipo no navegador, então a identidade com as artboards **pixel a pixel**
não foi conferida; o que está conferido é C = Python, e Python = a leitura do código do design.

Os vetores e a tabela da fonte do C saem de `uv run python -m analise.oled` (em `analise/`).

## Custo

Firmware compilado com o `arm-none-eabi-gcc` 14.2.1, sem avisos. Release (`-Os`), sobre a `main` da v0.4.0:

| | Flash | RAM |
|---|---|---|
| `main` (v0.4.0) | 54.284 B | 37.032 B |
| com o display | 60.084 B (**+5.800 B**) | 40.152 B (**+3.120 B**) |

A RAM a mais é o `oled_t` (~3 KB: a memória de imagem, a cópia do que o chip já tem e as 256 amostras da
onda). O display lê a ficha da cadeia, sem cópia.

**Ciclos de desenhar um quadro** (código ARM emulado, modelo simples do Cortex-M4F, **sem** a espera
da flash; `uv run testes/oled/ciclos/ciclos.py`, precisa do `arm-none-eabi-gcc`):

| Tela | Ciclos | Tempo a 96 MHz | Páginas que mudam no quadro seguinte |
|---|---|---|---|
| principal | ~75.500 | 0,8 ms | 6 |
| resumo | ~232.300 | 2,4 ms | 0 |
| alvo | ~125.800 | 1,3 ms | 4 |
| sem dedo | ~134.000 | 1,4 ms | 0 |
| sinal ruim | ~162.400 | 1,7 ms | 5 |

As páginas que mudam batem com as que o design previu (6, 4 e 5). Desenhar um quadro bloqueia o laço
por no máximo ~2,4 ms, uma vez a cada 50 ms. Mandar uma página leva 3,1 ms a 400 kHz (medido na placa
com o DWT; o cálculo dá 130 bytes × 9 bits ÷ 400 kHz ≈ 2,9 ms) e vai uma por volta, então o laço fica parado
~3 ms por vez, contra os 37,5 ms de folga depois do INT do sensor. Uma tela de onda completa (6 páginas)
ocupa o barramento ~18 ms a cada 50 ms (~36%).

## Pendente

- **Botão** pra trocar de tela, se o rodízio por tempo não servir: depende de configurar um pino no `.ioc`.
- **SpO2:** o display lê `spo2` em `ppg_resultados_t`, que a cadeia preenche com o módulo
  [SpO2](../spo2/) (uma estimativa, sem calibração); mostra `--` enquanto `spo2.valido` for falso.
- **Rodízio:** a fase vem de `agora_ms % ciclo`, e o ciclo muda de 12 s pra 16 s quando a tela alvo entra
  ou sai (SpO2 ou respiração mudam de válido). Nessa troca a tela pode pular de uma pra outra antes do tempo.
- O desenho foi medido no ARM emulado em `-Os`; na placa, em Debug (`-O0`), a pior chamada medida foi 4,8 ms.
