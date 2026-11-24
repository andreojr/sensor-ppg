/*
 * bancada_hrv.h: confere o HRV na placa com a fonte falsa (passo 4).
 *
 * Só existe com -DBANCADA_HRV=ON no CMake. Na partida, toca as marcas de
 * batimento do ECG de s1_sit (o mesmo vetor do teste no PC,
 * testes/hrv/vetores/s1_sit.h) no hrv_processa(), confere com a saída do
 * Python e mede os ciclos por batimento. O resultado sai pela serial como
 * comentário ("# bancada hrv ...").
 *
 * Com -DBANCADA_HRV_FREQ=ON, o mesmo para o LF/HF (hrv_freq_processa(), vetor
 * testes/hrv/vetores/freq_s1_sit.h), em linhas "# bancada lf/hf ...". A cada
 * BANCADA_HRV_FREQ_CADA batimentos, a mesma conta também é feita espalhada
 * (hrv_freq_comeca() e os HRV_FREQ_PASSOS hrv_freq_passo(), como na cadeia):
 * confere que dá o mesmo número e mede o pior passo. Depois, só o
 * hrv_freq_guarda() (o que a cadeia faz a cada batimento), com o pior caso
 * separado do batimento em que a janela está cheia.
 */
#ifndef BANCADA_HRV_H
#define BANCADA_HRV_H

#include <stdbool.h>

/*
 * Orçamento por batimento: 20000 ciclos (~0,2 ms a 96 MHz). A 200 bpm são
 * 3,3 batimentos/s, ou seja, menos de 0,1% da CPU.
 */
#define BANCADA_ORCAMENTO_HRV 20000u

/*
 * Orçamentos do LF/HF, por perfil (o Release é -Os, que define __OPTIMIZE__; o
 * Debug é -O0).
 *
 * A conta inteira (hrv_freq_processa: spline, Hann e 109 frequências de Goertzel
 * em ~600 amostras, ~65 mil iterações) medida na placa em 23/11/2026, 613
 * batimentos de s1_sit: pior batimento 1 284 715 ciclos em Release (13,4 ms) e
 * 2 985 443 em Debug (31 ms). O orçamento é essa medida com folga de ~15%. Na
 * cadeia ela não roda assim: vai espalhada.
 *
 * O pior passo da conta espalhada (hrv_freq_passo, um por amostra na cadeia, ou o
 * hrv_freq_comeca): 8 das 109 frequências, ~7% da conta inteira. Estimativa: ~200
 * mil ciclos em Debug (~2 ms) e ~90 mil em Release; o orçamento é 1/3 de um
 * período de amostra em Debug (3,3 ms) e metade disso em Release.
 */
#ifdef __OPTIMIZE__
#define BANCADA_ORCAMENTO_HRV_FREQ 1500000u
#define BANCADA_ORCAMENTO_HRV_FREQ_PASSO 160000u
#else
#define BANCADA_ORCAMENTO_HRV_FREQ 3400000u
#define BANCADA_ORCAMENTO_HRV_FREQ_PASSO 320000u
#endif
/*
 * O pior hrv_freq_guarda (o que a cadeia faz a cada batimento, dentro da medida
 * "hrv", junto do hrv_processa, que tem 20 000): com a fila circular, nenhum
 * vetor é movido, só se escreve o RR e se anda o início. Estimativa: algumas
 * centenas de ciclos em Debug; o orçamento é 10% do do HRV.
 */
#define BANCADA_ORCAMENTO_HRV_FREQ_GUARDA 2000u
/* Média por amostra na cadeia (uma conta a cada 500 amostras): 1% da CPU. */
#define BANCADA_ORCAMENTO_HRV_FREQ_MED 9600u
/* De quantos em quantos batimentos a bancada confere a conta espalhada. */
#define BANCADA_HRV_FREQ_CADA 10u

#ifdef BANCADA_HRV
/* Roda a fonte falsa no HRV e manda o resultado pela serial. true se passou. */
bool bancada_hrv(void);
#endif

#ifdef BANCADA_HRV_FREQ
/* Roda a fonte falsa no LF/HF e manda o resultado pela serial. true se passou. */
bool bancada_hrv_freq(void);
#endif

#endif /* BANCADA_HRV_H */
