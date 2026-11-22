/* respiracao.c: frequência respiratória pela banda lenta. Ver respiracao.h. */
#include "respiracao/respiracao.h"

#include <string.h>

#include "respiracao/respiracao_coef.h"

_Static_assert(RESPIRACAO_N_JANELA <= RESPIRACAO_JANELA_MAX, "janela maior que o anel");
_Static_assert(RESPIRACAO_N_GRADE <= RESPIRACAO_GRADE_MAX, "grade maior que o rascunho");
_Static_assert(RESPIRACAO_BLOCO * RESPIRACAO_PASSO == PPG_FS_HZ,
               "uma estimativa por segundo: 25 entradas x 4 pontos lentos");

void respiracao_init(respiracao_t *r)
{
    memset(r, 0, sizeof *r);
}

/* Biquads em cascata, forma direta II transposta (a mesma do scipy.sosfilt). */
static float banda_lenta(respiracao_t *r, float x)
{
    for (uint32_t s = 0; s < 2u; s++) {
        const float *c = respiracao_sos[s];
        float y = c[0] * x + r->z[s][0];
        r->z[s][0] = c[1] * x - c[3] * y + r->z[s][1];
        r->z[s][1] = c[2] * x - c[4] * y;
        x = y;
    }
    return x;
}

/* Potência de cada frequência da grade (Goertzel) sobre r->janela. */
static void espectro(respiracao_t *r)
{
    for (uint32_t k = 0; k < RESPIRACAO_N_GRADE; k++) {
        const float c = respiracao_cos2[k];
        float s1 = 0.0f, s2 = 0.0f;
        for (uint32_t j = 0; j < RESPIRACAO_N_JANELA; j++) {
            float s0 = r->janela[j] + c * s1 - s2;
            s2 = s1;
            s1 = s0;
        }
        r->potencia[k] = s1 * s1 + s2 * s2 - c * s1 * s2;
    }
}

static void estima(respiracao_t *r, ppg_respiracao_t *saida)
{
    /* A janela, da mais velha pra mais nova, sem a média e com Hann. */
    float media = 0.0f;
    for (uint32_t j = 0; j < RESPIRACAO_N_JANELA; j++)
        media += r->lentos[j];
    media /= (float)RESPIRACAO_N_JANELA;
    for (uint32_t j = 0; j < RESPIRACAO_N_JANELA; j++) {
        uint32_t i = r->pos + j;
        if (i >= RESPIRACAO_N_JANELA)
            i -= RESPIRACAO_N_JANELA;
        r->janela[j] = (r->lentos[i] - media) * respiracao_hann[j];
    }

    espectro(r);
    const float *p = r->potencia;
    uint32_t k = 0;
    float total = 0.0f;
    for (uint32_t i = 0; i < RESPIRACAO_N_GRADE; i++) {
        total += p[i];
        if (p[i] > p[k])
            k = i;
    }

    if (k == 0u || k + 1u == RESPIRACAO_N_GRADE) {
        /* Pico na ponta: a potência sobe pra fora da faixa, não é respiração. */
        r->qualidade = 0.0f;
        saida->rpm = 60.0f * (RESPIRACAO_GRADE_INI_HZ + (float)k * RESPIRACAO_GRADE_PASSO_HZ);
        saida->valido = false;
        return;
    }
    float desvio = 0.0f;
    float den = p[k - 1u] - 2.0f * p[k] + p[k + 1u];
    if (den != 0.0f)
        desvio = 0.5f * (p[k - 1u] - p[k + 1u]) / den;
    float perto = 0.0f;
    for (uint32_t i = (k > RESPIRACAO_VIZINHOS ? k - RESPIRACAO_VIZINHOS : 0u);
         i <= k + RESPIRACAO_VIZINHOS && i < RESPIRACAO_N_GRADE; i++)
        perto += p[i];

    r->qualidade = total > 0.0f ? perto / total : 0.0f;
    saida->rpm = 60.0f * (RESPIRACAO_GRADE_INI_HZ + ((float)k + desvio) * RESPIRACAO_GRADE_PASSO_HZ);
    saida->valido = r->qualidade >= RESPIRACAO_QUALIDADE_MIN;
}

bool respiracao_processa(respiracao_t *r, const ppg_amostra_t *bruto,
                         ppg_respiracao_t *saida)
{
    if (!r->iniciado) {
        r->ref = bruto->ir;
        r->iniciado = true;
    }
    r->soma += bruto->ir - r->ref;
    if (++r->no_bloco < RESPIRACAO_BLOCO)
        return false;

    float lento = banda_lenta(r, r->soma / (float)RESPIRACAO_BLOCO);
    r->soma = 0.0f;
    r->no_bloco = 0;
    r->lentos[r->pos] = lento;
    r->pos = (r->pos + 1u == RESPIRACAO_N_JANELA) ? 0u : r->pos + 1u;
    if (r->cheios < RESPIRACAO_N_JANELA)
        r->cheios++;
    if (++r->desde < RESPIRACAO_PASSO)
        return false;
    r->desde = 0;

    if (r->cheios < RESPIRACAO_N_JANELA) {
        r->qualidade = 0.0f;
        saida->valido = false;
        saida->rpm = 0.0f;
        return true;
    }
    estima(r, saida);
    return true;
}
