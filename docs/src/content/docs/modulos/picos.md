---
title: Picos
description: "Detecção robusta de batimentos e BPM."
sidebar:
  order: 6
---

| | |
|---|---|
| Frente | C · Celso |
| Item do plano | 3a (Piso) |
| Entrada | filtrado |
| Saída | ppg_batimento_t, bpm_picos |
| Código | `Core/*/pds/picos/` |

**O quê:** detecção robusta de batimentos e BPM.

## Estado

| Passo | Situação |
|---|---|
| 1. Python (`analise/src/analise/picos.py`) | feito, validado em 15 registros do PhysioNet |
| 2. C (`Core/*/pds/picos/picos.c`) | feito, porte linha a linha do Python |
| 3. Teste no PC (`testes/picos/`) | feito, 2 casos contra os vetores do Python |
| 4. Placa com a fonte falsa | a fazer |
| 5. Sensor real | a fazer |

Esta página é atualizada em todo PR que mexe no módulo.

## Método

O detector recebe o **filtrado** (0,5 a 4 Hz, média zero, a 100 Hz) **uma amostra
por vez**, sem guardar o sinal: só o estado de `picos_t`. Tudo em `float`.

1. **Envelope de pico com decaimento:** `env = max(x, env * DECAI)`, com
   constante de tempo de 1 s. É o nível dos picos recentes e acompanha a
   amplitude quando ela muda.
2. **Limiar adaptativo:** um máximo local só é candidato se passa de
   `0,4 * env`.
3. **Período refratário de 300 ms** (200 bpm): candidato mais perto que isso
   do batimento anterior é rejeitado. Corta a onda dicrótica e ruído colado
   no pico.
4. **Instante por interpolação parabólica** nos 3 pontos em volta do máximo.
   `n_pico` é a amostra inteira, `fracao` em [0, 1) é a parte fracionária, e
   `PPG_ATRASO_AMOSTRAS` do `ppg.h` é descontado.
5. **Rejeição de intervalo errado:** o RR só é válido (`rr_valido`) entre 300 e
   2000 ms e entre 0,7 e 1,4 vez o RR típico (média móvel dos RR). Um
   batimento perdido faz o RR dobrar e fica de fora, e o HRV ignora esse par.
6. **BPM:** `60000 / média` dos últimos 8 RR válidos. Só vale (`valido`) com 4
   ou mais.

Nos primeiros 2 s o detector só aprende o nível do sinal e não detecta (o
primeiro batimento fica sem referência). O pico é visto com 1 amostra de
atraso, porque o detector precisa da amostra seguinte para saber que passou
do máximo.

**Parâmetros:** `TAU_ENV_S = 1 s`, `LIMIAR = 0,4`, `REFRAT_S = 0,3 s`. Uma
varredura (limiar 0,3 a 0,6; refratário 0,25 a 0,35 s; envelope de 1 a 3 s)
mostrou que a **mediana** do erro de BPM ficou em 0,07 bpm em todas as
combinações que terminaram de rodar: o que muda é o erro nos registros com movimento. O envelope de 1 s
foi o que mais reduziu esse erro (média de 6,0 para 2,5 bpm). Os valores
ficaram nessa região, sem ajuste fino, para não decorar 15 registros.

**Vetores de teste:** `uv run python -m analise.picos` (em `analise/`) grava
`testes/picos/vetores/` com a entrada e a saída do Python. O teste em C
(`testes/picos/teste_picos.c`) roda o `picos.c` sobre a mesma entrada e compara:
instantes e `rr_valido` exatos, `fracao`, `rr_ms` e BPM com tolerância de 0,01.

## Validação

Contra o ECG do PhysioNet (Pulse Transit Time PPG): 5 pessoas × (sentado,
andando, correndo), 60 s de cada registro a partir de 30 s, sobre o `filtrado_ir`
da fonte falsa. Reproduzir: `uv run python -m analise.picos_validacao`.

O pico do PPG chega **110 a 180 ms depois** do pico R (tempo de trânsito do pulso),
então o atraso de cada registro é estimado e descontado antes de contar. Os
2,6 s do início (aquecimento) ficam fora da conta. Acerto: pico do PPG a
menos de 150 ms do R mais o atraso.

| Atividade | Registros | Sensibilidade | Precisão | Erro do BPM (mediana) |
|---|---|---|---|---|
| sentado | 5 | 98,7 a 100% | 98,3 a 98,7% | 0,07 bpm |
| correndo | 5 | 83 a 100% | 95 a 99% | 0,07 bpm |
| andando | 5 | 59 a 99% | 80 a 98% | 0,19 bpm |

Média dos 15: **sensibilidade 94,3%, precisão 95,4%, erro de BPM de 2,45 bpm**.
O erro do intervalo RR (nos pares de acertos seguidos) tem mediana de 4 a 5 ms
sentado e de 8 a 25 ms em movimento.

**Limitação conhecida:** em `s2_walk` e `s2_run` o movimento gera artefatos
maiores que o pulso, e o detector segue os passos em vez do coração (erro de
BPM de 25 e 8 bpm; sensibilidade de 59 e 83%). Nenhum parâmetro resolve isso:
é o papel do módulo `qualidade` marcar esse trecho como inutilizável
(`usavel = false`), e o laço principal descarta os batimentos dele.
