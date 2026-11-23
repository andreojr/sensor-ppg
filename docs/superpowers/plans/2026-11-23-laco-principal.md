# Laço principal (#17): plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** tirar a cadeia de PDS de dentro da leitura do sensor e montar o superloop
`sensor → fila → cadeia → ficha → display`, com o TIM2 de régua e o DWT medindo
módulo, cadeia e volta, sem mudar nenhum número de saída.

**Architecture:** um módulo `pds/cadeia/` sem HAL (chama os módulos na ordem de
hoje, preenche o `ppg_resultados_t`, mede ciclos por um relógio injetado, formata
as linhas da serial) e uma camada `app` com HAL (`sensor.c`, `monitor.c`, `app.c`)
que faz as tarefas do laço. `main.c` só chama `app_init()`/`app_laco()`.

**Tech Stack:** C11, STM32 HAL (F411, 96 MHz), CMake + arm-none-eabi-gcc, testes no
PC com gcc + ctest (`testes/`), Python 3 + uv + numpy (`analise/`), CMSIS-DSP.

**Spec:** `docs/superpowers/specs/2026-11-23-laco-principal-design.md` (ler junto).

## Global Constraints

- Nada em `Core/*/pds/` inclui HAL nem `main.h`; sem malloc, sem variável global; estado em struct de quem chama (`ppg.h`).
- Não mudar `Core/Inc/pds/comum/ppg.h`, o `.ioc`, nem nenhum módulo de `pds/` existente.
- Ordem dos módulos por amostra **igual à `decima()` da c6727a2**: filtro → picos → espectral → respiração → qualidade.
- Serial padrão: `b,` `p,` `e,` `h,` `r,` `t,` e linhas `#`; `-DSERIAL_COMPLETA=ON` acrescenta as cruas `n,ir,vermelho` e o `f,`. Formatos das linhas **idênticos** aos de hoje (`main.c:570-648`).
- Fila sensor → cadeia: 16 × `ppg_amostra_t`, cheia = descarta a nova e conta.
- TIM2 nunca marca o passo; o callback só incrementa um contador.
- Nada na placa sem o OK explícito do André; sem push/PR/merge sem o OK dele.
- Commits pequenos na branch `firmware/17-laco-principal`; PR ≤ ~2000 linhas alteradas sem contar gerado (vetores `.h`).
- Build sem avisos em Debug e Release (`cmake --preset Debug|Release`); testes do PC: `cmake -S testes -B build/testes && cmake --build build/testes && ctest --test-dir build/testes --output-on-failure`.
- Python: `cd analise && uv run pytest` e `uv run ruff check` limpos.

## Review Focus

1. **Amostras perdidas pelo sensor** (salto no `n`): a decimação tem que receber a última amostra no lugar de cada perdida, como hoje, e o `n` do bruto seguir o tempo do sensor. Teste no replay (Task 4).
2. **Duas saídas de HRV na mesma amostra** (fila do HRV transborda no picos e esvazia no julgamento): todas têm que sair, na ordem. Teste em `teste_cadeia` (Task 2).
3. **Fila cheia**: a 17ª amostra é descartada e contada, e as 16 seguem em ordem. Teste em `teste_fila` (Task 3).
4. **Relógio nulo no PC**: `cadeia_init(c, NULL)` não mede e não quebra. Teste em `teste_cadeia` (Task 2).
5. **Volta do contador DWT** (a cada ~44,7 s): diferenças em `uint32_t` continuam certas. Teste em `teste_fila`/`ciclos` (Task 3).

---

### Task 1: cadeia de referência em Python e vetor

**Files:**
- Create: `analise/src/analise/cadeia.py`
- Test: `analise/tests/test_cadeia.py`
- Create (gerado): `testes/cadeia/vetores/physionet.h`

**Interfaces:**
- Produces: `analise.cadeia.roda(ir: np.ndarray, vm: np.ndarray) -> Saidas` (dataclass com listas `batimentos`, `espectral`, `hrv`, `respiracao`, `tela`, cada item uma tupla nos campos das linhas `p,`/`e,`/`h,`/`r,`/`t,`); `analise.cadeia.gera_vetores(testes: Path | None = None) -> list[Path]`; `python -m analise.cadeia --vetores`.

- [ ] **Step 1: Teste que falha.** `test_batimentos_iguais_ao_picos`: num trecho de 30 s do `s1_sit` (`qualidade.registro_100hz`), os `n_pico` de `roda` são os de `picos.detecta(filtro.filtra(ir))`. `test_tela_segue_a_regra`: cada item de `tela` tem `mostra == qualidade.bpm_confiavel(...)` com o julgamento e o último batimento daquele instante. `test_hrv_usa_a_fila`: os `rr_usado` de `hrv` são os de `qualidade.rr_entrou_no_hrv` no mesmo bruto/filtrado.
- [ ] **Step 2:** `cd analise && uv run pytest tests/test_cadeia.py -v` → FAIL (módulo não existe).
- [ ] **Step 3: Implementar `roda`.** Laço por amostra, na ordem do Global Constraints, reaproveitando as classes que já existem (`picos.Picos`, `qualidade.Qualidade`/`Fila`/`batimento_usavel`/`bpm_confiavel`, `hrv.Hrv`, `espectral.Espectral`, `respiracao.Estimador`) e o filtro do Python que o `filtro --confere` usa. Mesma lógica de `rr_entrou_no_hrv`, estendida a espectral, respiração e tela.
- [ ] **Step 4:** pytest → PASS; `uv run ruff check` limpo.
- [ ] **Step 5: `gera_vetores`.** Trecho de **90 s** do `s1_sit` a partir de 60 s (100 Hz): arrays `ir`, `vermelho` (entrada) e as saídas esperadas, em colunas separadas (`bat_n_pico`, `bat_rr_valido`, `bat_rr_ms`, `bat_bpm_valido`, `bat_bpm`, `esp_n`, `esp_valido`, `esp_bpm`, `hrv_n_pico`, `hrv_valido`, `hrv_sdnn`, `hrv_rmssd`, `hrv_rr_usado`, `resp_n`, `resp_valido`, `resp_rpm`, `tela_n`, `tela_mostra`, `tela_bpm`), via `vetores.header("cadeia", "physionet", ...)`. Tolerância: a maior entre as dos vetores do filtro, picos, hrv, espectral e respiração.
- [ ] **Step 6:** `uv run python -m analise.cadeia --vetores` gera `testes/cadeia/vetores/physionet.h`.
- [ ] **Step 7: Commit** `cadeia: referência em Python e vetor do PhysioNet (#17)`.

### Task 2: módulo `pds/cadeia/` e teste no PC

**Files:**
- Create: `Core/Inc/pds/cadeia/ciclos.h`, `Core/Inc/pds/cadeia/cadeia.h`, `Core/Src/pds/cadeia/cadeia.c`
- Modify: `Core/Inc/bancada.h` (tirar `ciclos_t`, `ciclos_conta`; incluir `cadeia/ciclos.h`)
- Test: `testes/cadeia/teste_cadeia.c`

**Interfaces:**
- Produces (`ciclos.h`, sem HAL): `typedef struct { uint64_t soma; uint32_t max; uint32_t conta; } ciclos_t;` e `static inline void ciclos_conta(ciclos_t *c, uint32_t dt);` (movidos do `bancada.h`, mesma semântica). `ciclos_agora()` e `ciclos_liga()` ficam no `bancada.h` (usam DWT).
- Produces (`cadeia.h`):
  ```c
  typedef uint32_t (*cadeia_relogio_t)(void);   /* NULL: não mede */
  #define CADEIA_HRV_MAX (QUALIDADE_FILA + 1u)
  typedef struct { uint32_t n_pico; ppg_hrv_t hrv; bool rr_usado; } cadeia_hrv_t;
  typedef struct {
      ppg_amostra_t filtrado;
      bool bateu;     ppg_batimento_t batimento; ppg_bpm_t bpm;  /* bpm cru do picos */
      bool espectral; ppg_bpm_t bpm_espectral;
      bool respirou;  ppg_respiracao_t respiracao;
      bool julgou;    ppg_qualidade_t qualidade; bool mostra;
      uint32_t n_hrv; cadeia_hrv_t hrv[CADEIA_HRV_MAX];   /* na ordem em que saíram */
  } cadeia_saida_t;
  typedef struct { ciclos_t filtro, picos, espectral, respiracao, qualidade, hrv, total; } cadeia_ciclos_t;
  typedef struct { /* filtro_t, picos_t, espectral_t, hrv_t, qualidade_t, qualidade_fila_t,
                      julgamento/tem_julgamento/n_julgamento, bpm cru/tem_batimento/n_ultimo_pico,
                      ppg_resultados_t ficha, cadeia_ciclos_t ciclos, cadeia_relogio_t relogio */ } cadeia_t;
  bool cadeia_init(cadeia_t *c, cadeia_relogio_t relogio);   /* false se espectral_init falhar */
  void cadeia_processa(cadeia_t *c, const ppg_amostra_t *bruto, cadeia_saida_t *s);
  const ppg_resultados_t *cadeia_resultados(const cadeia_t *c);
  ```
- Ficha: `bpm_picos.bpm` = último BPM cru; `bpm_picos.valido` = última decisão de `qualidade_bpm_confiavel` (atualiza só quando julga); a regra recebe sempre o BPM **cru** guardado à parte. `spo2.valido = false`.

- [ ] **Step 1: Teste que falha** (`teste_cadeia.c`, padrão dos outros `teste_*.c` com `confere.h`): passa as 9000 amostras do vetor por `cadeia_processa` (`relogio = NULL`), junta as saídas e compara com `confere_int` (discretos: `n_pico`, `rr_valido`, `bpm_valido`, `valido`, `rr_usado`, `n`, `mostra`) e `confere_float` (números, com `PHYSIONET_TOL`). Mais três casos: (a) `cadeia_init(&c, NULL)` devolve true e `c.ciclos.total.conta == 0` depois de processar; (b) com um relógio falso que soma 10 a cada chamada, `c.ciclos.filtro.conta == amostras` e `c.ciclos.total.soma > 0`; (c) duas HRV na mesma amostra: o caso das bordas — a fila do HRV cheia (`QUALIDADE_FILA` batimentos sem julgamento) seguida de julgamento solta `n_hrv > 1` em ordem crescente de `n_pico`. Para (c), montar a entrada com `testes/qualidade/vetores/bordas.h` se ele provocar o transbordo; senão, testar só que `n_hrv <= CADEIA_HRV_MAX` em todo o vetor e anotar no doc.
- [ ] **Step 2:** build dos testes → falha (cabeçalho não existe).
- [ ] **Step 3:** mover `ciclos_t`/`ciclos_conta` para `cadeia/ciclos.h`; `bancada.h` inclui. Firmware ainda compila (`cmake --build --preset Debug`).
- [ ] **Step 4: Implementar a cadeia** em `cadeia.c` copiando a lógica da `decima()` (c6727a2, `main.c:667-770`) a partir de "if (saiu)", sem serial, gravando em `cadeia_saida_t` e na ficha. Medir cada `_processa` com `relogio` quando não-NULL; `total` = a chamada inteira.
- [ ] **Step 5:** `ctest` → PASS, incluindo `guarda_sem_hal`.
- [ ] **Step 6: Commit** `cadeia: módulo sem HAL que chama os módulos na ordem e preenche a ficha (#17)`.

### Task 3: linhas da serial e fila (sem HAL)

**Files:**
- Create: `Core/Inc/pds/cadeia/linhas.h`, `Core/Src/pds/cadeia/linhas.c`, `Core/Inc/pds/cadeia/fila.h` (inline)
- Test: `testes/cadeia/teste_linhas.c`, `testes/cadeia/teste_fila.c`

**Interfaces:**
- Produces (`linhas.h`): `#define LINHAS_MAX 640u`; `size_t linhas_cadeia(const cadeia_saida_t *s, const ppg_amostra_t *bruto, bool completa, char *buf, size_t tam);` escreve, nesta ordem, `b,` (sempre), `f,` (só `completa`), `p,`, cada `h,`, `e,`, `r,`, `t,`, com os formatos exatos de hoje (`centesimos`, `envia_ppg`, `envia_batimento`, `envia_espectral`, `envia_hrv`, `envia_respiracao`, e `t,n,mostra,bpm×100`); devolve os bytes escritos. `size_t linhas_cru(uint32_t n, uint32_t ir, uint32_t vermelho, char *buf, size_t tam);` (`"%lu,%lu,%lu\n"`).
- Produces (`fila.h`): `#define FILA_TAM 16u`; `typedef struct { ppg_amostra_t a[FILA_TAM]; uint32_t ini, conta, max, cheia; } fila_t;` `void fila_init(fila_t*)`, `bool fila_poe(fila_t*, const ppg_amostra_t*)` (cheia: false e `cheia++`), `bool fila_tira(fila_t*, ppg_amostra_t*)`, `max` = maior `conta` desde o último `fila_zera_medidas(fila_t*)` (que zera `max` e `cheia`).

- [ ] **Step 1: Testes que falham.** `teste_linhas`: valores fixos → strings exatas, ex. `centesimos(-1.005f)`, um `p,` com `fracao 0.25` e `rr 812.5` → `"p,1234,0.2500,1,812.50,1,73.85\n"`; `completa=false` não tem `f,`; `bpm` inválido sai `0.00`; buffer pequeno não estoura (devolve ≤ `tam`). `teste_fila`: 16 entram, a 17ª devolve false e `cheia == 1`; saem as 16 na ordem; `max == 16`; dá a volta no anel (poe/tira 40 vezes) mantendo a ordem. Mais um caso de ciclos: `ciclos_conta` com `dt = (uint32_t)(5u - 0xFFFFFFF0u)` conta 21.
- [ ] **Step 2:** ctest → falha.
- [ ] **Step 3:** implementar; os formatadores saem do `main.c` para `linhas.c` sem mudar o texto.
- [ ] **Step 4:** ctest → PASS.
- [ ] **Step 5: Commit** `cadeia: linhas da serial e fila do sensor, testadas no PC (#17)`.

### Task 4: replay no PC (prova de que nada mudou)

**Files:**
- Create: `testes/cadeia/replay_cadeia.c`; Modify: `testes/CMakeLists.txt` (executável `replay_cadeia`, fora do glob `teste_*`)
- Modify: `analise/src/analise/cadeia.py` (subcomando `--replay CAPTURA.csv --bin build/testes/replay_cadeia`)
- Test: `analise/tests/test_cadeia.py` (+ `add_test` no ctest)

**Interfaces:**
- Consumes: `decimacao_*`, `cadeia_*`, `linhas_*`.
- Produces: `replay_cadeia` lê da entrada padrão as cruas (`n,ir,vermelho`, ignora `#` e cabeçalho do CSV), preenche saltos de `n` repetindo a última amostra (mesma regra do `sensor.c`), decima, roda a cadeia e escreve as linhas de `linhas_cadeia(..., completa=true)`. `analise.cadeia.compara_replay(captura: Path, linhas: str) -> dict[str, int]` (diferenças por tipo, comparando com `<nome>_picos.csv`, `_espectral.csv`, `_hrv.csv`, `_respiracao.csv`, `_tela.csv`, `_bruto.csv`, `_filtrado.csv` pelos parsers `captura.le_*`).

- [ ] **Step 1: Testes que falham.** ctest `replay_decimacao`: o replay sobre `decimacao.vetor_sensor_400hz()` (gravado como CSV de teste) dá `b,` igual ao `decimacao.decima` do Python dentro da tolerância do vetor da decimação. pytest `test_replay_preenche_salto`: uma captura sintética com um salto de 3 no `n` gera `b,` com `n` contínuo e a mesma quantidade de linhas que a sem salto. pytest `test_compara_replay_acusa_diferenca`: CSVs fabricados com um `p,` trocado → `{"p": 1, ...}`.
- [ ] **Step 2:** rodar → FAIL.
- [ ] **Step 3:** implementar o replay e o comparador.
- [ ] **Step 4:** rodar → PASS.
- [ ] **Step 5: Commit** `cadeia: replay das cruas no PC pra conferir a placa (#17)`.

### Task 5: camada app no firmware (sensor, monitor, app, main)

**Files:**
- Create: `Core/Inc/app.h`, `Core/Src/app.c`, `Core/Inc/sensor.h`, `Core/Src/sensor.c`, `Core/Inc/monitor.h`, `Core/Src/monitor.c`
- Modify: `Core/Src/main.c` (blocos `USER CODE`), `CMakeLists.txt` (fontes novas; `option(SERIAL_COMPLETA ...)`)

**Interfaces:**
- Consumes: Tasks 2 e 3.
- Produces:
  - `sensor.h`: `void sensor_init(I2C_HandleTypeDef *hi2c, fila_t *fila);` (chama `max30102_init` e `decimacao_init`; erro → mensagem na serial e `Error_Handler()`, como hoje); `void sensor_int(void);` (do EXTI: levanta a bandeira); `void sensor_tarefa(void);` (bandeira ou PB5 baixo → `max30102_le_fifo`, cruas na serial se `SERIAL_COMPLETA`, `# perdidas: N`, decima, `fila_poe`; mede decimação e o maior intervalo entre leituras com o DWT); `sensor_medidas_t sensor_medidas_tira(void);` (`perdidas`, `maior_intervalo_ciclos`, `ciclos_t decimacao`; zera ao tirar).
  - `monitor.h`: `void monitor_init(TIM_HandleTypeDef *htim);` (`ciclos_liga()`, `HAL_TIM_Base_Start_IT`); `void monitor_tique(void);` (do callback do TIM2: `tiques++`); `void monitor_conta_volta(uint32_t ciclos);`; `void monitor_tarefa(fila_t *fila, cadeia_t *c, uint32_t amostras);` — a cada 100 tiques: `# laco: amostras X fila_max Y fila_cheia Z perdidas W`; a cada 1000 tiques: `ciclos_relata` de cada módulo (orçamentos atuais do `bancada*.h`), `ciclos_relata_max(&c->ciclos.total, "cadeia", 51000u, 960000u)`, `# volta: ciclos med X max Y` e `# leitura: maior intervalo X ms (limite 80)`.
  - `app.h`: `void app_init(I2C_HandleTypeDef *sensor, I2C_HandleTypeDef *display, UART_HandleTypeDef *serial, TIM_HandleTypeDef *regua);` `void app_laco(void);`. `app.c` tem `HAL_GPIO_EXTI_Callback` e `HAL_TIM_PeriodElapsedCallback` (só repassam), as bancadas `#ifdef` na mesma ordem de hoje, o cabeçalho `#` (diz o modo da serial), e `display_amostra`/`display_servico` vazias (`static`, mesma assinatura do #122) enquanto o #122 não entra. `app_laco`: `sensor_tarefa(); while (fila_tira) { cadeia_processa; display_amostra(saida.filtrado.ir); linhas → serial_escreve; BANCADA_QUALIDADE: linha q, quando julgou }; display_servico(cadeia_resultados(&c), HAL_GetTick()); monitor_tarefa(...); serial_envia();` e mede a volta com o DWT.
  - Orçamento da cadeia **sem a decimação** (51 000 = filtro 19 200 + picos 9 600 + espectral 9 600 + respiração 9 600 + qualidade 3 000); a decimação segue com o orçamento dela, medida no `sensor.c`. *Decisão do builder: a spec fala em ~61 000 com a decimação; aqui ela é medida à parte.*
  - `main.c`: só `#include "app.h"`, `destrava_i2c1()` (fica, usa `MX_I2C1_Init`), `app_init(&hi2c1, &hi2c3, &huart1, &htim2)` e `app_laco()` no `while`. Tudo o mais dos blocos `USER CODE` sai.

- [ ] **Step 1:** criar os arquivos e esvaziar o `main.c`.
- [ ] **Step 2:** `cmake --preset Debug && cmake --build --preset Debug` e o mesmo em Release: 0 avisos. Repetir com `-DSERIAL_COMPLETA=ON` e com cada `-DBANCADA_*=ON` existente.
- [ ] **Step 3:** ctest e pytest seguem verdes.
- [ ] **Step 4:** anotar Flash/RAM (saída do linker) de antes (c6727a2) e depois, para a doc.
- [ ] **Step 5: Commit** `firmware: superloop com tarefas (sensor, cadeia, display, monitor) e TIM2 de régua (#17)`.

### Task 6: bancada da cadeia na placa

**Files:**
- Create: `Core/Inc/bancada_cadeia.h`, `Core/Src/bancada_cadeia.c`
- Modify: `CMakeLists.txt` (`option(BANCADA_CADEIA ...)`, inclui `testes/`), `Core/Src/app.c` (`#ifdef BANCADA_CADEIA`)

**Interfaces:**
- Produces: `bool bancada_cadeia(void);` passa o vetor `testes/cadeia/vetores/physionet.h` por uma `cadeia_t` própria (`static`) com `relogio = ciclos_agora`, confere como o `teste_cadeia` e manda `# bancada cadeia: N de M saídas iguais: OK|FALHOU` e os ciclos por módulo e da cadeia. Roda antes do sensor, como a do HRV.

- [ ] **Step 1:** implementar reaproveitando o laço de comparação do `teste_cadeia.c` (extrair para `testes/cadeia/compara_cadeia.h` se ficar duplicado).
- [ ] **Step 2:** build Debug e Release com `-DBANCADA_CADEIA=ON`: 0 avisos; Flash cabe (anotar).
- [ ] **Step 3: Commit** `bancada: cadeia inteira na placa com o vetor do PhysioNet (#17)`.

### Task 7: documentação

**Files:**
- Modify: `docs/src/content/docs/firmware.md` (tabela de interrupções: TIM2 = régua; seção nova "Laço principal" com o diagrama, as tarefas, a fila, os modos da serial e o orçamento; "Laço simples, sem RTOS" passa a apontar pra ela; linha do status da #17)
- Create: `docs/src/content/docs/modulos/cadeia.md` (o módulo: ordem, ficha, regra do BPM, ciclos, testes, replay; tabela de passos do fluxo como as outras páginas)
- Modify: `docs/src/content/docs/interface.md` se ele listar os módulos/linhas da serial

- [ ] **Step 1:** escrever; números da placa ficam "a medir" até a Task 8.
- [ ] **Step 2:** `cd docs && npm run build` (ou o comando do `docs.yml`) sem erro.
- [ ] **Step 3:** conferir o tamanho: `git diff --stat main -- . ':!testes/*/vetores/*'` ≤ ~2000 linhas. Se passar, separar o replay (Task 4) num PR seguinte.
- [ ] **Step 4: Commit** `docs: laço principal, módulo cadeia e TIM2 de régua (#17)`.

### Task 8: placa e sensor — **só com o OK do André**

- [ ] **Step 1 (antes de gravar a versão nova):** com o firmware da `c6727a2` (padrão, manda as cruas), captura de 5 min com o dedo: `uv run python -m analise.captura <porta> --segundos 300 -o dados/regressao_17.csv`.
- [ ] **Step 2:** `-DBANCADA_CADEIA=ON`: a linha `# bancada cadeia: ... OK` e os ciclos.
- [ ] **Step 3:** `-DSERIAL_COMPLETA=ON`, 5–10 min com o dedo: `# laco` com `amostras` ≈ 100, `fila_cheia 0`, `perdidas 0`; `# leitura` < 80 ms; `# cadeia` e `# volta`; os `--confere` de decimação, filtro, picos, hrv e respiração passando.
- [ ] **Step 4:** `uv run python -m analise.cadeia --replay dados/regressao_17.csv`: 0 diferenças em todos os tipos.
- [ ] **Step 5:** números na doc (Task 7) e na descrição do PR; commit `docs: medidas do laço na placa (#17)`.
- [ ] **Step 6:** relatar ao André; PR com `Closes #17` só com o OK dele.
