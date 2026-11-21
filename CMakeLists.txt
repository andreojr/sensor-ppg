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
    ${CMAKE_SOURCE_DIR}/Core/Src/max30102.c
    ${CMAKE_SOURCE_DIR}/Core/Src/serial.c
    ${CMAKE_SOURCE_DIR}/Core/Src/bancada.c
    ${CMAKE_SOURCE_DIR}/Core/Src/bancada_hrv.c
    ${PDS_SOURCES}
    ${CMSIS_DSP_SOURCES}
)

# Bancadas: na partida, tocam a fonte falsa no módulo e conferem com o Python
# (os vetores de testes/<módulo>/). cmake --preset Debug -DBANCADA_FILTRO=ON
option(BANCADA_DECIMACAO "Confere a decimação na placa com a fonte falsa" OFF)
option(BANCADA_FILTRO "Confere o filtro na placa com a fonte falsa" OFF)
if(BANCADA_DECIMACAO)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE BANCADA_DECIMACAO)
endif()
if(BANCADA_FILTRO)
    target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE BANCADA_FILTRO)
endif()
if(BANCADA_DECIMACAO OR BANCADA_FILTRO)
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
