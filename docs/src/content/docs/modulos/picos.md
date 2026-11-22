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
| 4. Placa com a fonte falsa | feito, a bancada passou na placa |
| 5. Sensor real | feito: a placa detecta igual ao Python; a qualidade com o sensor depende do suporte de dedo (abaixo) |

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
   ou mais **e** com ritmo regular: nos últimos 8 batimentos, pelo menos 6 são
   "bons" (RR válido e a menos de 15% da mediana dos RR válidos). Ver "Regularidade
   do BPM" abaixo.

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

### Regularidade do BPM

**O problema.** Um sinal sem pulso (dedo mal apoiado) também gera "batimentos": o detector acha picos no
ruído, com RR de ~300 a ~1 500 ms. Cada RR pode passar sozinho pela faixa do `rr_valido`, e o `valido` do BPM,
que só pedia 4 RR válidos, **acreditava em 94% dos batimentos** (100% depois dos 8 primeiros, a mesma base da tabela abaixo) num ruído sem pulso (medido com ruído branco passando
pelo mesmo filtro e pelo picos). Só o picos, que vê a forma do sinal, consegue reconhecer que os batimentos não
formam um ritmo.

**A regra.** `picos_bpm().valido` agora também exige ritmo regular: nos últimos **8 batimentos** (o `picos_t`
guarda o `rr_valido` e o `rr_ms` de cada um), pelo menos **6 são bons**, isto é, têm RR válido e esse RR está a
menos de **15%** da mediana dos RR válidos. O `ppg.h` não muda: só fica mais estrito o que `ppg_bpm_t.valido`
significa ("BPM confiável pelo picos"). O BPM em si continua sendo a média dos últimos 8 RR válidos.

**Como se escolheu.** Os números 6 de 8 e 15% eram o ponto de partida; a variante também mudou, pelos dados
(`uv run python -m analise.picos_validacao --regularidade`, nos 66 registros do PhysioNet, baixados se faltarem, e em
12 trechos de 60 s de ruído branco, fração do tempo com o `valido` ligado):

| | todos os RR válidos perto da mediana (10 / 15 / 20 / 25%) | **6 de 8 bons** (10 / **15** / 20 / 25%) |
|---|---|---|
| sentado (22) | 72 / 89 / 95 / 98% | 91 / **97** / 99 / 100% |
| andando (22) | 34 / 47 / 51 / 54% | 48 / **52** / 54 / 57% |
| correndo (22) | 61 / 75 / 79 / 82% | 75 / **80** / 82 / 84% |
| **ruído sem pulso (12)** | 0 / 2 / 5 / 10% | 1 / **3** / 8 / 14% |

- **Exigir que *todos* os RR válidos fiquem perto da mediana** (a primeira ideia) rejeita o ruído tão bem quanto,
  mas **derruba o BPM de gente saudável com HRV alta**: a `s9_sit` (RMSSD de 84 ms) fica com o `valido` ligado só 58%
  do tempo, e uma única extrassístole desliga o BPM por 8 batimentos. Por isso a regra virou "6 de 8 bons": uma ou
  duas fora do ritmo não derrubam, e o ruído continua caindo em 3%.
- **15%** é o meio-termo: a 20% o ruído passa a ser aceito em 8% do tempo (14% a 25%), e a 10% já se perde o
  BPM de gente saudável (91% sentado, 48% andando).
- **Andando e correndo, o `valido` fica bem mais desligado** (52% e 80% do tempo, piores `s11_walk` com 0% e `s8_run`
  com 4%; sentado, o pior é `s17_sit` com 78%). Nos registros andando em que ele fica baixo (s8, s10 a s14), o BPM do
  picos erra de 5 a 17 bpm contra o ECG: desligar ali é o comportamento certo, não uma perda.
- No registro com movimento forte, `s2_walk`, o `valido` fica ligado em só 22% dos batimentos, que é o certo: o
  BPM dele erra 8,4 bpm.

**Na placa** (`-DBANCADA_PICOS=ON`, Release, 22/11/2026, com a regra nova):

```text
# bancada picos: 47 batimentos (esperado 47), 0 fora da tolerancia, erro max 0 milesimos
# bancada picos: ciclos por amostra med 108 max 1286 (orcamento 9600): OK
```

A bancada confere também o `bpm_valido` de cada batimento. No `s3_sit` ele só desliga nos 8 primeiros e depois fica
ligado: na STM32 roda a espera dos 8 batimentos e o caso regular. A mediana, o 6 de 8 e o desligar/religar são
conferidos no teste em C do PC (`ritmo_misto`).

**Limitações.**

- **Com arritmia de verdade, o `valido` desliga.** Fibrilação atrial, bigeminismo ou extrassístoles frequentes não
  formam um ritmo por esse critério, e o picos deixa de dar BPM. É a escolha de "só mostrar quando tem certeza".
  O picos não distingue arritmia de sinal ruim; o módulo `qualidade` (pulso presente) é o segundo teste.
- **Latência:** o `valido` só liga com 8 batimentos no histórico (~6 a 10 s a 75 bpm), contra 4 RR válidos antes, e
  volta a ligar só depois de os batimentos bons voltarem a ser 6 dos últimos 8.
- **O BPM é média, não mediana:** com 7 ou 8 RR válidos e 1 ou 2 fora do ritmo, esses entram na média. A regra só
  decide se mostra ou não.

**Captura real (dedo mal apoiado, `--confere`).** Aquela captura tinha 49% de RR válidos e RR de 300 a 1 600 ms
(ver "O que isso valida e o que não valida"), o mesmo perfil do ruído da varredura (52 a 66% de RR válidos, média de 60%), em que
o `valido` liga 3% do tempo. A captura em si não está no repositório e **não foi reprocessada** com a regra nova.

**Vetores de teste:** `uv run python -m analise.picos` (em `analise/`) grava
`testes/picos/vetores/` com a entrada e a saída do Python. O teste em C
(`testes/picos/teste_picos.c`) roda o `picos.c` sobre a mesma entrada e compara:
instantes, `rr_valido` e `bpm_valido` exatos, `fracao`, `rr_ms` e BPM com tolerância de 0,01. O vetor sintético
`ritmo_misto` (ritmo, uma pausa de 1 000 ms, 10 pares de RR de 600 e 1 000 ms que passam um a um pelo `rr_valido`, e o
ritmo de volta) faz o `valido` ligar, desligar e voltar, e confere C e Python nessas transições.

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

**O BPM não expira sozinho:** depois de 8 batimentos regulares, `picos_bpm()` continua
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

**Resultado na placa** (STM32F411, Debug `-O0`, 21/11/2026):

```text
# bancada picos: 47 batimentos (esperado 47), 0 fora da tolerancia, erro max 0 milesimos
# bancada picos: ciclos por amostra med 146 max 1465 (orcamento 9600): OK
```

Os 47 batimentos do `s3_sit` saem iguais aos do Python, inclusive os em que
o candidato pendente troca a corcova pelo pico verdadeiro. O custo médio é de
146 ciclos por amostra (1,5% do orçamento); o máximo, ~1 500, é a amostra em
que um candidato faz a parábola ou um batimento sai.

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

**Resultado com o sensor** (dedo parado no MAX30102, 60 s desde o boot, 21/11/2026):

```text
captura desde o boot: 70 batimentos da placa, 70 casados, 0 só na placa, 0 só no Python
erro máximo: instante 0.0378 amostra, rr 0.39 ms, bpm 0.01; rr_valido diferente em 0 (+0 na borda da faixa), bpm_valido em 0
BPM mediano 78.3: OK
# picos: ciclos med 162 max 1500 (orcamento 9600)
```

Nenhuma amostra perdida na captura. Todos os batimentos da placa casam com
os do Python (erro de instante abaixo de 0,04 amostra, 0,4 ms), com o mesmo
`rr_valido` e o mesmo BPM. Os ciclos com o sensor são os da bancada.

**O que isso valida e o que não valida.** O `--confere` mostra que a placa
detecta **igual ao Python**: o porte e a cadeia estão certos. Ele não mostra
que os batimentos são **reais**. Nessa captura, só 49% dos RR saíram válidos,
com intervalos de 300 ms misturados a outros de 1 600 ms, e o BPM de 78 estava
inflado por picos falsos. Olhando o sinal cru depois (na validação do HRV), o
pulso mal aparecia: a autocorrelação ficava em 0,1 a 0,4, quando um PPG bom
passa de 0,7.

A causa é a montagem: no módulo verde "MAX30100/30102", os capacitores e
reguladores em volta do sensor são mais altos que a janela dele. Com o dedo
apoiado de leve, ele não encosta na janela e o pulso some. Pressionando, o
pulso aparece (autocorrelação de 0,5 a 0,6, ritmo estável a ~70 bpm em 20 s;
em 2 min, o BPM ficou em 72 a 74 depois do primeiro minuto), mas ninguém
segura a pressão constante por minutos. Subir a corrente dos LEDs (7,2 → 12,6
mA) não ajudou, e as tensões do módulo estavam dentro da folha de dados.
**O projeto precisa de um suporte que segure o dedo sobre o sensor com pressão
leve e constante** (como um oxímetro de dedo). Com ele, esta captura deve ser
refeita conferindo o BPM contra uma referência (oxímetro ou relógio).
