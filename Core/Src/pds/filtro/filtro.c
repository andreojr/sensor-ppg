/* filtro.c: FIR passa-faixa de fase linear. Ver filtro.h. */
#include "filtro/filtro.h"

#include <string.h>

#include "filtro/filtro_coef.h"

_Static_assert(FILTRO_N <= FILTRO_N_MAX, "FIR maior que o histórico");
_Static_assert(FILTRO_N % 2u == 1u, "a dobra da simetria supõe N ímpar");
_Static_assert((FILTRO_N - 1u) / 2u == (uint32_t)PPG_ATRASO_AMOSTRAS,
               "PPG_ATRASO_AMOSTRAS tem que ser (FILTRO_N - 1) / 2");

void filtro_init(filtro_t *f)
{
    memset(f, 0, sizeof *f);
}

/*
 * Soma de h[j] * x[j] pra j = 0..N-1, com h simétrico: h[j] * (x[j] + x[N-1-j])
 * até o meio, mais o termo do meio. Metade das multiplicações.
 */
static float fir_simetrico(const float *x)
{
    const uint32_t meio = (FILTRO_N - 1u) / 2u;
    float soma = filtro_coef[meio] * x[meio];
    for (uint32_t j = 0; j < meio; j++)
        soma += filtro_coef[j] * (x[j] + x[FILTRO_N - 1u - j]);
    return soma;
}

bool filtro_processa(filtro_t *f, const ppg_amostra_t *bruto, ppg_amostra_t *filtrado)
{
    if (!f->iniciado) {
        /* Histórico zerado no init = desvio 0 = a primeira amostra repetida. */
        f->ref_ir = bruto->ir;
        f->ref_vermelho = bruto->vermelho;
        f->iniciado = true;
    }

    const uint32_t p = f->pos;
    f->hist_ir[p] = f->hist_ir[p + FILTRO_N] = bruto->ir - f->ref_ir;
    f->hist_vermelho[p] = f->hist_vermelho[p + FILTRO_N] = bruto->vermelho - f->ref_vermelho;
    f->pos = (p + 1u == FILTRO_N) ? 0u : p + 1u;

    /* As N amostras mais recentes, da mais velha pra mais nova: p+1 a p+N.
       Ganho 0 em DC: a referência não volta somada. */
    filtrado->n = bruto->n;
    filtrado->ir = fir_simetrico(&f->hist_ir[p + 1u]);
    filtrado->vermelho = fir_simetrico(&f->hist_vermelho[p + 1u]);
    return true;
}
