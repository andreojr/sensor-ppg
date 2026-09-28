# sensor-ppg

Processamento digital de sinais de fotopletismografia (PPG) em tempo real.
Projeto da disciplina ENGG54 (Laboratório Integrado III, UFBA, 2026.2).

**Hardware:** STM32F411 (Black Pill) + sensor MAX30102 (I2C1) + display OLED
SSD1306 (I2C3). Dedo em repouso, sensor fixo na protoboard.

**O foco é PDS.** A STM32 roda a cadeia em tempo real e mostra no display, mas
o trabalho está nos módulos de processamento:

| Módulo | O quê | Nível |
|---|---|---|
| `decimacao` | anti-aliasing próprio e redução da taxa pra 100 Hz | piso |
| `filtro` | remoção de DC e passa-faixa 0,5 a 4 Hz | piso |
| `picos` | detecção robusta de batimentos, BPM | piso |
| `espectral` | BPM pela FFT | piso |
| `hrv` | variabilidade entre batimentos (SDNN, RMSSD; LF/HF no alvo) | piso |
| `qualidade` | detecção de sinal ruim (dedo mal posicionado) | piso |
| `spo2` | oxigenação pela razão vermelho/infravermelho | alvo |
| `respiracao` | frequência respiratória pela variação lenta do sinal | alvo |

## Estrutura

```
Core/Inc, Core/Src      firmware (gerado pelo CubeMX + código nosso que usa HAL)
Core/Inc/pds, Core/Src/pds
                        PDS em C puro, SEM HAL, uma pasta por módulo
  comum/ppg.h           a interface combinada entre os módulos
analise/                Python: protótipo e validação de cada módulo
testes/                 testes do PDS no PC (sem placa)
docs/                   documentação (um documento por módulo)
```

## Como compilar

Precisa de `arm-none-eabi-gcc`, `cmake` e `ninja`; pro Python, `uv`.

```bash
# firmware
cmake --preset Debug
cmake --build --preset Debug

# testes do PDS no PC
cmake -S testes -B build/testes -G Ninja
cmake --build build/testes
ctest --test-dir build/testes --output-on-failure

# Python
cd analise && uv sync && uv run pytest
```

Gravar na placa: `st-flash write build/Debug/sensor-ppg.bin 0x8000000`
(ou STM32CubeProgrammer).

## Como trabalhamos

Leia o [CONTRIBUTING.md](CONTRIBUTING.md) antes do primeiro PR.
