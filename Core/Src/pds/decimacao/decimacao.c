/* decimacao.c: FIR anti-aliasing e redução pra PPG_FS_HZ. Ver decimacao.h. */
#include "decimacao/decimacao.h"

#include <string.h>

#include "decimacao/decimacao_coef.h"

_Static_assert(DECIMACAO_COEF_400_N <= DECIMACAO_N_MAX, "FIR de 400 Hz maior que o histórico");
_Static_assert(DECIMACAO_COEF_500_N <= DECIMACAO_N_MAX, "FIR de 500 Hz maior que o histórico");
_Static_assert((DECIMACAO_COEF_400_N - 1u) / 2u == DECIMACAO_LATENCIA_SAIDA * (400u / PPG_FS_HZ),
               "atraso do FIR de 400 Hz diferente de DECIMACAO_LATENCIA_SAIDA");
_Static_assert((DECIMACAO_COEF_500_N - 1u) / 2u == DECIMACAO_LATENCIA_SAIDA * (500u / PPG_FS_HZ),
               "atraso do FIR de 500 Hz diferente de DECIMACAO_LATENCIA_SAIDA");

bool decimacao_init(decimacao_t *d, uint32_t fs_entrada_hz)
{
    memset(d, 0, sizeof *d);
    switch (fs_entrada_hz) {
    case 400u:
        d->coef = decimacao_coef_400;
        d->n_coef = DECIMACAO_COEF_400_N;
        break;
    case 500u:
        d->coef = decimacao_coef_500;
        d->n_coef = DECIMACAO_COEF_500_N;
        break;
    default:
        return false;
    }
    d->fator = fs_entrada_hz / PPG_FS_HZ;
    /* A primeira saída sai quando chega a entrada de índice (N - 1) / 2. */
    d->falta = (d->n_coef - 1u) / 2u;
    return true;
}

/* Soma de coef[j] * x[j]: a janela é simétrica, então a ordem não importa. */
static float fir(const float *coef, const float *x, uint32_t n)
{
    float soma = 0.0f;
    for (uint32_t j = 0; j < n; j++)
        soma += coef[j] * x[j];
    return soma;
}

bool decimacao_processa(decimacao_t *d, const decimacao_entrada_t *entrada,
                        ppg_amostra_t *saida)
{
    if (d->coef == NULL)
        return false;

    if (!d->iniciado) {
        /* Histórico zerado no init = desvio 0 = a primeira amostra repetida. */
        d->ref_ir = (float)entrada->ir;
        d->ref_vermelho = (float)entrada->vermelho;
        d->iniciado = true;
    }

    /* Desvio da primeira amostra: inteiros de 18 bits, a diferença é exata. */
    const float ir = (float)((int32_t)entrada->ir - (int32_t)d->ref_ir);
    const float vermelho = (float)((int32_t)entrada->vermelho - (int32_t)d->ref_vermelho);
    const uint32_t p = d->pos;
    d->hist_ir[p] = d->hist_ir[p + d->n_coef] = ir;
    d->hist_vermelho[p] = d->hist_vermelho[p + d->n_coef] = vermelho;
    d->pos = (p + 1u == d->n_coef) ? 0u : p + 1u;

    if (d->falta > 0u) {
        d->falta--;
        return false;
    }
    d->falta = d->fator - 1u;

    /* As n_coef amostras mais recentes, da mais velha pra mais nova: p+1 a p+n. */
    saida->n = d->n++;
    saida->ir = d->ref_ir + fir(d->coef, &d->hist_ir[p + 1u], d->n_coef);
    saida->vermelho = d->ref_vermelho + fir(d->coef, &d->hist_vermelho[p + 1u], d->n_coef);
    return true;
}
