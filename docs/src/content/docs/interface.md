---
title: Interface (ppg.h)
description: O contrato entre os módulos de PDS.
---

Arquivo: `Core/Inc/pds/comum/ppg.h`. É o que permite as três frentes
andarem em paralelo: cada módulo só depende deste arquivo, nunca do código de
outro módulo. **Mudar o `ppg.h` precisa do ok dos três.**

## A cadeia

```
sensor --> decimacao --> bruto --> filtro --> filtrado --> picos --> batimento --> hrv
                           |                     |
                           +--> spo2             +--> espectral
                           +--> qualidade
                           +--> respiracao
```

O `ppg.h` define a cara do que passa em cada seta **a partir da saída da
decimação**. O que entra na decimação (taxa e formato do sensor) é assunto do
próprio módulo `decimacao` e fica fora da interface.

## Taxa

Todas as saídas da cadeia são a $f_s = 100$ Hz (`PPG_FS_HZ`). É a única taxa
do arquivo. A taxa do sensor (400 Hz na placa, 500 Hz no PhysioNet) é
parâmetro de `decimacao_init()`: mudar o sensor não muda o `ppg.h`.

Cada amostra leva uma posição $n$ na fila a 100 Hz, contada a partir da
primeira amostra que saiu da decimação ($n = 0$). O tempo em segundos é
$t = n / f_s$. Antes da decimação não existe $n$.

## Dois pontos de saída

| Saída | Quem gera | Conteúdo | Quem usa |
|---|---|---|---|
| **bruto** | `decimacao` | IR e vermelho **com DC** | `filtro`, `spo2`, `qualidade`, `respiracao` |
| **filtrado** | `filtro` | IR e vermelho, passa-faixa 0,5 a 4 Hz, média zero | `picos`, `espectral` |

Os dois usam o mesmo tipo, `ppg_amostra_t` (`n`, `ir`, `vermelho`).

**Unidade:** contagens do ADC de 18 bits do MAX30102 (0 a 262143), em
`float`. Nenhum módulo converte pra outra escala. Com o dedo, o DC fica na
casa de 100 mil e o pulso é de 0,2 a 2% disso. Quem lê o sensor garante que
`ir` e `vermelho` são mesmo o IR e o vermelho; os LEDs do módulo podem vir
trocados.

O bruto não traz o DC separado: separar AC e DC é trabalho do `spo2` e da
`qualidade`.

## Atraso do filtro

`PPG_ATRASO_AMOSTRAS` diz quantas amostras o filtro atrasa o sinal. É `float`,
porque um FIR com número par de coeficientes ou um IIR atrasam valor
fracionário. O filtro repete na saída o `n` da amostra de entrada, e o módulo
`picos` subtrai o atraso do instante do pico. Quando o filtro mudar (IIR ou
FIR), o dono do `filtro` atualiza a constante.

## Resultados

`ppg_resultados_t` junta tudo o que o laço principal e o display leem. Cada
resultado tem `valido`, que fica `false` até o módulo ter confiança (janela
ainda não encheu, sinal ruim). O display mostra `--` nesse caso.

| Campo | Módulo | Conteúdo |
|---|---|---|
| `ultimo_batimento` | `picos` | instante do pico e RR em ms (abaixo) |
| `bpm_picos` | `picos` | BPM |
| `bpm_espectral` | `espectral` | BPM |
| `hrv` | `hrv` | SDNN, RMSSD, LF/HF |
| `spo2` | `spo2` | SpO2 em % |
| `respiracao` | `respiracao` | respirações por minuto |
| `qualidade` | `qualidade` | dedo presente, índice 0 a 1, usável |

### Batimento

`ppg_batimento_t` tem o instante do pico em duas partes: `n_pico`, a amostra
(já corrigida do atraso do filtro), e `fracao` em $[0, 1)$, a posição do pico
entre `n_pico` e `n_pico + 1` por interpolação. O instante em segundos é
$(n_{pico} + fracao) / f_s$. A 100 Hz, só `n_pico` dá resolução de 10 ms, e o
RMSSD típico é de 20 a 50 ms; a interpolação é o que deixa o HRV preciso. Um
detector que não interpola deixa `fracao = 0`.

`rr_ms` é o intervalo até o batimento anterior, e `rr_valido` diz se ele pode
entrar no HRV: fica `false` no primeiro batimento e sempre que o intervalo
atravessa um batimento perdido ou rejeitado. Sem isso, um batimento perdido
vira um RR de valor dobrado e o SDNN explode.

A fonte falsa entrega as marcas do ECG neste mesmo tipo.

### Qualidade

`ppg_qualidade_t` tem `dedo_presente`, `indice` (0 inutilizável, 1 ótimo) e
`usavel`, que resume os dois com o limiar do módulo. **Só o laço principal lê
a qualidade:** com `usavel` falso, ele mostra `--` e descarta os batimentos do
trecho. `picos` e `hrv` não dependem da qualidade, então nenhum módulo precisa
esperar outro.

## Padrão dos módulos

Sem `malloc`, sem variável global. O estado fica numa struct de quem chama:

```c
void <m>_init(<m>_t *m, ...);     /* zera o estado; chamar de novo reinicia */
bool <m>_processa(<m>_t *m, const <entrada> *e, <saida> *s);
```

`processa()` devolve `true` quando escreveu na saída. Módulos que não soltam
saída a cada entrada (`decimacao` só a cada fator amostras, `picos` só quando
há batimento) devolvem `false` nas demais chamadas e não tocam na saída.

```c
typedef struct { /* estado */ } filtro_t;
void filtro_init(filtro_t *f);
bool filtro_processa(filtro_t *f, const ppg_amostra_t *bruto,
                     ppg_amostra_t *filtrado);
```
