/*
 * app.h: a aplicação, um superloop com tarefas cooperativas (#17).
 *
 * O main.c (CubeMX) liga o hardware e chama app_init() uma vez e app_laco() pra
 * sempre. Cada volta do laço chama as tarefas em ordem; cada uma faz pouco e
 * devolve o controle (nenhuma espera nada):
 *
 *   sensor_tarefa()   o INT avisou: lê a FIFO, decima, põe o bruto na fila
 *   cadeia            esvazia a fila: cadeia_processa(), linhas na serial,
 *                     a onda pro display
 *   display           uma página (~3 ms) com a ficha (ppg_resultados_t)
 *   monitor_tarefa()  a cada 1 s de TIM2: taxa, fila, perdidas; a cada 10 s, ciclos
 *   serial_envia()    despacha o buffer por DMA
 *
 * O sensor marca o passo (relógio próprio, 400 Hz); o TIM2 só fiscaliza.
 */
#ifndef APP_H
#define APP_H

#include <stdbool.h>

#include "main.h"

/* -DSERIAL_COMPLETA=ON no CMake: as cruas (400 Hz) e o filtrado também saem. */
#ifdef SERIAL_COMPLETA
#define APP_SERIAL_COMPLETA true
#else
#define APP_SERIAL_COMPLETA false
#endif

void app_init(I2C_HandleTypeDef *sensor, I2C_HandleTypeDef *display, UART_HandleTypeDef *serial,
              TIM_HandleTypeDef *regua);

void app_laco(void);

#endif /* APP_H */
