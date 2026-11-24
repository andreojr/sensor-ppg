/* hrv_freq.c: LF/HF numa janela deslizante. Ver hrv_freq.h. */
#include "hrv/hrv_freq.h"

#include <math.h>
#include <string.h>

#define PI_F 3.14159265358979f
/* Amostras de 100 Hz entre duas amostras da série reamostrada. */
#define PASSO_AMOSTRAS ((float)PPG_FS_HZ / (float)HRV_FREQ_FS_REAMOSTRA)

_Static_assert(HRV_FREQ_PASSOS_GOERTZEL * HRV_FREQ_K_POR_PASSO >= HRV_FREQ_K_FIM - HRV_FREQ_K_LF + 1u,
               "os passos do Goertzel não cobrem as frequências das bandas");

void hrv_freq_init(hrv_freq_t *h)
{
    memset(h, 0, sizeof *h);
}

/* Tira os `quantos` RR mais antigos (os vetores ficam contíguos). */
static void tira_antigos(hrv_freq_t *h, uint32_t quantos)
{
    uint32_t resto = h->conta - quantos;
    memmove(h->n, h->n + quantos, resto * sizeof h->n[0]);
    memmove(h->fracao, h->fracao + quantos, resto * sizeof h->fracao[0]);
    memmove(h->rr, h->rr + quantos, resto * sizeof h->rr[0]);
    h->conta = resto;
}

static bool aceita(const hrv_freq_t *h, const ppg_batimento_t *b)
{
    if (!(b->rr_valido && isfinite(b->rr_ms) && b->rr_ms >= HRV_RR_MIN_MS &&
          b->rr_ms <= HRV_RR_MAX_MS))
        return false;
    /* O instante tem que andar pra frente: a spline não aceita dois pontos
       no mesmo instante. */
    if (h->conta == 0)
        return true;
    uint32_t u = h->conta - 1u;
    return b->n_pico > h->n[u] || (b->n_pico == h->n[u] && b->fracao > h->fracao[u]);
}

/*
 * Spline cúbica natural pelos pontos (t[i], v[i]), i = 0..m-1: calcula a
 * segunda derivada mm[i] em cada ponto (mm[0] = mm[m-1] = 0, "natural"). O
 * sistema é tridiagonal e sai com o algoritmo de Thomas (eliminação de Gauss
 * sem pivô): uma ida e uma volta. c guarda os coeficientes da ida.
 */
static void spline(const float *t, const float *v, float *mm, float *c, uint32_t m)
{
    mm[0] = 0.0f;
    mm[m - 1u] = 0.0f;
    for (uint32_t i = 1; i + 1u < m; i++) {
        float h0 = t[i] - t[i - 1u];
        float h1 = t[i + 1u] - t[i];
        float d = 6.0f * ((v[i + 1u] - v[i]) / h1 - (v[i] - v[i - 1u]) / h0);
        float b = 2.0f * (h0 + h1);
        if (i > 1u) { /* elimina com a linha anterior */
            b -= h0 * c[i - 1u];
            d -= h0 * mm[i - 1u];
        }
        c[i] = h1 / b;
        mm[i] = d / b;
    }
    for (uint32_t i = m - 2u; i >= 1u; i--) /* volta */
        mm[i] -= c[i] * mm[i + 1u];
}

/* Valor da spline em x, no trecho [t[i], t[i+1]]. */
static float avalia(const float *t, const float *v, const float *mm, uint32_t i, float x)
{
    float d = t[i + 1u] - t[i];
    float a = (t[i + 1u] - x) / d;
    float b = (x - t[i]) / d;
    return a * v[i] + b * v[i + 1u] +
           ((a * a * a - a) * mm[i] + (b * b * b - b) * mm[i + 1u]) * d * d / 6.0f;
}

/*
 * Copia a janela pra área de trabalho: t[] (instantes) e aux[] (RR menos a
 * média), e o tamanho da série reamostrada. Daqui em diante a conta não lê mais
 * n[], fracao[] nem rr[].
 */
static void copia_janela(hrv_freq_t *h)
{
    uint32_t m = h->conta;
    /* Instantes relativos ao primeiro RR. Subtrai os inteiros antes: em
       float32, n_pico / 100 perderia os milissegundos depois de ~2 dias. */
    for (uint32_t i = 0; i < m; i++)
        h->t[i] = ((float)(h->n[i] - h->n[0]) + (h->fracao[i] - h->fracao[0])) / (float)PPG_FS_HZ;

    /* A spline é linear nos valores: tirar a média antes não muda o
       resultado (a reta sai depois) e deixa os números pequenos em float32. */
    float media = 0.0f;
    for (uint32_t i = 0; i < m; i++)
        media += h->rr[i];
    media /= (float)m;
    for (uint32_t i = 0; i < m; i++)
        h->aux[i] = h->rr[i] - media;

    float d_amostras = (float)(h->n[m - 1u] - h->n[0]) + (h->fracao[m - 1u] - h->fracao[0]);
    uint32_t n = (uint32_t)floorf(d_amostras / PASSO_AMOSTRAS) + 1u;
    h->pontos = m;
    h->amostras = n > HRV_FREQ_N_MAX ? HRV_FREQ_N_MAX : n;
}

/* A spline pelos pontos copiados -> série regular y[0..amostras-1] a
   HRV_FREQ_FS_REAMOSTRA. */
static void reamostra(hrv_freq_t *h)
{
    uint32_t i = 0;
    for (uint32_t j = 0; j < h->amostras; j++) {
        float x = (float)j / (float)HRV_FREQ_FS_REAMOSTRA;
        while (i + 2u < h->pontos && x > h->t[i + 1u])
            i++;
        h->y[j] = avalia(h->t, h->aux, h->m, i, x);
    }
}

/* Tira a reta (mínimos quadrados) e aplica a janela de Hann simétrica. */
static void prepara(float *y, uint32_t n)
{
    float centro = 0.5f * (float)(n - 1u);
    float media = 0.0f;
    for (uint32_t j = 0; j < n; j++)
        media += y[j];
    media /= (float)n;
    float suy = 0.0f;
    for (uint32_t j = 0; j < n; j++)
        suy += ((float)j - centro) * (y[j] - media);
    float suu = (float)n * ((float)n * (float)n - 1.0f) / 12.0f; /* soma de (j - centro)² */
    float incl = suy / suu;
    for (uint32_t j = 0; j < n; j++) {
        float hann = 0.5f - 0.5f * cosf(2.0f * PI_F * (float)j / (float)(n - 1u));
        y[j] = (y[j] - media - incl * ((float)j - centro)) * hann;
    }
}

/*
 * Goertzel: o |X(f)|² de uma frequência só, com uma multiplicação por amostra.
 * É um ressonador de 2ª ordem, s[j] = y[j] + 2 cos(w) s[j-1] - s[j-2]; no fim,
 * |X|² = s1² + s2² - 2 cos(w) s1 s2.
 */
static float goertzel(const float *y, uint32_t n, float w)
{
    float coef = 2.0f * cosf(w);
    float s1 = 0.0f, s2 = 0.0f;
    for (uint32_t j = 0; j < n; j++) {
        float s0 = y[j] + coef * s1 - s2;
        s2 = s1;
        s1 = s0;
    }
    return s1 * s1 + s2 * s2 - coef * s1 * s2;
}

/* Soma |X(f_k)|² de k = k0 até k1 - 1 em *lf (k < HRV_FREQ_K_HF) ou *hf, na
   ordem de k: a conta de uma vez e a espalhada somam na mesma ordem. */
static void soma_bandas(const float *y, uint32_t n, uint32_t k0, uint32_t k1, float *lf,
                        float *hf)
{
    const float passo = 2.0f * PI_F / (float)(HRV_FREQ_JANELA_S * HRV_FREQ_FS_REAMOSTRA);
    for (uint32_t k = k0; k < k1; k++) {
        float p = goertzel(y, n, passo * (float)k);
        if (k < HRV_FREQ_K_HF)
            *lf += p;
        else
            *hf += p;
    }
}

void hrv_freq_potencias(const float *y, uint32_t n, float *lf, float *hf)
{
    *lf = 0.0f;
    *hf = 0.0f;
    soma_bandas(y, n, HRV_FREQ_K_LF, HRV_FREQ_K_FIM + 1u, lf, hf);
}

void hrv_freq_comeca(hrv_freq_t *h)
{
    float soma = 0.0f;
    for (uint32_t i = 0; i < h->conta; i++)
        soma += h->rr[i];
    h->cobre = soma >= HRV_FREQ_COBERTURA_MIN * (float)HRV_FREQ_JANELA_S * 1000.0f;
    if (h->cobre)
        copia_janela(h);
    h->k = HRV_FREQ_K_LF;
    h->soma_lf = 0.0f;
    h->soma_hf = 0.0f;
    h->etapa = 1u;
}

bool hrv_freq_calculando(const hrv_freq_t *h)
{
    return h->etapa != 0u;
}

bool hrv_freq_passo(hrv_freq_t *h, ppg_hrv_t *s)
{
    if (h->etapa == 0u)
        return false;
    if (h->cobre) {
        if (h->etapa == 1u) {
            spline(h->t, h->aux, h->m, h->y, h->pontos); /* y de rascunho */
        } else if (h->etapa == 2u) {
            reamostra(h); /* sobrescreve o rascunho */
        } else if (h->etapa == 3u) {
            prepara(h->y, h->amostras);
        } else {
            uint32_t fim = h->k + HRV_FREQ_K_POR_PASSO;
            if (fim > HRV_FREQ_K_FIM + 1u)
                fim = HRV_FREQ_K_FIM + 1u;
            soma_bandas(h->y, h->amostras, h->k, fim, &h->soma_lf, &h->soma_hf);
            h->k = fim;
        }
    }
    if (h->etapa < HRV_FREQ_PASSOS) {
        h->etapa++;
        return false;
    }
    h->etapa = 0u;
    s->lf_hf_valido = false;
    s->lf_hf = 0.0f;
    float lf = h->soma_lf, hf = h->soma_hf;
    if (h->cobre && hf > 0.0f && isfinite(lf) && isfinite(hf)) {
        s->lf_hf_valido = true;
        s->lf_hf = lf / hf;
    }
    return true;
}

bool hrv_freq_processa(hrv_freq_t *h, const ppg_batimento_t *b, ppg_hrv_t *s)
{
    if (!hrv_freq_guarda(h, b))
        return false;
    hrv_freq_comeca(h);
    while (!hrv_freq_passo(h, s)) {
    }
    return true;
}

bool hrv_freq_guarda(hrv_freq_t *h, const ppg_batimento_t *b)
{
    if (!b->valido)
        return false;
    if (h->tem_n && b->n_pico < h->ultimo_n)
        hrv_freq_init(h); /* a fonte recomeçou */
    h->tem_n = true;
    h->ultimo_n = b->n_pico;

    uint32_t velhos = 0;
    while (velhos < h->conta && b->n_pico - h->n[velhos] >= HRV_FREQ_JANELA_AMOSTRAS)
        velhos++;
    if (velhos > 0u)
        tira_antigos(h, velhos);

    if (aceita(h, b)) {
        if (h->conta == HRV_FREQ_CAP)
            tira_antigos(h, 1u);
        h->n[h->conta] = b->n_pico;
        h->fracao[h->conta] = b->fracao;
        h->rr[h->conta] = b->rr_ms;
        h->conta++;
    }
    return true;
}
