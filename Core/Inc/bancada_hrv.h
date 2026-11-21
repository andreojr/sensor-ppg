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
 * testes/hrv/vetores/freq_s1_sit.h), em linhas "# bancada lf/hf ...".
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
 * Orçamento do LF/HF por batimento: 2 000 000 ciclos (~21 ms a 96 MHz). A conta
 * inteira (spline, Hann e 109 frequências de Goertzel em ~600 amostras) roda a
 * cada batimento: ~65 mil iterações do Goertzel. A 75 bpm, ~2,6% da CPU. É
 * uma estimativa: a bancada mede.
 */
#define BANCADA_ORCAMENTO_HRV_FREQ 2000000u

#ifdef BANCADA_HRV
/* Roda a fonte falsa no HRV e manda o resultado pela serial. true se passou. */
bool bancada_hrv(void);
#endif

#ifdef BANCADA_HRV_FREQ
/* Roda a fonte falsa no LF/HF e manda o resultado pela serial. true se passou. */
bool bancada_hrv_freq(void);
#endif

#endif /* BANCADA_HRV_H */
