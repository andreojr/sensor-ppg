/*
 * bancada.h: medição de ciclos (DWT) e conferência do PDS na placa.
 *
 * bancada_decimacao() só existe com -DBANCADA_DECIMACAO=ON no CMake: toca a
 * fonte falsa a 400 Hz (o vetor do teste no PC) na decimação, confere com a
 * saída do Python e mede os ciclos. O resultado sai pela serial como
 * comentário ("# bancada ...").
 */
#ifndef BANCADA_H
#define BANCADA_H

#include <stdbool.h>
#include <stdint.h>

#include "main.h"

/* Orçamento da decimação: 1% da CPU por amostra do sensor (96 MHz / 400 Hz / 100). */
#define BANCADA_ORCAMENTO_DECIMACAO 2400u

/* Liga o contador de ciclos do núcleo (DWT->CYCCNT). */
void ciclos_liga(void);

static inline uint32_t ciclos_agora(void)
{
    return DWT->CYCCNT;
}

#ifdef BANCADA_DECIMACAO
/* Roda a fonte falsa na decimação e manda o resultado pela serial. true se passou. */
bool bancada_decimacao(void);
#endif

#endif /* BANCADA_H */
