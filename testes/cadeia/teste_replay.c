/*
 * Teste do replay (as cruas de uma captura de novo pela decimação e pela cadeia,
 * no PC): o bruto bate com o vetor da decimação, um salto no n é preenchido com
 * a última amostra (como a placa faz com as perdidas) e um n que volta a 0
 * (a placa resetou) reinicia tudo.
 */
#define _GNU_SOURCE
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cadeia/replay.h"
#include "../decimacao/vetores/sensor_400hz.h"

static int falhas;
static replay_t r; /* ~25 KB */

/* Roda as cruas e devolve o texto que saiu (malloc; quem chama libera). */
static char *roda(const uint32_t *n, const int32_t *ir, const int32_t *vm, uint32_t total)
{
    char *texto = NULL;
    size_t tam = 0;
    FILE *out = open_memstream(&texto, &tam);
    if (!replay_init(&r))
        falhas++;
    for (uint32_t i = 0; i < total; i++)
        replay_amostra(&r, n[i], (uint32_t)ir[i], (uint32_t)vm[i], out);
    fclose(out);
    return texto;
}

/* Os "b," do texto: n e ir. Devolve quantos. */
static uint32_t brutos(const char *texto, uint32_t *n, float *ir, uint32_t max)
{
    uint32_t k = 0;
    for (const char *p = texto; p && *p; p = strchr(p, '\n') ? strchr(p, '\n') + 1 : NULL) {
        unsigned long nn;
        float a, b;
        if (k < max && sscanf(p, "b,%lu,%f,%f", &nn, &a, &b) == 3) {
            n[k] = (uint32_t)nn;
            ir[k] = a;
            k++;
        }
    }
    return k;
}

static uint32_t ns[SENSOR_400HZ_IR_N + 8u];
static uint32_t bn[2048];
static float bir[2048];

static void bate_com_a_decimacao(void)
{
    for (uint32_t i = 0; i < SENSOR_400HZ_IR_N; i++)
        ns[i] = i;
    char *t = roda(ns, sensor_400hz_ir, sensor_400hz_vermelho, SENSOR_400HZ_IR_N);
    uint32_t k = brutos(t, bn, bir, 2048u);
    if (k != SENSOR_400HZ_ESPERADO_IR_N) {
        printf("decimação: %lu linhas b, esperadas %u\n", (unsigned long)k,
               SENSOR_400HZ_ESPERADO_IR_N);
        falhas++;
    }
    int fora = 0;
    for (uint32_t i = 0; i < k && i < SENSOR_400HZ_ESPERADO_IR_N; i++)
        if (bn[i] != i || fabsf(bir[i] - sensor_400hz_esperado_ir[i]) > SENSOR_400HZ_TOL + 0.005f)
            fora++;
    if (fora) {
        printf("decimação: %d linhas b diferentes\n", fora);
        falhas++;
    }
    if (strstr(t, "\nf,") == NULL) {
        printf("replay sem as linhas f,\n");
        falhas++;
    }
    free(t);
}

static void salto_e_preenchido(void)
{
    /* Com 3 amostras "perdidas" (salto de 3 no n), a placa repete a última no lugar
       delas: sai o mesmo número de brutos que 2003 cruas contínuas, com n contínuo. */
    for (uint32_t i = 0; i < 2003u; i++)
        ns[i] = i;
    char *c = roda(ns, sensor_400hz_ir, sensor_400hz_vermelho, 2003u);
    uint32_t esperado = brutos(c, bn, bir, 2048u);
    free(c);

    for (uint32_t i = 0; i < 2000u; i++)
        ns[i] = i < 1000u ? i : i + 3u;
    char *t = roda(ns, sensor_400hz_ir, sensor_400hz_vermelho, 2000u);
    uint32_t k = brutos(t, bn, bir, 2048u);
    int fora = k != esperado;
    for (uint32_t i = 0; i < k; i++)
        fora += bn[i] != i;
    if (fora) {
        printf("salto: %lu linhas b (esperadas %lu), %d problemas\n", (unsigned long)k,
               (unsigned long)esperado, fora);
        falhas++;
    }
    free(t);
}

static void reset_reinicia(void)
{
    /* 800 cruas, a placa reseta (n volta a 0) e mais 800: o bruto recomeça do 0. */
    for (uint32_t i = 0; i < 1600u; i++)
        ns[i] = i < 800u ? i : i - 800u;
    char *t = roda(ns, sensor_400hz_ir, sensor_400hz_vermelho, 1600u);
    uint32_t k = brutos(t, bn, bir, 2048u);
    uint32_t meia = 800u / 4u - DECIMACAO_LATENCIA_SAIDA;
    if (k != 2u * meia || bn[meia] != 0u) {
        printf("reset: %lu linhas b (esperadas %lu), n depois do reset %lu\n", (unsigned long)k,
               (unsigned long)(2u * meia), (unsigned long)(k > meia ? bn[meia] : 0u));
        falhas++;
    }
    free(t);
}

int main(void)
{
    bate_com_a_decimacao();
    salto_e_preenchido();
    reset_reinicia();
    printf("%s\n", falhas ? "FALHOU" : "OK");
    return falhas ? 1 : 0;
}
