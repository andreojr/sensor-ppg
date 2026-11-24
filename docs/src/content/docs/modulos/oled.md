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
`- . , : % / ! ? ( ) > = * ~` (o `*` é o coração e o `~` marca a SpO2 como estimada): minúscula vira
maiúscula e o que não está na fonte vira `?`. Texto grande é a mesma fonte com cada pixel dobrado (12×16).

| Tela | Quando aparece | O que mostra |
|---|---|---|
| Principal | rodízio (8 s) | BPM grande, coração, 5 barras de qualidade e a onda (128 × 47, 2,56 s) |
| Resumo | rodízio (4 s) | BPM picos e FFT, SDNN, RMSSD, LF/HF, qualidade, SpO2 (rótulo `SPO2~`) e respiração |
| Alvo | rodízio (4 s), só se SpO2 ou respiração têm valor | SpO2 (rótulo `SPO2~`) e respiração grandes, BPM, sinal e a onda (128 × 32) |
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

## Linha da serial (`oled_linha_tela`)

`oled_linha_tela(pagina, dados, saida)` escreve `d,<página>,<256 hex minúsculos>\n` (261 bytes) com os
128 bytes de uma página, pro espelho do display (`-DSERIAL_TELA=ON`, ver [firmware](../../firmware/)). É só
formatação: pura, sem HAL, testada em `testes/oled/teste_oled.c` (prefixo, hex minúsculo, ida e volta
byte a byte e página fora de 0 a 7).

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

## Espelho no terminal (`--tela`)

Dá pra ver o display no PC enquanto a placa roda. Com o firmware compilado com `-DSERIAL_TELA=ON`, a
placa manda pela serial uma cópia de cada página enviada ao SSD1306, numa linha nova:

```text
d,<página>,<256 caracteres hexadecimais minúsculos>
```

A página vai de 0 a 7, e os 256 caracteres são os 128 bytes dela (coluna 0 a 127). Cada byte é uma
coluna e o bit 0 é a linha de cima da página, igual à memória do SSD1306 e ao `oled.py`. Só sai a
página que mudou, mais as 8 páginas a cada ~10 s, pra tela fechar mesmo ligando a captura no meio.

No PC (da pasta `analise/`):

```bash
uv run python -m analise.captura /dev/ttyUSB0 --tela             # meio-blocos, 128 x 32 caracteres
uv run python -m analise.captura /dev/ttyUSB0 --tela --braille   # braille, 64 x 16 caracteres
```

- Enquanto roda, o terminal mostra **só a tela do OLED**, na tela alternativa (a mesma de `vim` e
  `less`): nada de "gravando..." antes. Ao sair (Ctrl+C, fim do `--segundos` ou erro) o terminal volta
  ao que era antes, e só então sai o resumo, com "N páginas de tela (d,) recebidas".
- O CSV é gravado normal ao mesmo tempo (é a evidência da #30). As linhas `d,` não entram em nenhum CSV.
- O desenho é refeito no mesmo lugar (o cursor volta ao topo, sem rolar), no máximo 10 vezes por
  segundo; o redesenho que ficou esperando sai na volta seguinte do laço, mesmo sem linha nova. O
  terminal precisa de pelo menos 128 colunas e 32 linhas (64 e 16 no `--braille`), com fonte que tenha
  os caracteres `▀ ▄ █` (ou braille), e de 256 cores. O fundo é preto.
- As cores imitam o painel bicolor da placa: as 16 primeiras linhas de pixel (as páginas 0 e 1: BPM,
  coração e barras de qualidade) saem em **amarelo** e as 48 de baixo em **azul**. Em meio-blocos são
  8 linhas de caractere amarelas e 24 azuis; em braille, 4 e 12. A cor não vem nos dados `d,` (o chip
  só recebe 1 bit por pixel), é só como o desenho aparece no terminal. O corte em 16 px fica na
  constante `CORTE_AMARELO_PX` (e as cores em `COR_AMARELO` e `COR_AZUL`), fácil de mudar se o corte do
  seu painel for outro.
- Ao começar, aparece um quadro vazio com "esperando as linhas d, da placa (firmware com
  -DSERIAL_TELA=ON)". Se isso não some, o firmware não está mandando as linhas `d,`. O aviso some quando
  chega a primeira página.
- O espelho só desenha se a saída for um terminal e couber nele. Se o terminal for menor, ou se a saída
  estiver redirecionada (`> arquivo`, pipe), nada é desenhado nem escrito: a captura avisa em uma linha
  antes de começar e de novo no resumo, e só o CSV é gravado.
- Página que ainda não chegou aparece apagada até chegar (no máximo ~10 s, pelo reenvio).
- Linha `d,` inválida (página fora de 0 a 7, tamanho errado, hexadecimal inválido, com espaço ou em maiúsculo) é ignorada e conta
  em "linhas inválidas", como as outras.
- `--tela` não anda junto com `--qualidade`: os dois escrevem no mesmo terminal. `--braille` só vale
  com `--tela`.

O código está em `analise/src/analise/tela_terminal.py`. O teste (`analise/tests/test_tela_terminal.py`)
não usa a placa: monta as linhas `d,` a partir das 10 telas do `oled.py`, e confere que a tela remontada
é byte a byte igual e que o desenho tem o tamanho certo, além das linhas inválidas.

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
  O rótulo sai como `SPO2~` nas telas resumo e alvo: o `~` é a marca de "estimada" que a #27 pede (não há
  oxímetro de referência). Cabe sem encostar na respiração mesmo com 3 algarismos (`SPO2~ 100` vai até a
  coluna 52, e o `RESP 99` começa na 87; na alvo, o rótulo vai até a coluna 68 e o número grande da
  respiração começa na 78). Quando houver calibração, sai o `~`.
- **Rodízio:** a fase vem de `agora_ms % ciclo`, e o ciclo muda de 12 s pra 16 s quando a tela alvo entra
  ou sai (SpO2 ou respiração mudam de válido). Nessa troca a tela pode pular de uma pra outra antes do tempo.
- O desenho foi medido no ARM emulado em `-Os`; na placa, em Debug (`-O0`), a pior chamada medida foi 4,8 ms.
