cmake_minimum_required(VERSION 3.22)

#
# This file is generated only once,
# and is not re-generated if converter is called multiple times.
#
# User is free to modify the file as much as necessary
#

# Setup compiler settings
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)


# Define the build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Debug")
endif()

# Set the project name
set(CMAKE_PROJECT_NAME sensor-ppg)

# Enable compile command to ease indexing with e.g. clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

# Core project settings
project(${CMAKE_PROJECT_NAME})
message("Build type: " ${CMAKE_BUILD_TYPE})

# Enable CMake support for ASM and C languages
enable_language(C ASM)

# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})

# Add STM32CubeMX generated sources
add_subdirectory(cmake/stm32cubemx)

# Link directories setup
target_link_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined library search paths
)

# Módulos de PDS (C puro, sem HAL): Core/Src/pds/<módulo>/*.c
file(GLOB_RECURSE PDS_SOURCES CONFIGURE_DEPENDS ${CMAKE_SOURCE_DIR}/Core/Src/pds/*.c)
# Sem FMA: o C tem que bater com o Python (float32, sem fundir multiplicação e
# soma). Em -Os o GCC funde por padrão (vfma), e aí n_pico/rr_valido podem
# mudar na borda.
set_source_files_properties(${PDS_SOURCES} PROPERTIES COMPILE_OPTIONS -ffp-contract=off)

# CMSIS-DSP: só a FFT real de float32 (v1.16.2), copiada em Drivers/CMSIS/DSP.
# Compilada aqui, sem o pacote do CubeMX (que mexeria no .ioc). A FPU (fpv4-sp-d16,
# hard) já vem do cmake/gcc-arm-none-eabi.cmake, e -ffunction-sections/-fdata-sections
# deixam o linker descartar as tabelas dos tamanhos que o fft.c não usa. É código da
# ARM, então sem avisos (-w).
set(CMSIS_DSP_DIR ${CMAKE_SOURCE_DIR}/Drivers/CMSIS/DSP)
file(GLOB_RECURSE CMSIS_DSP_SOURCES CONFIGURE_DEPENDS ${CMSIS_DSP_DIR}/Source/*.c)
set_source_files_properties(${CMSIS_DSP_SOURCES} PROPERTIES COMPILE_OPTIONS "-w")

# Add sources to executable
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user sources here
    ${CMAKE_SOURCE_DIR}/Core/Src/app.c
    ${CMAKE_SOURCE_DIR}/Core/Src/sensor.c
    ${CMAKE_SOURCE_DIR}/Core/Src/monitor.c
    ${CMAKE_SOURCE_DIR}/Core/Src/max30102.c
    ${CMAKE_SOURCE_DIR}/Core/Src/serial.c
    ${CMAKE_SOURCE_DIR}/Core/Src/bancada.c
    ${CMAKE_SOURCE_DIR}/Core/Src/bancada_hrv.c
    ${CMAKE_SOURCE_DIR}/Core/Src/bancada_qualidade.c
    ${CMAKE_SOURCE_DIR}/Core/Src/bancada_cadeia.c
    ${PDS_SOURCES}
    ${CMSIS_DSP_SOURCES}
)

# Serial completa: além dos resultados e do bruto (b,), as amostras cruas a 400 Hz
# (n,ir,vermelho) e o filtrado (f,), pra conferir contra o Python.
# cmake --preset Debug -DSERIAL_COMPLETA=ON
option(SERIAL_COMPLETA "Manda as cruas e o filtrado pela serial" OFF)
if(SERIAL_COMPLETA)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE SERIAL_COMPLETA)
endif()

# Bancadas: na partida, tocam a fonte falsa no módulo e conferem com o Python
# (os vetores de testes/<módulo>/). cmake --preset Debug -DBANCADA_FILTRO=ON
option(BANCADA_DECIMACAO "Confere a decimação na placa com a fonte falsa" OFF)
option(BANCADA_FILTRO "Confere o filtro na placa com a fonte falsa" OFF)
option(BANCADA_PICOS "Confere o picos na placa com a fonte falsa" OFF)
option(BANCADA_ESPECTRAL "Confere o espectral na placa com a fonte falsa" OFF)
option(BANCADA_RESPIRACAO "Confere a respiração na placa com 5 min do PhysioNet" OFF)
if(BANCADA_DECIMACAO)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE BANCADA_DECIMACAO)
endif()
if(BANCADA_FILTRO)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE BANCADA_FILTRO)
endif()
if(BANCADA_PICOS)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE BANCADA_PICOS)
endif()
if(BANCADA_ESPECTRAL)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE BANCADA_ESPECTRAL)
endif()
if(BANCADA_RESPIRACAO)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE BANCADA_RESPIRACAO)
endif()
if(BANCADA_DECIMACAO OR BANCADA_FILTRO OR BANCADA_PICOS OR BANCADA_ESPECTRAL OR BANCADA_RESPIRACAO)
    target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE ${CMAKE_SOURCE_DIR}/testes)
endif()

# Bancada do HRV: na partida, toca as marcas de batimento da fonte falsa no
# hrv/ e confere com o Python (o vetor de testes/hrv/).
# cmake --preset Debug -DBANCADA_HRV=ON
option(BANCADA_HRV "Confere o HRV na placa com a fonte falsa" OFF)
if(BANCADA_HRV)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE BANCADA_HRV)
    target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE ${CMAKE_SOURCE_DIR}/testes)
endif()

# Bancada da qualidade: na partida, toca o vetor "bordas" na qualidade/ e
# confere com o Python (passo 4); no laço, uma linha "q,..." por segundo com a
# qualidade do bruto do sensor (passo 5).
# cmake --preset Debug -DBANCADA_QUALIDADE=ON
option(BANCADA_QUALIDADE "Confere a qualidade na placa e manda a do sensor pela serial" OFF)
if(BANCADA_QUALIDADE)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE BANCADA_QUALIDADE)
    target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE ${CMAKE_SOURCE_DIR}/testes)
endif()

# Bancada da cadeia: na partida, passa os 90 s do vetor do PhysioNet pela cadeia
# inteira, confere com o Python e mede os ciclos (testes/cadeia/).
# cmake --preset Debug -DBANCADA_CADEIA=ON
option(BANCADA_CADEIA "Confere a cadeia inteira na placa com o vetor do PhysioNet" OFF)
if(BANCADA_CADEIA)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE BANCADA_CADEIA)
    target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE ${CMAKE_SOURCE_DIR}/testes)
endif()

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined include paths
    ${CMAKE_SOURCE_DIR}/Core/Inc/pds
    ${CMSIS_DSP_DIR}/Include
)

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    # Add user defined symbols
    ARM_MATH_CM4
)

# Remove wrong libob.a library dependency when using cpp files
list(REMOVE_ITEM CMAKE_C_IMPLICIT_LINK_LIBRARIES ob)

# Add linked libraries
target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx

    # Add user defined libraries
)
