/* buzzer.c: ver buzzer.h. */
#include "buzzer.h"

#include "buzzer_logica.h"

static buzzer_logica_t logica;
static bool nivel; /* o que o pino mostra agora */

/* Só vale o julgamento já feito: antes do primeiro (valido false), não é ruim. */
static bool sinal_ruim(const ppg_qualidade_t *q)
{
    return q->valido && !q->usavel;
}

static bool sem_dedo(const ppg_qualidade_t *q)
{
    return q->valido && !q->dedo_presente;
}

static void escreve(bool soa)
{
    nivel = soa;
    HAL_GPIO_WritePin(BUZZER_GPIO_Port, BUZZER_Pin, soa ? GPIO_PIN_SET : GPIO_PIN_RESET);
}

void buzzer_init(void)
{
    buzzer_logica_init(&logica, BUZZER_BIPE_MS, BUZZER_PERDA_MS, BUZZER_SEM_DEDO_MS);
    escreve(false);
}

void buzzer_bateu(const ppg_qualidade_t *qualidade, uint32_t agora_ms)
{
    buzzer_logica_bateu(&logica, agora_ms, sinal_ruim(qualidade));
}

void buzzer_servico(const ppg_qualidade_t *qualidade, uint32_t agora_ms)
{
    bool soa = buzzer_logica_soa(&logica, agora_ms, sem_dedo(qualidade), sinal_ruim(qualidade));
    if (soa != nivel)
        escreve(soa);
}
