/*
 * fila.h: fila de amostras a PPG_FS_HZ entre quem lê o sensor (e decima) e a
 * cadeia. Anel de FILA_TAM posições, sem HAL.
 *
 * Uma leitura da FIFO do MAX30102 traz no máximo 32 amostras cruas e o sensor conta
 * até 31 perdidas (que entram como a última repetida): 63 cruas, até 16 decimadas.
 * Normalmente são 17 cruas = 4 ou 5 decimadas; 16 só no boot, depois das bancadas.
 * Como o laço esvazia a fila a cada leitura, ela nunca enche: o contador cheia é
 * sanidade. A prova de que nada se perdeu são as perdidas do sensor e o intervalo
 * entre leituras (monitor.h).
 */
#ifndef PDS_CADEIA_FILA_H
#define PDS_CADEIA_FILA_H

#include <stdbool.h>
#include <stdint.h>

#include "comum/ppg.h"

#define FILA_TAM 16u

typedef struct {
    ppg_amostra_t a[FILA_TAM];
    uint32_t ini;    /* a mais antiga */
    uint32_t conta;  /* quantas há */
    uint32_t max;    /* maior conta desde fila_zera_medidas() */
    uint32_t cheia;  /* amostras descartadas desde fila_zera_medidas() */
} fila_t;

static inline void fila_init(fila_t *f)
{
    f->ini = f->conta = f->max = f->cheia = 0u;
}

static inline bool fila_poe(fila_t *f, const ppg_amostra_t *a)
{
    if (f->conta == FILA_TAM) {
        f->cheia++;
        return false;
    }
    f->a[(f->ini + f->conta) % FILA_TAM] = *a;
    f->conta++;
    if (f->conta > f->max)
        f->max = f->conta;
    return true;
}

static inline bool fila_tira(fila_t *f, ppg_amostra_t *a)
{
    if (f->conta == 0u)
        return false;
    *a = f->a[f->ini];
    f->ini = (f->ini + 1u) % FILA_TAM;
    f->conta--;
    return true;
}

static inline void fila_zera_medidas(fila_t *f)
{
    f->max = f->conta;
    f->cheia = 0u;
}

#endif /* PDS_CADEIA_FILA_H */
