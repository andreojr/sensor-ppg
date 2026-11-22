# Ritmo na qualidade: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a qualidade passa a marcar como ruim a janela cujo sinal não se repete no ritmo de um coração (autocorrelação baixa), fechando o furo achado no passo 5 do PR #113.

**Architecture:** o IR depois do passa-altas que a qualidade já calcula é reduzido a 25 Hz e guardado em 4 s. No fim de cada bloco, a autocorrelação normalizada é calculada sobre esses 4 s (atrasos de 0,4 a 1,5 s) e o maior valor vira o indicador `ritmo`. Abaixo de 0,5, a janela ganha o motivo `SEM_RITMO`. O Python é a referência; o C faz a mesma conta espalhada pelas amostras do bloco seguinte, para caber no orçamento.

**Tech Stack:** Python 3 + numpy/scipy (`uv`, em `analise/`), C99 sem HAL (Arm GNU, ctest no PC), STM32F411.

**Spec:** `docs/superpowers/specs/2026-11-21-bpm-confiavel-design.md` (etapa 1).

## Global Constraints

- Regras de módulo de PDS (CONTRIBUTING): sem HAL, sem malloc, sem global em `pds/`; `float`; 100 Hz; estado na struct `qualidade_t`.
- Python primeiro; os vetores de teste saem dele (`uv run python -m analise.qualidade --vetores`).
- Orçamento da qualidade: **2 000 ciclos por amostra no pior caso** (`BANCADA_ORCAMENTO_QUALIDADE`).
- Falso alarme no PhysioNet limpo (janela ruim) **até 5%**.
- Não mexer em `ppg.h` (o `ritmo` fica em `qualidade_t`, como os outros diagnósticos).
- `printf` sem float: a linha da serial só leva inteiros escalados.
- `main.c` é CRLF: editar preservando CRLF.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Constantes (iguais no Python e no C)

| Python | C | valor |
|---|---|---|
| `RITMO_DECIMA` | `QUALIDADE_RITMO_DECIMA` | 4 (100 → 25 Hz) |
| `RITMO_N` | `QUALIDADE_RITMO_N` | 100 (4 s a 25 Hz) |
| `RITMO_ATRASO_MIN` | `QUALIDADE_RITMO_ATRASO_MIN` | 10 (0,4 s, 150 bpm) |
| `RITMO_ATRASO_MAX` | `QUALIDADE_RITMO_ATRASO_MAX` | 37 (1,48 s, ~40 bpm) |
| `Limiares.ritmo_min` | `QUALIDADE_RITMO_MIN` | 0.5 |
| `SEM_RITMO_BIT` | `QUALIDADE_SEM_RITMO` | 32 |

## O algoritmo (o que o Python e o C têm que dar igual)

```text
a cada amostra (depois de calcular y = ir - media):
    soma4 += y; conta4 += 1
    se conta4 == RITMO_DECIMA:
        anel[pos] = soma4 / RITMO_DECIMA; pos = (pos + 1) % RITMO_N
        cheio = min(cheio + 1, RITMO_N); soma4 = 0; conta4 = 0

no fim de cada bloco (onde hoje se chama _janela), nesta ordem:
    ritmo_desta = calcula(foto) se tem_foto, senão None
    foto = anel do mais antigo ao mais novo, se cheio == RITMO_N  (tem_foto = cheio == RITMO_N)
    a janela usa ritmo_desta

calcula(z0..z99):
    m = média; z = z - m; e = soma(z^2)
    se e == 0: devolve 0
    devolve max sobre k em [RITMO_ATRASO_MIN, RITMO_ATRASO_MAX] de soma_{i=k}^{N-1} z[i]*z[i-k] / e
```

- A foto é tirada em todo fim de bloco, mesmo o primeiro (quando `anterior` ainda é `None` e não sai janela).
- Na janela: `if dedo and (ritmo_desta is None or ritmo_desta < lim.ritmo_min): motivo |= SEM_RITMO_BIT`. `Saida.ritmo` = `ritmo_desta` ou 0.0 se `None`.
- `reinicia()` zera o anel, a foto e a fase da redução (`soma4`, `conta4`).
- Consequência: o primeiro ritmo sai no 5º fim de bloco (a foto do 4º, com 4 s cheios), e o sinal limpo vira usável no 7º segundo, não mais no 4º.
- No C, a mesma conta pode ser espalhada pelas amostras do bloco seguinte (média e energia numa amostra, um atraso por amostra nas próximas 28). O resultado é o mesmo, porque a foto não muda durante o bloco.

## Review Focus

1. **Movimento rítmico** (bater o dedo no ritmo, ~1 Hz): o `ritmo` sobe; tem que continuar barrado por pi/razão/aspereza. Teste em Task 1.
2. **BPM nas bordas** (40 e 150 bpm): pulso sintético a 42 e a 145 bpm tem que dar `ritmo` ≥ 0,5. Teste em Task 1.
3. **Reinício no meio** (n pula com o anel cheio): a próxima janela não pode usar o ritmo de antes do pulo. Teste em Task 1 e Task 3.
4. **Sinal constante** (energia 0 depois de tirar a média): `ritmo` 0, sem divisão por zero, nem NaN. Teste em Task 3.
5. **Testes antigos do C que comparam `motivo` exato** (saturado, sem pulso, sinal constante com dedo): agora também ligam `SEM_RITMO`. Comparar por bit, não por igualdade. Ajuste em Task 3.

---

### Task 1: ritmo no protótipo Python

**Files:**
- Modify: `analise/src/analise/qualidade.py` (constantes no topo, `Limiares`, `Saida`, `Qualidade.processa`, `Qualidade._janela`)
- Test: `analise/tests/test_qualidade.py`

**Interfaces:**
- Produces: `qualidade.RITMO_DECIMA`, `RITMO_N`, `RITMO_ATRASO_MIN`, `RITMO_ATRASO_MAX`, `SEM_RITMO_BIT`; `Limiares.ritmo_min: float = 0.5`; `Saida.ritmo: float` (último campo); `qualidade.ritmo_de(z: np.ndarray) -> float` (o `calcula` acima, usado pelos testes e pela Task 2).

- [ ] **Step 1: testes que falham**

```python
def test_ritmo_de_pulso_e_de_ruido():
    t = np.arange(qualidade.RITMO_N) / 25
    assert qualidade.ritmo_de(np.sin(2 * np.pi * 1.2 * t)) > 0.8
    assert qualidade.ritmo_de(np.zeros(qualidade.RITMO_N)) == 0.0
    rng = np.random.default_rng(1)
    assert qualidade.ritmo_de(rng.normal(size=qualidade.RITMO_N)) < 0.5

@pytest.mark.parametrize("bpm", [42.0, 72.0, 145.0])
def test_pulso_limpo_tem_ritmo(bpm):
    ir, vm = pulso(12, bpm=bpm)
    saidas = qualidade.roda(ir, vm)
    assert all(s.ritmo >= 0.5 for s in saidas[3:])
    assert saidas[-1].usavel

def test_sem_ritmo_antes_de_quatro_segundos():
    ir, vm = pulso(10)
    saidas = qualidade.roda(ir, vm)
    assert all(s.motivo & qualidade.SEM_RITMO_BIT and s.ritmo == 0.0 for s in saidas[:3])
    assert [s.usavel for s in saidas[:6]] == [False] * 5 + [True]

def test_ruido_na_faixa_do_pulso_e_barrado():
    # ruído filtrado de 0,7 a 3,5 Hz, com o desvio do pulso, sobre o DC do pulso
    ...  # montar com scipy.signal.butter/sosfiltfilt; semente fixa
    assert sum(bool(s.motivo & qualidade.SEM_RITMO_BIT) for s in saidas[4:]) >= 0.9 * len(saidas[4:])
    assert not any(s.usavel for s in saidas)

def test_movimento_ritmico_continua_barrado():
    # pulso + meio-seno a 1 Hz com 4x a altura do pulso (bater o dedo no ritmo)
    ...
    assert not any(s.usavel for s in saidas[4:])

def test_reinicio_apaga_o_ritmo():
    ir, vm = pulso(20)
    n = np.arange(len(ir)); n[1000:] += 50
    depois = [s for s in qualidade.roda(ir, vm, n) if s.n >= 1050]
    assert all(s.motivo & qualidade.SEM_RITMO_BIT for s in depois[:3])
```

Ajustar `test_limpo_usavel_depois_de_tres_janelas`: agora as 3 primeiras saídas têm `SEM_RITMO`, e `usavel` liga na 6ª saída (7º segundo). Ajustar `test_constantes_iguais_ao_c`: incluir os 5 novos `#define` e o bit (falha até a Task 3; marque `xfail(strict=True)` com motivo "C na Task 3" e tire na Task 3).

- [ ] **Step 2:** `cd analise && uv run pytest tests/test_qualidade.py -q` → os novos falham (`AttributeError: ritmo_de`).
- [ ] **Step 3:** implementar seguindo "O algoritmo". Estado novo em `Qualidade`: `anel: list[float]` (`RITMO_N` zeros), `pos`, `cheio`, `soma4`, `conta4`, `foto: list[float] | None`. `ritmo_de` em float64 com numpy.
- [ ] **Step 4:** `uv run pytest -q` → tudo passa (fora o xfail); `uv run ruff check .` limpo.
- [ ] **Step 5:** commit `qualidade: ritmo (autocorrelação de 4 s) no protótipo Python`.

### Task 2: validação no PhysioNet com o defeito "sem ritmo"

**Files:**
- Modify: `analise/src/analise/qualidade.py` (`degrada`, `TIPOS`, `DEFEITOS`, `relatorio`/`main` imprimem o ritmo)
- Modify: `docs/src/content/docs/modulos/qualidade.md` (indicadores, tabela de limiares, tabelas de validação, latência)
- Test: `analise/tests/test_qualidade.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `degrada("sem_ritmo", ir, vm, rng, forca)`: tendência + ruído filtrado de 0,7 a 3,5 Hz (Butterworth de 4ª ordem, `sosfiltfilt`), com desvio = `forca` × desvio do pulso.

- [ ] **Step 1:** acrescentar `("sem_ritmo", 1.0, qualidade.SEM_RITMO_BIT)` ao `parametrize` de `test_defeito_depois_do_limpo`; roda e falha (`ValueError: tipo desconhecido`).
- [ ] **Step 2:** implementar o tipo; colocar `("sem_ritmo", 1.0)` em `DEFEITOS`.
- [ ] **Step 3:** `uv run pytest -q` passa.
- [ ] **Step 4:** `uv run python -m analise.qualidade` (os 22 `*_sit`, PhysioNet em `analise/dados/physionet/`). Critérios: limpo, janela ruim ≤ 5%; `sem_ritmo` usável ≤ 5%; nenhum defeito antigo piora mais que 1 ponto percentual. Se o limpo passar de 5%, **parar e reportar** (não mexer no limiar sem o André).
- [ ] **Step 5:** checagem com a captura real do passo 5 (`passo5_bruto.csv` do scratchpad da sessão, ou uma nova): rodar `roda()` alinhado ao limite de bloco e contar as janelas usáveis no trecho "parado" (19–38 s). Esperado: quase nenhuma. Registrar o número na doc.
- [ ] **Step 6:** atualizar a doc (o ritmo entre os indicadores, com o porquê do 0,5 e das 4 s; tabelas e latência novas); `uv run python -m analise.plota_qualidade` se a figura mudar.
- [ ] **Step 7:** commit `qualidade: defeito sem ritmo e validação no PhysioNet`.

### Task 3: porte para C e teste no PC

**Files:**
- Modify: `Core/Inc/pds/qualidade/qualidade.h` (defines da tabela, campos novos em `qualidade_t`, comentário do topo)
- Modify: `Core/Src/pds/qualidade/qualidade.c`
- Modify: `testes/qualidade/teste_qualidade.c`
- Regenerate: `testes/qualidade/vetores/physionet.h`, `testes/qualidade/vetores/bordas.h`
- Modify: `analise/tests/test_qualidade.py` (tirar o xfail; `test_vetor_em_dia` passa a conferir `ritmo`)
- Modify: `analise/src/analise/qualidade.py` (`_arrays` exporta `ritmo`)

**Interfaces:**
- Consumes: Task 1 (algoritmo e constantes).
- Produces: em `qualidade_t`: `float anel[QUALIDADE_RITMO_N]`, `float foto[QUALIDADE_RITMO_N]`, `uint32_t pos, cheio, conta4`, `float soma4`, `bool tem_foto`, mais o que a conta espalhada precisar, e o diagnóstico `float ritmo` (0 se não havia foto). `qualidade_processa` mantém a assinatura.

- [ ] **Step 1:** `uv run python -m analise.qualidade --vetores` (vetores com `ritmo`); no `teste_qualidade.c`, conferir `ritmo` com a mesma tolerância relativa dos outros campos (`confere_rel`, TOL 1e-3) e as decisões exatas. Novos casos em `estados()`: sinal constante com dedo dá `ritmo == 0` e `SEM_RITMO` sem NaN; reinício com o anel cheio dá `SEM_RITMO` nas 3 saídas seguintes. Trocar as comparações exatas de `motivo` por teste de bit (Review Focus 5).
- [ ] **Step 2:** build e `ctest` em diretório próprio → falha (campos não existem).
- [ ] **Step 3:** implementar em C. A conta pode ser espalhada pelas amostras do bloco seguinte; o resultado tem que ser o do Python.
- [ ] **Step 4:** `ctest` passa; `uv run pytest -q` passa sem xfail; firmware Debug compila sem warnings com e sem `-DBANCADA_QUALIDADE=ON` (anotar a flash).
- [ ] **Step 5:** commit `qualidade: ritmo no C e vetores novos`.

### Task 4: serial, captura e bancada (passo 4 na placa)

**Files:**
- Modify: `Core/Src/bancada_qualidade.c`, `Core/Inc/bancada_qualidade.h` (linha `q,` ganha `ritmo x1000` no fim: 11 campos)
- Modify: `analise/src/analise/captura.py` (`COLUNAS_QUALIDADE` + `"ritmo"`; `le_qualidade` aceita 11 campos e devolve `ritmo / 1000`)
- Modify: `analise/tests/test_captura.py` (`test_qualidade_vai_pro_terceiro_csv` com o campo novo)
- Modify: `docs/src/content/docs/firmware.md`, `docs/src/content/docs/modulos/qualidade.md` (formato da linha; resultado da bancada)

**Interfaces:**
- Consumes: Task 3.
- Produces: linha `q,<n>,<dedo>,<usavel>,<indice x1000>,<motivo>,<dc>,<pi x1e5>,<aspereza x100>,<razao x100>,<ritmo x1000>`.

- [ ] **Step 1:** teste de captura com a linha de 11 campos (`ritmo` 0.512 e 0.0); roda e falha.
- [ ] **Step 2:** implementar o formato nos dois lados; `pytest` passa.
- [ ] **Step 3:** gravar na placa: build `-DBANCADA_QUALIDADE=ON`, `STM32_Programmer_CLI -c port=SWD -w <elf> -v`, abrir `/dev/ttyUSB0` a 921600 **antes** do reset (`-c port=SWD -rst`). Esperado: `# bancada qualidade: 55 saidas (esperado 55), ... 0 fora da tolerancia` e `ciclos ... max < 2000: OK`. Se o pior caso passar de 2 000, espalhar mais a conta (não subir o orçamento sem o André).
- [ ] **Step 4:** atualizar a doc com as duas linhas da bancada e os ciclos no laço.
- [ ] **Step 5:** commit `qualidade: ritmo na serial e bancada na placa`.

### Task 5: passo 5 de novo, com o André e o relógio

**Files:**
- Modify: `docs/src/content/docs/modulos/qualidade.md` (resultado com o sensor)
- PR #113: descrição

- [ ] **Step 1:** conferir 3 s de serial (linhas chegando, nenhum `# erro`) **antes** de pedir o dedo.
- [ ] **Step 2:** com o André: `uv run python -m analise.captura /dev/ttyUSB0 --segundos 120 -o <scratchpad>/passo5b.csv`, roteiro cronometrado: 0–10 s sem dedo; 10–50 s dedo leve parado (como antes); 50–90 s dedo apertado parado, com o BPM do relógio anotado a cada 10 s; 90–105 s mexendo; 105–120 s sem dedo.
- [ ] **Step 3:** analisar: decisões placa = Python no `_bruto.csv`; no dedo leve, usável ≤ 5% do tempo; no apertado, usável e com `ritmo` ≥ 0,5 na maior parte; BPM do picos contra o relógio nos trechos usáveis (só como informação: a decisão final é a etapa 3).
- [ ] **Step 4:** doc e descrição do PR com os números; commit `qualidade: passo 5 com o ritmo`; push sem force.
