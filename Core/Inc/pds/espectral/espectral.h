/*
 * espectral: BPM pelo pico da FFT, em janela deslizante.
 *
 * Porte de analise/src/analise/espectral.py (o Python é a referência: os vetores
 * de teste saem dele). Sem HAL, sem malloc, sem global.
 *
 * Entrada: filtrado (ppg.h), uma amostra por vez, usando o canal ir.
 * Saída: um ppg_bpm_t a cada ESPECTRAL_HOP_S, com a janela cheia.
 *
 * A cada passo: janela das últimas 8 s, menos a média, janela de Hann, FFT de
 * 1024 pontos (zero-padding), maior pico na banda de 0,7 a 3,5 Hz (42 a 210 bpm)
 * e interpolação parabólica pra achar a frequência entre dois bins. Só vale
 * (valido) se o pico e os dois vizinhos têm 30% ou mais da potência da banda.
 *
 * A FFT é a do módulo fft/ (CMSIS-DSP), que precisa do tamanho 1024 compilado
 * (o padrão).
 */
#ifndef PDS_ESPECTRAL_ESPECTRAL_H
#define PDS_ESPECTRAL_ESPECTRAL_H

#include <stdbool.h>
#include <stdint.h>

#include "comum/ppg.h"
#include "fft/fft.h"

#define ESPECTRAL_JANELA (8u * PPG_FS_HZ) /* 8 s: 800 amostras */
#define ESPECTRAL_HOP (1u * PPG_FS_HZ)    /* uma saída por segundo */
#define ESPECTRAL_NFFT 1024u              /* tamanho da FFT (>= ESPECTRAL_JANELA) */

/* ~15 KB (a janela, a janela de Hann e as duas áreas da FFT): aloque fora da pilha. */
typedef struct {
    fft_t fft;
    uint32_t idx;    /* onde entra a próxima amostra do buffer circular */
    uint32_t faltam; /* amostras até a próxima saída */
    float prominencia;
    float buffer[ESPECTRAL_JANELA]; /* circular */
    float hann[ESPECTRAL_JANELA];
    float x[ESPECTRAL_NFFT];        /* janela, depois o espectro de potência */
    float trabalho[ESPECTRAL_NFFT]; /* área de trabalho da FFT */
} espectral_t;

/* Zera o estado e prepara a FFT; chamar de novo reinicia. false se a FFT de 1024 não está compilada. */
bool espectral_init(espectral_t *e);

/*
 * Processa uma amostra filtrada. Devolve true e preenche *saida a cada
 * ESPECTRAL_HOP amostras, depois de a janela encher (a primeira saída vem na
 * amostra 800); senão devolve false e não toca em *saida. Com valido = false o
 * bpm sai 0, como no picos_bpm(). O BPM é o da janela que termina em filtrado->n;
 * no tempo do sinal, essa janela termina PPG_ATRASO_AMOSTRAS antes.
 */
bool espectral_processa(espectral_t *e, const ppg_amostra_t *filtrado, ppg_bpm_t *saida);

/* Fração da potência da banda que ficou no pico e nos vizinhos, na última saída (0 a 1;
   na borda, o vizinho de fora da banda entra no total). */
float espectral_prominencia(const espectral_t *e);

#endif /* PDS_ESPECTRAL_ESPECTRAL_H */
