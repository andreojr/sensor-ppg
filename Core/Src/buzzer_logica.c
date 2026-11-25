/* buzzer_logica.c: ver buzzer_logica.h. Diferenças de tempo em uint32_t: valem na volta do relógio. */
#include "buzzer_logica.h"

void buzzer_logica_init(buzzer_logica_t *b, uint32_t bipe_ms, uint32_t perda_ms)
{
    b->bipe_ms = bipe_ms;
    b->perda_ms = perda_ms;
    b->armado = false;
    b->bipando = false;
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

bool buzzer_logica_soa(buzzer_logica_t *b, uint32_t agora_ms, bool sinal_ruim)
{
    if (b->bipe_ms == 0u || b->perda_ms == 0u || !b->armado)
        return false;
    if (sinal_ruim || (agora_ms - b->t_ultimo) >= b->perda_ms)
        return true; /* batimento perdido: tom contínuo */
    if (b->bipando && (agora_ms - b->t_bipe) >= b->bipe_ms)
        b->bipando = false;
    return b->bipando;
}
