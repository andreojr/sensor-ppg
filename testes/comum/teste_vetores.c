/* Prova de ida e volta do formato dos vetores: o C lê o que o Python gerou. */
#include <stdint.h>
#include <stdio.h>
#include "confere.h"
#include "vetores/exemplo.h"

int main(void)
{
    float obtido[EXEMPLO_ENTRADA_N];
    for (uint32_t i = 0; i < EXEMPLO_ENTRADA_N; i++)
        obtido[i] = 2.0f * exemplo_entrada[i];

    int32_t indices[EXEMPLO_INDICES_N];
    for (uint32_t i = 0; i < EXEMPLO_INDICES_N; i++)
        indices[i] = (int32_t)(i * 100u);

    int falhas = confere_float("esperado", obtido, exemplo_esperado,
                               EXEMPLO_ESPERADO_N, EXEMPLO_TOL)
               + confere_int("indices", indices, exemplo_indices, EXEMPLO_INDICES_N);
    return falhas ? 1 : 0;
}
