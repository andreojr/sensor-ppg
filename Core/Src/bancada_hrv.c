/* bancada_hrv.c: HRV na placa com a fonte falsa. Ver bancada_hrv.h. */
#include "bancada_hrv.h"

#if defined(BANCADA_HRV) || defined(BANCADA_HRV_FREQ)
#include <math.h>
#include <stdio.h>

#include "bancada.h"
#include "serial.h"
#endif

#ifdef BANCADA_HRV

#include "hrv/hrv.h"
/* O mesmo vetor do teste no PC (testes/ entra no include path com a opção). */
#include "hrv/vetores/s1_sit.h"

bool bancada_hrv(void)
{
    ciclos_liga(); /* bancada.h; roda antes do ciclos_liga() do main */

    static hrv_t h; /* ~3,3 KiB: fora da pilha */
    hrv_init(&h);

    uint32_t fora = 0, validos = 0, max_ciclos = 0;
    uint64_t soma_ciclos = 0;
    float pior = 0.0f;
    for (uint32_t i = 0; i < S1_SIT_VALIDO_N; i++) {
        ppg_batimento_t b = {s1_sit_valido[i] != 0, (uint32_t)s1_sit_n_pico[i], s1_sit_fracao[i],
                             s1_sit_rr_valido[i] != 0, s1_sit_rr_ms[i]};
        ppg_hrv_t s = {0};
        uint32_t t0 = ciclos_agora();
        bool escreveu = hrv_processa(&h, &b, &s);
        uint32_t dt = ciclos_agora() - t0;
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

#ifdef BANCADA_HRV_FREQ

#include "hrv/hrv_freq.h"
#include "hrv/vetores/freq_s1_sit.h"

bool bancada_hrv_freq(void)
{
    ciclos_liga();

    static hrv_freq_t h; /* ~16,4 KiB: fora da pilha */
    hrv_freq_init(&h);

    uint32_t fora = 0, validos = 0, max_ciclos = 0;
    uint32_t contas = 0, diferentes = 0, max_passo = 0, max_comeca = 0;
    uint64_t soma_ciclos = 0;
    float pior = 0.0f;
    for (uint32_t i = 0; i < FREQ_S1_SIT_VALIDO_N; i++) {
        ppg_batimento_t b = {freq_s1_sit_valido[i] != 0, (uint32_t)freq_s1_sit_n_pico[i],
                             freq_s1_sit_fracao[i], freq_s1_sit_rr_valido[i] != 0,
                             freq_s1_sit_rr_ms[i]};
        ppg_hrv_t s = {0};
        uint32_t t0 = ciclos_agora();
        bool escreveu = hrv_freq_processa(&h, &b, &s);
        uint32_t dt = ciclos_agora() - t0;
        soma_ciclos += dt;
        if (dt > max_ciclos)
            max_ciclos = dt;

        /* A mesma conta, espalhada: sobre a mesma janela (o batimento acabou de ser
           guardado), tem que dar o mesmo float. */
        if (escreveu && i % BANCADA_HRV_FREQ_CADA == 0u) {
            t0 = ciclos_agora();
            hrv_freq_comeca(&h);
            dt = ciclos_agora() - t0;
            if (dt > max_comeca)
                max_comeca = dt;
            ppg_hrv_t e = {0};
            bool saiu = false;
            for (uint32_t k = 0; k < HRV_FREQ_PASSOS; k++) {
                t0 = ciclos_agora();
                saiu = hrv_freq_passo(&h, &e);
                dt = ciclos_agora() - t0;
                if (dt > max_passo)
                    max_passo = dt;
            }
            contas++;
            diferentes += !saiu || e.lf_hf_valido != s.lf_hf_valido || e.lf_hf != s.lf_hf;
        }

        float erro = fabsf(s.lf_hf - freq_s1_sit_lf_hf[i]);
        if (erro > pior)
            pior = erro;
        fora += (int32_t)escreveu != freq_s1_sit_escreveu[i] ||
                (int32_t)s.lf_hf_valido != freq_s1_sit_lf_hf_valido[i] ||
                !(erro <= FREQ_S1_SIT_TOL);
        validos += s.lf_hf_valido;
    }

    uint32_t media = (uint32_t)(soma_ciclos / FREQ_S1_SIT_VALIDO_N);
    uint32_t pior_passo = max_passo > max_comeca ? max_passo : max_comeca;
    bool ok_espalhada = diferentes == 0u && pior_passo <= BANCADA_ORCAMENTO_HRV_FREQ_PASSO;
    bool ok = fora == 0 && max_ciclos <= BANCADA_ORCAMENTO_HRV_FREQ && ok_espalhada;
    char linha[160];
    int n = snprintf(linha, sizeof linha,
                     "# bancada lf/hf: %lu batimentos, %lu validos, %lu fora da tolerancia, "
                     "erro max %lu milionesimos\n",
                     (unsigned long)FREQ_S1_SIT_VALIDO_N, (unsigned long)validos,
                     (unsigned long)fora, (unsigned long)(pior * 1e6f + 0.5f));
    serial_escreve(linha, (uint32_t)n);
    n = snprintf(linha, sizeof linha,
                 "# bancada lf/hf: ciclos por batimento med %lu max %lu (orcamento %lu)\n",
                 (unsigned long)media, (unsigned long)max_ciclos,
                 (unsigned long)BANCADA_ORCAMENTO_HRV_FREQ);
    serial_escreve(linha, (uint32_t)n);
    n = snprintf(linha, sizeof linha,
                 "# bancada lf/hf: espalhada em %u passos, %lu contas, %lu diferentes; "
                 "pior passo %lu, comeca %lu (orcamento %lu): %s\n",
                 (unsigned)HRV_FREQ_PASSOS, (unsigned long)contas, (unsigned long)diferentes,
                 (unsigned long)max_passo, (unsigned long)max_comeca,
                 (unsigned long)BANCADA_ORCAMENTO_HRV_FREQ_PASSO, ok ? "OK" : "FALHOU");
    serial_escreve(linha, (uint32_t)n);
    serial_envia();
    return ok;
}

#endif /* BANCADA_HRV_FREQ */
