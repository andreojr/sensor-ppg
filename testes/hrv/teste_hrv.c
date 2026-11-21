/*
 * Teste do HRV no PC: a saída do C bate com a do protótipo em Python
 * (vetores gerados por `uv run python -m analise.hrv --vetores`), mais casos
 * de borda conferidos aqui mesmo.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include "confere.h"
#include "hrv/hrv.h"
#include "vetores/bordas.h"
#include "vetores/s1_sit.h"

#define BATIMENTOS_MAX 1000u

static int32_t obt_escreveu[BATIMENTOS_MAX];
static int32_t obt_valido[BATIMENTOS_MAX];
static float obt_sdnn[BATIMENTOS_MAX];
static float obt_rmssd[BATIMENTOS_MAX];

/* Roda o HRV num vetor de batimentos e confere as quatro saídas. */
static int caso(const char *nome, uint32_t n, const int32_t *valido, const int32_t *n_pico,
                const float *fracao, const int32_t *rr_valido, const float *rr_ms,
                const int32_t *esp_escreveu, const int32_t *esp_valido, const float *esp_sdnn,
                const float *esp_rmssd, float tol)
{
    printf("-- %s\n", nome);
    if (n > BATIMENTOS_MAX) {
        printf("vetor grande demais\n");
        return 1;
    }
    hrv_t h;
    hrv_init(&h);
    uint32_t validos = 0;
    for (uint32_t i = 0; i < n; i++) {
        ppg_batimento_t b = {valido[i] != 0, (uint32_t)n_pico[i], fracao[i], rr_valido[i] != 0,
                             rr_ms[i]};
        ppg_hrv_t s = {0};
        obt_escreveu[i] = hrv_processa(&h, &b, &s);
        obt_valido[i] = s.valido;
        obt_sdnn[i] = s.sdnn_ms;
        obt_rmssd[i] = s.rmssd_ms;
        validos += s.valido;
    }
    printf("%u batimentos, %u saídas válidas\n", (unsigned)n, (unsigned)validos);
    return confere_int("escreveu", obt_escreveu, esp_escreveu, n)
         + confere_int("valido", obt_valido, esp_valido, n)
         + confere_float("sdnn", obt_sdnn, esp_sdnn, n, tol)
         + confere_float("rmssd", obt_rmssd, esp_rmssd, n, tol);
}

/* Alimenta batimentos com RR fixo; devolve a última saída. */
static ppg_hrv_t alimenta(hrv_t *h, uint32_t *n, uint32_t quantos, float rr_a, float rr_b)
{
    ppg_hrv_t s = {0};
    for (uint32_t k = 0; k < quantos; k++) {
        float rr = (k % 2) ? rr_a : rr_b;
        *n += (uint32_t)(rr / 10.0f + 0.5f);
        ppg_batimento_t b = {true, *n, 0.0f, true, rr};
        hrv_processa(h, &b, &s);
    }
    return s;
}

static int falha(const char *msg)
{
    printf("FALHOU: %s\n", msg);
    return 1;
}

/* Poucos batimentos: nunca fica válido, e LF/HF nunca é válido. */
static int poucos_batimentos(void)
{
    hrv_t h;
    hrv_init(&h);
    uint32_t n = 0;
    ppg_hrv_t s = alimenta(&h, &n, 40, 1000.0f, 1000.0f);
    if (s.valido || s.lf_hf_valido)
        return falha("40 s de batimentos já deu válido");
    s = alimenta(&h, &n, 10, 1000.0f, 1000.0f);
    if (!s.valido || s.lf_hf_valido)
        return falha("50 s de batimentos não deu válido");
    printf("poucos batimentos: ok\n");
    return 0;
}

/* RR alternando 800/850: RMSSD exatamente 50 ms. */
static int alternado(void)
{
    hrv_t h;
    hrv_init(&h);
    uint32_t n = 0;
    ppg_hrv_t s = alimenta(&h, &n, 120, 800.0f, 850.0f);
    if (!s.valido || fabsf(s.rmssd_ms - 50.0f) > 1e-3f || fabsf(s.sdnn_ms - 25.0f) > 0.5f)
        return falha("alternado 800/850");
    printf("alternado: rmssd %.4f sdnn %.4f ok\n", (double)s.rmssd_ms, (double)s.sdnn_ms);
    return 0;
}

/* RR inválido (NaN, infinito, rr_valido false) não entra e quebra a diferença. */
static int intervalo_invalido(void)
{
    const float ruins[] = {NAN, INFINITY, -INFINITY, 0.0f, 299.0f, 2001.0f};
    int falhas = 0;
    for (uint32_t r = 0; r < sizeof ruins / sizeof ruins[0]; r++) {
        hrv_t h;
        hrv_init(&h);
        uint32_t n = 0;
        alimenta(&h, &n, 60, 800.0f, 850.0f);
        uint32_t antes = h.conta;
        ppg_batimento_t b = {true, n + 80u, 0.0f, true, ruins[r]};
        ppg_hrv_t s;
        hrv_processa(&h, &b, &s);
        if (h.conta > antes || h.tem_rr || isnan(s.sdnn_ms) || isnan(s.rmssd_ms)) {
            printf("RR %g aceito\n", (double)ruins[r]);
            falhas++;
        }
    }
    /* rr_valido false com um RR bom: também fica de fora. */
    hrv_t h;
    hrv_init(&h);
    uint32_t n = 0;
    alimenta(&h, &n, 60, 800.0f, 850.0f);
    uint32_t antes = h.conta;
    ppg_batimento_t b = {true, n + 80u, 0.0f, false, 800.0f};
    ppg_hrv_t s;
    hrv_processa(&h, &b, &s);
    falhas += h.conta > antes || h.tem_rr;
    printf("intervalo inválido: %d aceitos\n", falhas);
    return falhas;
}

/* Batimento com valido false: devolve false, *s intocado, estado igual. */
static int batimento_invalido(void)
{
    hrv_t h;
    hrv_init(&h);
    uint32_t n = 0;
    alimenta(&h, &n, 60, 800.0f, 850.0f);
    uint32_t conta = h.conta;
    ppg_hrv_t s = {true, 123.0f, 456.0f, true, 7.0f};
    ppg_batimento_t b = {false, n + 80u, 0.0f, true, 800.0f};
    if (hrv_processa(&h, &b, &s) || s.sdnn_ms != 123.0f || h.conta != conta || h.ultimo_n != n)
        return falha("batimento inválido mexeu no estado ou na saída");
    printf("batimento inválido: ok\n");
    return 0;
}

/* Reinício: hrv_init de novo zera; n voltando pra trás também. */
static int reinicio(void)
{
    hrv_t h;
    hrv_init(&h);
    uint32_t n = 100000u;
    ppg_hrv_t s = alimenta(&h, &n, 80, 800.0f, 850.0f);
    if (!s.valido)
        return falha("não ficou válido antes do reinício");
    n = 10u;
    s = alimenta(&h, &n, 1, 800.0f, 800.0f);
    if (s.valido || h.conta != 1u)
        return falha("n voltando não reiniciou");
    hrv_init(&h);
    if (h.conta != 0u || h.tem_n || h.tem_rr)
        return falha("hrv_init não zerou");
    printf("reinício: ok\n");
    return 0;
}

int main(void)
{
    int falhas = 0;
    falhas += caso("s1_sit", S1_SIT_VALIDO_N, s1_sit_valido, s1_sit_n_pico, s1_sit_fracao,
                   s1_sit_rr_valido, s1_sit_rr_ms, s1_sit_escreveu, s1_sit_saida_valido,
                   s1_sit_sdnn, s1_sit_rmssd, S1_SIT_TOL);
    falhas += caso("bordas", BORDAS_VALIDO_N, bordas_valido, bordas_n_pico, bordas_fracao,
                   bordas_rr_valido, bordas_rr_ms, bordas_escreveu, bordas_saida_valido,
                   bordas_sdnn, bordas_rmssd, BORDAS_TOL);
    falhas += poucos_batimentos();
    falhas += alternado();
    falhas += intervalo_invalido();
    falhas += batimento_invalido();
    falhas += reinicio();
    printf(falhas ? "FALHOU (%d)\n" : "OK\n", falhas);
    return falhas ? 1 : 0;
}
