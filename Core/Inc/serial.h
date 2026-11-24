/*
 * serial.h: envio pro PC pela USART1 com DMA, sem travar a CPU.
 *
 * Buffer duplo: o laço principal escreve num buffer enquanto o DMA envia o
 * outro. serial_escreve() e serial_envia() só podem ser chamadas do laço
 * principal, nunca de interrupção.
 */
#ifndef SERIAL_H
#define SERIAL_H

#include <stdbool.h>
#include <stdint.h>

#include "main.h"

void serial_init(UART_HandleTypeDef *huart);

/* Copia pro buffer. false se não couber (os dados são descartados). */
bool serial_escreve(const char *dados, uint32_t n);

/* true se n bytes cabem e ainda sobram "reserva" bytes livres (pra quem tem prioridade). */
bool serial_cabe(uint32_t n, uint32_t reserva);

/* Começa o envio do que está no buffer, se o DMA estiver livre. */
void serial_envia(void);

#endif /* SERIAL_H */
