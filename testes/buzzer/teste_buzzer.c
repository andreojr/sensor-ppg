/* Teste da regra do buzzer (#152): bipe por batimento, tom sem batimento, volta do relógio. */
#include <stdio.h>

#include "buzzer_logica.h"

static int falhas;

#define CONFERE(cond)                                                                       \
    if (!(cond)) {                                                                          \
        printf("falhou: %s (linha %d)\n", #cond, __LINE__);                                  \
        falhas++;                                                                           \
    }

#define BIPE 80u
#define PERDA 3000u

static void mudo_ate_o_primeiro_batimento(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, BIPE, PERDA);
    for (uint32_t t = 0; t < 10000u; t += 100u)
        CONFERE(!buzzer_logica_soa(&b, t, false));
    CONFERE(!buzzer_logica_soa(&b, 10000u, true)); /* sem dedo e sem nunca ter batido: mudo */
}

static void bipe_curto_por_batimento(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, BIPE, PERDA);
    for (uint32_t k = 0; k < 5u; k++) {
        uint32_t t0 = 1000u + k * 800u; /* 75 bpm */
        buzzer_logica_bateu(&b, t0, false);
        CONFERE(buzzer_logica_soa(&b, t0, false));
        CONFERE(buzzer_logica_soa(&b, t0 + BIPE - 1u, false));
        CONFERE(!buzzer_logica_soa(&b, t0 + BIPE, false));
        CONFERE(!buzzer_logica_soa(&b, t0 + 799u, false));
    }
}

static void tom_sem_batimento_e_para_ao_voltar(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, BIPE, PERDA);
    buzzer_logica_bateu(&b, 1000u, false);
    CONFERE(!buzzer_logica_soa(&b, 1500u, false));
    CONFERE(!buzzer_logica_soa(&b, 1000u + PERDA - 1u, false));
    CONFERE(buzzer_logica_soa(&b, 1000u + PERDA, false)); /* perdeu: tom contínuo */
    CONFERE(buzzer_logica_soa(&b, 9000u, false));
    buzzer_logica_bateu(&b, 9100u, false); /* voltou a detectar */
    CONFERE(buzzer_logica_soa(&b, 9100u, false)); /* o bipe do batimento */
    CONFERE(!buzzer_logica_soa(&b, 9100u + BIPE, false)); /* e o tom parou */
    CONFERE(!buzzer_logica_soa(&b, 9500u, false));
}

static void sinal_ruim_vira_tom_e_ignora_batimento(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, BIPE, PERDA);
    buzzer_logica_bateu(&b, 1000u, false);
    CONFERE(buzzer_logica_soa(&b, 1300u, true)); /* qualidade julgou: tom já */
    buzzer_logica_bateu(&b, 1400u, true);        /* ruído: não conta */
    CONFERE(buzzer_logica_soa(&b, 1400u + BIPE + 1u, true));
    CONFERE(buzzer_logica_soa(&b, 1500u, false) == 0); /* sinal bom de novo, ainda dentro da perda */
}

static void volta_do_relogio(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, BIPE, PERDA);
    uint32_t t0 = 0xFFFFFFF0u;
    buzzer_logica_bateu(&b, t0, false);
    CONFERE(buzzer_logica_soa(&b, t0 + 5u, false));        /* bipando, antes da volta */
    CONFERE(!buzzer_logica_soa(&b, t0 + 100u, false));     /* depois da volta */
    CONFERE(!buzzer_logica_soa(&b, t0 + PERDA - 1u, false));
    CONFERE(buzzer_logica_soa(&b, t0 + PERDA, false));
}

static void parametro_faltando_fica_mudo(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, 0u, PERDA);
    buzzer_logica_bateu(&b, 100u, false);
    CONFERE(!buzzer_logica_soa(&b, 100u, false));
    CONFERE(!buzzer_logica_soa(&b, 9000u, false));
    buzzer_logica_init(&b, BIPE, 0u);
    buzzer_logica_bateu(&b, 100u, false);
    CONFERE(!buzzer_logica_soa(&b, 100u, false));
    CONFERE(!buzzer_logica_soa(&b, 9000u, true));
}

int main(void)
{
    mudo_ate_o_primeiro_batimento();
    bipe_curto_por_batimento();
    tom_sem_batimento_e_para_ao_voltar();
    sinal_ruim_vira_tom_e_ignora_batimento();
    volta_do_relogio();
    parametro_faltando_fica_mudo();
    printf(falhas ? "buzzer: FALHOU (%d)\n" : "buzzer: OK\n", falhas);
    return falhas ? 1 : 0;
}
