/*
 * hrv.h: variabilidade da frequência cardíaca no tempo (SDNN e RMSSD).
 *
 * Recebe um batimento (ppg_batimento_t) por vez e devolve SDNN e RMSSD dos
 * batimentos dos últimos HRV_JANELA_S segundos. O LF/HF (na frequência) ainda
 * não existe: lf_hf_valido sai sempre false.
 *
 *   SDNN   desvio padrão dos RR da janela (divide por N - 1).
 *   RMSSD  raiz da média dos quadrados das diferenças entre RR seguidos.
 *
 * Regras (as mesmas do protótipo analise/src/analise/hrv.py):
 *  - Um batimento sai da janela quando n_atual - n_pico >= HRV_JANELA_AMOSTRAS.
 *  - Só entra RR com rr_valido e entre HRV_RR_MIN_MS e HRV_RR_MAX_MS. Um RR
 *    rejeitado quebra a sequência: a diferença do RMSSD só existe entre dois
 *    RR aceitos seguidos.
 *  - valido quando os RR aceitos somam pelo menos HRV_COBERTURA_MIN da janela
 *    e há pelo menos HRV_MIN_DIF diferenças.
 *  - Batimento com valido false é ignorado (processa devolve false). Se n_pico
 *    voltar pra trás, o módulo reinicia.
 */
#ifndef PDS_HRV_HRV_H
#define PDS_HRV_HRV_H

#include <stdbool.h>
#include <stdint.h>

#include "comum/ppg.h"

#define HRV_JANELA_S 60u
#define HRV_JANELA_AMOSTRAS (HRV_JANELA_S * PPG_FS_HZ)
#define HRV_CAP 256u           /* cabe a janela a 200 bpm; cheio, sai o mais antigo */
#define HRV_RR_MIN_MS 300.0f   /* 200 bpm */
#define HRV_RR_MAX_MS 2000.0f  /* 30 bpm */
#define HRV_COBERTURA_MIN 0.75f
#define HRV_MIN_DIF 20u

typedef struct {
    /* Fila circular dos RR aceitos na janela, do mais antigo ao mais novo. */
    uint32_t n[HRV_CAP];   /* n_pico do batimento que fechou o RR */
    float rr[HRV_CAP];     /* ms */
    float dif[HRV_CAP];    /* rr - rr anterior, se dif_ok */
    bool dif_ok[HRV_CAP];
    uint32_t inicio;       /* índice do mais antigo */
    uint32_t conta;

    bool tem_n;
    uint32_t ultimo_n;
    bool tem_rr;           /* o último batimento teve RR aceito */
    float rr_anterior;
} hrv_t;

/* Zera o estado. Chamar de novo reinicia. */
void hrv_init(hrv_t *h);

/*
 * Um batimento. Devolve true e escreve *s para todo batimento com valido
 * true; false (e *s intocado) se b->valido for false.
 */
bool hrv_processa(hrv_t *h, const ppg_batimento_t *b, ppg_hrv_t *s);

#endif /* PDS_HRV_HRV_H */
