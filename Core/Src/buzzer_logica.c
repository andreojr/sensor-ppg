/* buzzer_logica.c: ver buzzer_logica.h. Diferenças de tempo em uint32_t: valem na volta do relógio. */
#include "buzzer_logica.h"

void buzzer_logica_init(buzzer_logica_t *b, uint32_t bipe_ms, uint32_t perda_ms,
                        uint32_t sem_dedo_ms)
{
    b->bipe_ms = bipe_ms;
    b->perda_ms = perda_ms;
    b->sem_dedo_ms = sem_dedo_ms;
    b->armado = false;
    b->bipando = false;
    b->alarme_sem_dedo = false;
    b->t_alarme = 0u;
    b->t_ultimo = 0u;
    b->t_bipe = 0u;
}

void buzzer_logica_bateu(buzzer_logica_t *b, uint32_t agora_ms, bool sinal_ruim)
{
    if (sinal_ruim)
        return;
    b->armado = true;
    b->t_ultimo = agora_ms;
    b->t_bipe = agora_ms;
    b->bipando = true;
}

bool buzzer_logica_soa(buzzer_logica_t *b, uint32_t agora_ms, bool sem_dedo, bool sinal_ruim)
{
    if (b->bipe_ms == 0u || b->perda_ms == 0u || b->sem_dedo_ms == 0u)
        return false;
    if (sem_dedo) {
        if (b->armado) { /* o dedo acabou de sair: começa o aviso e desarma */
            b->armado = false;
            b->bipando = false;
            b->alarme_sem_dedo = true;
            b->t_alarme = agora_ms;
        }
        if (b->alarme_sem_dedo && (agora_ms - b->t_alarme) < b->sem_dedo_ms)
            return true;
        b->alarme_sem_dedo = false; /* passou o aviso: cala até o dedo voltar */
        return false;
    }
    b->alarme_sem_dedo = false;
    if (!b->armado)
        return false;
    if (sinal_ruim || (agora_ms - b->t_ultimo) >= b->perda_ms)
        return true; /* dedo presente e batimento perdido: tom contínuo */
    if (b->bipando && (agora_ms - b->t_bipe) >= b->bipe_ms)
        b->bipando = false;
    return b->bipando;
}
