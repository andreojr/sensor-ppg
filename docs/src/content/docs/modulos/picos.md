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
| 3. Teste no PC (`testes/picos/`) | feito, 3 casos contra os vetores do Python |
| 4. Placa com a fonte falsa | código pronto (`-DBANCADA_PICOS=ON`), falta rodar |
| 5. Sensor real | código pronto (linhas `p,` e `--confere`), falta capturar |

Esta página é atualizada em todo PR que mexe no módulo.

## Método

O detector recebe o **filtrado** (0,5 a 4 Hz, média zero, a 100 Hz) **uma amostra
por vez**, sem guardar o sinal: só o estado de `picos_t`. Tudo em `float`.

1. **Envelope de pico com decaimento:** `env = max(x, env * DECAI)`, com
   constante de tempo de 1 s. É o nível dos picos recentes e acompanha a
   amplitude quando ela muda.
2. **Limiar adaptativo:** um máximo local só é candidato se passa de
   `0,3 * env`.
3. **Período refratário de 300 ms** (200 bpm), com **candidato pendente**:
   candidato mais perto que isso do batimento anterior é rejeitado. E o
   candidato novo não vira batimento na hora: fica pendente por 300 ms, e um
   candidato **maior** nesse intervalo toma o lugar dele. Só depois do refratário
   o pendente sai como batimento. Isso corta a onda dicrótica e o ruído colado
   no pico, e impede que a corcova que o FIR deixa antes do batimento (32 a
   41% do pico, uns 200 a 250 ms antes) vire batimento e bloqueie o pico
   verdadeiro.
4. **Instante por interpolação parabólica** nos 3 pontos em volta do máximo.
   `n_pico` é a amostra inteira, no mesmo `n` da cadeia que vem na entrada
   (`ppg_amostra_t.n`, contado desde a decimação, não desde o `picos_init`),
   `fracao` em [0, 1) é a parte fracionária, e `PPG_ATRASO_AMOSTRAS` do
   `ppg.h` é descontado.
5. **Rejeição de intervalo errado:** o RR só é válido (`rr_valido`) entre 300 e
   2000 ms e entre 0,7 e 1,4 vez o RR típico (média móvel dos RR). Um
   batimento perdido faz o RR dobrar e fica de fora, e o HRV ignora esse par.
6. **BPM:** `60000 / média` dos últimos 8 RR válidos. Só vale (`valido`) com 4
   ou mais.

Nos primeiros 2 s o detector só aprende o nível do sinal e não detecta (o
primeiro batimento fica sem referência). O pico é visto com 1 amostra de
atraso, porque o detector precisa da amostra seguinte para saber que passou
do máximo, e o batimento sai 300 ms (30 amostras) depois do pico (o tempo do pendente).
O `n_pico` continua sendo o do pico.

**Parâmetros:** `TAU_ENV_S = 1 s`, `LIMIAR = 0,3`, `REFRAT_S = 0,3 s`. Varredura
refeita com o filtrado do FIR (#108), já com o candidato pendente: limiar de 0,15
a 0,6, refratário de 0,25 a 0,35 s e envelope de 0,5 a 3 s. O que se viu:

- **Envelope de 1 s** foi o melhor em quase todas as combinações (em todas
  contra 2 e 3 s; contra 0,5 s perdeu só com limiar de 0,35). Provavelmente
  porque um envelope mais lento guarda o nível de um pico grande (passo,
  movimento) e rejeita o pulso verdadeiro que vem depois; não medi isso.
- **Limiar menor é melhor até 0,3:** de 0,6 para 0,3 o erro médio de BPM cai de
  3,1 para 1,0 bpm e a pior sensibilidade sobe de 66 para 80%. Abaixo de 0,25
  entram picos falsos e o erro volta a subir. O ótimo fica num platô de 0,25 a
  0,35, então não é ajuste fino sobre 15 registros.
- O **refratário** (0,25 a 0,35 s) muda pouco.

**Vetores de teste:** `uv run python -m analise.picos` (em `analise/`) grava
`testes/picos/vetores/` com a entrada e a saída do Python. O teste em C
(`testes/picos/teste_picos.c`) roda o `picos.c` sobre a mesma entrada e compara:
instantes e `rr_valido` exatos, `fracao`, `rr_ms` e BPM com tolerância de 0,01.

## Validação

Contra o ECG do PhysioNet (Pulse Transit Time PPG): 5 pessoas × (sentado,
andando, correndo), 60 s de cada registro a partir de 30 s, sobre o `filtrado_ir`
da fonte falsa (o FIR do módulo `filtro`, com o atraso de `PPG_ATRASO_AMOSTRAS`
descontado pelo picos). Reproduzir: `uv run python -m analise.picos_validacao`.

O pico do PPG chega **100 a 155 ms depois** do pico R (tempo de trânsito do pulso),
então o atraso de cada registro é estimado e descontado antes de contar. Os
2,6 s do início (aquecimento) ficam fora da conta. Acerto: pico do PPG a
menos de 150 ms do R mais o atraso.

| Atividade | Registros | Sensibilidade | Precisão | Erro do BPM (mediana) |
|---|---|---|---|---|
| sentado | 5 | 97,2 a 98,5% | 95,7 a 97,3% | 0,14 bpm |
| correndo | 5 | 84,6 a 98,7% | 88,9 a 97,7% | 0,15 bpm |
| andando | 5 | 80,5 a 97,6% | 89,0 a 96,7% | 0,23 bpm |

Média dos 15: **sensibilidade 95,4%, precisão 95,2%, erro de BPM de 0,97 bpm**.
Para comparar: com o filtrado antigo (fase zero) eram 94,3%, 95,4% e 2,45 bpm; com
o FIR e o detector sem o candidato pendente, 88,4%, 89,5% e 2,10 bpm.
O "erro do BPM" aqui é o do BPM médio do trecho de 60 s (60000 / média dos RR
válidos detectados) contra o do ECG, não o `picos_bpm()` batimento a
batimento (últimos 8 RR).
O erro do intervalo RR (nos pares de acertos seguidos) tem mediana de 3 a 5 ms
sentado e de 8 a 45 ms em movimento.

**Limitação conhecida:** em `s2_walk` e `s2_run` o movimento gera artefatos
maiores que o pulso, e o detector segue os passos em vez do coração (erro de
BPM de 8 e 3,5 bpm; sensibilidade de 80 e 85%). Nenhum parâmetro resolve isso:
é o papel do módulo `qualidade` marcar esse trecho como inutilizável
(`usavel = false`), e o laço principal descarta os batimentos dele.

**A corcova do FIR (`s3_sit`), resolvida:** o FIR de fase linear deixa uma corcova
antes do batimento. Sem tratamento, ela passava do limiar, virava batimento e o
refratário bloqueava o pico verdadeiro: sensibilidade de 50% nesse registro, e
batimentos deslocados saindo com `rr_valido = true` (RR de 679 e 894 ms contra
~790 reais). Com o candidato pendente o `s3_sit` voltou a **98,5%**. Para conferir o
que o HRV enxerga (e a validação por pares casados não mostra), nos 5 registros
"sentado": **nenhum RR marcado como válido destoa mais de 15% dos intervalos do
ECG**, e o erro do RMSSD fica entre −0,2 e 4,2 ms. O teste
`test_corcova_antes_do_pico_nao_toma_o_lugar` reproduz o defeito.

**O BPM não expira sozinho:** depois de 4 RR válidos, `picos_bpm()` continua
`valido` com o último valor mesmo que não chegue batimento novo (dedo
retirado, sinal parado). Quem tira o "--" do display nesse caso é a
`qualidade` (`dedo_presente`).

### Placa com a fonte falsa

```bash
cmake --preset Debug -DBANCADA_PICOS=ON
cmake --build --preset Debug
```

Na partida, a placa passa os 40 s do `s3_sit` (o filtrado da fonte falsa, o
mesmo vetor do teste no PC, com a corcova do FIR) pelo `picos.c` e confere
`n_pico`, `rr_valido` e `bpm_valido` exatos e `fracao`, `rr_ms` e BPM com a
tolerância do vetor:

```text
# bancada picos: 47 batimentos (esperado 47), 0 fora da tolerancia, erro max ... milesimos
# bancada picos: ciclos por amostra med ... max ... (orcamento 9600): OK
```

**Orçamento:** 1% da CPU por amostra a 100 Hz, ou seja, 96 MHz / 100 Hz /
100 = 9 600 ciclos. O detector faz poucas contas por amostra (envelope e um
máximo local); a parábola e o RR só rodam nos candidatos.

**Resultado na placa:** *(preencher com a saída da bancada)*

### Sensor real

O firmware passa cada filtrado pelo picos e, a cada batimento, manda uma linha
`p,n_pico,fracao,rr_valido,rr_ms,bpm_valido,bpm`. A captura grava essas linhas
em `_picos.csv`, e o Python roda o mesmo detector sobre o `_filtrado.csv` da
placa e compara:

```bash
uv run python -m analise.captura COM3 --segundos 60   # e aperte o reset da placa
uv run python -m analise.picos --confere dados/sensor_<data>_<hora>.csv
```

**Capture desde o boot:** abra a captura e só então resete a placa (botão ou
`STM32_Programmer_CLI -c port=SWD -rst`), pra o primeiro `n` do filtrado ser 0.
Aí o Python vê o mesmo filtrado que a placa desde o começo e tudo tem que
bater: instantes (tolerância de 0,15 amostra, porque o Python roda sobre o
filtrado com 2 casas), RR (2 ms), `rr_valido` e BPM (0,1 bpm). A única
exceção é um RR a menos de 2 ms de uma fronteira (300 ou 2000 ms, ou 0,7 e
1,4 vez o RR típico): as 2 casas podem virar a decisão, e o RR típico (média
móvel) e a janela de 8 RR do BPM ficam diferentes por alguns batimentos; o
`--confere` mostra essas diferenças como "na borda".

Capturando no meio, o Python começa do zero: ele precisa de vários batimentos
(e às vezes nunca chega, se pegar um batimento falso no começo) pra ter o
mesmo RR típico e os mesmos 8 RR da placa. Então só os instantes e o RR entram
no OK, depois de 10 s (pro envelope); `rr_valido` e BPM saem só como
informação. Numa placa simulada no PC (o `picos.c` com as linhas `p,` do
`main.c`), os 42 registros do PhysioNet deram OK desde o boot e em 126 janelas
começando no meio.

Sem ECG na placa, o BPM é conferido a olho contra o pulso (ou um oxímetro).
A linha `p,` chega uns 1,3 s depois do pulso de verdade: 1 s do atraso do
filtro, 0,3 s do candidato pendente.

**Resultado com o sensor:** *(preencher com a saída do `--confere` e os ciclos)*
