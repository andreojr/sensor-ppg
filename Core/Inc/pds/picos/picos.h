/*
 * picos: batimentos e BPM a partir do PPG filtrado.
 *
 * Porte linha a linha de analise/src/analise/picos.py (o Python é a
 * referência: os vetores de teste saem dele). Sem HAL, sem malloc, sem global.
 *
 * Entrada: filtrado (ppg.h), uma amostra por vez, usando o canal ir.
 * Saída: um ppg_batimento_t quando a amostra fecha um pico, e o BPM sobre os
 * últimos intervalos válidos (picos_bpm).
 */
#ifndef PDS_PICOS_PICOS_H
#define PDS_PICOS_PICOS_H

#include <stdbool.h>
#include <stdint.h>

#include "comum/ppg.h"

#define PICOS_BPM_JANELA 8u /* BPM = média dos últimos 8 RR válidos */

typedef struct {
    uint32_t n;            /* amostras recebidas */
    float x1;              /* x[n-1] */
    float x2;              /* x[n-2] */
    float env;             /* envelope de pico, com decaimento */
    bool tem_ultimo;       /* já houve um batimento */
    uint32_t ultimo_n;     /* n_pico do último batimento */
    uint32_t ultimo_base;  /* n da entrada (sem descontar o atraso) do último batimento */
    float ultimo_fracao;   /* fracao do último batimento */
    float rr_tipico;       /* 0 = ainda não conhece */
    float rrs[PICOS_BPM_JANELA]; /* últimos RR válidos, do mais antigo ao mais novo */
    uint8_t n_rrs;
} picos_t;

/* Zera o estado; chamar de novo reinicia. */
void picos_init(picos_t *p);

/*
 * Processa uma amostra filtrada. Devolve true e preenche *saida (valido = true)
 * quando esta amostra fechou um pico; senão devolve false e não toca em *saida.
 * O pico é visto com 1 amostra de atraso (precisa da amostra seguinte).
 */
bool picos_processa(picos_t *p, const ppg_amostra_t *filtrado, ppg_batimento_t *saida);

/* BPM sobre os últimos RR válidos; valido = false até haver RR suficientes. */
void picos_bpm(const picos_t *p, ppg_bpm_t *saida);

#endif /* PDS_PICOS_PICOS_H */
