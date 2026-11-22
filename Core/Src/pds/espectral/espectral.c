/*
 * espectral: ver espectral.h. Constantes e ordem das contas iguais às de
 * espectral.py; mudou lá, muda aqui (e regenere os vetores de testes/espectral/).
 */
#include "espectral/espectral.h"

#include <math.h>

/* Banda de 0,7 a 3,5 Hz em bins da FFT de 1024 pontos a 100 Hz (0,0977 Hz por bin):
   o primeiro bin com frequência >= 0,7 Hz é o 8 (0,78 Hz) e o primeiro >= 3,5 Hz é o 36. */
#define K0 8u
#define K1 36u
#define PROMINENCIA_MIN 0.3 /* em double, como no Python */
#define PI_F 3.14159265358979323846f

_Static_assert(ESPECTRAL_JANELA <= ESPECTRAL_NFFT, "a janela tem mais amostras que a FFT");

bool espectral_init(espectral_t *e)
{
    if (!fft_init(&e->fft, ESPECTRAL_NFFT))
        return false;
    e->idx = 0;
    e->faltam = ESPECTRAL_JANELA;
    e->prominencia = 0.0f;
    for (uint32_t i = 0; i < ESPECTRAL_JANELA; i++) {
        e->buffer[i] = 0.0f;
        /* Hann sem os zeros das pontas: np.hanning(n + 2)[1:-1]. */
        e->hann[i] = 0.5f - 0.5f * cosf(2.0f * PI_F * (float)(i + 1u) / (float)(ESPECTRAL_JANELA + 1u));
    }
    return true;
}

float espectral_prominencia(const espectral_t *e)
{
    return e->prominencia;
}

static void estima(espectral_t *e, ppg_bpm_t *saida)
{
    /* Janela em ordem do tempo: a mais antiga primeiro (a que vai ser sobrescrita). */
    float soma = 0.0f;
    uint32_t j = e->idx;
    for (uint32_t i = 0; i < ESPECTRAL_JANELA; i++) {
        e->x[i] = e->buffer[j];
        soma += e->buffer[j];
        j = j + 1u == ESPECTRAL_JANELA ? 0u : j + 1u;
    }
    const float media = soma / (float)ESPECTRAL_JANELA;
    for (uint32_t i = 0; i < ESPECTRAL_JANELA; i++)
        e->x[i] = (e->x[i] - media) * e->hann[i];
    for (uint32_t i = ESPECTRAL_JANELA; i < ESPECTRAL_NFFT; i++)
        e->x[i] = 0.0f;

    fft_potencia(&e->fft, e->x, e->trabalho); /* x[0..n/2] = |X[k]|^2 */

    /* Maior pico na banda (o primeiro, se empatar) e a potência total dela. */
    float banda = 0.0f;
    uint32_t k = K0;
    for (uint32_t i = K0; i < K1; i++) {
        banda += e->x[i];
        if (e->x[i] > e->x[k])
            k = i;
    }
    if (banda <= 0.0f) {
        e->prominencia = 0.0f;
        saida->valido = false;
        saida->bpm = 0.0f;
        return;
    }

    const float a = e->x[k - 1u];
    const float b = e->x[k];
    const float c = e->x[k + 1u];
    const float prominencia = (a + b + c) / banda;
    e->prominencia = prominencia;

    /* Vértice da parábola por (k-1, k, k+1), no log da amplitude. */
    const float la = logf(a > 1e-30f ? a : 1e-30f) / 2.0f;
    const float lb = logf(b > 1e-30f ? b : 1e-30f) / 2.0f;
    const float lc = logf(c > 1e-30f ? c : 1e-30f) / 2.0f;
    const float den = la - 2.0f * lb + lc;
    const float d = den != 0.0f ? 0.5f * (la - lc) / den : 0.0f;
    const float f_hz = ((float)k + d) * (float)PPG_FS_HZ / (float)ESPECTRAL_NFFT;

    saida->valido = (double)prominencia >= PROMINENCIA_MIN;
    saida->bpm = saida->valido ? 60.0f * f_hz : 0.0f;
}

bool espectral_processa(espectral_t *e, const ppg_amostra_t *filtrado, ppg_bpm_t *saida)
{
    e->buffer[e->idx] = filtrado->ir;
    e->idx = e->idx + 1u == ESPECTRAL_JANELA ? 0u : e->idx + 1u;

    if (--e->faltam != 0u)
        return false;
    e->faltam = ESPECTRAL_HOP;
    estima(e, saida);
    return true;
}
