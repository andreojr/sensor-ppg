---
title: Qualidade do sinal
description: "Detectar dedo ausente ou mal posicionado e marcar janela inválida."
sidebar:
  order: 5
---

| | |
|---|---|
| Frente | B · André |
| Item do plano | 7 (Piso) |
| Entrada | bruto |
| Saída | ppg_qualidade_t |
| Código | `Core/*/pds/qualidade/` |
| Protótipo | `analise/src/analise/qualidade.py` |

**O quê:** detectar dedo ausente ou mal posicionado e marcar janela inválida.

## Estado

| Passo | Estado |
|---|---|
| 1. Python, validado no PhysioNet | feito |
| 2. C sem HAL | feito: `qualidade.h`, `qualidade.c` |
| 3. Teste no PC contra os vetores | feito: `testes/qualidade/`, no CI |
| 4. Placa com a fonte falsa | feito: a bancada passou na placa |
| 5. Sensor real | feito: com o ritmo, barra o sinal sem pulso desse sensor e libera o pulso bom (na validação final, BPM de 62,5 a 67,4 contra 60 a 68 do relógio; abaixo) |

## Método

### O problema

O laço principal precisa saber quando **não** confiar no sinal: sem dedo, o
sensor lê ~1500 contagens de luz que vaza; com o dedo mexendo, o movimento
gera ondas maiores que o próprio pulso (vimos isso no relatório 1), e o
`picos/` acharia batimentos falsos. O detector olha o **bruto** (com DC),
porque o nível DC é justamente o que diz se há dedo, e solta uma resposta por
segundo: dá pra usar os últimos 2 s ou não.

### Janela de 2 s, uma resposta por segundo

As amostras chegam a 100 Hz. O módulo acumula **blocos de 1 s** e, no fim de
cada bloco, julga a **janela** formada pelo bloco anterior e o atual (2 s).
Por que 2 s: a janela precisa ter pelo menos um batimento inteiro pra medir a
altura do pulso, e a 30 bpm um batimento dura 2 s. Janela maior demora mais
pra perceber o defeito e mistura trecho bom com ruim.

Tudo é acumulado amostra a amostra (soma, máximo, mínimo, soma de
diferenças), sem guardar as 200 amostras: essa parte do estado tem 108
bytes e custa umas poucas somas e comparações por amostra. Só a amostra que
fecha o bloco faz 6 divisões. O ritmo (abaixo) precisa guardar 4 s a 25 Hz,
num buffer de 125 pontos guardado em dobro (abaixo): com ele, o estado
inteiro tem 1 184 bytes, mais que a pilha da placa (1 KB). No firmware, o
`qualidade_t` tem que ser `static` ou global, nunca variável local.

### O passa-altas

O IR bruto tem o DC (~130 mil), a respiração e derivas lentas (0,1 a
0,3 Hz) e o pulso (~1 Hz, 0,2 a 2% do DC). Pra medir só o pulso, o módulo
tira do IR uma **média exponencial**:

$m[n] = m[n-1] + \alpha\,(x[n] - m[n-1])$, $\quad y[n] = x[n] - m[n]$, $\quad \alpha = 0{,}02$

$m$ é uma média que "esquece" o passado devagar (constante de tempo
$1/(\alpha f_s) = 0{,}5$ s); $y$ é o que sobra quando se tira essa média: um
passa-altas de 1ª ordem com corte em
$f_c = \alpha f_s / 2\pi \approx 0{,}32$ Hz. Passa o pulso (0,5 a 3 Hz) e
corta quase todo o DC e a deriva. Custa uma multiplicação e duas somas por
amostra. Sem ele (testado com $\alpha = 0$, que mede a altura direto no
bruto), a deriva da respiração entra na altura: o falso alarme no limpo
triplica (1,0% das janelas contra 0,3%) e o dedo sem pulso passa mais (12,9%
das janelas contra 7,5%).

### Os indicadores de cada janela

| Indicador | Conta | O que mostra |
|---|---|---|
| `dc` | média do bruto, IR e vermelho | se há dedo |
| `maior` | maior amostra bruta dos dois canais | se o ADC saturou |
| `altura` | máx(y) − mín(y) | o tamanho do pulso, em contagens |
| `pi` | altura / dc do IR | **índice de perfusão**: o pulso em % do nível |
| `aspereza` | Σ\|y[n] − y[n−1]\| / altura | quantas "alturas" o sinal percorre: um pulso limpo sobe e desce ~uma vez por batimento (4 a 7 numa janela de 2 s); ruído sobe e desce toda amostra (> 20) |
| `razao` | altura / altura de referência | se o pulso mudou de tamanho de repente |
| `ritmo` | maior autocorrelação dos últimos 4 s, nos atrasos de 0,4 a 1,5 s | se o sinal **se repete** no ritmo de um coração (abaixo) |

A **altura de referência** é uma média das alturas das últimas janelas boas
(cada janela boa puxa a referência 1/4 do caminho até ela). Ela só aprende
com janela boa e é **esquecida** depois de 10 janelas ruins seguidas, porque
o pulso pode ter mudado de verdade (o dedo mudou de posição e ficou bom de
novo).

### O ritmo

Os indicadores acima medem tamanho e suavidade. No passo 5 com o sensor
real, isso não bastou: com o dedo mal encostado, o sinal tinha altura e
aspereza de pulso, mas **não se repetia** (os RR do picos misturavam 300 e
1 500 ms), e a qualidade marcava como usável. O `ritmo` mede justamente
isso.

**A conta.** O IR passa por um passa-faixa de 0,5 a 4 Hz (Butterworth de 2ª
ordem, duas seções de 2ª ordem, a do passa-altas primeiro), é reduzido a
25 Hz (média de 4 amostras) e os últimos 4 s (100 pontos) ficam num buffer
circular. No fim de cada bloco, sobre esses 4 s sem a média:

$r[k] = \dfrac{\sum_{i=k}^{99} z_i\, z_{i-k}}{\sum_i z_i^2}$, $\quad$ `ritmo` $= \max_{10 \le k \le 37} r[k]$

$r[k]$ é a semelhança do sinal com ele mesmo atrasado de $k$ amostras (1 =
idêntico). Um pulso a 72 bpm repete a cada 0,83 s (21 amostras a 25 Hz), e
$r[21]$ fica perto de 0,8 (não chega a 1 porque a soma do numerador tem
$100 - k$ termos). Ruído na mesma faixa não tem atraso nenhum com $r$ alto.
Os atrasos de 10 a 37 (0,4 a 1,48 s) cobrem de ~41 a 150 bpm. Perto de
40 bpm a folga é pequena: cabem só 2,7 batimentos em 4 s e o fator
$(100-k)/100$ no atraso 37 é 0,63, então um pulso sintético perfeito a
40 bpm dá 0,58 a 0,64, a 38 bpm desce até 0,49 e a 36 bpm (0,39 a 0,47) já cai abaixo
do limiar de 0,45. Bradicardia com variação
forte de ritmo pode ser marcada `SEM_RITMO`.

**Por que um passa-faixa próprio.** Com o $y$ do passa-altas de 1ª ordem, a
respiração e a deriva que sobram derrubam o $r$: 8,5% das janelas limpas do
PhysioNet ficavam abaixo de 0,5. Com o passa-faixa, 4,1% (`--distribuicao`). Custa 10
multiplicações por amostra.

**Por que 4 s.** Precisa caber pelo menos 2 batimentos a 40 bpm (3 s) pra
comparar um com o seguinte. Mais que isso atrasa a resposta.

**Quando ainda não há 4 s** (início, reinício): a janela conta como ruim
(`SEM_RITMO`), e o sinal limpo só fica usável no 7º segundo, não no 4º.

**No C**, a conta (~2 240 multiplicações, 2 342 passos com as somas) é
feita sobre os 4 s que fecharam o bloco anterior, espalhada pelas amostras
do bloco seguinte (25 passos por amostra), pra nenhuma amostra passar do
orçamento. Sem cópia: o buffer tem 125 pontos (os 100 da janela parada +
os 25 que chegam durante um bloco) e cada ponto é gravado duas vezes
(`pos` e `pos + 125`), então a janela é sempre um trecho contíguo que o
bloco atual não sobrescreve. O Python faz a mesma conta de uma vez, sobre
os 4 s do bloco anterior, e dá o mesmo número.

**Limitação conhecida:** um movimento **periódico** na faixa do pulso
(bater o dedo a 1 Hz) tem ritmo alto. Enquanto há referência, a `razao`
barra; depois de 10 janelas ruins a referência é esquecida e a batida
regular passa. Sem referência (a batida desde o início, antes de qualquer
janela boa), só o pi e a aspereza decidem, e ela pode passar logo. Sem um acelerômetro, isso não se separa de pulso.

### A regra e os limiares

Uma janela é **boa** quando passa em tudo. Cada falha liga um bit em
`qualidade_t.motivo`, pra serial e o display explicarem o porquê:

| Critério | Limiar | Motivo | De onde vem o número |
|---|---|---|---|
| dc dos dois canais ≥ | 10 000 contagens | `SEM_DEDO` | Sem dedo o sensor lê ~1500; com dedo, 64 mil a 87 mil no PhysioNet e ~130 mil no nosso. 10 mil é a média geométrica de 1500 e 65 mil (folga de ~6× pros dois lados). |
| maior < | 250 000 | `SATURADO` | ~95% do topo do ADC de 18 bits (262 143). Perto do topo o pulso é cortado. |
| pi ≥ | 0,05% | `PULSO_FRACO` | Menor pi limpo do PhysioNet: 0,09%. Metade disso. |
| razao ≥ | 0,4 | `PULSO_FRACO` | Pulso que cai a menos de 40% de repente: dedo apertado demais ou saindo. No limpo, só 1% das janelas fica abaixo de 0,58. |
| pi ≤ | 5% | `MOVIMENTO` | Maior pi limpo do PhysioNet: 5,0%; 99% ficam abaixo de 2,9%. |
| razao ≤ | 2,0 | `MOVIMENTO` | O pulso não dobra de um segundo pro outro; o movimento, sim. No limpo, 99,9% ficam abaixo de 2,4 contra a referência (média exponencial das alturas das janelas boas). |
| aspereza ≥ | 1,5 | `MOVIMENTO` | Abaixo disso o sinal só subiu ou só desceu na janela: deriva ou transitório (o dedo acabou de entrar), não pulso. Menor aspereza limpa: 1,97. |
| aspereza ≤ | 12 | `RUIDO` | Maior aspereza limpa: 10,6. Ruído de metade do tamanho do pulso já dá aspereza mediana de 22. |
| ritmo ≥ | 0,45 | `SEM_RITMO` | No PhysioNet limpo, ~3% das janelas de 4 s ficam abaixo (quase todas nos registros de perfusão baixa); no sinal do nosso sensor sem pulso de verdade, 0,04 a 0,26. Começou em 0,5 (só a qualidade decidia); baixou pra 0,45 quando o picos virou o segundo teste do BPM (etapa 3 do BPM confiável). A troca está na validação. |

Os limiares saíram da distribuição dos indicadores nos 22 registros `sit` do
PhysioNet (10 783 janelas limpas) contra os defeitos fabricados (abaixo):
os de dedo, saturação, pi mínimo e aspereza ficam com folga do sinal limpo; o pi
máximo e a razão ficam na cauda do limpo (pi máximo limpo de 5,02%, razão p99,9 de
2,39) e respondiam pelos 0,3% de falso alarme de antes do ritmo (com ele, o falso alarme no
limpo é de 3,4%). Os números do sinal limpo
saem de `uv run python -m analise.qualidade --distribuicao`.

### Histerese: rejeita rápido, aceita devagar

`indice` = janelas boas seguidas / 3, limitado a 1. **Uma janela ruim zera.**
`usavel` = `dedo_presente` e `indice` ≥ 1, ou seja, **3 janelas boas
seguidas** (`QUALIDADE_JANELAS_ACEITA`). Assim um sinal que pisca entre bom e
ruim fica marcado como ruim o tempo todo, e um defeito curto tira o sinal do
ar por pelo menos 3 s. Errar pro lado de descartar é mais barato: perder
alguns segundos de BPM é melhor que mostrar um BPM falso ou estragar o HRV.

### A saída

Uma por segundo (`qualidade_processa` devolve `true`), a partir do segundo
segundo:

| Campo | Significado |
|---|---|
| `valido` | a janela de 2 s encheu (desde o início ou o último reinício) |
| `dedo_presente` | dc dos dois canais ≥ 10 000 |
| `indice` | 0, 1/3, 2/3 ou 1 |
| `usavel` | `dedo_presente` e `indice` ≥ `QUALIDADE_LIMIAR` (1) |

A resposta vale para **os últimos 2 s** (o `ritmo` olha os 4 s que terminaram 1 s antes): o
laço principal tem que descartar os batimentos desse trecho, não só os que vierem depois.
Pro HRV, o batimento espera o julgamento seguinte (ver "O HRV só com batimentos
usáveis", abaixo).

### Casos de borda

| Situação | O que acontece |
|---|---|
| primeiras 199 amostras | nada sai (`processa` devolve `false`, `*s` intocado) |
| `n` que não é o seguinte do anterior (perdeu amostra, voltou) | reinicia e começa a janela de novo nessa amostra |
| amostra NaN ou infinita | descartada, reinicia |
| dedo entra | a deriva do passa-altas (o DC saindo de 1500 pra 130 mil) dá janelas de movimento por 2 a 4 s, e o ritmo precisa de 4 s limpos; usável em ~10 s |
| `qualidade_init` de novo | zera tudo, inclusive a referência |

### Implementação em C

```c
static qualidade_t q;         /* 1 184 B: static, não cabe na pilha de 1 KB */
qualidade_init(&q);
...
ppg_qualidade_t qual;
if (qualidade_processa(&q, &bruto, &qual)) {
    /* qual.usavel; q.motivo diz o porquê */
}
```

As contas são as mesmas do Python, em `float`. A diferença do C pro Python
(float64) é de no máximo 1,2 × 10⁻⁴ relativo (2,4 × 10⁻⁵ no ritmo), e nenhuma
decisão muda.

## Validação

### 1. Python: limpo e defeitos fabricados

`uv run python -m analise.qualidade` (22 registros `sit`, decimados a
100 Hz pela mesma conta da placa). Não existe gabarito de "sinal ruim" no
PhysioNet, então os defeitos são **fabricados** a partir dos trechos reais:

| Defeito | Como é feito |
|---|---|
| ausente | nível do nosso sensor sem dedo: 1500 + ruído de 5 contagens |
| sem pulso | só a parte lenta do sinal (< 0,3 Hz, respiração e deriva) + ruído de 2 contagens (o ruído medido no PhysioNet a 100 Hz) |
| saturado | ganho que leva o DC a 99% do topo, cortado em 262 143 |
| ruído ×k | ruído branco com desvio de k vezes o desvio do pulso |
| movimento ×k | solavancos de meio seno (0,2 a 0,8 s), a cada ~1,5 s, de altura k vezes a do pulso |
| sem ritmo | a parte lenta + ruído filtrado de 0,7 a 3,5 Hz com o desvio do pulso: altura e aspereza de pulso, sem se repetir (o caso do passo 5) |

As tabelas e o texto abaixo são do limiar 0,5 (o primeiro); o resultado
com o limiar atual (0,45) está logo depois da tabela da troca de limiar.

Cada registro é cortado em trechos de 20 s: os primeiros 10 s ficam limpos
(o detector aprende a referência) e os 10 s seguintes viram o defeito. Contam
as janelas inteiras dentro do defeito. **Acerto** = janela de defeito marcada
não usável; **falso alarme** = janela limpa marcada ruim.

| Caso | Janelas | Janela boa | Usável |
|---|---|---|---|
| **limpo** | 10 783 | 95,0% | 91,4% |
| limpo, no nível do nosso sensor (IR 130 mil, vermelho 137 mil) | 10 783 | 95,0% | 91,4% |
| ausente | 4 770 | 0% | 0% |
| sem pulso | 4 770 | 5,7% | 3,7% |
| saturado | 4 770 | 0% | 0% |
| ruído ×0,5, ×1, ×2 | 4 770 cada | 0% | 0% |
| movimento ×1 | 4 770 | 21,9% | 15,7% |
| movimento ×2 | 4 770 | 2,2% | 1,5% |
| movimento ×4 | 4 770 | 0% | 0% |
| **sem ritmo** | 4 770 | 7,0% | 5,6% |
| sem pulso, **sem limpo antes** | 10 070 | 37,2% | 16,1% |
| movimento ×4, **sem limpo antes** | 10 070 | 2,1% | 0,1% |

Antes do ritmo, o limpo dava 99,7% de janela boa e 99,0% de usável; o
movimento ×1 passava em 94%, o ×4 sem limpo antes em 53%.

- **Falso alarme no limpo: 5,0% das janelas.** 66 são as 3 primeiras de cada
  registro (ainda sem 4 s de ritmo); das outras 471, 426 só por `SEM_RITMO`,
  concentradas nos registros de perfusão baixa (`s17`: 166, `s9`: 53,
  `s15`: 36) e nos que têm artefato de verdade (`s8`: 83, `s19`: 49). É o
  preço do ritmo: era 0,3%. O "usável" cai mais (91%) porque cada janela
  ruim tira 3 s do ar.
- **Nível do sensor:** multiplicar o sinal pra ficar no nível do nosso
  sensor não muda nada (o pi e o ritmo são relativos), e o "sem dedo" do
  nosso sensor (1500) é pego em 100%.
- **Ausente, saturado e ruído: 100% de acerto.**
- **Sem ritmo: 94% de acerto.** O ruído fabricado na faixa do pulso às vezes
  se repete por acaso por alguns segundos.
- **Sem pulso: 96% de acerto** quando havia pulso antes (pega pela queda da
  `razao`); sem limpo antes, 84% (o ritmo pegou boa parte do que só o pi
  absoluto deixava passar: era 75%).
- **Movimento:** solavanco de 4× o pulso, 100%; de 2×, 98%; do tamanho do
  pulso, 84% (era 6%): os solavancos irregulares quebram o ritmo mesmo
  quando a amplitude não denuncia.

**Troca do limiar do ritmo** (`uv run python -m analise.qualidade --limiares-ritmo`, mesmos registros; a última coluna é a
captura do passo 5 com o dedo mal encostado, nos trechos "parados"):

| ritmo ≥ | limpo ruim | limpo usável | sem ritmo usável | passo 5 usável |
|---|---|---|---|---|
| 0,40 | 2,5% | 95,5% | 11,0% | 0 de 31 s |
| 0,45 | 3,4% | 93,9% | 7,8% | 0 de 31 s |
| **0,50** | **5,0%** | **91,4%** | **5,6%** | **0 de 31 s** |
| 0,55 | 7,5% | 87,6% | 3,5% | 0 de 31 s |
| 0,60 | 11,0% | 82,7% | 2,0% | 0 de 31 s |

Sem o ritmo, o passo 5 tinha 17 de 31 s usáveis. Qualquer limiar dessa
faixa resolve o caso real; o 0,5 equilibrava falso alarme e acerto no
fabricado enquanto a qualidade era o único teste.

**Limiar atual: 0,45.** Com o picos exigindo ritmo regular (#123), o BPM só
aparece quando os dois concordam, e o sinal sem ritmo que escapa da
qualidade ainda precisa enganar o picos. Simulando os dois juntos nas três
capturas do sensor real, nenhum lixo passou com 0,45 (nem a oscilação sem
dedo que enganava o picos sozinho), e no pulso bom o BPM apareceu em 21 de
43 s contra 14 com 0,5. Com 0,45, no PhysioNet:

| Caso | Janela boa | Usável |
|---|---|---|
| limpo | 96,6% | 93,9% |
| sem pulso | 6,0% | 4,0% |
| movimento ×1 / ×2 / ×4 | 31,7% / 3,2% / 0% | 22,3% / 1,9% / 0% |
| sem ritmo | 11,7% | 7,8% |
| ausente, saturado, ruído | 0% | 0% |

A latência não muda (dedo entra → usável: mediana 10 s, pior 22 s).

### Latência

Mesmos registros, trechos de 40 s, defeitos de 5 s no meio
(`latencias()`), em segundos:

| Evento | Mediana | Pior |
|---|---|---|
| dedo entra → usável | 10 | 22 |
| começa movimento ×4 → não usável | 1 | 2 |
| começa ruído ×1 → não usável | 1 | 1 |
| começa sem pulso → não usável | 2 | 4 |
| acaba movimento ×4 → usável de novo | 8 | 14 |

Com o ritmo, voltar a ser usável demora mais (os 4 s do ritmo precisam
sair do trecho ruim antes das 3 janelas boas): dedo entrando de 6 para
10 s, depois do movimento de 4 para 8 s.

![Vetor bordas: IR bruto com as janelas usáveis, pi e aspereza de cada janela](../../../assets/qualidade.png)

A figura é o vetor `bordas` do teste. No movimento (34,5 a 38,5 s), o pi
fica dentro da faixa e quem pega é a `razao`. Depois da saturação, o degrau
de ~130 mil contagens leva uns 3 s pra sair do passa-altas, e o sinal só
volta a ser usável no trecho limpo seguinte. Gerar de novo:
`uv run python -m analise.qualidade --figura ../docs/src/assets/qualidade.png`.

### 2. C no PC

`testes/qualidade/teste_qualidade.c`, no CI. Vetores gerados por
`uv run python -m analise.qualidade --vetores`:

| Caso | Entrada | Amostras | Saídas | Maior erro relativo |
|---|---|---|---|---|
| `physionet` | `s1_sit` de 60 a 90 s, no nível do nosso sensor | 3 000 | 29 | 6,8 × 10⁻⁵ |
| `bordas` | sem dedo, dedo entra, saturado, ruído, movimento, sem pulso, dedo sai, e o `n` pulando no meio; começa em n = 1000 | 5 800 | 55 | 1,2 × 10⁻⁴ |

`n`, `valido`, `dedo_presente`, `usavel` e `motivo` têm que bater exatos;
`indice` com 10⁻⁶; dc, pi, aspereza, razão e ritmo com 10⁻³ relativo. O teste também
confere, no próprio C: nada sai antes de 2 s e `*s` fica intocado; índice
1/3, 2/3, 1 e usável só depois que o ritmo e as 3 janelas boas fecham; sem dedo, saturado (IR ou só o
vermelho), sem pulso, pulso de 8% do DC, pulso que triplica de repente
(`razao` > 2), referência esquecida e reaprendida; `qualidade_init` zera,
`n` que pula e NaN reiniciam. Errar de propósito pega: sem esquecer a
referência, sem o critério de razão mínima, sem a aspereza mínima, peso da
referência trocado, sem reiniciar no `n` que pula, saturação só do IR, sem a
soma das diferenças; no ritmo, sem o espelho do anel, atraso trocado, passos a
menos por amostra; na decisão, sem `usavel`, sem `valido`, sem `tem_batimento`.

No Python (`analise/tests/test_qualidade.py`): os defeitos num PPG sintético,
os limiares iguais aos `#define` do C, e os vetores em dia (o Python de hoje,
na entrada gravada no vetor, tem que dar a saída gravada; roda no CI sem
baixar o PhysioNet).

### 3. Placa com a fonte falsa

```bash
cmake --preset Debug -DBANCADA_QUALIDADE=ON
cmake --build --preset Debug
STM32_Programmer_CLI -c port=SWD -w build/Debug/sensor-ppg.elf -v -rst
```

Na partida, logo depois de abrir a serial (antes do sensor, então roda mesmo
sem o MAX30102), a placa toca as 5 800 amostras do vetor `bordas` no
`qualidade_processa()`, confere com o mesmo vetor do teste no PC e mede os
ciclos de cada chamada. Esperado:

```text
# bancada qualidade: 55 saidas (esperado 55), 4 usaveis, 0 fora da tolerancia, erro rel max ... milionesimos
# bancada qualidade: ciclos por amostra med ... max ... (orcamento 3000): OK
```

**Orçamento:** 3 000 ciclos por amostra no pior caso (~31 µs a 96 MHz, 0,3%
da CPU a 100 Hz). Era 2 000 antes do ritmo; com ele, mesmo espalhando a
conta em 25 passos por amostra, o pior caso no build Debug (sem otimização,
onde cada multiplicação da autocorrelação custa ~30 ciclos) ficou em ~2 200,
e o orçamento subiu pra 3 000 (decisão do André, 21/11/2026; o filtro gasta
~9 900). Compila com o
Arm GNU com e sem a opção (e com todas as bancadas juntas), sem warnings
(a bancada acrescenta ~73 KB de flash, quase tudo o vetor `bordas`). No laço,
os ciclos da qualidade no sensor real saem a cada 10 s, junto dos da
decimação e do filtro (`# qualidade: ciclos med ... max ...`).

**Resultado na placa, com o ritmo e o limiar de 0,45** (22/11/2026), build Debug:

```text
# bancada qualidade: 55 saidas (esperado 55), 4 usaveis, 0 fora da tolerancia, erro rel max 123 milionesimos
# bancada qualidade: ciclos por amostra med 1647 max 2149 (orcamento 3000): OK
```

No Release, o mesmo vetor dá `med 786 max 1603`. O orçamento é conferido no Debug, o
pior dos dois.

No laço, com o sensor, `med 1454 max 2225`. Antes do ritmo eram 491/1393 na
bancada e 532/1163 no laço. No vetor `bordas`, as janelas usáveis caíram de
13 pra 4: os trechos limpos dele têm 6 s, e com o ritmo (4 s de sinal) mais as 3
janelas boas seguidas, quase todo o trecho passa antes de ficar usável.

### 4. Sensor real

Com a mesma opção, o laço principal passa cada amostra do bruto decimado
pela qualidade e manda, uma vez por segundo:

```text
q,<n>,<dedo>,<usavel>,<indice x1000>,<motivo>,<dc>,<pi x100000>,<aspereza x100>,<razao x100>,<ritmo x1000>
```

(só inteiros: o `printf` do firmware não tem float). `analise.captura` grava
essas linhas em `<nome>_qualidade.csv`, ao lado do cru e do bruto. Roteiro,
~2 min, provocando cada caso de propósito e anotando o tempo de cada um:

1. 15 s sem dedo → `dedo` 0, `motivo` 1.
2. Pôr o dedo e deixar parado 30 s → usável em ~10 s (com o ritmo) e ficar usável.
3. Mexer o dedo 10 s → não usável em ~1 s (`motivo` 8); parar → volta em ~8 s.
4. Apertar forte o dedo 10 s → pulso some (`motivo` 4)?
5. Encostar só a ponta do dedo (mal posicionado) 10 s → o que acontece?
6. Tirar o dedo → `dedo` 0 em ≤ 2 s.

A referência é o roteiro anotado. Conferir também com o bruto: nos trechos
marcados usáveis, o pulso tem que estar visível no `_bruto.csv`.

**1ª captura, antes do ritmo** (21/11/2026, 80 s, roteiro curto com cronômetro:
0–10 s sem dedo, 10–40 s parado, 40–50 s mexendo, 50–65 s parado, 65–75 s
sem dedo; nenhuma amostra perdida):

| trecho | o que a placa disse |
|---|---|
| sem dedo (0–9 s) | `dedo` 0, `motivo` 1 em todas as saídas |
| dedo entra (~9 s) | usável aos 19 s (10 s: o transitório do dedo entrando dura ~6 s, depois 3 janelas boas) |
| parado (19–38 s) | usável em 16 de 20 s; 4 s de `motivo` 8 (pi de 5,5 a 6,4%, acima do máximo de 5%) |
| mexendo (39–53 s) | não usável em todas, `motivo` 8 (pi até 270%, razão até 66) |
| parado de novo (54–64 s) | usável só 1 s; depois `motivo` 4 (pulso fraco): o dedo voltou mais apertado (dc de 90 para 128 mil) e o pulso caiu a ~1/3 da referência recém-aprendida |
| sem dedo (64 s em diante) | `dedo` 0 em 1 s |

**Placa = Python.** Rodando `analise.qualidade` no `_bruto.csv` gravado
(começando no mesmo limite de bloco da placa), as 78 saídas em comum têm a
mesma decisão (`usavel`, `dedo`, `motivo`) nas 78.

**O que isso não valida.** As decisões de dedo ausente e de movimento estão
certas. Mas, olhando o filtrado, **não há pulso regular em nenhum trecho**,
nem nos que a placa marcou usáveis: a autocorrelação de 4 s (no atraso de
0,4 a 1,5 s) ficou entre 0,04 e 0,26 nos trechos usáveis, quando um PPG bom
passa de 0,7, e os RR do picos saíram misturando 300 e 1 500 ms. É o mesmo
problema de montagem descrito em [Picos](../picos/): no módulo verde, os
componentes em volta são mais altos que a janela do sensor e o dedo não
encosta direito. A qualidade não pega isso porque nenhum dos critérios
mede **regularidade**: um sinal irregular com altura e aspereza de pulso
passa. Duas saídas possíveis: um critério de periodicidade (autocorrelação,
custa CPU no fim do bloco) ou refazer esta captura com o suporte de dedo
antes de mexer nos critérios. Também apareceu pi de 5 a 6% com o dedo parado,
perto do limite de 5% calibrado no PhysioNet. Foi daí que veio o ritmo.

**Com o ritmo, a mesma captura:** rodando o Python de agora no `_bruto.csv`
dela, os 31 s "parados" que tinham 17 usáveis passam a ter 0 (com qualquer
limiar de 0,4 a 0,6).

**2ª captura, com o ritmo** (21/11/2026, 125 s: sem dedo, dedo leve, dedo
apertado, mexendo, sem dedo; algumas linhas perdidas na serial, nenhuma na
placa): **nenhuma** janela usável, sempre por `SEM_RITMO` com dedo. O
filtrado mostrava o mesmo sinal irregular de ~0,1 a 0,4% do nível, sem pulso
visível, nos dois jeitos de apoiar. Placa = Python em 89 de 89 saídas.
Sem dedo, apareceu uma oscilação regular de ±5 contagens que acelera de ~80
a ~180 por minuto (luz do ambiente ou a mão perto do sensor): a qualidade
barra por `SEM_DEDO`, mas o picos sozinho acha "batimentos" nela, que é o
caso da decisão final (qualidade + picos) do
[desenho do BPM confiável](https://github.com/andreojr/sensor-ppg/blob/main/docs/superpowers/specs/2026-11-21-bpm-confiavel-design.md).

**3ª captura, com o ritmo e o relógio** (21/11/2026, 85 s: 10 s sem dedo,
~55 s com o dedo firme, parado e coberto com a outra mão pra tirar a luz do
ambiente, depois sem dedo; nenhuma amostra perdida). Pela primeira vez, um
pulso de verdade: de 25 a 68 s, RR estável de 920 a 1 050 ms e `ritmo` entre
0,5 e 0,7, mas fraco (pi 0,2 a 0,3%).

| | |
|---|---|
| usável com o dedo (25 a 68 s) | 15 de 44 s, em trechos de 1 a 5 s |
| BPM do picos nos trechos usáveis | 59 a 64 |
| BPM do relógio no mesmo período | 58 a 62 |
| placa = Python | 71 de 71 saídas |

O número que a placa liberaria estava certo. O que incomoda é ele
**piscar**: com o pulso fraco, o `ritmo` fica em volta de 0,5, e cada janela
abaixo tira o sinal do ar por 3 s. A mesma captura com outros limiares:

| ritmo ≥ | usável (de 44 s) | limpo ruim (PhysioNet) | sem ritmo usável |
|---|---|---|---|
| 0,40 | 29 | 2,5% | 11,0% |
| 0,45 | 23 | 3,4% | 7,8% |
| **0,50** | **15** | **5,0%** | **5,6%** |

## A decisão do BPM confiável

A tela só mostra o BPM do picos quando **dois testes independentes**
concordam (etapa 3 do
[desenho do BPM confiável](https://github.com/andreojr/sensor-ppg/blob/main/docs/superpowers/specs/2026-11-21-bpm-confiavel-design.md)):

| qualidade `usavel` | picos `bpm.valido` (ritmo regular, #123) | último batimento ≤ 3 s | tela |
|---|---|---|---|
| sim | sim | sim | BPM |
| qualquer outra combinação | | | `--` |

`qualidade_bpm_confiavel()` (C) e `bpm_confiavel()` (Python) fazem essa
conta, uma vez por segundo, a cada saída da qualidade. A qualidade roda sempre
no laço, e a placa manda `t,n,mostra,bpm x100` pela serial (é o que o display
vai ler).

**Por que 3 s pro último batimento.** O picos só solta o batimento ~1,3 s
depois do pulso (atraso do filtro + refratário), e a 40 bpm o intervalo é
de 1,5 s: no pior caso normal, o último batimento tem 2,8 s quando a
qualidade julga. Com 2 s, a tela piscaria a cada batimento em ritmo lento.
Mais que isso, um BPM antigo ficaria na tela depois que os batimentos param.

**Por que os dois.** Cada um sozinho se engana num caso que o outro pega:
nas capturas do sensor, o picos sozinho acreditou numa oscilação sem dedo
(22 de 31 s) que a qualidade barra por `SEM_DEDO`; a qualidade sozinha, com
o limiar 0,45, deixa passar uma janela ou outra de ruído na faixa do pulso,
que não forma o ritmo regular que o picos exige.

**Limitação:** com arritmia de verdade (fibrilação, extrassístoles
frequentes), o picos desliga o `valido` e a tela fica em `--`.

**Na placa, com o relógio** (22/11/2026, firmware sem bancada, 100 s:
sem dedo, dedo firme coberto, dedo leve, sem dedo):

| trecho | tela |
|---|---|
| sem dedo (início e fim, ~25 s) | `--` em todos |
| dedo leve, só apoiado (~12 s) | `--` em todos |
| dedo firme, pulso bom (24 a 37 s) | BPM em 8 s: **62,5 a 67,4** |
| dedo firme, sinal piorou (38 a 70 s; RR misturando 300 a 1 000 ms, ritmo 0,1 a 0,3) | `--` em todos |
| **relógio no mesmo período** | **60 a 68** |

Todo número que a tela mostrou estava na faixa do relógio. O que falta é
tempo de tela: com este módulo de sensor, o pulso bom é curto e fraco (pi
0,2%), e a regra prefere `--` a um número duvidoso.

**Com movimento de vez em quando** (22/11/2026, 115 s: sem dedo, parado,
mexendo 5 s, parado, mexendo 5 s, parado, sem dedo; relógio aos 35 s e aos
95 s):

| trecho | tela |
|---|---|
| sem dedo (início e fim) | `--` em todos; no fim, o picos sozinho voltou a ver "batimentos" na oscilação sem dedo (~150 por minuto, `valido` ligado), e a qualidade barrou por `SEM_DEDO` |
| mexendo (~41 a 52 s e ~66 a 72 s, contando o dedo assentar) | `--` desde o 1º segundo do movimento |
| tirando o dedo | `--` na hora |
| parado com pulso bom | BPM em 13 s: 58,6 a 67,3 |
| **relógio** | **63 (aos 35 s) e 61 (aos 95 s)** |

Nenhum número apareceu durante o movimento, o caso em que o limiar 0,45
deixa mais janelas passarem na qualidade sozinha. Dos 13 números, 12 ficaram
a até 5 bpm da leitura do relógio mais próxima no tempo; o 13º (67,3, no 1º segundo
depois de voltar do `--`) ficou 4 acima de 63 e 6 acima de 61. Depois de
cada movimento, o número levou 10 a 20 s pra voltar.

**Contra os critérios do spec.** O desenho
([BPM confiável](https://github.com/andreojr/sensor-ppg/blob/main/docs/superpowers/specs/2026-11-21-bpm-confiavel-design.md))
pedia o número a até 5 bpm do relógio em ≥ 95% das leituras e o número na tela em ~80% do
trecho bom. Ficou em 12 de 13 (92%) e ~50% do tempo bom, com um método mais simples que o do
spec (leitura a leitura, não a mediana de 10 s com o dedo parado há 20 s). Aceito assim porque o
erro que sobrou (6 bpm, no 1º segundo depois de um movimento) é pequeno e o tempo de tela baixo
vem do sinal fraco deste módulo de sensor, não da regra: ela prefere `--` a um número duvidoso.

## O HRV só com batimentos usáveis

O `ppg.h` pede que, com `usavel` falso, o laço descarte os batimentos do trecho. Pro
HRV, o RR de um batimento só entra se **dois julgamentos** da qualidade disserem usável:
o último antes de o picos soltar o batimento e o primeiro depois.

| julgamento de antes (≤ 1 s) | julgamento de depois | RR do picos válido | o RR entra no HRV |
|---|---|---|---|
| usável | usável | sim | sim |
| qualquer outra combinação | | | não |

**Por que os dois.** O picos solta o batimento ~1,3 s depois do pulso, e o pulso
filtrado depende do sinal até 1 s depois dele (o lado direito do FIR). A janela julgada
logo depois da soltura cobre o pulso e esse 1 s; só o julgamento de antes deixava passar
o batimento quando o movimento começava logo depois do pulso (2 de 39 RR numa captura
real). Cada "usável" já vale por 3 janelas boas seguidas (4 s), e os dois juntos cobrem
também o começo do RR (até 2 s antes do pulso, o maior RR aceito). O de antes vale por
um bloco (1 s): mais velho quer dizer que a qualidade recomeçou (`n` pulou, NaN) e ainda
não julgou.

**Como.** O batimento espera numa fila (`qualidade_fila_t`, 8 lugares: 2 s a 300 ms de
RR) até o julgamento seguinte: até 1 s (até ~3 s se a qualidade recomeçou; aí a fila pode
encher, e os excedentes saem com o RR de fora, que já seria o resultado). Aí vai ao `hrv_processa()`, com
`rr_valido` falso se não entra: o RR fica fora da janela e quebra a sequência das
diferenças (o RMSSD não usa um par que atravessa o trecho ruim). O `hrv.c` não muda.
`qualidade_batimento_usavel()`, `qualidade_fila_poe()` e `qualidade_fila_tira()` (C) e
`batimento_usavel()` e `Fila` (Python) têm a mesma tabela de casos nos dois testes.

**Na serial.** A linha `p,` sai na hora, como o picos viu. A `h,` sai quando a fila
libera (até ~1 s depois) e ganha `rr_usado`: 1 se o RR entrou no HRV, 0 se ficou de fora
(trecho não usável, ou o picos já tinha recusado o RR). O
`analise.hrv --confere` refaz a decisão no Python a partir do `_bruto.csv` e do
`_filtrado.csv` (qualidade, picos e fila, na ordem do laço) e compara com o `rr_usado`
da placa. Linha perdida na serial: o Python preenche o buraco por interpolação (senão a
qualidade dele recomeçaria e julgaria fora de fase com a placa até o fim) e deixa de fora
da comparação os batimentos de 1 s antes a 3 s depois dele (perder só as primeiras
linhas conta como buraco no começo). Uma `p,` ou `h,` perdida faz o HRV pular uma janela
(60 s) depois dela e voltar a comparar; o `rr_usado` casa por `n_pico` (±1 amostra). O comando termina
com uma linha `ACEITE: sim/não, porque …`, e o código de saída segue ela. Pra "sim", além
de placa = Python, a captura tem que ter exercitado a regra: pelo menos um batimento com o
sinal piorando logo depois do pulso (usável antes, não depois: é o movimento) e um com ele
melhorando (o contrário: já acontece quando o dedo assenta no começo); barrado nos dois
julgamentos não distingue nada. Os batimentos casam com ±1 amostra (o Python acha o pico no
filtrado com 2 casas), e o `rr_valido` da regra é o da `p,` da placa. E
o HRV tem que ter ficado válido e batido com o Python. Isso roda mesmo quando não
sai nenhum HRV válido.

**Ciclos.** O `hrv_processa()` agora roda na amostra em que a qualidade julga (uma por
segundo), não na que o picos solta o batimento: normalmente 1 ou 2 chamadas (20 000
ciclos de orçamento cada) somadas ao pico dessa amostra. Depois de um reinício da
qualidade (na placa, só com NaN), até ~7 chamadas numa amostra, ~1,5 ms a 96 MHz, bem
abaixo do pico do espectral (estimado pelo orçamento do HRV, não medido).

**O que muda no HRV.** Com este módulo de sensor, o trecho usável é curto (o número da
tela aparece em ~50% do tempo bom), e o HRV precisa de 45 s de RR aceitos na janela de
60 s: na prática, ele vai sair `valido` bem menos vezes. É o comportamento certo, porque
os RR de trecho ruim (movimento, dedo mal apoiado) eram justamente os que estragavam o
SDNN e o RMSSD.
