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
#define PICOS_REG_JANELA 8u /* batimentos que o teste de regularidade olha */

typedef struct {
    uint32_t n;            /* amostras recebidas */
    float x1;              /* x[n-1] */
    float x2;              /* x[n-2] */
    float env;             /* envelope de pico, com decaimento */
    bool tem_ultimo;       /* já houve um batimento */
    uint32_t ultimo_n;     /* n_pico do último batimento */
    uint32_t ultimo_base;  /* n da entrada (sem descontar o atraso) do último batimento */
    float ultimo_fracao;   /* fracao do último batimento */
    bool tem_pendente;     /* candidato esperando o refratário passar */
    uint32_t pend_base;    /* n da entrada do candidato */
    uint32_t pend_n_pico;  /* n_pico do candidato, já descontado o atraso */
    float pend_fracao;
    float pend_altura;     /* um candidato maior dentro do refratário toma o lugar */
    float rr_tipico;       /* 0 = ainda não conhece */
    float rrs[PICOS_BPM_JANELA]; /* últimos RR válidos, do mais antigo ao mais novo */
    uint8_t n_rrs;
    bool hist_valido[PICOS_REG_JANELA]; /* rr_valido dos últimos batimentos, do mais antigo ao mais novo */
    float hist_rr[PICOS_REG_JANELA];    /* e o rr_ms de cada um */
    uint8_t n_hist;                     /* quantos há, até PICOS_REG_JANELA */
} picos_t;

/* Zera o estado; chamar de novo reinicia. */
void picos_init(picos_t *p);

/*
 * Processa uma amostra filtrada. Devolve true e preenche *saida (valido = true)
 * quando esta amostra fechou um batimento; senão devolve false e não toca em
 * *saida.
 *
 * O batimento sai com atraso: o pico só é visto com 1 amostra de atraso, e
 * depois fica pendente pelo período refratário (0,3 s), porque um pico maior
 * nesse intervalo toma o lugar dele (a corcova do FIR antes do batimento não
 * pode bloquear o pico verdadeiro). n_pico continua sendo o do pico.
 */
bool picos_processa(picos_t *p, const ppg_amostra_t *filtrado, ppg_batimento_t *saida);

/*
 * BPM sobre os últimos RR válidos. valido = há RR válidos suficientes E o ritmo é regular: nos últimos
 * 8 batimentos, pelo menos 6 são "bons" (RR válido e a menos de 15% da mediana dos RR válidos). Sinal sem
 * pulso (dedo mal apoiado) gera "batimentos" com RR de 300 a 1500 ms que passam um a um pelo rr_valido mas
 * não formam um ritmo: com isso o valido fica false. Com arritmia de verdade o valido também desliga.
 */
void picos_bpm(const picos_t *p, ppg_bpm_t *saida);

#endif /* PDS_PICOS_PICOS_H */
