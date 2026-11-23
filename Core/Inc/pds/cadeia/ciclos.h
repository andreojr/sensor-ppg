/*
 * ciclos.h: média e máximo de ciclos de um trecho de código, sem HAL.
 *
 * Quem mede (o DWT na placa) fica fora daqui: este arquivo só acumula. A cadeia
 * usa sem incluir HAL, e o bancada.h reexporta pra quem já usava.
 */
#ifndef PDS_CADEIA_CICLOS_H
#define PDS_CADEIA_CICLOS_H

#include <stdint.h>

/* Ciclos de um trecho: média e máximo desde o último relato. */
typedef struct {
    uint64_t soma;
    uint32_t max;
    uint32_t conta;
} ciclos_t;

/* dt = fim - inicio em uint32_t: certo mesmo se o contador deu a volta no meio. */
static inline void ciclos_conta(ciclos_t *c, uint32_t dt)
{
    c->soma += dt;
    c->max = dt > c->max ? dt : c->max;
    c->conta++;
}

#endif /* PDS_CADEIA_CICLOS_H */
