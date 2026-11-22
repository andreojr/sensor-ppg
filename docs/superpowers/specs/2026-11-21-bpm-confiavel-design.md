# BPM confiável: só mostrar o número quando há pulso de verdade

Data: 21/11/2026. Origem: passo 5 da qualidade (PR #113).

## Por quê

No passo 5 da qualidade, com o dedo no MAX30102, a placa marcou como usáveis
trechos **sem pulso regular**: a autocorrelação do filtrado ficou entre 0,04
e 0,26 (um PPG bom passa de 0,7), e os RR do picos misturavam 300 e 1 500 ms.
A causa física é a montagem do módulo (o dedo não encosta na janela do
sensor), mas a decisão do André é que **o código tem que perceber isso
sozinho**: um suporte de dedo ajuda, mas não dá pra depender dele. Na dúvida,
a tela mostra `--`, nunca um número errado.

## Objetivos

- A tela só mostra BPM quando **dois testes independentes** concordam que há
  pulso:
  1. a **qualidade** (sobre o sinal, antes de achar batimentos) diz que há
     pulso, agora incluindo **ritmo**;
  2. o **picos** (sobre os batimentos achados) diz que os últimos batimentos
     são **regulares**.
- Cada módulo diz o quanto confia no **próprio** resultado; a combinação fica
  num lugar só, antes da tela.
- Validado contra um relógio que mede BPM, com o sensor real.

## Fora do escopo

- Detectar arritmia. Limitação conhecida: com batimentos irregulares de
  verdade (fibrilação atrial, extrassístoles frequentes), a tela fica em `--`.
  Vai escrita na documentação.
- O desenho da tela (o que aparece além de `--`); isso é da frente do display.
- O módulo espectral (etapa 4 abaixo só reserva o lugar dele).

## Anti-objetivos (falha mesmo se "funcionar")

- A tela mostra um BPM que discorda do relógio por mais de 5 bpm.
- Um módulo passa a depender do estado interno de outro.
- Mudar `ppg.h` sem o ok do grupo (João e Celso).

## Restrições

- Regras dos módulos de PDS (CONTRIBUTING): sem HAL, sem malloc, sem global,
  `float`, 100 Hz, estado numa struct, Python como referência e vetores de
  teste gerados dele, os 5 passos do fluxo.
- Orçamento de CPU por amostra de cada módulo (o da qualidade é 2 000 ciclos
  no pior caso).
- `Core/*/pds/picos/` é da frente do Celso (CODEOWNERS: Celso e André): a
  mudança no picos precisa do ok dele.

## Abordagens consideradas

| | O quê | A favor | Contra |
|---|---|---|---|
| A | Só a qualidade ganha um teste de ritmo (autocorrelação) | Independente; separa bem PhysioNet (mediana 0,75) do sinal ruim (0,20) | Um único teste; um sinal que se repete sem ser pulso passa |
| B | Só o picos julga (regularidade dos RR) | Quase de graça | Depende do picos, que vem depois; se ele errar sempre igual, engana |
| **C (escolhida)** | **Os dois, combinados num lugar só antes da tela** | Dois testes independentes; cada módulo cuida do seu | Mais trabalho e validação |

O André escolheu C: o picos tem que participar, porque "os batimentos fazem
sentido?" é uma pergunta que só ele responde.

## Desenho

### A decisão final

| qualidade `usavel` | picos `bpm.valido` | tela |
|---|---|---|
| sim | sim | BPM do picos |
| sim | não | `--` |
| não | sim | `--` |
| não | não | `--` |

Uma função pura, testada no PC, chamada no laço principal antes de
atualizar a tela. Usa a saída mais recente de cada módulo (a qualidade sai
uma vez por segundo; o picos, a cada batimento, ~1,3 s depois do pulso).

**Validade do BPM do picos (decisão do Claude):** o picos só atualiza o
BPM quando acha um batimento; se os batimentos param, o último BPM ficaria
"valendo" pra sempre. Então a função também recebe o `n` atual e o `n_pico`
do último batimento, e diz não se o último batimento tem mais de 2 s
(abaixo de 30 bpm, impossível em repouso). Assim:
`bool bpm_confiavel(const ppg_qualidade_t *q, const ppg_bpm_t *b, uint32_t n, uint32_t n_ultimo_pico)`.

> **Como ficou no código** (ver `modulos/qualidade.md`): o limite é de 3 s
> (`QUALIDADE_BATIMENTO_VALE`), a função recebe também `tem_batimento`, e um
> `n_pico` à frente de `n` bloqueia.
O picos não é reiniciado pela qualidade: os módulos continuam sem
depender um do outro.

**A qualidade no build normal (decisão do Claude):** hoje a qualidade só
roda com `-DBANCADA_QUALIDADE`. Pra decidir a tela, ela passa a rodar
sempre no laço (custa ~530 ciclos por amostra, medido); a opção de bancada
fica só pro vetor de teste e a linha `q,` da serial.

### Etapa 1: ritmo na qualidade (frente do André)

- O IR depois do passa-altas que a qualidade já calcula é reduzido a 25 Hz
  (média de 4 amostras) e guardado num buffer circular de 4 s (100 floats,
  400 B na struct).
- Uma vez por segundo: autocorrelação normalizada para atrasos de 0,4 a
  1,5 s (40 a 150 bpm; 10 a 37 amostras a 25 Hz), e fica o **maior valor**
  (`ritmo`, de −1 a 1).
- Janela ruim se `ritmo < QUALIDADE_RITMO_MIN`. Ponto de partida: 0,5 (no
  PhysioNet limpo, 2,6% das janelas de 4 s ficam abaixo). Calibrar com as
  capturas da validação.
- Novo bit de motivo `QUALIDADE_SEM_RITMO` (32) e `ritmo` no diagnóstico e
  na linha `q,` da serial.
- Até ter 4 s de sinal desde o último reinício, ainda não dá pra julgar o
  ritmo: a janela conta como ruim (o dedo entrando já leva ~6 s de
  transitório, então quase não muda a latência).
- Custo: ~2 800 multiplicações por segundo. Espalhar o cálculo pelas
  amostras do bloco (alguns atrasos por amostra) para o pior caso ficar
  dentro dos 2 000 ciclos.
- Validação no PhysioNet (passo 1) refeita: falso alarme no limpo e os
  defeitos fabricados, mais um defeito novo "sem ritmo" (ruído filtrado na
  faixa do pulso, com a altura e a aspereza de um pulso).

### Etapa 2: regularidade no picos (frente do Celso, precisa do ok dele)

- Proposta: `picos_bpm()` passa a dar `valido = true` só quando, nos últimos
  8 batimentos, pelo menos 6 tiveram `rr_valido` **e** os RR válidos estão
  perto da mediana deles (desvio menor que ~15%). Hoje basta haver RR
  suficientes.
- Não muda `ppg.h`: só fica mais estrito o significado de `ppg_bpm_t.valido`
  ("BPM confiável pelo picos").
- Os números (6 de 8, 15%) saem da validação no PhysioNet (passo 1 do
  picos): com sinal limpo, `valido` deve ficar ligado quase sempre.
- Tamanho real: o `picos_t` hoje só guarda os RR válidos, então precisa de
  um histórico novo (os `rr_valido` dos últimos 8 batimentos). Muda também
  o `picos.py` (a referência), os vetores e o passo 1 do picos. É isso que
  vai pro Celso concordar.

### Etapa 3: a decisão e a validação com o relógio

- A função `bpm_confiavel` e a chamada no laço. **"Tela" nesta etapa é a
  linha da serial (decisão do Claude):** o display OLED ainda está nas
  branches `firmware/26-display-oled` e `firmware/26-oled-modulo`, fora da
  main. A placa manda, uma vez por segundo, o BPM que mostraria (ou `--`);
  quando o display entrar na main, ele lê o mesmo resultado.
- **Os limiares podem ser reajustados nesta etapa (decisão do Claude):** se
  as capturas pedirem outro `QUALIDADE_RITMO_MIN` ou outros números no
  picos, o PR desta etapa muda as constantes e refaz o passo 1 do módulo
  mexido, desde que o falso alarme no PhysioNet limpo fique em até 5%.
- **Comparação com o relógio (decisão do Claude):** a placa faz média de 8
  RR (atraso de ~6 a 10 s) e o relógio tem a média dele. Por isso as
  anotações só valem com o dedo parado há pelo menos 20 s, e cada anotação
  é comparada com a mediana do que a placa mostrou nos 10 s em volta.
- Capturas de ~2 min cada, com o BPM do relógio anotado a cada ~10 s:
  1. dedo apertado e parado (sinal bom);
  2. dedo leve (sinal sem pulso, como no passo 5);
  3. dedo parado com movimentos de vez em quando.
- Critérios:
  - quando a tela mostra número, ele fica a até 5 bpm do relógio em pelo
    menos 95% das leituras;
  - no trecho bom, o número aparece na maior parte do tempo (meta: 80%;
    revisar com os dados);
  - no trecho sem pulso, `--` em pelo menos 95% do tempo.

### Etapa 4 (depois): concordância com o espectral

Quando o espectral (frente do Celso) existir, a decisão passa a exigir
também que o BPM do picos e o do espectral fiquem a até ~10% um do outro.

## Em que ordem

Cada etapa é um PR que deixa tudo funcionando e testado:

1. Ritmo na qualidade. Entra no PR #113, que ainda é rascunho e cujo passo
   5 só fecha com o ritmo (decisão do Claude).
2. Regularidade no picos (com o Celso).
3. Decisão + tela + captura com o relógio.
4. Espectral, quando existir.

As etapas 1 e 2 são independentes e podem andar em paralelo. A etapa 2 já está com o Celso, numa branch dele. Se ela demorar, a etapa 3 começa só com a qualidade e o picos entra quando a branch dele for pra main (decisão do Claude).

## O que fica com quem implementar

- Como espalhar a autocorrelação pelas amostras do bloco.
- Nomes de constantes e campos, seguindo o padrão dos módulos.
- O formato exato das linhas novas da serial (só inteiros).
- Onde mora a função `bpm_confiavel` (precisa ser C puro testável no PC).
