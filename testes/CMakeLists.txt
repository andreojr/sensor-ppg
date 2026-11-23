# Testes do PDS no PC (gcc nativo, sem placa).
# Compila Core/Src/pds/ enxergando SÓ Core/Inc/pds/: se um módulo incluir HAL
# ou main.h, a compilação quebra.
#
#   cmake -S testes -B build/testes && cmake --build build/testes
#   ctest --test-dir build/testes --output-on-failure
cmake_minimum_required(VERSION 3.22)
project(pds_testes C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
add_compile_options(-Wall -Wextra -Werror)

set(RAIZ ${CMAKE_CURRENT_SOURCE_DIR}/..)
set(PDS_INC ${RAIZ}/Core/Inc/pds)

file(GLOB_RECURSE PDS_SOURCES CONFIGURE_DEPENDS ${RAIZ}/Core/Src/pds/*.c)
add_library(pds STATIC ${PDS_SOURCES} ${CMAKE_CURRENT_SOURCE_DIR}/vazio.c)
target_include_directories(pds PUBLIC ${PDS_INC})
target_link_libraries(pds PUBLIC m)

# CMSIS-DSP (só a FFT real de float32, Drivers/CMSIS/DSP): o mesmo código da
# placa, rodando no PC. __GNUC_PYTHON__ é o modo "host" do arm_math_types.h (sem
# o cmsis_compiler.h, que usa instruções do ARM). É código da ARM, então sem
# avisos (-w); os do nosso fft.c continuam valendo. Só o pds enxerga o CMSIS
# (PRIVATE): quem usa a FFT inclui "fft/fft.h", nunca um cabeçalho do CMSIS.
set(DSP_DIR ${RAIZ}/Drivers/CMSIS/DSP)
file(GLOB_RECURSE DSP_SOURCES CONFIGURE_DEPENDS ${DSP_DIR}/Source/*.c)
add_library(cmsis_dsp STATIC ${DSP_SOURCES})
target_include_directories(cmsis_dsp PUBLIC ${DSP_DIR}/Include)
target_compile_definitions(cmsis_dsp PUBLIC __GNUC_PYTHON__)
target_compile_options(cmsis_dsp PRIVATE -w)
target_link_libraries(pds PRIVATE cmsis_dsp)

enable_testing()

# Um executável por arquivo testes/<módulo>/teste_*.c
file(GLOB_RECURSE TESTES CONFIGURE_DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/*/teste_*.c)
list(FILTER TESTES EXCLUDE REGEX "/guarda/")
foreach(arquivo ${TESTES})
    get_filename_component(nome ${arquivo} NAME_WE)
    add_executable(${nome} ${arquivo})
    target_link_libraries(${nome} PRIVATE pds)
    # confere.h; os vetores (vetores/<caso>.h) vêm da pasta do próprio teste.
    target_include_directories(${nome} PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    add_test(NAME ${nome} COMMAND ${nome})
endforeach()

# Replay: as cruas de uma captura de novo pela cadeia (testes/cadeia/replay.h).
add_executable(replay_cadeia cadeia/replay_cadeia.c)
target_link_libraries(replay_cadeia PRIVATE pds)
target_include_directories(replay_cadeia PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# Guarda: um arquivo que inclui HAL TEM que falhar ao compilar aqui.
add_executable(guarda_sem_hal EXCLUDE_FROM_ALL guarda/inclui_hal.c)
target_link_libraries(guarda_sem_hal PRIVATE pds)
add_test(NAME guarda_sem_hal
         COMMAND ${CMAKE_COMMAND} --build ${CMAKE_BINARY_DIR} --target guarda_sem_hal)
set_tests_properties(guarda_sem_hal PROPERTIES WILL_FAIL TRUE)
