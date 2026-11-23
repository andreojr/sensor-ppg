/*
 * sensor.h: a tarefa do sensor no laço principal.
 *
 * O INT do MAX30102 (EXTI no PB5) só levanta uma bandeira (sensor_int). A
 * sensor_tarefa(), chamada a cada volta do laço, lê a FIFO quando a bandeira está
 * levantada (ou o PB5 está baixo), decima pra PPG_FS_HZ e põe o bruto na fila da
 * cadeia. Amostras perdidas pelo sensor (FIFO cheia) viram a última amostra
 * repetida, pro n seguir o tempo do sensor.
 */
#ifndef SENSOR_H
#define SENSOR_H

#include <stdint.h>

#include "cadeia/ciclos.h"
#include "cadeia/fila.h"
#include "main.h"

/* O que o monitor relata e zera. */
typedef struct {
    uint32_t perdidas;         /* amostras que o sensor descartou (FIFO cheia) */
    uint32_t maior_intervalo;  /* ciclos entre duas leituras da FIFO, o maior */
    ciclos_t decimacao;        /* por amostra do sensor */
} sensor_medidas_t;

/* Liga o sensor e a decimação; se falhar, avisa na serial e para (Error_Handler). */
void sensor_init(I2C_HandleTypeDef *hi2c, fila_t *fila);

/* Do callback do EXTI: tem amostra na FIFO. */
void sensor_int(void);

/* Uma volta: lê a FIFO se o sensor avisou. */
void sensor_tarefa(void);

sensor_medidas_t *sensor_medidas(void);

#endif /* SENSOR_H */
