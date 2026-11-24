/*
 * spo2: saturação de oxigênio pela razão das razões, em janela deslizante.
 *
 * Porte de analise/src/analise/spo2.py (o Python é a referência: os vetores de teste saem
 * dele). Sem HAL, sem malloc, sem global.
 *
 * Entrada: o bruto (saída da decimação, COM o DC) dos dois canais, uma amostra por vez.
 * Saída: um ppg_spo2_t a cada SPO2_HOP amostras (1 s), com a janela de 8 s cheia.
 *
 * Cada canal passa por um passa-altas de 1ª ordem (dc = dc + ALFA * (x - dc), ac = x - dc).
 * Na janela, DC é a média de x e AC é o RMS de ac. R = (AC_vermelho / DC_vermelho) /
 * (AC_ir / DC_ir) e SpO2 = 110 - 25 * R, limitada a 0 a 100%.
 *
 * ESTIMATIVA: a reta é a usual de livro, sem calibração com oxímetro de referência. Serve pra
 * ver a tendência e a ordem de grandeza (95 a 100% em pessoas saudáveis), não como medida clínica.
 *
 * valido = a janela encheu, o DC dos dois canais passa de SPO2_DC_MIN em cada segundo (tem dedo o
 * tempo todo), o DC não varia mais que SPO2_DC_VARIACAO_MAX vezes entre os segundos, nenhuma
 * amostra de nenhum canal chega a SPO2_SATURA (o pulso cortado no topo do ADC dá um R errado sem
 * outro aviso), o AC do IR é maior que zero e R está entre SPO2_R_MIN e SPO2_R_MAX. Não olha
 * movimento nem ruído: quem decide se o trecho presta é o módulo qualidade (só mostre o SpO2 com
 * qualidade.usavel).
 * Com valido = false o spo2_pct sai 0, como o picos_bpm(): o display mostra "--".
 */
#ifndef PDS_SPO2_SPO2_H
#define PDS_SPO2_SPO2_H

#include <stdbool.h>
#include <stdint.h>

#include "comum/ppg.h"

#define SPO2_JANELA_S 8u
#define SPO2_HOP (1u * PPG_FS_HZ)                   /* um bloco e uma saída por segundo */
#define SPO2_BLOCOS SPO2_JANELA_S                   /* a janela são os últimos 8 blocos */
#define SPO2_JANELA (SPO2_JANELA_S * PPG_FS_HZ)     /* 800 amostras */
#define SPO2_SATURA 250000.0f   /* ~95% do topo do ADC (262143): o mesmo QUALIDADE_SATURA */

typedef struct {
    bool tem_dc;
    float dc[2];                    /* o DC de cada canal: ir, vermelho */
    uint32_t cont;                  /* amostras do bloco em andamento */
    float bloco[4];                 /* soma de x e de ac^2 do bloco: ir, vm, ir, vm */
    float maior;                    /* maior amostra do bloco, dos dois canais */
    float blocos[SPO2_BLOCOS][4];   /* os últimos blocos */
    float maiores[SPO2_BLOCOS];     /* maior amostra de cada bloco da janela */
    uint32_t idx;                   /* onde entra o próximo bloco */
    uint32_t cheios;
    float r;                        /* o R da última saída (0 se não deu pra calcular) */
} spo2_t;

/* Zera o estado; chamar de novo reinicia. */
void spo2_init(spo2_t *s);

/*
 * Processa uma amostra do bruto. Devolve true e preenche *saida a cada SPO2_HOP amostras, depois
 * de a janela encher (a primeira saída vem na amostra 800); senão devolve false e não toca em
 * *saida. Amostra com NaN ou infinito é descartada (não entra em conta nenhuma).
 */
bool spo2_processa(spo2_t *s, const ppg_amostra_t *bruto, ppg_spo2_t *saida);

/* O R da última saída (a razão das razões), pra diagnóstico. */
float spo2_r(const spo2_t *s);

#endif /* PDS_SPO2_SPO2_H */
