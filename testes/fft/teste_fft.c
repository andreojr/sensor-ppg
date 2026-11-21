/* fft: a potência da FFT do CMSIS (via fft_potencia) bate com a do NumPy. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "confere.h"
#include "fft/fft.h"
#include "vetores/n1024.h"
#include "vetores/n256.h"
#include "vetores/n512.h"
#include "vetores/ppg1024.h"

#define N_MAX 1024u

static int roda(const char *nome, uint16_t n, const float *entrada, const float *esperado,
                uint32_t n_esperado, float tol)
{
    static float x[N_MAX];
    static float trabalho[N_MAX];
    float obtido[N_MAX / 2u + 1u];

    fft_t f;
    if (!fft_init(&f, n) || fft_n(&f) != n) {
        printf("== %s: fft_init(%u) falhou\n", nome, (unsigned)n);
        return 1;
    }
    for (uint32_t i = 0; i < n; i++)
        x[i] = entrada[i];

    fft_potencia(&f, x, trabalho);

    /* O vetor vem dividido por n^2 (pico de uma senoide de amplitude 1 = 0,25). */
    const float escala = 1.0f / ((float)n * (float)n);
    for (uint32_t k = 0; k <= n / 2u; k++)
        obtido[k] = x[k] * escala;

    printf("== %s (%u pontos)\n", nome, (unsigned)n);
    if (n_esperado != n / 2u + 1u) {
        printf("tamanho esperado %u, mas a FFT dá %u valores\n", (unsigned)n_esperado,
               (unsigned)(n / 2u + 1u));
        return 1;
    }
    return confere_float("potencia", obtido, esperado, n_esperado, tol);
}

static int recusa(uint16_t n)
{
    fft_t f;
    if (fft_init(&f, n) || fft_n(&f) != 0u) {
        printf("fft_init(%u) devia recusar\n", (unsigned)n);
        return 1;
    }
    return 0;
}

int main(void)
{
    int falhas = 0;
    falhas += roda("n256", 256, n256_entrada, n256_potencia, N256_POTENCIA_N, N256_TOL);
    falhas += roda("n512", 512, n512_entrada, n512_potencia, N512_POTENCIA_N, N512_TOL);
    falhas += roda("n1024", 1024, n1024_entrada, n1024_potencia, N1024_POTENCIA_N, N1024_TOL);
    falhas += roda("ppg1024", 1024, ppg1024_entrada, ppg1024_potencia, PPG1024_POTENCIA_N,
                   PPG1024_TOL);

    /* Tamanhos que não estão compilados (ou nem são potência de 2). */
    falhas += recusa(0);
    falhas += recusa(300);
    falhas += recusa(1000);
    falhas += recusa(4096);

    return falhas ? 1 : 0;
}
