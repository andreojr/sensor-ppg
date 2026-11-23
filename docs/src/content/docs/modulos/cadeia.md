---
title: Cadeia
description: "Os módulos juntos, na ordem da placa: do bruto aos resultados que o display lê."
sidebar:
  order: 9
---

| | |
|---|---|
| Frente | André (#17) |
| Entrada | ppg_amostra_t (bruto, a 100 Hz) |
| Saída | ppg_resultados_t (a ficha) e cadeia_saida_t (o que saiu em cada amostra) |
| Código | `Core/*/pds/cadeia/` |
| Protótipo | `analise/src/analise/cadeia.py` |

**O quê:** chama os módulos de PDS em sequência, a cada amostra do bruto, aplica as
regras que ligam um ao outro e preenche a ficha que o display lê. Não tem conta de
PDS própria: é a "cola" que antes ficava no `main.c`.

## Estado

| Passo | Estado |
|---|---|
| 1. Python (os módulos que já existem, na ordem da placa) | feito: `analise.cadeia.roda()` |
| 2. C sem HAL | feito: `cadeia.h`, `cadeia.c`, `linhas.c`, `fila.h` |
| 3. Teste no PC contra o vetor | feito: `testes/cadeia/`, no CI (90 s do PhysioNet, 478 saídas iguais) |
| 4. Placa com o vetor | feito (23/11): `-DBANCADA_CADEIA=ON`, 478 saídas, 0 fora da tolerância |
| 5. Sensor real | feito (23/11): `analise.cadeia --replay` numa captura de ~2 min (abaixo); usa só as linhas `b,` e as de resultado, sem `-DSERIAL_COMPLETA` |

## A ordem

Por amostra do bruto (a decimação fica antes, no `sensor.c`):

```text
bruto ─► filtro ─► picos ─► espectral ─► respiração ─► qualidade
          │         │                                    │
          │         └─ batimento: fila do HRV ◄──────────┘ julgamento: esvazia a fila
          │                                                no HRV e decide o BPM da tela
          └─ filtrado (onda do display)
```

A ordem importa: o picos roda antes da qualidade na mesma amostra, então o
julgamento "de antes" de um batimento é o anterior e o desta amostra (se houver) é
o "de depois". É a mesma ordem da v0.3, e o teste confere contra o Python
(`analise.cadeia`), que segue a mesma ordem.

## As regras

- **Batimento:** guarda o BPM cru do picos e entra na fila do HRV com o julgamento
  da qualidade "de antes" (`qualidade_batimento_usavel`). Fila cheia: o mais antigo
  vai direto pro HRV, com o RR de fora.
- **Julgamento da qualidade (1 por segundo):** esvazia a fila no HRV (o RR entra se
  o picos aceitou e os julgamentos de antes e de agora dizem usável) e decide se a
  tela mostra o BPM (`qualidade_bpm_confiavel`: qualidade usável, ritmo regular no
  picos e último batimento com até 3 s).
- Numa amostra podem sair várias saídas de HRV (o que transbordou mais a fila toda):
  `cadeia_saida_t` guarda até `CADEIA_HRV_MAX`, na ordem.

## A ficha (`ppg_resultados_t`)

O que o display lê. A cadeia sobrescreve a cada saída (de número só interessa o
mais recente):

| Campo | Quando muda |
|---|---|
| `ultimo_batimento` | a cada batimento |
| `bpm_picos.bpm` | a cada batimento (o BPM cru do picos) |
| `bpm_picos.valido` | acende só no julgamento (a decisão de `qualidade_bpm_confiavel`); apaga também num batimento com BPM inválido |
| `bpm_espectral` | a cada saída do espectral (1 por segundo) |
| `hrv` | a cada saída do HRV |
| `respiracao` | a cada estimativa (1 por segundo) |
| `qualidade` | a cada julgamento |
| `spo2` | nunca: `valido = false` até a #125 |

Entre dois julgamentos, `bpm_picos.valido` mantém a última decisão e o número
acompanha o último batimento; se esse batimento vier com BPM inválido (o picos perdeu o
ritmo, `bpm` 0), a ficha apaga na hora, pra o display nunca mostrar "0" como válido. A regra recebe sempre o BPM cru, guardado à parte (a
ficha nunca realimenta a regra). O display não precisa repetir a regra.

## Ciclos

A cadeia mede cada módulo com um relógio que quem chama passa
(`cadeia_init(c, relogio)`): na placa, `ciclos_agora` (DWT); no PC, `NULL` (não
mede). Assim ela mede sem incluir HAL. Os orçamentos estão em
[Firmware → Ciclos e orçamento](../../firmware/#ciclos-e-orçamento).

## Linhas da serial

`linhas_cadeia()` escreve as linhas de uma amostra (`b,` `f,` `p,` `h,` `e,` `r,`
`t,`), com o mesmo texto da v0.3 (`teste_linhas` confere caractere a caractere).
Fica em `pds/` pra o replay no PC escrever exatamente o que a placa manda.

## Testes

```bash
uv run python -m analise.cadeia --vetores        # gera testes/cadeia/vetores/physionet.h
cmake -S testes -B build/testes && cmake --build build/testes
ctest --test-dir build/testes --output-on-failure
```

- `teste_cadeia`: 90 s de `s1_sit` (a partir de 60 s, no nível do sensor) pela
  cadeia; batimentos, espectral, HRV, respiração e tela iguais ao Python (discretos
  exatos, números com tolerância 0,01). Também: relógio nulo não mede, relógio falso
  conta cada módulo, e 21 amostras com duas saídas de HRV.
- `teste_linhas`, `teste_fila`: o texto das linhas e a fila (cheia, ordem, volta do
  anel, volta do contador de ciclos).
- `teste_replay`: o replay (abaixo) decima igual ao vetor da decimação, preenche um
  salto no `n` como a placa faz com as perdidas e reinicia no reset.

### Replay: a prova de que nada mudou

`analise.cadeia --replay` pega o bruto que a placa mandou (linhas `b,`, a partir do
último reset), passa pela cadeia em C no PC (`build/testes/replay_cadeia --bruto`) e
confere cada linha de resultado contra a captura: decisões (`n`, válidos, `rr_usado`,
`mostra`) iguais e números dentro de uma tolerância pequena (0,01 na `fracao`, 0,1 em
ms, bpm e rpm), porque a linha `b,` tem 2 casas e a placa passa o valor inteiro.

```bash
uv run python -m analise.captura /dev/ttyUSB0 --segundos 130 -o dados/regressao.csv   # e aperte o reset
uv run python -m analise.cadeia --replay dados/regressao.csv
```

A entrada é o bruto, e não as cruas, porque a serial perde ~0,1% das linhas cruas a
400 Hz (e embaralha algumas): a placa usou a amostra verdadeira, e o replay a partir das
cruas divergia depois da primeira perda. Linha `b,` perdida entra como a anterior
repetida; linha embaralhada (n que volta sem ser reset) é descartada.

O `replay_cadeia` sem `--bruto` ainda refaz tudo a partir das cruas (decimação incluída);
o `teste_replay` usa isso pra conferir a decimação, o preenchimento das perdidas e o reset.

**Resultado (23/11/2026):** captura com o firmware anterior (c6727a2), ~2,3 min depois do
reset, dedo sem suporte (sinal "não usável" na maior parte): **0 diferenças** em 155
batimentos, 155 saídas de HRV, 135 do espectral, 142 da respiração e 141 telas. A maior
diferença de número foi 0,06 ms num `rr_ms`.

**Resultado com o laço novo (23/11/2026):** firmware da #17, ~2 min depois do reset,
dedo no sensor: 193 batimentos, 192 HRV, 120 espectral, 127 respiração e 126 telas.
Só **1 linha diferente**: o pico 3521, com `rr_ms` 572,74 na placa e 572,61 no
replay. A serial perdeu a linha `b,` de n = 3492, 29 amostras antes; o replay
repetiu a anterior no lugar dela, e o filtro do PC saiu um pouco do da placa. Não é
erro da cadeia: o resto, depois disso, bateu.

## Limitações da v0.4.0

O que a cadeia integrada **não** prova, e precisa ser dito na apresentação:

- **Sem suporte de dedo.** Decisão do grupo (falta de tempo e de material): o módulo
  verde do MAX30102 não deixa o dedo encostar sem pressão, então o sinal varia com a
  força do dedo. Por isso a qualidade marca boa parte das capturas como "não usável"
  (ver [Picos](../picos/), [HRV](../hrv/) e [Qualidade](../qualidade/)).
- **A cadeia integrada foi conferida na placa em duas capturas de 23/11** (o
  `--replay` acima, antes e depois do laço novo). As capturas mais antigas são de
  firmwares anteriores e validam os módulos, não a cadeia.
- **Coleta com o nosso sensor só pelas capturas que já existem** (#29, escopo
  reduzido): metrônomo a 6, 10 e 15 rpm, repouso com o dedo parado e dedo solto ou em
  movimento. Não houve coleta com a câmera do celular nem dumps do relógio: a
  comparação com uma referência externa é só o BPM de um relógio anotado à mão
  (tabelas de [Qualidade](../qualidade/)), qualitativa e com poucos pontos. A
  referência de verdade continua sendo o ECG do PhysioNet.
- **O BPM só aparece com a qualidade e o picos concordando** (linha `t,` e
  `bpm_picos.valido`). Na ficha do display, entre dois julgamentos, o número segue o
  último batimento com a decisão anterior (acima, em "A ordem"); a linha `t,`
  sai só no julgamento.
- **A pior amostra passa do orçamento de um período** (1,23 M de 960 000 ciclos, em
  Debug), uma vez por segundo; a fila absorve e nada se perdeu. O firmware da release
  (Release, serial padrão) não foi medido na placa. Ver
  [Firmware → Ciclos e orçamento](../../firmware/#ciclos-e-orçamento).
- **Fora da v0.4.0:** display (PRs #121 e #122; `display_amostra()` e
  `display_servico()` ainda são vazias), SpO2 (#125, `spo2.valido` sempre falso) e
  LF/HF do HRV (#115).
