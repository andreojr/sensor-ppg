/*
 * respiracao.h: frequência respiratória pela banda lenta do PPG.
 *
 * Entrada: o bruto do ppg.h (a PPG_FS_HZ, com DC; só o IR é usado). Saída:
 * ppg_respiracao_t uma vez por segundo (a cada 100 entradas). valido fica
 * false até a janela de 60 s encher e sempre que o pico do espectro não se
 * destaca (qualidade abaixo de RESPIRACAO_QUALIDADE_MIN) ou cai numa ponta da
 * grade (a potência continua subindo fora da faixa: deriva, não respiração).
 *
 * Conta (mesma do protótipo analise/src/analise/respiracao.py):
 *  1. média de 25 entradas: a linha de base a 4 Hz;
 *  2. passa-faixa Butterworth 0,07 a 0,6 Hz (2 biquads), a "banda lenta";
 *  3. janela de 60 s (240 pontos) com Hann;
 *  4. Goertzel em 89 frequências de 4,8 a 31,2 rpm, pico refinado por parábola;
 *  5. qualidade = potência a até 0,02 Hz do pico / potência da grade.
 *
 * Custo: quase nada por entrada; o passo 4 (240 x 89 iterações) roda uma vez
 * por segundo.
 */
#ifndef PDS_RESPIRACAO_H
#define PDS_RESPIRACAO_H

#include <stdbool.h>
#include <stdint.h>

#include "comum/ppg.h"

#define RESPIRACAO_JANELA_MAX 240u
#define RESPIRACAO_GRADE_MAX 89u

typedef struct {
    bool iniciado;
    float ref;              /* primeira entrada: a média guarda o desvio dela */
    float soma;             /* soma dos desvios do bloco atual */
    uint32_t no_bloco;      /* entradas no bloco atual (até 25) */
    float z[2][2];          /* estado dos biquads (forma direta II transposta) */
    float lentos[RESPIRACAO_JANELA_MAX];  /* banda lenta, anel de 60 s */
    uint32_t pos;           /* onde entra o próximo ponto lento */
    uint32_t cheios;        /* pontos lentos guardados (até 240) */
    uint32_t desde;         /* pontos lentos desde a última estimativa */
    float qualidade;        /* da última estimativa, pra depuração e teste */
    /* Rascunhos do espectro: aqui, e não na pilha (a pilha mínima é de 1 KiB). */
    float janela[RESPIRACAO_JANELA_MAX];
    float potencia[RESPIRACAO_GRADE_MAX];
} respiracao_t;

/* Zera o estado. Chamar de novo reinicia. */
void respiracao_init(respiracao_t *r);

/*
 * Entrega uma amostra do bruto. Uma vez por segundo devolve true e escreve
 * *saida (valido false enquanto não houver estimativa confiável); nas demais
 * chamadas devolve false e não toca *saida.
 */
bool respiracao_processa(respiracao_t *r, const ppg_amostra_t *bruto,
                         ppg_respiracao_t *saida);

#endif /* PDS_RESPIRACAO_H */
