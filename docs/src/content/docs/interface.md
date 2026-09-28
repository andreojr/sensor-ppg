---
title: Interface (ppg.h)
description: O contrato entre os módulos de PDS.
---

Arquivo: `Core/Inc/pds/comum/ppg.h`. É o que permite as três frentes
andarem em paralelo: cada módulo só depende deste arquivo, nunca do código de
outro módulo. **Mudar o `ppg.h` precisa do ok dos três.**

## Taxa

Todas as saídas da cadeia são a $f_s = 100$ Hz (`PPG_FS_HZ`). Cada amostra
leva um índice $n$; o tempo em segundos é $t = n / f_s$.

## Dois pontos de saída

| Saída | Quem gera | Conteúdo | Quem usa |
|---|---|---|---|
| **bruto** | `decimacao` | IR e vermelho **com DC** | `spo2`, `qualidade`, `respiracao`, `filtro` |
| **filtrado** | `filtro` | IR e vermelho, passa-faixa 0,5 a 4 Hz | `picos`, `espectral` |

Os dois usam o mesmo tipo, `ppg_amostra_t` (`n`, `ir`, `vermelho`).

## Atraso do filtro

`PPG_ATRASO_AMOSTRAS` diz quantas amostras o filtro atrasa o sinal. O módulo
`picos` subtrai esse valor do instante do pico. Quando o filtro mudar (IIR ×
FIR), o dono do `filtro` atualiza a constante.

## Resultados

`ppg_resultados_t` junta tudo o que o laço principal e o display leem. Cada
resultado tem `valido`, que fica `false` até o módulo ter confiança.

| Campo | Módulo |
|---|---|
| `ultimo_batimento` (instante e RR em ms) | `picos` |
| `bpm_picos` | `picos` |
| `bpm_espectral` | `espectral` |
| `hrv` (SDNN, RMSSD, LF/HF) | `hrv` |
| `spo2` | `spo2` |
| `respiracao` | `respiracao` |
| `qualidade` (dedo presente, índice 0 a 1) | `qualidade` |

## Padrão dos módulos

Sem `malloc`, sem variável global. O estado fica numa struct de quem chama:

```c
typedef struct { /* estado */ } filtro_t;
void filtro_init(filtro_t *f);
void filtro_processa(filtro_t *f, const ppg_amostra_t *entrada,
                     ppg_amostra_t *saida);
```
