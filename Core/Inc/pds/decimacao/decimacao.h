/*
 * decimacao.h: anti-aliasing próprio e redução da taxa do sensor pra PPG_FS_HZ.
 *
 * Entrada: uma amostra do sensor (contagens do ADC, com DC) à taxa dada no
 * init (400 Hz na placa, 500 Hz no PhysioNet). Saída: o "bruto" do ppg.h, a
 * PPG_FS_HZ, com DC, uma a cada fator = taxa / PPG_FS_HZ entradas.
 *
 * Filtro: FIR de fase linear (Remez), passa 0 a 20 Hz, rejeita ~76 dB de
 * 50 Hz pra cima, ganho 1 em DC. Coeficientes em decimacao_coef.h, gerados
 * por analise/src/analise/decimacao.py, que é o protótipo desta conta.
 *
 * Tempo: a saída n corresponde ao instante n / PPG_FS_HZ da entrada (a
 * primeira entrada é o instante 0). Ela só sai DECIMACAO_LATENCIA_SAIDA
 * amostras de saída depois (60 ms), quando chega a entrada que fecha a janela
 * do FIR. Antes da primeira entrada, o histórico vale a primeira entrada.
 *
 * Custo: N multiplicações por canal a cada saída (N = 49 a 400 Hz), nada nas
 * demais entradas além de guardar a amostra.
 */
#ifndef PDS_DECIMACAO_H
#define PDS_DECIMACAO_H

#include <stdbool.h>
#include <stdint.h>

#include "comum/ppg.h"

/* Maior FIR (500 Hz). */
#define DECIMACAO_N_MAX 61u

/* Saídas entre o instante de uma amostra e a hora em que ela sai (60 ms). */
#define DECIMACAO_LATENCIA_SAIDA 6u

/* Uma amostra do sensor: contagens do ADC de 18 bits, com DC. */
typedef struct {
    uint32_t ir;
    uint32_t vermelho;
} decimacao_entrada_t;

typedef struct {
    const float *coef;      /* NULL: taxa sem filtro, processa() não faz nada */
    uint32_t n_coef;
    uint32_t fator;         /* taxa de entrada / PPG_FS_HZ */
    uint32_t pos;           /* onde entra a próxima amostra no histórico */
    uint32_t falta;         /* entradas até a próxima saída */
    uint32_t n;             /* n da próxima saída */
    bool iniciado;          /* já chegou a primeira entrada */
    float ref_ir;           /* primeira entrada: o histórico guarda o desvio dela */
    float ref_vermelho;
    /* Histórico duplicado (posições i e i + n_coef): a janela é sempre contínua. */
    float hist_ir[2u * DECIMACAO_N_MAX];
    float hist_vermelho[2u * DECIMACAO_N_MAX];
} decimacao_t;

/*
 * Zera o estado para a taxa de entrada fs_entrada_hz. Chamar de novo
 * reinicia (o n volta a 0). false se a taxa não tem filtro (só 400 e 500 Hz);
 * aí processa() sempre devolve false.
 */
bool decimacao_init(decimacao_t *d, uint32_t fs_entrada_hz);

/*
 * Entrega uma amostra do sensor. Devolve true e escreve *saida (com n, ir e
 * vermelho) a cada fator entradas; nas demais devolve false e não toca *saida.
 */
bool decimacao_processa(decimacao_t *d, const decimacao_entrada_t *entrada,
                        ppg_amostra_t *saida);

#endif /* PDS_DECIMACAO_H */
