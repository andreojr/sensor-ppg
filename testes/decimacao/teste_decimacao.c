/*
 * Teste da decimação no PC: a saída do C bate com a do protótipo em Python
 * (vetores gerados por `uv run python -m analise.decimacao --vetores`).
 */
#include <stdint.h>
#include <stdio.h>
#include "confere.h"
#include "decimacao/decimacao.h"
#include "vetores/physionet_500hz.h"
#include "vetores/sensor_400hz.h"

#define SAIDA_MAX 1000u

static float obtido_ir[SAIDA_MAX];
static float obtido_vermelho[SAIDA_MAX];

/* Roda a decimação na entrada toda; devolve quantas saídas, -1 se o n pular. */
static int roda(uint32_t fs, const int32_t *ir, const int32_t *vermelho, uint32_t n)
{
    decimacao_t d;
    if (!decimacao_init(&d, fs)) {
        printf("init(%u) falhou\n", (unsigned)fs);
        return -1;
    }
    uint32_t saidas = 0;
    for (uint32_t i = 0; i < n; i++) {
        decimacao_entrada_t e = {(uint32_t)ir[i], (uint32_t)vermelho[i]};
        ppg_amostra_t s;
        if (!decimacao_processa(&d, &e, &s))
            continue;
        if (s.n != saidas || saidas >= SAIDA_MAX) {
            printf("n = %u na saída %u\n", (unsigned)s.n, (unsigned)saidas);
            return -1;
        }
        obtido_ir[saidas] = s.ir;
        obtido_vermelho[saidas++] = s.vermelho;
    }
    return (int)saidas;
}

static int caso(const char *nome, uint32_t fs, const int32_t *ir, const int32_t *vermelho,
                uint32_t n, const float *esp_ir, const float *esp_vermelho, uint32_t n_esp,
                float tol)
{
    printf("-- %s (%u Hz)\n", nome, (unsigned)fs);
    int saidas = roda(fs, ir, vermelho, n);
    if (saidas != (int)n_esp) {
        printf("%d saídas, esperado %u\n", saidas, (unsigned)n_esp);
        return 1;
    }
    return confere_float("ir", obtido_ir, esp_ir, n_esp, tol)
         + confere_float("vermelho", obtido_vermelho, esp_vermelho, n_esp, tol);
}

/* Taxa sem filtro: init devolve false e processa nunca solta saída. */
static int taxa_invalida(void)
{
    const uint32_t taxas[] = {0u, 100u, 250u, 450u, 800u};
    decimacao_entrada_t e = {100000u, 90000u};
    ppg_amostra_t s;
    int falhas = 0;
    for (uint32_t t = 0; t < sizeof taxas / sizeof taxas[0]; t++) {
        decimacao_t d;
        bool ok = decimacao_init(&d, taxas[t]);
        for (int i = 0; i < 100; i++)
            ok = ok || decimacao_processa(&d, &e, &s);
        if (ok) {
            printf("taxa %u aceita\n", (unsigned)taxas[t]);
            falhas++;
        }
    }
    printf("taxas inválidas: %d aceitas\n", falhas);
    return falhas;
}

/* DC na entrada sai exatamente igual, desde a primeira saída. */
static int dc_exato(uint32_t fs)
{
    decimacao_t d;
    decimacao_init(&d, fs);
    decimacao_entrada_t e = {262143u, 1234u};
    ppg_amostra_t s;
    int falhas = 0, saidas = 0;
    for (int i = 0; i < 2000; i++) {
        if (decimacao_processa(&d, &e, &s)) {
            saidas++;
            falhas += s.ir != 262143.0f || s.vermelho != 1234.0f;
        }
    }
    printf("DC a %u Hz: %d saídas, %d diferentes\n", (unsigned)fs, saidas, falhas);
    return falhas + (saidas != 2000 / (int)(fs / PPG_FS_HZ) - (int)DECIMACAO_LATENCIA_SAIDA);
}

/* Degrau de 1000: antes da janela chegar nele, sai o nível antigo; depois, o novo. */
static int degrau(void)
{
    decimacao_t d;
    decimacao_init(&d, 400u);
    ppg_amostra_t s;
    int falhas = 0;
    for (uint32_t i = 0; i < 400u; i++) {
        decimacao_entrada_t e = {i < 200u ? 100000u : 101000u, 50000u};
        if (!decimacao_processa(&d, &e, &s))
            continue;
        /* A saída n olha as entradas 4n - 24 a 4n + 24; o degrau está na 200. */
        float esperado = s.n * 4u + 24u < 200u ? 100000.0f : s.n * 4u >= 224u ? 101000.0f : -1.0f;
        if (esperado > 0.0f && fabsf(s.ir - esperado) > 0.01f) {
            printf("degrau: n = %u deu %.3f, esperado %.0f\n", (unsigned)s.n, (double)s.ir,
                   (double)esperado);
            falhas++;
        }
    }
    printf("degrau: %d fora\n", falhas);
    return falhas;
}

/* Chamar o init de novo reinicia: o n volta a 0 e o histórico é esquecido. */
static int reinicia(void)
{
    decimacao_t d;
    decimacao_init(&d, 500u);
    decimacao_entrada_t a = {10000u, 10000u}, b = {200000u, 200000u};
    ppg_amostra_t s;
    for (int i = 0; i < 1000; i++)
        decimacao_processa(&d, &a, &s);
    decimacao_init(&d, 500u);
    while (!decimacao_processa(&d, &b, &s)) {
    }
    int falhas = s.n != 0u || s.ir != 200000.0f;
    printf("reinicia: n = %u, ir = %.1f%s\n", (unsigned)s.n, (double)s.ir, falhas ? " ERRO" : "");
    return falhas;
}

int main(void)
{
    int falhas = 0;
    falhas += caso("fonte falsa", 400u, sensor_400hz_ir, sensor_400hz_vermelho,
                   SENSOR_400HZ_IR_N, sensor_400hz_esperado_ir, sensor_400hz_esperado_vermelho,
                   SENSOR_400HZ_ESPERADO_IR_N, SENSOR_400HZ_TOL);
    falhas += caso("physionet", 500u, physionet_500hz_ir, physionet_500hz_vermelho,
                   PHYSIONET_500HZ_IR_N, physionet_500hz_esperado_ir,
                   physionet_500hz_esperado_vermelho, PHYSIONET_500HZ_ESPERADO_IR_N,
                   PHYSIONET_500HZ_TOL);
    falhas += taxa_invalida();
    falhas += dc_exato(400u) + dc_exato(500u);
    falhas += degrau();
    falhas += reinicia();
    printf(falhas ? "FALHOU\n" : "ok\n");
    return falhas ? 1 : 0;
}
