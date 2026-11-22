# CMSIS-DSP (só a FFT real de float32)

Cópia **parcial e sem alteração** da biblioteca CMSIS-DSP da ARM, só o que a FFT
real de `float32` (`arm_rfft_fast_f32`) precisa.

| | |
|---|---|
| Origem | https://github.com/ARM-software/CMSIS-DSP |
| Versão | **v1.16.2** (tag `v1.16.2`, commit `d5717e454fec0337bef114a21f1d2d01d74f2701`) |
| Licença | Apache 2.0 (`LICENSE.txt`, copiada da raiz do repositório da ARM) |
| Usada por | `Core/*/pds/fft/` (o `espectral` nunca inclui um cabeçalho daqui) |

Por que a v1.16.2: é a última da série 1.16, que funciona com o CMSIS-Core 5.6
que o projeto já tem em `Drivers/CMSIS/Include`. A série 1.17 em diante passa pro
CMSIS 6.

## O que foi copiado, e por quê

**`Source/TransformFunctions/`** (a FFT em si)

| Arquivo | Por que |
|---|---|
| `arm_rfft_fast_f32.c` | `arm_rfft_fast_f32()`: a FFT de sinal real |
| `arm_rfft_fast_init_f32.c` | `arm_rfft_fast_init_<n>_f32()`: prepara a FFT de cada tamanho |
| `arm_cfft_f32.c` | FFT complexa de n/2 pontos, que a real usa por dentro |
| `arm_cfft_init_f32.c` | prepara a FFT complexa de cada tamanho |
| `arm_cfft_radix8_f32.c` | as borboletas da FFT complexa (versão sem Helium) |
| `arm_bitreversal2.c` | reordenação dos índices (bit reversal) |

**`Source/CommonTables/`** (as tabelas de constantes)

| Arquivo | Por que |
|---|---|
| `arm_common_tables.c` | as tabelas de seno/cosseno (twiddle) e de bit reversal de **todos** os tamanhos. São 4,9 MB de texto, mas o linker só leva as dos tamanhos chamados (ver abaixo) |
| `arm_const_structs.c` | estruturas constantes da FFT complexa, exigidas pelo `arm_cfft_init_f32.c` |

**`Include/`** (só os 10 cabeçalhos que esses arquivos incluem, direta ou indiretamente,
conferidos com `gcc -MM`): `arm_math_types.h`, `arm_math_memory.h`,
`arm_common_tables.h`, `arm_const_structs.h` e `dsp/{transform_functions,
basic_math_functions, complex_math_functions, fast_math_functions, none, utils}.h`.

Não foram copiados: o `PrivateInclude/`, o `arm_math.h` inteiro, e tudo o que é
Helium (MVE), fixed-point (q15/q31), `float16` e `float64`.

## Como é compilado

- **Firmware:** `CMakeLists.txt` da raiz lista `Drivers/CMSIS/DSP/Source/*.c`, põe
  `Drivers/CMSIS/DSP/Include` nos includes e define `ARM_MATH_CM4`. A FPU
  (`-mfpu=fpv4-sp-d16 -mfloat-abi=hard`) e o `-ffunction-sections -fdata-sections`
  já vêm do `cmake/gcc-arm-none-eabi.cmake`, e o `-Wl,--gc-sections` faz o linker
  descartar o que ninguém usa. Os fontes da ARM são compilados com `-w` (sem avisos);
  os do nosso `fft.c` seguem com `-Wall`. Não mexe no `.ioc`.
- **Testes no PC:** `testes/CMakeLists.txt` compila os mesmos arquivos com
  `-D__GNUC_PYTHON__`, o modo "host" do `arm_math_types.h` (sem o `cmsis_compiler.h`,
  que usa instruções ARM). É código da ARM, igual ao da placa.
- **`arm_dsp_config.h` não existe aqui** e não precisa: só é incluído com
  `ARM_DSP_CUSTOM_CONFIG`, que não definimos.

## Flash: só os tamanhos usados

Nesta versão não existe mais `-DARM_DSP_CONFIG_TABLES`. O jeito de não levar as
tabelas de todos os tamanhos pra flash é **chamar a inicialização do tamanho**
(`arm_rfft_fast_init_1024_f32`) e **nunca** a genérica `arm_rfft_fast_init_f32(S, n)`,
que referencia todas. É o que o `Core/Src/pds/fft/fft.c` faz. Detalhes e medidas em
`docs/src/content/docs/modulos/fft.md`.

## Atualizar

1. Escolher a tag nova e conferir se ainda casa com o CMSIS-Core de `Drivers/CMSIS/Include`.
2. Copiar os mesmos arquivos, sem editar.
3. Rodar os testes no PC (`teste_fft`) e `testes/fft/ciclos/ciclos.py`; conferir o `.map` do firmware.
4. Atualizar a versão e o commit nesta página.
