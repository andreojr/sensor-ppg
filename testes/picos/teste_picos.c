/* picos: a saída do C bate com a do protótipo Python (vetores de analise.picos). */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "confere.h"
#include "picos/picos.h"
#include "vetores/s1_sit.h"
#include "vetores/s2_walk.h"

#define MAX_BATIMENTOS 128u

typedef struct {
    const char *nome;
    const float *entrada;
    uint32_t n_entrada;
    uint32_t n_batimentos;
    const int32_t *n_pico;
    const float *fracao;
    const int32_t *rr_valido;
    const float *rr_ms;
    const int32_t *bpm_valido;
    const float *bpm;
    float tol;
} caso_t;

static int roda(const caso_t *c)
{
    int32_t n_pico[MAX_BATIMENTOS], rr_valido[MAX_BATIMENTOS], bpm_valido[MAX_BATIMENTOS];
    float fracao[MAX_BATIMENTOS], rr_ms[MAX_BATIMENTOS], bpm[MAX_BATIMENTOS];
    uint32_t n = 0;

    picos_t p;
    picos_init(&p);
    for (uint32_t i = 0; i < c->n_entrada; i++) {
        ppg_amostra_t x = {.n = i, .ir = c->entrada[i], .vermelho = 0.0f};
        ppg_batimento_t b;
        if (!picos_processa(&p, &x, &b))
            continue;
        if (n < MAX_BATIMENTOS) {
            ppg_bpm_t v;
            picos_bpm(&p, &v);
            n_pico[n] = (int32_t)b.n_pico;
            fracao[n] = b.fracao;
            rr_valido[n] = b.rr_valido ? 1 : 0;
            rr_ms[n] = b.rr_ms;
            bpm_valido[n] = v.valido ? 1 : 0;
            bpm[n] = v.valido ? v.bpm : 0.0f;
        }
        n++;
    }

    printf("== %s: %u batimentos (esperado %u)\n", c->nome, (unsigned)n,
           (unsigned)c->n_batimentos);
    if (n != c->n_batimentos || n > MAX_BATIMENTOS)
        return 1;

    return confere_int("n_pico", n_pico, c->n_pico, n)
         + confere_float("fracao", fracao, c->fracao, n, c->tol)
         + confere_int("rr_valido", rr_valido, c->rr_valido, n)
         + confere_float("rr_ms", rr_ms, c->rr_ms, n, c->tol)
         + confere_int("bpm_valido", bpm_valido, c->bpm_valido, n)
         + confere_float("bpm", bpm, c->bpm, n, c->tol);
}

int main(void)
{
    const caso_t casos[] = {
        {"s1_sit", s1_sit_entrada, S1_SIT_ENTRADA_N, S1_SIT_N_PICO_N, s1_sit_n_pico,
         s1_sit_fracao, s1_sit_rr_valido, s1_sit_rr_ms, s1_sit_bpm_valido, s1_sit_bpm,
         S1_SIT_TOL},
        {"s2_walk", s2_walk_entrada, S2_WALK_ENTRADA_N, S2_WALK_N_PICO_N, s2_walk_n_pico,
         s2_walk_fracao, s2_walk_rr_valido, s2_walk_rr_ms, s2_walk_bpm_valido, s2_walk_bpm,
         S2_WALK_TOL},
    };

    int falhas = 0;
    for (uint32_t i = 0; i < sizeof casos / sizeof casos[0]; i++)
        falhas += roda(&casos[i]);
    return falhas ? 1 : 0;
}
