/* espectral: a saída do C bate com a do protótipo Python (vetores de analise.espectral). */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "confere.h"
#include "espectral/espectral.h"
#include "vetores/borda.h"
#include "vetores/s1_sit.h"
#include "vetores/s2_walk.h"

#define MAX_SAIDAS 64u

typedef struct {
    const char *nome;
    const float *entrada;
    uint32_t n_entrada;
    uint32_t n_saidas;
    const int32_t *valido;
    const float *bpm;
    const float *prominencia;
    float tol;
} caso_t;

/* Roda o caso e guarda o que saiu; devolve quantas saídas e em que amostra veio a primeira. */
static uint32_t roda(espectral_t *e, const caso_t *c, int32_t *valido, float *bpm, float *prom,
                     uint32_t *primeira)
{
    uint32_t n = 0;
    *primeira = 0;
    for (uint32_t i = 0; i < c->n_entrada; i++) {
        ppg_amostra_t x = {.n = i, .ir = c->entrada[i], .vermelho = 0.0f};
        ppg_bpm_t s;
        if (!espectral_processa(e, &x, &s))
            continue;
        if (n == 0)
            *primeira = i;
        if (n < MAX_SAIDAS) {
            valido[n] = s.valido ? 1 : 0;
            bpm[n] = s.bpm;
            prom[n] = espectral_prominencia(e);
        }
        n++;
    }
    return n;
}

static int confere_caso(espectral_t *e, const caso_t *c)
{
    int32_t valido[MAX_SAIDAS];
    float bpm[MAX_SAIDAS], prom[MAX_SAIDAS];
    uint32_t primeira;

    if (!espectral_init(e)) {
        printf("== %s: espectral_init falhou\n", c->nome);
        return 1;
    }
    uint32_t n = roda(e, c, valido, bpm, prom, &primeira);
    printf("== %s: %u saidas (esperado %u), a primeira na amostra %u\n", c->nome, (unsigned)n,
           (unsigned)c->n_saidas, (unsigned)primeira);
    if (n != c->n_saidas || n > MAX_SAIDAS)
        return 1;
    /* A janela enche na amostra 800 (índice 799) e sai uma por segundo. */
    int falhas = primeira != ESPECTRAL_JANELA - 1u;

    falhas += confere_int("valido", valido, c->valido, n) +
              confere_float("bpm", bpm, c->bpm, n, c->tol) +
              confere_float("prominencia", prom, c->prominencia, n, c->tol);

    /* Reiniciar tem que dar o mesmo resultado. */
    int32_t valido2[MAX_SAIDAS];
    float bpm2[MAX_SAIDAS], prom2[MAX_SAIDAS];
    espectral_init(e);
    if (roda(e, c, valido2, bpm2, prom2, &primeira) != n)
        return falhas + 1;
    falhas += confere_int("valido (reiniciado)", valido2, valido, n) +
              confere_float("bpm (reiniciado)", bpm2, bpm, n, 0.0f);
    return falhas;
}

int main(void)
{
    static espectral_t e; /* ~15 KB */
    const caso_t casos[] = {
        {"s1_sit", s1_sit_entrada, S1_SIT_ENTRADA_N, S1_SIT_VALIDO_N, s1_sit_valido, s1_sit_bpm,
         s1_sit_prominencia, S1_SIT_TOL},
        {"s2_walk", s2_walk_entrada, S2_WALK_ENTRADA_N, S2_WALK_VALIDO_N, s2_walk_valido,
         s2_walk_bpm, s2_walk_prominencia, S2_WALK_TOL},
        /* Silêncio e senoides perto das bordas da banda (ver BORDA_HZ no espectral.py). */
        {"borda", borda_entrada, BORDA_ENTRADA_N, BORDA_VALIDO_N, borda_valido, borda_bpm,
         borda_prominencia, BORDA_TOL},
    };

    int falhas = 0;
    for (uint32_t i = 0; i < sizeof casos / sizeof casos[0]; i++)
        falhas += confere_caso(&e, &casos[i]);

    /* Saída fora do passo: nenhuma antes da janela encher. */
    espectral_init(&e);
    ppg_amostra_t x = {.n = 0, .ir = 1.0f, .vermelho = 0.0f};
    ppg_bpm_t s;
    for (uint32_t i = 0; i < ESPECTRAL_JANELA - 1u; i++)
        if (espectral_processa(&e, &x, &s)) {
            printf("saiu antes da janela encher (amostra %u)\n", (unsigned)i);
            falhas++;
            break;
        }
    return falhas ? 1 : 0;
}
