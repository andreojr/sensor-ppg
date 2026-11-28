/* Teste da regra do buzzer (#152): bipe, tom com dedo sem batimento, aviso curto sem dedo, relógio. */
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
#define SEM_DEDO 3000u

static void mudo_ate_o_primeiro_batimento(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, BIPE, PERDA, SEM_DEDO);
    for (uint32_t t = 0; t < 10000u; t += 100u)
        CONFERE(!buzzer_logica_soa(&b, t, false, false));
    CONFERE(!buzzer_logica_soa(&b, 10000u, false, true)); /* sem dedo e sem nunca ter batido: mudo */
}

static void bipe_curto_por_batimento(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, BIPE, PERDA, SEM_DEDO);
    for (uint32_t k = 0; k < 5u; k++) {
        uint32_t t0 = 1000u + k * 800u; /* 75 bpm */
        buzzer_logica_bateu(&b, t0, false);
        CONFERE(buzzer_logica_soa(&b, t0, false, false));
        CONFERE(buzzer_logica_soa(&b, t0 + BIPE - 1u, false, false));
        CONFERE(!buzzer_logica_soa(&b, t0 + BIPE, false, false));
        CONFERE(!buzzer_logica_soa(&b, t0 + 799u, false, false));
    }
}

static void tom_sem_batimento_e_para_ao_voltar(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, BIPE, PERDA, SEM_DEDO);
    buzzer_logica_bateu(&b, 1000u, false);
    CONFERE(!buzzer_logica_soa(&b, 1500u, false, false));
    CONFERE(!buzzer_logica_soa(&b, 1000u + PERDA - 1u, false, false));
    CONFERE(buzzer_logica_soa(&b, 1000u + PERDA, false, false)); /* perdeu: tom contínuo */
    CONFERE(buzzer_logica_soa(&b, 9000u, false, false));
    buzzer_logica_bateu(&b, 9100u, false); /* voltou a detectar */
    CONFERE(buzzer_logica_soa(&b, 9100u, false, false)); /* o bipe do batimento */
    CONFERE(!buzzer_logica_soa(&b, 9100u + BIPE, false, false)); /* e o tom parou */
    CONFERE(!buzzer_logica_soa(&b, 9500u, false, false));
}

static void sinal_ruim_vira_tom_e_ignora_batimento(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, BIPE, PERDA, SEM_DEDO);
    buzzer_logica_bateu(&b, 1000u, false);
    CONFERE(buzzer_logica_soa(&b, 1300u, false, true)); /* qualidade julgou: tom já */
    buzzer_logica_bateu(&b, 1400u, true);        /* ruído: não conta */
    CONFERE(buzzer_logica_soa(&b, 1400u + BIPE + 1u, false, true));
    CONFERE(buzzer_logica_soa(&b, 1500u, false, false) == 0); /* sinal bom de novo, ainda dentro da perda */
}

static void sem_dedo_apita_um_pouco_e_cala(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, BIPE, PERDA, SEM_DEDO);
    buzzer_logica_bateu(&b, 1000u, false);
    CONFERE(buzzer_logica_soa(&b, 5000u, true, true)); /* dedo saiu: aviso */
    CONFERE(buzzer_logica_soa(&b, 5000u + SEM_DEDO - 1u, true, true));
    CONFERE(!buzzer_logica_soa(&b, 5000u + SEM_DEDO, true, true)); /* cala */
    CONFERE(!buzzer_logica_soa(&b, 60000u, true, true));           /* e fica calado */
    /* dedo volta: mudo até o primeiro batimento, mesmo passando a perda */
    CONFERE(!buzzer_logica_soa(&b, 61000u, false, false));
    CONFERE(!buzzer_logica_soa(&b, 70000u, false, true)); /* dedo mal posto, sem nunca ter batido */
    buzzer_logica_bateu(&b, 70500u, false);
    CONFERE(buzzer_logica_soa(&b, 70500u, false, false));
    CONFERE(!buzzer_logica_soa(&b, 70700u, false, false));
    CONFERE(buzzer_logica_soa(&b, 70500u + PERDA, false, false)); /* dedo e sem batimento: contínuo */
}

static void volta_do_relogio(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, BIPE, PERDA, SEM_DEDO);
    uint32_t t0 = 0xFFFFFFF0u;
    buzzer_logica_bateu(&b, t0, false);
    CONFERE(buzzer_logica_soa(&b, t0 + 5u, false, false));        /* bipando, antes da volta */
    CONFERE(!buzzer_logica_soa(&b, t0 + 100u, false, false));     /* depois da volta */
    CONFERE(!buzzer_logica_soa(&b, t0 + PERDA - 1u, false, false));
    CONFERE(buzzer_logica_soa(&b, t0 + PERDA, false, false));
}

static void parametro_faltando_fica_mudo(void)
{
    buzzer_logica_t b;
    buzzer_logica_init(&b, 0u, PERDA, SEM_DEDO);
    buzzer_logica_bateu(&b, 100u, false);
    CONFERE(!buzzer_logica_soa(&b, 100u, false, false));
    CONFERE(!buzzer_logica_soa(&b, 9000u, false, false));
    buzzer_logica_init(&b, BIPE, 0u, SEM_DEDO);
    buzzer_logica_bateu(&b, 100u, false);
    CONFERE(!buzzer_logica_soa(&b, 100u, false, false));
    CONFERE(!buzzer_logica_soa(&b, 9000u, false, true));
}

int main(void)
{
    mudo_ate_o_primeiro_batimento();
    bipe_curto_por_batimento();
    tom_sem_batimento_e_para_ao_voltar();
    sinal_ruim_vira_tom_e_ignora_batimento();
    sem_dedo_apita_um_pouco_e_cala();
    volta_do_relogio();
    parametro_faltando_fica_mudo();
    printf(falhas ? "buzzer: FALHOU (%d)\n" : "buzzer: OK\n", falhas);
    return falhas ? 1 : 0;
}
