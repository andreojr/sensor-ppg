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
 * Duas formas de usar:
 *  - hrv_freq_processa(): guarda o batimento e faz a conta inteira na hora
 *    (13,4 ms no pior caso em Release, 31 ms em Debug, medidos na placa);
 *  - hrv_freq_guarda() a cada batimento (custo constante: fila circular, sem
 *    mover vetores) e, quando quiser um valor,
 *    hrv_freq_comeca() seguido de HRV_FREQ_PASSOS chamadas de hrv_freq_passo(),
 *    uma por amostra: a mesma conta, em pedaços (é o que a cadeia usa).
 * As duas dão exatamente o mesmo número: processa() é guarda() + comeca() +
 * os passos todos de uma vez.
 *
 * A janela é a dos HRV_FREQ_JANELA_S segundos que terminam no ÚLTIMO BATIMENTO
 * GUARDADO (com valido true), não no n atual: comeca() calcula sobre o que já
 * está guardado. Sem batimentos novos, a janela não anda (como no HRV no tempo)
 * e o último valor continua válido: não há prazo de validade.
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
/* Não há mínimo de RR à parte: 270 s de RR de até HRV_RR_MAX_MS (2000 ms) já são
   pelo menos 135 pontos na spline. */
#define HRV_FREQ_COBERTURA_MIN 0.9f

/* Bandas em índices k da grade f = k / HRV_FREQ_JANELA_S. */
#define HRV_FREQ_K_LF (4u * HRV_FREQ_JANELA_S / 100u)   /* 12:  0,04 Hz */
#define HRV_FREQ_K_HF (15u * HRV_FREQ_JANELA_S / 100u)  /* 45:  0,15 Hz (LF vai até 44) */
#define HRV_FREQ_K_FIM (40u * HRV_FREQ_JANELA_S / 100u) /* 120: 0,40 Hz, inclusive */

/* A conta espalhada: 3 passos (spline; reamostragem; reta e Hann) e as 109
   frequências do Goertzel, HRV_FREQ_K_POR_PASSO por passo. */
#define HRV_FREQ_K_POR_PASSO 8u
#define HRV_FREQ_PASSOS_GOERTZEL                                                            \
    ((HRV_FREQ_K_FIM - HRV_FREQ_K_LF + HRV_FREQ_K_POR_PASSO) / HRV_FREQ_K_POR_PASSO) /* 14 */
#define HRV_FREQ_PASSOS (3u + HRV_FREQ_PASSOS_GOERTZEL) /* 17 */

typedef struct {
    /* Fila circular dos RR aceitos na janela, do mais antigo ao mais novo (como
       no hrv_t): guardar e tirar não movem os outros. */
    uint32_t n[HRV_FREQ_CAP]; /* n_pico do batimento que fechou o RR */
    float fracao[HRV_FREQ_CAP];
    float rr[HRV_FREQ_CAP];   /* ms */
    uint32_t inicio;          /* índice do mais antigo */
    uint32_t conta;

    bool tem_n;
    uint32_t ultimo_n;

    /* A conta em andamento (hrv_freq_comeca / hrv_freq_passo). */
    uint32_t etapa;   /* 0: parada; 1 a HRV_FREQ_PASSOS: o próximo passo */
    bool cobre;       /* a janela tinha RR o bastante (senão os passos não fazem nada) */
    uint32_t pontos;  /* RR copiados pra t[] e aux[] */
    uint32_t amostras; /* tamanho da série reamostrada */
    uint32_t k;       /* próxima frequência do Goertzel */
    float soma_lf, soma_hf;

    /* Área de trabalho da conta: uma cópia da janela no hrv_freq_comeca(), já
       desembrulhada (do mais antigo ao mais novo, a partir do 0), pra os
       batimentos guardados no meio da conta não mexerem nela. */
    float t[HRV_FREQ_CAP];  /* instante relativo ao primeiro, s */
    float m[HRV_FREQ_CAP];  /* segunda derivada da spline */
    float aux[HRV_FREQ_CAP]; /* RR menos a média */
    float y[HRV_FREQ_N_MAX]; /* série reamostrada (antes, rascunho da spline) */
} hrv_freq_t;

/* Zera o estado (e larga uma conta em andamento). Chamar de novo reinicia. */
void hrv_freq_init(hrv_freq_t *h);

/*
 * Um batimento, com a conta inteira. Devolve true e escreve s->lf_hf_valido e
 * s->lf_hf para todo batimento com valido true (os outros campos de *s ficam
 * como estão); false (e *s intocado) se b->valido for false. Usa a mesma área
 * de trabalho da conta espalhada: não chame no meio de uma.
 */
bool hrv_freq_processa(hrv_freq_t *h, const ppg_batimento_t *b, ppg_hrv_t *s);

/*
 * Só guarda o batimento (as regras acima), sem conta: escreve o RR na fila
 * circular e anda o início pelos que saíram da janela. Nenhum vetor é movido:
 * o custo é constante por RR que entra ou sai (e cada RR sai uma vez só). A
 * exceção é um n_pico voltando, que zera o hrv_freq_t inteiro (~16 KiB). false
 * (e nada muda) se b->valido for false. Pode ser chamada no meio de uma conta
 * espalhada: a conta usa a cópia que o hrv_freq_comeca() fez. Um n_pico
 * voltando reinicia tudo, e a conta em andamento é largada (não sai resultado).
 */
bool hrv_freq_guarda(hrv_freq_t *h, const ppg_batimento_t *b);

/*
 * Começa uma conta sobre a janela guardada agora (a que termina no último
 * batimento guardado): confere a cobertura e copia os instantes e os RR. Custa
 * 4 passadas nos RR (a soma da cobertura; na cópia, os instantes, a média e os
 * RR menos a média). Se já havia uma conta em andamento, recomeça.
 */
void hrv_freq_comeca(hrv_freq_t *h);

/*
 * Um pedaço da conta. Na HRV_FREQ_PASSOS-ésima chamada depois do
 * hrv_freq_comeca(), escreve s->lf_hf_valido e s->lf_hf (o mesmo que
 * hrv_freq_processa() daria no último batimento guardado) e devolve true; nas
 * outras (e sem conta em andamento), false e *s intocado. Sempre o mesmo número
 * de passos, mesmo quando a janela não cobre (aí os passos não fazem nada e sai
 * lf_hf_valido false): o resultado sai numa amostra previsível.
 */
bool hrv_freq_passo(hrv_freq_t *h, ppg_hrv_t *s);

/* true entre o hrv_freq_comeca() e o passo que solta o resultado. */
bool hrv_freq_calculando(const hrv_freq_t *h);

/*
 * A conta do espectro, separada pra poder trocar por FFT depois: potência
 * nas bandas LF (k de HRV_FREQ_K_LF a HRV_FREQ_K_HF - 1) e HF (de
 * HRV_FREQ_K_HF a HRV_FREQ_K_FIM) de y[0..n-1], amostrado a
 * HRV_FREQ_FS_REAMOSTRA Hz. Cada potência é a soma de |X(f_k)|², com
 * X(f) = soma de y[j] e^{-i 2π f j / fs}.
 */
void hrv_freq_potencias(const float *y, uint32_t n, float *lf, float *hf);

#endif /* PDS_HRV_HRV_FREQ_H */
