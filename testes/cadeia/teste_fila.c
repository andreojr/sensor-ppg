/* Teste da fila sensor -> cadeia e da conta de ciclos com volta do contador. */
#include <stdio.h>

#include "cadeia/ciclos.h"
#include "cadeia/fila.h"

static int falhas;

#define CONFERE(cond)                                                                       \
    if (!(cond)) {                                                                          \
        printf("falhou: %s (linha %d)\n", #cond, __LINE__);                                  \
        falhas++;                                                                           \
    }

static void cheia_descarta_a_nova(void)
{
    fila_t f;
    fila_init(&f);
    for (uint32_t i = 0; i < FILA_TAM; i++) {
        ppg_amostra_t a = {i, (float)i, 0.0f};
        CONFERE(fila_poe(&f, &a));
    }
    ppg_amostra_t extra = {99u, 99.0f, 0.0f};
    CONFERE(!fila_poe(&f, &extra));
    CONFERE(f.cheia == 1u);
    CONFERE(f.max == FILA_TAM);
    ppg_amostra_t a;
    for (uint32_t i = 0; i < FILA_TAM; i++) {
        CONFERE(fila_tira(&f, &a));
        CONFERE(a.n == i);
    }
    CONFERE(!fila_tira(&f, &a));
    fila_zera_medidas(&f);
    CONFERE(f.max == 0u && f.cheia == 0u);
}

static void anel_da_volta(void)
{
    fila_t f;
    fila_init(&f);
    uint32_t prox = 0;
    for (uint32_t i = 0; i < 40u; i++) {
        ppg_amostra_t a = {i, 0.0f, 0.0f};
        CONFERE(fila_poe(&f, &a));
        if (i % 3u != 0u) { /* esvazia às vezes, pra posição andar no anel */
            ppg_amostra_t b;
            while (fila_tira(&f, &b)) {
                CONFERE(b.n == prox);
                prox++;
            }
        }
    }
    CONFERE(f.max == 2u);
}

static void ciclos_com_volta(void)
{
    ciclos_t c = {0};
    uint32_t inicio = 0xFFFFFFF0u, fim = 5u;
    ciclos_conta(&c, fim - inicio);
    CONFERE(c.conta == 1u && c.max == 21u && c.soma == 21u);
}

int main(void)
{
    cheia_descarta_a_nova();
    anel_da_volta();
    ciclos_com_volta();
    printf("%s\n", falhas ? "FALHOU" : "OK");
    return falhas ? 1 : 0;
}
