---
title: Espectral
description: "BPM pela FFT em janela deslizante."
sidebar:
  order: 7
---

| | |
|---|---|
| Frente | C · Celso |
| Item do plano | 3b (Piso) |
| Entrada | filtrado |
| Saída | bpm_espectral |
| Código | `Core/*/pds/espectral/` |

**O quê:** BPM pela FFT em janela deslizante.

## Estado

| Passo | Situação |
|---|---|
| 1. Python (`analise/src/analise/espectral.py`) | feito, validado em 15 registros do PhysioNet |
| 2. C (`Core/*/pds/espectral/`) | feito, bate com o Python (erro máx. de 1,5e-5 bpm) |
| 3. Teste no PC (`testes/espectral/`) | feito, 2 casos contra os vetores do Python |
| 4. Placa com a fonte falsa | **código pronto, compila; falta rodar na placa** (`-DBANCADA_ESPECTRAL=ON`) |
| 5. Sensor real | **código pronto, compila; falta rodar com o sensor** (linha `e,...` na serial) |

Esta página é atualizada em todo PR que mexe no módulo.

## Método

Recebe o **filtrado** (0,5 a 4 Hz, média zero, a 100 Hz) uma amostra por vez,
guarda as últimas `JANELA_S` e, a cada `HOP_S`, com a janela cheia, devolve um
`ppg_bpm_t`:

1. **Tira a média** da janela.
2. **Janela de Hann.** Sem ela, o corte abrupto das bordas espalha o pico por
   todo o espectro (vazamento espectral).
3. **Zero-padding até `NFFT`.** Não traz informação nova, mas interpola o
   espectro e deixa o pico mais fácil de localizar.
4. **Maior pico de potência na banda de 0,7 a 3,5 Hz** (42 a 210 bpm).
5. **Interpolação parabólica** em volta do pico, no log da amplitude. É o que
   faz o erro cair para cerca de 1 bpm, mesmo com a resolução de 7,5 bpm.
6. **Validade:** o pico e seus dois vizinhos precisam ter 30% ou mais da potência
   da banda. Ruído branco quase nunca passa; um pulso com ruído passa.

**Resolução × atraso.** A resolução da FFT é `1 / JANELA_S` (8 s dá 0,125 Hz, ou 7,5
bpm entre bins), e o BPM é o da janela inteira, então chega com atraso de cerca de
`JANELA_S / 2`. Janela longa resolve melhor e responde mais devagar.

**Parâmetros:** `JANELA_S = 8 s`, `HOP_S = 1 s`, `NFFT = 1024`, 800 amostras de
janela. A janela de 8 s é o meio-termo medido abaixo.

## Em C

`espectral_t` guarda a janela de 800 amostras, a janela de Hann (calculada no
`espectral_init`), as duas áreas da FFT de 1024 pontos e o estado: **~14,7 KB de RAM**
(aloque fora da pilha). `espectral_processa()` devolve `true` uma vez por segundo, a
partir da amostra 800, e **`bpm = 0` quando `valido = false`**, como o `picos_bpm()`
(o display mostra "--"). A FFT é a do módulo [FFT](../fft/) (CMSIS-DSP).

Diferenças pro Python, todas dentro da tolerância: o C faz as contas em `float` (a janela de
Hann com `cosf`, a média por soma sequencial) e o NumPy em `float64`/pairwise. No teste
(`testes/espectral/teste_espectral.c`, sobre 60 s do `s1_sit` e do `s2_walk`, 53 saídas
cada) o `valido` sai **igual em todas** e o BPM difere no máximo **1,5e-5** (tolerância
1e-3); reiniciar dá o mesmo resultado. O teste falha de verdade: com o limite de
validade em 0,6 em vez de 0,3, o `s2_walk` dá 36 diferenças.

**Custo** (código ARM emulado, modelo do Cortex-M4F; ver [FFT](../fft/)): **~1 050 ciclos por
amostra em média** (orçamento 9 600) e **~106 000 no pior caso**, a amostra em que
sai a FFT (orçamento 960 000, 11% de um período de amostra, 1,1 ms a 96 MHz). Em Release,
o espectral acrescenta ~26 KB de flash e ~14,7 KB de RAM ao firmware.

**Na placa e com o sensor real:** o `main.c` já passa o filtrado pelo espectral e manda
`e,n,bpm_valido,bpm` a cada segundo, e a bancada confere a fonte falsa. Nada disso rodou
no hardware ainda: faltam as linhas `# bancada espectral` e um BPM do dedo comparado com
um oxímetro ou com o picos.

## Validação

Contra o ECG do PhysioNet (Pulse Transit Time PPG): 5 pessoas × (sentado,
andando, correndo), 60 s de cada registro a partir de 30 s, sobre o `filtrado_ir`
da fonte falsa. Reproduzir: `uv run python -m analise.espectral_validacao`.

- **Erro:** |BPM da FFT − BPM do ECG na mesma janela|, em que o BPM do ECG é `60 /
  média dos RR` dentro da janela.
- **Atraso:** quantos segundos antes do fim da janela o BPM da FFT mais combina
  com a frequência cardíaca instantânea do ECG (RR suavizado em 5 batimentos).

**Estudo da janela** (mediana dos 15 registros):

| Janela | NFFT | Resolução | Válidos | Erro mediano | Erro p95 | Atraso |
|---|---|---|---|---|---|---|
| 4 s | 1024 | 15 bpm | 98,4% | 0,91 bpm | 15,3 bpm | 2 s |
| 6 s | 1024 | 10 bpm | 99,6% | 0,82 bpm | 11,0 bpm | 3 s |
| **8 s** | 1024 | 7,5 bpm | 99,7% | **0,83 bpm** | 9,3 bpm | **4 s** |
| 10 s | 1024 | 6 bpm | 99,9% | 0,99 bpm | 7,3 bpm | 5 s |
| 12 s | 2048 | 5 bpm | 98,9% | 0,99 bpm | 10,1 bpm | 6 s |
| 16 s | 2048 | 3,8 bpm | 98,8% | 1,15 bpm | 4,7 bpm | 8 s |

O atraso medido é metade da janela, como previsto. O erro **mediano** quase não
muda com a janela: a interpolação parabólica já recupera a precisão. O que a
janela longa melhora são os erros grandes (p95), ao custo de atraso. A de 8 s
dá erro mediano de 0,83 bpm com atraso de 4 s.

**Com a janela de 8 s,** o erro mediano fica entre 0,59 e 1,23 bpm em 13 dos 15
registros (sentado, andando e correndo), com 100% das saídas válidas.

**Limitação conhecida:** em `s2_walk` e `s2_run` o artefato de movimento é maior
que o pulso. `s2_walk` tem erro p95 de 88 bpm (96% válidas) e `s2_run`, mediana de 3,2
bpm e p95 de 15,8. É o mesmo caso que atrapalha o módulo `picos`, e a resposta é a
mesma: o módulo `qualidade` marca o trecho como inutilizável.
