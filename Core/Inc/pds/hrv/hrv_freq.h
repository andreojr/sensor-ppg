/*
 * hrv_freq.h: variabilidade da frequência cardíaca na frequência (LF/HF).
 *
 * Recebe um batimento (ppg_batimento_t) por vez e devolve a razão LF/HF dos
 * RR dos últimos HRV_FREQ_JANELA_S segundos. Preenche só os campos
 * lf_hf_valido e lf_hf de ppg_hrv_t: chame DEPOIS de hrv_processa(), que
 * escreve lf_hf_valido = false.
 *
 *   LF  potência entre 0,04 e 0,15 Hz (períodos de 7 a 25 s)
 *   HF  potência entre 0,15 e 0,40 Hz (a respiração)
 *
 * A conta (a mesma do protótipo analise/src/analise/hrv_freq.py):
 *  1. os RR aceitos da janela, cada um no instante do batimento que o fecha;
 *  2. spline cúbica natural por esses pontos, reamostrada a
 *     HRV_FREQ_FS_REAMOSTRA Hz (amostras regulares);
 *  3. tira a reta (tendência linear) e aplica a janela de Hann;
 *  4. hrv_freq_potencias(): DFT nas frequências k / HRV_FREQ_JANELA_S das
 *     bandas (Goertzel), soma |X|² em cada banda. LF/HF = LF / HF.
 *
 * Regras dos batimentos (as mesmas do HRV no tempo, hrv.h): só RR com
 * rr_valido e entre HRV_RR_MIN_MS e HRV_RR_MAX_MS; janela pelo n_pico;
 * batimento com valido false é ignorado; n_pico voltando reinicia. A mais:
 * um RR cujo instante não anda pra frente (mesmo n_pico e fracao do último
 * guardado) não entra, porque a spline não aceita dois pontos no mesmo instante.
 * lf_hf_valido quando os RR aceitos somam HRV_FREQ_COBERTURA_MIN da janela
 * (270 s: é o atraso até o primeiro valor).
 *
 * Uma janela de 5 min é o padrão. Janelas curtas dão LF/HF que muda muito
 * (60 s: fator típico de 1,8 contra o de 5 min). Ver docs/.../modulos/hrv.md.
 */
#ifndef PDS_HRV_HRV_FREQ_H
#define PDS_HRV_HRV_FREQ_H

#include <stdbool.h>
#include <stdint.h>

#include "comum/ppg.h"
#include "hrv/hrv.h"

#define HRV_FREQ_JANELA_S 300u
#define HRV_FREQ_JANELA_AMOSTRAS (HRV_FREQ_JANELA_S * PPG_FS_HZ)
#define HRV_FREQ_FS_REAMOSTRA 2u /* Hz; 4 Hz dá o mesmo LF/HF (medido) */
#define HRV_FREQ_CAP 600u        /* 300 s até 120 bpm de média; cheio, sai o mais antigo */
#define HRV_FREQ_N_MAX (HRV_FREQ_JANELA_S * HRV_FREQ_FS_REAMOSTRA + 1u)
#define HRV_FREQ_COBERTURA_MIN 0.9f
#define HRV_FREQ_MIN_RR 4u

/* Bandas em índices k da grade f = k / HRV_FREQ_JANELA_S. */
#define HRV_FREQ_K_LF (4u * HRV_FREQ_JANELA_S / 100u)   /* 12:  0,04 Hz */
#define HRV_FREQ_K_HF (15u * HRV_FREQ_JANELA_S / 100u)  /* 45:  0,15 Hz (LF vai até 44) */
#define HRV_FREQ_K_FIM (40u * HRV_FREQ_JANELA_S / 100u) /* 120: 0,40 Hz, inclusive */

typedef struct {
    /* RR aceitos na janela, do mais antigo ao mais novo (contíguos). */
    uint32_t n[HRV_FREQ_CAP]; /* n_pico do batimento que fechou o RR */
    float fracao[HRV_FREQ_CAP];
    float rr[HRV_FREQ_CAP];   /* ms */
    uint32_t conta;

    bool tem_n;
    uint32_t ultimo_n;

    /* Área de trabalho da conta (não é estado: fica aqui pra não ir à pilha). */
    float t[HRV_FREQ_CAP];  /* instante relativo ao primeiro, s */
    float m[HRV_FREQ_CAP];  /* segunda derivada da spline */
    float aux[HRV_FREQ_CAP]; /* RR menos a média */
    float y[HRV_FREQ_N_MAX]; /* série reamostrada (antes, rascunho da spline) */
} hrv_freq_t;

/* Zera o estado. Chamar de novo reinicia. */
void hrv_freq_init(hrv_freq_t *h);

/*
 * Um batimento. Devolve true e escreve s->lf_hf_valido e s->lf_hf para todo
 * batimento com valido true (os outros campos de *s ficam como estão);
 * false (e *s intocado) se b->valido for false.
 */
bool hrv_freq_processa(hrv_freq_t *h, const ppg_batimento_t *b, ppg_hrv_t *s);

/*
 * A conta do espectro, separada pra poder trocar por FFT depois: potência
 * nas bandas LF (k de HRV_FREQ_K_LF a HRV_FREQ_K_HF - 1) e HF (de
 * HRV_FREQ_K_HF a HRV_FREQ_K_FIM) de y[0..n-1], amostrado a
 * HRV_FREQ_FS_REAMOSTRA Hz. Cada potência é a soma de |X(f_k)|², com
 * X(f) = soma de y[j] e^{-i 2π f j / fs}.
 */
void hrv_freq_potencias(const float *y, uint32_t n, float *lf, float *hf);

#endif /* PDS_HRV_HRV_FREQ_H */
