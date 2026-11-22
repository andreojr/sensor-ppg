# BPM confiável, etapa 3: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** a placa só "mostra" o BPM quando a qualidade (`usavel`) e o picos (`bpm.valido`, já com a regularidade do #123) concordam e o último batimento é recente; o limiar do ritmo baixa para 0,45.

**Architecture:** uma função pura `qualidade_bpm_confiavel()` no módulo da qualidade (frente do André), espelhada em Python. A qualidade passa a rodar sempre no laço (não só com a bancada); uma vez por segundo sai a linha `t,<n>,<mostra>,<bpm x100>` com o que a tela mostraria.

**Spec:** `docs/superpowers/specs/2026-11-21-bpm-confiavel-design.md` (etapa 3).

## Global Constraints

- Regras de PDS (CONTRIBUTING): sem HAL/malloc/global em `pds/`, float, Python como referência, testes no PC.
- Não mudar `ppg.h`. `main.c` é CRLF.
- Falso alarme no PhysioNet limpo ≤ 5% com o novo limiar.
- Linhas da serial só com inteiros.
- Branch `pds/19-bpm-confiavel` (sobre #113 + #123); PR rascunho com base `pds/19-qualidade-sinal`.

## Decisões (do Claude, a conferir pelo André)

- **Validade do último batimento: 3 s** (não os 2 s do spec). O `p,` sai ~1,3 s depois do pulso; a 40 bpm o RR é 1,5 s: no pior caso normal o último `n_pico` tem 2,8 s quando a qualidade julga. Com 2 s a tela piscaria a cada batimento em ritmos lentos.
- **Função no módulo da qualidade** (não em `comum/`, que exige os três donos): ela recebe só tipos do `ppg.h`.

## Review Focus

1. Antes do primeiro batimento (nenhum `n_pico` ainda): não mostra. Task 2.
2. `n` da qualidade menor que `n_pico` (batimento "do futuro" por causa do atraso de alinhamento): não pode virar idade negativa/enorme por wrap de `uint32`. Task 2.
3. Dedo sai com o picos ainda `valido`: some na primeira saída da qualidade sem dedo. Task 2 (tabela) e Task 4 (placa).
4. Reinício da qualidade no meio: `usavel` falso até reaprender, mesmo com picos válido. Coberto pela regra.
5. Build sem nenhuma bancada: a qualidade roda e a linha `t,` sai. Task 3.

---

### Task 1: limiar do ritmo 0,45

**Files:** `analise/src/analise/qualidade.py` (`Limiares.ritmo_min`), `Core/Inc/pds/qualidade/qualidade.h` (`QUALIDADE_RITMO_MIN`), vetores `testes/qualidade/vetores/*.h`, `docs/.../modulos/qualidade.md`.

- [ ] Teste: `test_constantes_iguais_ao_c` já cobre; mudar só o Python primeiro e ver falhar.
- [ ] Mudar o C, regerar vetores, `pytest` + `ctest` verdes.
- [ ] `uv run python -m analise.qualidade`: limpo ruim ≤ 5% (esperado ~3,4%). Atualizar as tabelas e o texto do limiar na doc.
- [ ] Commit `qualidade: limiar do ritmo 0,45 (com o picos como segundo teste)`.

### Task 2: a decisão

**Interfaces:**
- C: `bool qualidade_bpm_confiavel(const ppg_qualidade_t *q, const ppg_bpm_t *b, bool tem_batimento, uint32_t n, uint32_t n_ultimo_pico);` em `qualidade.h/.c`; `#define QUALIDADE_BATIMENTO_VALE (3u * PPG_FS_HZ)`.
- Python: `bpm_confiavel(usavel: bool, bpm_valido: bool, tem_batimento: bool, n: int, n_pico: int) -> bool` e `BATIMENTO_VALE = 300`.
- Regra: `usavel && b->valido && tem_batimento && (n >= n_pico ? n - n_pico : 0) <= BATIMENTO_VALE` (batimento "à frente" do n conta como recente).

- [ ] Testes (Python e C, mesmos casos): as 4 combinações usavel × valido; sem batimento; idade 300 (mostra) e 301 (não); `n_pico > n` (mostra).
- [ ] Ver falhar, implementar, ver passar. Commit `qualidade: decisão do BPM confiável (qualidade + picos)`.

### Task 3: qualidade no laço + linha `t,`

**Files:** `Core/Src/main.c`, `analise/src/analise/captura.py` (+ teste), `docs/.../firmware.md`.

- [ ] Teste de captura: linhas `t,1299,1,6050` e `t,1399,0,0` vão pra `<nome>_tela.csv` com colunas `n,mostra,bpm` (bpm /100); linha cortada conta inválida.
- [ ] `main.c`: `qualidade_t` e os ciclos fora do `#ifdef BANCADA_QUALIDADE` (só a linha `q,` e a bancada continuam sob a opção); guardar o último `ppg_batimento_t`/`ppg_bpm_t` do picos; a cada saída da qualidade, `t,<n>,<mostra>,<bpm x100 ou 0>`; `ciclos_relata` da qualidade sempre.
- [ ] Firmware Debug com e sem `-DBANCADA_QUALIDADE=ON` sem warnings. Commit `firmware: qualidade sempre no laço e linha t, do BPM que a tela mostraria`.

### Task 4: placa com o relógio

- [ ] Gravar o firmware sem bancada (avisar a sessão do #109 antes de usar a placa). Conferir 3 s de serial.
- [ ] Com o André: 10 s sem dedo; ~60 s dedo firme coberto (relógio anotado em 2 momentos); ~15 s dedo leve; 10 s sem dedo.
- [ ] Critérios: dedo leve e sem dedo → `mostra` 0 em ≥ 95%; quando `mostra` 1, BPM a até 5 do relógio em ≥ 95%; tempo mostrando no trecho bom (meta 80%, registrar o que der).
- [ ] Doc (qualidade.md, seção da decisão) e commit `bpm confiável: validação na placa com o relógio`.

### Task 5: PR e revisão

- [ ] Push da branch, PR rascunho (base `pds/19-qualidade-sinal`, dizendo que depende do #123), revisão final por um revisor novo.
