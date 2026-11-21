/*
 * confere.h: compara a saída do C com um vetor de referência do Python
 * (testes/<módulo>/vetores/<caso>.h, gerado por analise/src/analise/vetores.py).
 *
 *   #include "confere.h"
 *   #include "vetores/trecho_1.h"
 *   ...
 *   int falhas = confere_float("saida", obtido, trecho_1_esperado,
 *                              TRECHO_1_ESPERADO_N, TRECHO_1_TOL);
 *   return falhas ? 1 : 0;
 *
 * Retorna o número de posições diferentes e imprime as primeiras.
 */
#ifndef TESTES_CONFERE_H
#define TESTES_CONFERE_H

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#define CONFERE_MOSTRA 5 /* quantas divergências imprimir */

static inline int confere_float(const char *nome, const float *obtido,
                                const float *esperado, size_t n, float tol)
{
    int falhas = 0;
    float pior = 0.0f;
    for (size_t i = 0; i < n; i++) {
        float erro = fabsf(obtido[i] - esperado[i]);
        if (!(erro <= tol)) { /* NaN também falha */
            if (falhas < CONFERE_MOSTRA)
                printf("%s[%zu]: obtido %.9g, esperado %.9g (erro %.3g > tol %.3g)\n",
                       nome, i, (double)obtido[i], (double)esperado[i],
                       (double)erro, (double)tol);
            falhas++;
        }
        if (erro > pior)
            pior = erro;
    }
    printf("%s: %zu amostras, %d fora da tolerância, maior erro %.3g\n",
           nome, n, falhas, (double)pior);
    return falhas;
}

static inline int confere_int(const char *nome, const int32_t *obtido,
                              const int32_t *esperado, size_t n)
{
    int falhas = 0;
    for (size_t i = 0; i < n; i++) {
        if (obtido[i] != esperado[i]) {
            if (falhas < CONFERE_MOSTRA)
                printf("%s[%zu]: obtido %ld, esperado %ld\n", nome, i,
                       (long)obtido[i], (long)esperado[i]);
            falhas++;
        }
    }
    printf("%s: %zu valores, %d diferentes\n", nome, n, falhas);
    return falhas;
}

#endif /* TESTES_CONFERE_H */
