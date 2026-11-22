/*
 * Teste da respiração no PC: a saída do C bate com a do protótipo em Python
 * (vetores gerados por `uv run python -m analise.respiracao --vetores`).
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include "confere.h"
#include "respiracao/respiracao.h"
#include "vetores/metronomo.h"
#include "vetores/s1_sit.h"

#define SAIDAS_MAX 400u

static int32_t amostra[SAIDAS_MAX];
static int32_t valido[SAIDAS_MAX];
static float rpm[SAIDAS_MAX];
static float qualidade[SAIDAS_MAX];

static int caso(const char *nome, const float *ir, uint32_t n, const int32_t *esp_amostra,
                const int32_t *esp_valido, const float *esp_rpm, const float *esp_q,
                uint32_t n_esp, float tol)
{
    static respiracao_t r;
    respiracao_init(&r);
    uint32_t saidas = 0;
    for (uint32_t i = 0; i < n; i++) {
        ppg_amostra_t e = {i, ir[i], 0.0f};
        ppg_respiracao_t s;
        if (!respiracao_processa(&r, &e, &s))
            continue;
        if (saidas < SAIDAS_MAX) {
            amostra[saidas] = (int32_t)i;
            valido[saidas] = s.valido;
            rpm[saidas] = s.rpm;
            qualidade[saidas] = r.qualidade;
        }
        saidas++;
    }
    printf("-- %s: %u saídas (esperado %u)\n", nome, (unsigned)saidas, (unsigned)n_esp);
    if (saidas != n_esp)
        return 1;
    return confere_int("amostra", amostra, esp_amostra, n_esp)
         + confere_int("valido", valido, esp_valido, n_esp)
         + confere_float("rpm", rpm, esp_rpm, n_esp, tol)
         + confere_float("qualidade", qualidade, esp_q, n_esp, 1e-3f);
}

/* Metrônomo: depois do 1º minuto de cada trecho, todas válidas e no ritmo. */
static int ritmos(void)
{
    const float alvo[3] = {6.0f, 10.0f, 15.0f};
    int falhas = 0;
    for (uint32_t t = 0; t < 3u; t++) {
        uint32_t validas = 0, total = 0;
        float pior = 0.0f;
        for (uint32_t k = 0; k < METRONOMO_AMOSTRA_N; k++) {
            uint32_t i = (uint32_t)amostra[k];
            if (i < t * 12000u + 6000u || i >= (t + 1u) * 12000u)
                continue;
            total++;
            if (valido[k]) {
                validas++;
                if (fabsf(rpm[k] - alvo[t]) > pior)
                    pior = fabsf(rpm[k] - alvo[t]);
            }
        }
        int f = validas != total || pior > 0.5f;
        printf("metrônomo %.0f rpm: %u/%u válidas, pior erro %.2f rpm%s\n", (double)alvo[t],
               (unsigned)validas, (unsigned)total, (double)pior, f ? " ERRO" : "");
        falhas += f;
    }
    return falhas;
}

/* Antes de 60 s não há estimativa válida; DC puro nunca é válido. */
static int sem_janela_e_dc(void)
{
    static respiracao_t r;
    respiracao_init(&r);
    int falhas = 0, saidas = 0;
    for (uint32_t i = 0; i < 9000u; i++) {
        ppg_amostra_t e = {i, 120000.0f, 0.0f};
        ppg_respiracao_t s;
        if (respiracao_processa(&r, &e, &s)) {
            saidas++;
            falhas += s.valido;
        }
    }
    printf("DC por 90 s: %d saídas, %d válidas%s\n", saidas, falhas, falhas ? " ERRO" : "");
    return falhas + (saidas != 90);
}

int main(void)
{
    int falhas = caso("s1_sit", s1_sit_ir, S1_SIT_IR_N, s1_sit_amostra, s1_sit_valido,
                      s1_sit_rpm, s1_sit_qualidade, S1_SIT_AMOSTRA_N, S1_SIT_TOL);
    falhas += caso("metronomo", metronomo_ir, METRONOMO_IR_N, metronomo_amostra,
                   metronomo_valido, metronomo_rpm, metronomo_qualidade, METRONOMO_AMOSTRA_N,
                   METRONOMO_TOL);
    falhas += ritmos(); /* usa a saída do caso metronomo, que rodou por último */
    falhas += sem_janela_e_dc();
    printf(falhas ? "FALHOU\n" : "ok\n");
    return falhas ? 1 : 0;
}
