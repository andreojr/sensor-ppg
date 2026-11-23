/*
 * monitor.h: a régua de tempo (TIM2 a 100 Hz) e as medidas do laço.
 *
 * O sensor marca o passo da cadeia; o TIM2, que conta pelo cristal da placa, só
 * fiscaliza. Cada tique soma 1. A cada 100 tiques (1 s), a placa manda
 *   # laco: amostras X fila_max Y fila_cheia Z perdidas W
 * (amostras oscila de 96 a 104: chegam em lotes de 4 ou 5 a cada 42,5 ms; o resto
 * diz que nada estourou) e a cada 1000 tiques (10 s), os ciclos (DWT) de cada módulo,
 * da cadeia, da volta do laço, o maior intervalo entre leituras da FIFO e a taxa média
 * desde o início do laço:
 *   # taxa: 100.02 amostras/s em 600 s (TIM2)
 * que é o número que prova os 100 Hz (no tempo do sensor; o desvio do oscilador dele
 * aparece aqui).
 */
#ifndef MONITOR_H
#define MONITOR_H

#include <stdint.h>

#include "cadeia/cadeia.h"
#include "cadeia/fila.h"
#include "main.h"

/* Orçamento da cadeia por amostra a 100 Hz, SEM a decimação (medida no sensor.c):
   a soma dos orçamentos dos módulos (filtro 19 200 + picos 9 600 + espectral 9 600 +
   respiração 9 600 + qualidade 3 000). O pior caso cabe num período (960 000). */
#define MONITOR_ORCAMENTO_CADEIA 51000u
#define MONITOR_ORCAMENTO_CADEIA_MAX 960000u
/* A volta do laço tem que caber na folga do sensor depois do INT: 37,5 ms. */
#define MONITOR_ORCAMENTO_VOLTA 3600000u
/* Entre duas leituras da FIFO: 32 amostras a 400 Hz = 80 ms (depois, perde). */
#define MONITOR_LIMITE_LEITURA_MS 80u

/* Liga o DWT e o TIM2 (com interrupção). */
void monitor_init(TIM_HandleTypeDef *htim);

/* Começa a contar do zero: chamar no fim do app_init(), depois das bancadas (que podem
   levar segundos), pra o primeiro relato não vir atrasado. */
void monitor_comeca(void);

/* Do callback do TIM2. */
void monitor_tique(void);

/* Uma amostra saiu da cadeia. */
void monitor_conta_amostra(void);

/* Ciclos de uma volta do laço. */
void monitor_conta_volta(uint32_t ciclos);

/* Uma volta: relata quando passou 1 s (e 10 s) de TIM2. */
void monitor_tarefa(fila_t *fila, cadeia_t *c);

#endif /* MONITOR_H */
