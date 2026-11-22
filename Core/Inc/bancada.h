/*
 * bancada.h: medição de ciclos (DWT) e conferência do PDS na placa.
 *
 * As bancadas só existem com a opção do CMake ligada (-DBANCADA_DECIMACAO=ON,
 * -DBANCADA_FILTRO=ON, -DBANCADA_PICOS=ON, -DBANCADA_ESPECTRAL=ON): tocam a fonte falsa (o vetor do teste no PC) no
 * módulo, conferem com a saída do Python e medem os ciclos. O resultado sai
 * pela serial como comentário ("# bancada ...").
 */
#ifndef BANCADA_H
#define BANCADA_H

#include <stdbool.h>
#include <stdint.h>

#include "main.h"

/* Orçamento da decimação: 1% da CPU por amostra do sensor (96 MHz / 400 Hz / 100). */
#define BANCADA_ORCAMENTO_DECIMACAO 2400u

/* Orçamento do filtro: 2% da CPU por amostra a 100 Hz (96 MHz / 100 Hz * 2 / 100). */
#define BANCADA_ORCAMENTO_FILTRO 19200u

/* Orçamento do picos: 1% da CPU por amostra a 100 Hz (96 MHz / 100 Hz / 100). */
#define BANCADA_ORCAMENTO_PICOS 9600u

/* Orçamento do espectral, em dois números: a MÉDIA por amostra a 100 Hz é 1% da CPU
   (9 600 ciclos), e o PIOR caso (a amostra em que sai a FFT, uma por segundo) tem que
   caber num período de amostra inteiro (96 MHz / 100 Hz = 960 000 ciclos). */
#define BANCADA_ORCAMENTO_ESPECTRAL 9600u
#define BANCADA_ORCAMENTO_ESPECTRAL_MAX 960000u

/* Ciclos de um módulo: média e máximo desde o último relato. */
typedef struct {
    uint64_t soma;
    uint32_t max;
    uint32_t conta;
} ciclos_t;

/* Liga o contador de ciclos do núcleo (DWT->CYCCNT). */
void ciclos_liga(void);

static inline uint32_t ciclos_agora(void)
{
    return DWT->CYCCNT;
}

static inline void ciclos_conta(ciclos_t *c, uint32_t dt)
{
    c->soma += dt;
    c->max = dt > c->max ? dt : c->max;
    c->conta++;
}

/* Manda "# <nome>: ciclos med X max Y (orcamento Z)" pela serial e zera. */
void ciclos_relata(ciclos_t *c, const char *nome, uint32_t orcamento);

/* Igual, pra quem tem um orçamento da média e outro do pior caso (o espectral):
   "# <nome>: ciclos med X (orcamento A) max Y (orcamento B)". */
void ciclos_relata_max(ciclos_t *c, const char *nome, uint32_t orcamento_med,
                       uint32_t orcamento_max);

#ifdef BANCADA_DECIMACAO
/* Roda a fonte falsa na decimação e manda o resultado pela serial. true se passou. */
bool bancada_decimacao(void);
#endif

#ifdef BANCADA_FILTRO
/* Roda o bruto da fonte falsa no filtro e manda o resultado pela serial. true se passou. */
bool bancada_filtro(void);
#endif

#ifdef BANCADA_PICOS
/* Roda o filtrado da fonte falsa no picos e manda o resultado pela serial. true se passou. */
bool bancada_picos(void);
#endif

#ifdef BANCADA_ESPECTRAL
/* Roda o filtrado da fonte falsa no espectral e manda o resultado pela serial. true se passou. */
bool bancada_espectral(void);
#endif

#endif /* BANCADA_H */
