/* Confere o contrato básico de comum/ppg.h. */
#include <assert.h>
#include <stdio.h>
#include "comum/ppg.h"

int main(void)
{
    assert(PPG_FS_HZ == 100u);

    ppg_amostra_t a = { .n = 250u, .ir = 1.0f, .vermelho = 2.0f };
    assert((float)a.n / (float)PPG_FS_HZ == 2.5f); /* índice -> segundos */

    /* O atraso do filtro pode ser fracionário. */
    float atraso = PPG_ATRASO_AMOSTRAS;
    assert(atraso >= 0.0f);

    /* Instante do pico: amostra + fração interpolada. */
    ppg_batimento_t b = { .valido = true, .n_pico = 100u, .fracao = 0.25f,
                          .rr_valido = true, .rr_ms = 800.0f };
    assert(b.fracao >= 0.0f && b.fracao < 1.0f);
    assert(((float)b.n_pico + b.fracao) / (float)PPG_FS_HZ == 1.0025f);

    ppg_resultados_t r = { 0 };
    assert(!r.bpm_picos.valido && !r.hrv.valido && !r.qualidade.valido);
    assert(!r.ultimo_batimento.rr_valido && !r.qualidade.usavel);

    puts("ppg.h ok");
    return 0;
}
