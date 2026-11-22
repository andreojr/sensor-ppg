/* bancada.c: ciclos e conferência do PDS na placa. Ver bancada.h. */
#include "bancada.h"

#include <stdio.h>

#include "serial.h"

void ciclos_liga(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

void ciclos_relata(ciclos_t *c, const char *nome, uint32_t orcamento)
{
    char linha[80];
    int n = snprintf(linha, sizeof linha, "# %s: ciclos med %lu max %lu (orcamento %lu)\n", nome,
                     (unsigned long)(c->conta ? c->soma / c->conta : 0u), (unsigned long)c->max,
                     (unsigned long)orcamento);
    serial_escreve(linha, (uint32_t)n);
    c->soma = 0;
    c->max = 0;
    c->conta = 0;
}

void ciclos_relata_max(ciclos_t *c, const char *nome, uint32_t orcamento_med,
                       uint32_t orcamento_max)
{
    char linha[112];
    int n = snprintf(linha, sizeof linha,
                     "# %s: ciclos med %lu (orcamento %lu) max %lu (orcamento %lu)\n", nome,
                     (unsigned long)(c->conta ? c->soma / c->conta : 0u),
                     (unsigned long)orcamento_med, (unsigned long)c->max,
                     (unsigned long)orcamento_max);
    serial_escreve(linha, (uint32_t)n);
    c->soma = 0;
    c->max = 0;
    c->conta = 0;
}

#ifdef BANCADA_DECIMACAO

#include <math.h>

#include "decimacao/decimacao.h"
/* O mesmo vetor do teste no PC (testes/ entra no include path com a opção). */
#include "decimacao/vetores/sensor_400hz.h"

bool bancada_decimacao(void)
{
    static decimacao_t d; /* ~1 KiB: fora da pilha */
    if (!decimacao_init(&d, 400u)) {
        static const char erro[] = "# bancada decimacao: sem filtro para 400 Hz: FALHOU\n";
        serial_escreve(erro, sizeof erro - 1u);
        serial_envia();
        return false;
    }

    uint32_t saidas = 0, fora = 0, max_ciclos = 0;
    uint64_t soma_ciclos = 0;
    float pior = 0.0f;
    for (uint32_t i = 0; i < SENSOR_400HZ_IR_N; i++) {
        decimacao_entrada_t e = {(uint32_t)sensor_400hz_ir[i], (uint32_t)sensor_400hz_vermelho[i]};
        ppg_amostra_t s;
        uint32_t t0 = ciclos_agora();
        bool saiu = decimacao_processa(&d, &e, &s);
        uint32_t dt = ciclos_agora() - t0;
        soma_ciclos += dt;
        if (dt > max_ciclos)
            max_ciclos = dt;
        if (!saiu)
            continue;
        if (saidas < SENSOR_400HZ_ESPERADO_IR_N && s.n == saidas) {
            float erro = fmaxf(fabsf(s.ir - sensor_400hz_esperado_ir[saidas]),
                               fabsf(s.vermelho - sensor_400hz_esperado_vermelho[saidas]));
            if (erro > pior)
                pior = erro;
            fora += !(erro <= SENSOR_400HZ_TOL);
        } else {
            fora++;
        }
        saidas++;
    }

    uint32_t media = (uint32_t)(soma_ciclos / SENSOR_400HZ_IR_N);
    bool ok = saidas == SENSOR_400HZ_ESPERADO_IR_N && fora == 0 &&
              media <= BANCADA_ORCAMENTO_DECIMACAO;
    char linha[160];
    int n = snprintf(linha, sizeof linha,
                     "# bancada decimacao: %lu saidas (esperado %lu), %lu fora da tolerancia, "
                     "erro max %lu milesimos\n",
                     (unsigned long)saidas, (unsigned long)SENSOR_400HZ_ESPERADO_IR_N,
                     (unsigned long)fora, (unsigned long)(pior * 1000.0f + 0.5f));
    serial_escreve(linha, (uint32_t)n);
    n = snprintf(linha, sizeof linha,
                 "# bancada decimacao: ciclos por amostra med %lu max %lu (orcamento %lu): %s\n",
                 (unsigned long)media, (unsigned long)max_ciclos,
                 (unsigned long)BANCADA_ORCAMENTO_DECIMACAO, ok ? "OK" : "FALHOU");
    serial_escreve(linha, (uint32_t)n);
    serial_envia();
    return ok;
}

#endif /* BANCADA_DECIMACAO */

#ifdef BANCADA_FILTRO

#include <math.h>

#include "filtro/filtro.h"
/* O mesmo vetor do teste no PC: o bruto da fonte falsa, 60 s a 100 Hz. */
#include "filtro/vetores/bruto_100hz.h"

bool bancada_filtro(void)
{
    static filtro_t f; /* ~3 KiB: fora da pilha */
    filtro_init(&f);

    ciclos_t c = {0};
    uint32_t fora = 0;
    float pior = 0.0f;
    for (uint32_t i = 0; i < BRUTO_100HZ_IR_N; i++) {
        ppg_amostra_t e = {i, bruto_100hz_ir[i], bruto_100hz_vermelho[i]}, s;
        uint32_t t0 = ciclos_agora();
        filtro_processa(&f, &e, &s);
        ciclos_conta(&c, ciclos_agora() - t0);
        float erro = fmaxf(fabsf(s.ir - bruto_100hz_esperado_ir[i]),
                           fabsf(s.vermelho - bruto_100hz_esperado_vermelho[i]));
        if (erro > pior)
            pior = erro;
        fora += !(erro <= BRUTO_100HZ_TOL) || s.n != i;
    }

    uint32_t media = (uint32_t)(c.soma / c.conta);
    bool ok = fora == 0 && media <= BANCADA_ORCAMENTO_FILTRO;
    char linha[160];
    int n = snprintf(linha, sizeof linha,
                     "# bancada filtro: %lu saidas, %lu fora da tolerancia, erro max %lu milesimos\n",
                     (unsigned long)c.conta, (unsigned long)fora,
                     (unsigned long)(pior * 1000.0f + 0.5f));
    serial_escreve(linha, (uint32_t)n);
    n = snprintf(linha, sizeof linha,
                 "# bancada filtro: ciclos por amostra med %lu max %lu (orcamento %lu): %s\n",
                 (unsigned long)media, (unsigned long)c.max,
                 (unsigned long)BANCADA_ORCAMENTO_FILTRO, ok ? "OK" : "FALHOU");
    serial_escreve(linha, (uint32_t)n);
    serial_envia();
    return ok;
}

#endif /* BANCADA_FILTRO */

#ifdef BANCADA_PICOS

#include <math.h>

#include "picos/picos.h"
/* O mesmo vetor do teste no PC: o s3_sit tem a corcova do FIR e exercita o
   candidato pendente. */
#include "picos/vetores/s3_sit.h"

bool bancada_picos(void)
{
    static picos_t p;
    picos_init(&p);

    ciclos_t c = {0};
    uint32_t k = 0, fora = 0;
    float pior = 0.0f;
    for (uint32_t i = 0; i < S3_SIT_ENTRADA_N; i++) {
        ppg_amostra_t e = {i, s3_sit_entrada[i], 0.0f};
        ppg_batimento_t b;
        uint32_t t0 = ciclos_agora();
        bool saiu = picos_processa(&p, &e, &b);
        ciclos_conta(&c, ciclos_agora() - t0);
        if (!saiu)
            continue;
        if (k < S3_SIT_N_PICO_N) {
            ppg_bpm_t v;
            picos_bpm(&p, &v);
            float bpm = v.valido ? v.bpm : 0.0f;
            float erro = fmaxf(fabsf(b.fracao - s3_sit_fracao[k]),
                               fmaxf(fabsf(b.rr_ms - s3_sit_rr_ms[k]), fabsf(bpm - s3_sit_bpm[k])));
            if (erro > pior)
                pior = erro;
            fora += !b.valido || (int32_t)b.n_pico != s3_sit_n_pico[k] ||
                    (int32_t)b.rr_valido != s3_sit_rr_valido[k] ||
                    (int32_t)v.valido != s3_sit_bpm_valido[k] || !(erro <= S3_SIT_TOL);
        }
        k++;
    }

    uint32_t media = (uint32_t)(c.soma / c.conta);
    bool ok = k == S3_SIT_N_PICO_N && fora == 0 && media <= BANCADA_ORCAMENTO_PICOS;
    char linha[160];
    int n = snprintf(linha, sizeof linha,
                     "# bancada picos: %lu batimentos (esperado %lu), %lu fora da tolerancia, "
                     "erro max %lu milesimos\n",
                     (unsigned long)k, (unsigned long)S3_SIT_N_PICO_N, (unsigned long)fora,
                     (unsigned long)(pior * 1000.0f + 0.5f));
    serial_escreve(linha, (uint32_t)n);
    n = snprintf(linha, sizeof linha,
                 "# bancada picos: ciclos por amostra med %lu max %lu (orcamento %lu): %s\n",
                 (unsigned long)media, (unsigned long)c.max,
                 (unsigned long)BANCADA_ORCAMENTO_PICOS, ok ? "OK" : "FALHOU");
    serial_escreve(linha, (uint32_t)n);
    serial_envia();
    return ok;
}

#endif /* BANCADA_PICOS */

#ifdef BANCADA_ESPECTRAL

#include <math.h>

#include "espectral/espectral.h"
/* O mesmo vetor do teste no PC: o s2_walk tem saídas válidas e inválidas. */
#include "espectral/vetores/s2_walk.h"

bool bancada_espectral(void)
{
    static espectral_t e; /* ~15 KB: fora da pilha */
    if (!espectral_init(&e)) {
        static const char erro[] = "# bancada espectral: FFT de 1024 pontos nao compilada: FALHOU\n";
        serial_escreve(erro, sizeof erro - 1u);
        serial_envia();
        return false;
    }

    ciclos_t c = {0};
    uint32_t k = 0, fora = 0;
    float pior = 0.0f;
    for (uint32_t i = 0; i < S2_WALK_ENTRADA_N; i++) {
        ppg_amostra_t x = {i, s2_walk_entrada[i], 0.0f};
        ppg_bpm_t s;
        uint32_t t0 = ciclos_agora();
        bool saiu = espectral_processa(&e, &x, &s);
        ciclos_conta(&c, ciclos_agora() - t0);
        if (!saiu)
            continue;
        if (k < S2_WALK_VALIDO_N) {
            float erro = fmaxf(fabsf(s.bpm - s2_walk_bpm[k]),
                               fabsf(espectral_prominencia(&e) - s2_walk_prominencia[k]));
            if (erro > pior)
                pior = erro;
            fora += (int32_t)s.valido != s2_walk_valido[k] || !(erro <= S2_WALK_TOL);
        }
        k++;
    }

    uint32_t media = (uint32_t)(c.soma / c.conta);
    bool ok = k == S2_WALK_VALIDO_N && fora == 0 && media <= BANCADA_ORCAMENTO_ESPECTRAL &&
              c.max <= BANCADA_ORCAMENTO_ESPECTRAL_MAX;
    char linha[160];
    int n = snprintf(linha, sizeof linha,
                     "# bancada espectral: %lu saidas (esperado %lu), %lu fora da tolerancia, "
                     "erro max %lu milesimos\n",
                     (unsigned long)k, (unsigned long)S2_WALK_VALIDO_N, (unsigned long)fora,
                     (unsigned long)(pior * 1000.0f + 0.5f));
    serial_escreve(linha, (uint32_t)n);
    n = snprintf(linha, sizeof linha,
                 "# bancada espectral: ciclos por amostra med %lu (orcamento %lu), max %lu "
                 "(orcamento %lu): %s\n",
                 (unsigned long)media, (unsigned long)BANCADA_ORCAMENTO_ESPECTRAL,
                 (unsigned long)c.max, (unsigned long)BANCADA_ORCAMENTO_ESPECTRAL_MAX,
                 ok ? "OK" : "FALHOU");
    serial_escreve(linha, (uint32_t)n);
    serial_envia();
    return ok;
}

#endif /* BANCADA_ESPECTRAL */

#ifdef BANCADA_RESPIRACAO

#include <math.h>

#include "respiracao/respiracao.h"
/* O mesmo vetor do teste no PC: 5 min do bruto (IR) do s1_sit, decimado. */
#include "respiracao/vetores/s1_sit.h"

bool bancada_respiracao(void)
{
    static respiracao_t r; /* ~2,3 KiB: fora da pilha */
    respiracao_init(&r);

    ciclos_t c = {0};
    uint32_t saidas = 0, fora = 0;
    float pior = 0.0f;
    for (uint32_t i = 0; i < S1_SIT_IR_N; i++) {
        ppg_amostra_t e = {i, s1_sit_ir[i], 0.0f};
        ppg_respiracao_t s;
        uint32_t t0 = ciclos_agora();
        bool saiu = respiracao_processa(&r, &e, &s);
        ciclos_conta(&c, ciclos_agora() - t0);
        if (!saiu)
            continue;
        if (saidas < S1_SIT_AMOSTRA_N && (int32_t)i == s1_sit_amostra[saidas]) {
            float erro = fabsf(s.rpm - s1_sit_rpm[saidas]);
            if (erro > pior)
                pior = erro;
            fora += !(erro <= S1_SIT_TOL) || (int32_t)s.valido != s1_sit_valido[saidas];
        } else {
            fora++;
        }
        saidas++;
    }

    uint32_t media = (uint32_t)(c.soma / c.conta);
    bool ok = saidas == S1_SIT_AMOSTRA_N && fora == 0 && media <= BANCADA_ORCAMENTO_RESPIRACAO;
    char linha[160];
    int n = snprintf(linha, sizeof linha,
                     "# bancada respiracao: %lu estimativas (esperado %lu), %lu diferentes, "
                     "erro max %lu milesimos de rpm\n",
                     (unsigned long)saidas, (unsigned long)S1_SIT_AMOSTRA_N, (unsigned long)fora,
                     (unsigned long)(pior * 1000.0f + 0.5f));
    serial_escreve(linha, (uint32_t)n);
    n = snprintf(linha, sizeof linha,
                 "# bancada respiracao: ciclos por amostra med %lu max %lu (orcamento %lu): %s\n",
                 (unsigned long)media, (unsigned long)c.max,
                 (unsigned long)BANCADA_ORCAMENTO_RESPIRACAO, ok ? "OK" : "FALHOU");
    serial_escreve(linha, (uint32_t)n);
    serial_envia();
    return ok;
}

#endif /* BANCADA_RESPIRACAO */
