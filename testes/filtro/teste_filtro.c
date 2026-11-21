/*
 * Teste do filtro no PC: a saída do C bate com a do protótipo em Python
 * (vetor gerado por `uv run python -m analise.filtro --vetores`).
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include "confere.h"
#include "filtro/filtro.h"
#include "vetores/bruto_100hz.h"

static float obtido_ir[BRUTO_100HZ_IR_N];
static float obtido_vermelho[BRUTO_100HZ_IR_N];

/* Fonte falsa: 60 s de bruto, saída a saída, n igual ao da entrada. */
static int fonte_falsa(void)
{
    static filtro_t f;
    filtro_init(&f);
    int n_errado = 0;
    for (uint32_t i = 0; i < BRUTO_100HZ_IR_N; i++) {
        ppg_amostra_t e = {i + 1000u, bruto_100hz_ir[i], bruto_100hz_vermelho[i]}, s;
        if (!filtro_processa(&f, &e, &s) || s.n != e.n)
            n_errado++;
        obtido_ir[i] = s.ir;
        obtido_vermelho[i] = s.vermelho;
    }
    printf("n repetido da entrada: %d errados\n", n_errado);
    return n_errado
         + confere_float("ir", obtido_ir, bruto_100hz_esperado_ir, BRUTO_100HZ_ESPERADO_IR_N,
                         BRUTO_100HZ_TOL)
         + confere_float("vermelho", obtido_vermelho, bruto_100hz_esperado_vermelho,
                         BRUTO_100HZ_ESPERADO_VERMELHO_N, BRUTO_100HZ_TOL);
}

/* DC constante (até o fundo de escala do ADC): sai exatamente 0. */
static int dc_zero(void)
{
    static filtro_t f;
    filtro_init(&f);
    int falhas = 0;
    for (uint32_t i = 0; i < 1000u; i++) {
        ppg_amostra_t e = {i, 262143.0f, 100000.0f}, s;
        filtro_processa(&f, &e, &s);
        falhas += s.ir != 0.0f || s.vermelho != 0.0f;
    }
    printf("DC: %d saídas diferentes de 0\n", falhas);
    return falhas;
}

/* DC que muda depois da primeira amostra (0, depois o fundo de escala): o
   histórico guarda desvios de ~2,6e5 e a soma em float tem que zerar quase
   exato quando a janela enche. */
static int dc_degrau(void)
{
    static filtro_t f;
    filtro_init(&f);
    float pior = 0.0f;
    for (uint32_t i = 0; i < 1000u; i++) {
        ppg_amostra_t e = {i, i ? 262143.0f : 0.0f, i ? 262143.0f : 0.0f}, s;
        filtro_processa(&f, &e, &s);
        if (i >= 2u * (uint32_t)PPG_ATRASO_AMOSTRAS + 1u) {
            pior = fmaxf(pior, fmaxf(fabsf(s.ir), fabsf(s.vermelho)));
        }
    }
    printf("DC em degrau: pior saída depois da janela %g\n", (double)pior);
    return !(pior < 0.5f);
}

/* Senoide de 1,5 Hz no meio da banda: sai com o mesmo tamanho, atrasada de
   exatamente PPG_ATRASO_AMOSTRAS. A 0,05 Hz (deriva), quase some. */
static int senoide(float f_hz, float ganho_min, float ganho_max, int confere_atraso)
{
    static filtro_t f;
    filtro_init(&f);
    const float w = 2.0f * 3.14159265f * f_hz / (float)PPG_FS_HZ;
    float pior = 0.0f, pico = 0.0f;
    for (uint32_t i = 0; i < 6000u; i++) {
        ppg_amostra_t e = {i, 100000.0f + 1000.0f * sinf(w * (float)i), 0.0f}, s;
        filtro_processa(&f, &e, &s);
        if (i < 2000u)
            continue; /* enche o FIR e passa o transiente */
        float esperado = 1000.0f * sinf(w * ((float)i - PPG_ATRASO_AMOSTRAS));
        if (fabsf(s.ir) > pico)
            pico = fabsf(s.ir);
        if (fabsf(s.ir - esperado) > pior)
            pior = fabsf(s.ir - esperado);
    }
    float ganho = pico / 1000.0f;
    int falhas = ganho < ganho_min || ganho > ganho_max || (confere_atraso && pior > 15.0f);
    printf("senoide %.2f Hz: ganho %.4f, erro contra o atraso de %.0f amostras %.2f%s\n",
           (double)f_hz, (double)ganho, (double)PPG_ATRASO_AMOSTRAS, (double)pior,
           falhas ? " ERRO" : "");
    return falhas;
}

/* Chamar o init de novo reinicia: o histórico antigo não vaza. */
static int reinicia(void)
{
    static filtro_t f;
    filtro_init(&f);
    ppg_amostra_t a = {0, 5000.0f, 5000.0f}, b = {0, 200000.0f, 200000.0f}, s;
    for (int i = 0; i < 500; i++)
        filtro_processa(&f, &a, &s);
    filtro_init(&f);
    filtro_processa(&f, &b, &s);
    int falhas = s.ir != 0.0f;
    printf("reinicia: %.3f%s\n", (double)s.ir, falhas ? " ERRO" : "");
    return falhas;
}

int main(void)
{
    int falhas = fonte_falsa() + dc_zero() + dc_degrau() + reinicia();
    falhas += senoide(1.5f, 0.99f, 1.01f, 1);
    falhas += senoide(0.05f, 0.0f, 0.01f, 0); /* -43 dB */
    falhas += senoide(6.0f, 0.0f, 0.001f, 0); /* -73 dB */
    printf(falhas ? "FALHOU\n" : "ok\n");
    return falhas ? 1 : 0;
}
