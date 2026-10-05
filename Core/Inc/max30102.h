/*
 * max30102.h: leitura do MAX30102 pela I2C, com a FIFO do sensor.
 *
 * Modo SpO2 (vermelho + IR) a MAX30102_FS_HZ, 18 bits, sem média no sensor.
 * O INT (PB5) desce quando a FIFO chega a 17 amostras; quem trata o INT chama
 * max30102_le_fifo(), que esvazia a FIFO e solta o INT.
 */
#ifndef MAX30102_H
#define MAX30102_H

#include <stdint.h>

#include "main.h"

/* Taxa de amostragem do sensor, em Hz (antes da decimação pra PPG_FS_HZ). */
#define MAX30102_FS_HZ 400u

/* Tamanho da FIFO do sensor, em amostras. */
#define MAX30102_FIFO_TAM 32u

/* Uma amostra crua dos dois canais: contagens do ADC, 18 bits, com DC. */
typedef struct {
    uint32_t ir;
    uint32_t vermelho;
} max30102_amostra_t;

/* Reseta e configura o sensor. HAL_ERROR se o sensor não responder. */
HAL_StatusTypeDef max30102_init(I2C_HandleTypeDef *hi2c);

/*
 * Lê todas as amostras que estão na FIFO (no máximo MAX30102_FIFO_TAM).
 * *n recebe quantas foram lidas; *perdidas, quantas o sensor descartou por
 * FIFO cheia desde a última leitura (0 se ninguém atrasou).
 */
HAL_StatusTypeDef max30102_le_fifo(max30102_amostra_t amostras[MAX30102_FIFO_TAM],
                                   uint32_t *n, uint32_t *perdidas);

#endif /* MAX30102_H */
