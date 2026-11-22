/*
 * filtro.h: remoção de DC e passa-faixa 0,5 a 4 Hz, do bruto pro filtrado.
 *
 * Entrada: o bruto do ppg.h (a PPG_FS_HZ, com DC). Saída: o filtrado (média
 * zero), uma por entrada, com o MESMO n da entrada. O sinal sai atrasado de
 * PPG_ATRASO_AMOSTRAS (100 amostras = 1 s), igual em todas as frequências:
 * quem detecta o instante do pico subtrai esse valor.
 *
 * Filtro: FIR de fase linear, janela de Hamming, FILTRO_N coeficientes, -6 dB
 * em 0,5 e 4 Hz, ganho 0 em DC. Coeficientes em filtro_coef.h, gerados por
 * analise/src/analise/filtro.py, que é o protótipo desta conta.
 *
 * Antes da primeira entrada, o histórico vale a primeira entrada: o filtrado
 * começa em 0, sem transiente de DC, e fica válido depois de FILTRO_N
 * entradas (2 s).
 *
 * Custo: os coeficientes são simétricos, então são (FILTRO_N + 1) / 2
 * multiplicações por canal a cada entrada.
 */
#ifndef PDS_FILTRO_H
#define PDS_FILTRO_H

#include <stdbool.h>
#include <stdint.h>

#include "comum/ppg.h"

#define FILTRO_N_MAX 201u

typedef struct {
    uint32_t pos;           /* onde entra a próxima amostra no histórico */
    bool iniciado;          /* já chegou a primeira entrada */
    float ref_ir;           /* primeira entrada: o histórico guarda o desvio dela */
    float ref_vermelho;
    /* Histórico duplicado (posições i e i + N): a janela é sempre contínua. */
    float hist_ir[2u * FILTRO_N_MAX];
    float hist_vermelho[2u * FILTRO_N_MAX];
} filtro_t;

/* Zera o estado. Chamar de novo reinicia. */
void filtro_init(filtro_t *f);

/* Filtra uma amostra do bruto. Sempre devolve true e escreve *filtrado (n igual ao da entrada).
   A primeira amostra vira a referência do DC: se ela for NaN, a saída fica NaN
   até o próximo init (NaN depois dela some em FILTRO_N amostras). */
bool filtro_processa(filtro_t *f, const ppg_amostra_t *bruto, ppg_amostra_t *filtrado);

#endif /* PDS_FILTRO_H */
