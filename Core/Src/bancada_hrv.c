/* bancada_hrv.c: HRV na placa com a fonte falsa. Ver bancada_hrv.h. */
#include "bancada_hrv.h"

#ifdef BANCADA_HRV

#include <math.h>
#include <stdio.h>

#include "hrv/hrv.h"
#include "main.h"
#include "serial.h"
/* O mesmo vetor do teste no PC (testes/ entra no include path com a opção). */
#include "hrv/vetores/s1_sit.h"

bool bancada_hrv(void)
{
    /* Contador de ciclos do núcleo (DWT). */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    static hrv_t h; /* ~3,3 KiB: fora da pilha */
    hrv_init(&h);

    uint32_t fora = 0, validos = 0, max_ciclos = 0;
    uint64_t soma_ciclos = 0;
    float pior = 0.0f;
    for (uint32_t i = 0; i < S1_SIT_VALIDO_N; i++) {
        ppg_batimento_t b = {s1_sit_valido[i] != 0, (uint32_t)s1_sit_n_pico[i], s1_sit_fracao[i],
                             s1_sit_rr_valido[i] != 0, s1_sit_rr_ms[i]};
        ppg_hrv_t s = {0};
        uint32_t t0 = DWT->CYCCNT;
        bool escreveu = hrv_processa(&h, &b, &s);
        uint32_t dt = DWT->CYCCNT - t0;
        soma_ciclos += dt;
        if (dt > max_ciclos)
            max_ciclos = dt;

        float erro = fmaxf(fabsf(s.sdnn_ms - s1_sit_sdnn[i]), fabsf(s.rmssd_ms - s1_sit_rmssd[i]));
        if (erro > pior)
            pior = erro;
        fora += (int32_t)escreveu != s1_sit_escreveu[i] ||
                (int32_t)s.valido != s1_sit_saida_valido[i] || !(erro <= S1_SIT_TOL);
        validos += s.valido;
    }

    uint32_t media = (uint32_t)(soma_ciclos / S1_SIT_VALIDO_N);
    bool ok = fora == 0 && max_ciclos <= BANCADA_ORCAMENTO_HRV;
    char linha[160];
    int n = snprintf(linha, sizeof linha,
                     "# bancada hrv: %lu batimentos, %lu validos, %lu fora da tolerancia, "
                     "erro max %lu milesimos de ms\n",
                     (unsigned long)S1_SIT_VALIDO_N, (unsigned long)validos, (unsigned long)fora,
                     (unsigned long)(pior * 1000.0f + 0.5f));
    serial_escreve(linha, (uint32_t)n);
    n = snprintf(linha, sizeof linha,
                 "# bancada hrv: ciclos por batimento med %lu max %lu (orcamento %lu): %s\n",
                 (unsigned long)media, (unsigned long)max_ciclos,
                 (unsigned long)BANCADA_ORCAMENTO_HRV, ok ? "OK" : "FALHOU");
    serial_escreve(linha, (uint32_t)n);
    serial_envia();
    return ok;
}

#endif /* BANCADA_HRV */
