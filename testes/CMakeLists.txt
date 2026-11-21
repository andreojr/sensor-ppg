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

# Guarda: um arquivo que inclui HAL TEM que falhar ao compilar aqui.
add_executable(guarda_sem_hal EXCLUDE_FROM_ALL guarda/inclui_hal.c)
target_link_libraries(guarda_sem_hal PRIVATE pds)
add_test(NAME guarda_sem_hal
         COMMAND ${CMAKE_COMMAND} --build ${CMAKE_BINARY_DIR} --target guarda_sem_hal)
set_tests_properties(guarda_sem_hal PROPERTIES WILL_FAIL TRUE)
