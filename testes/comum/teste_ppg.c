/* Confere o contrato básico de comum/ppg.h. */
#include <assert.h>
#include <stdio.h>
#include "comum/ppg.h"

int main(void)
{
    assert(PPG_FS_HZ == 100u);

    ppg_amostra_t a = { .n = 250u, .ir = 1.0f, .vermelho = 2.0f };
    assert((float)a.n / (float)PPG_FS_HZ == 2.5f); /* índice -> segundos */

    ppg_resultados_t r = { 0 };
    assert(!r.bpm_picos.valido && !r.hrv.valido && !r.qualidade.valido);

    puts("ppg.h ok");
    return 0;
}
