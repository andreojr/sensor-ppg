/*
 * buzzer: o buzzer ativo no PB14 (BUZZER, nível alto soa, ligado direto no pino) (#152).
 * Só liga e desliga o pino; a regra de quando soar está em buzzer_logica.h.
 * Não bloqueia: o tempo vem de HAL_GetTick(), sem espera.
 */
#ifndef BUZZER_H
#define BUZZER_H

#include "main.h"
#include "comum/ppg.h"

/* Duração de cada bipe, tempo sem batimento até o tom contínuo e duração do tom de aviso
   quando o dedo sai. 0 em qualquer um = buzzer mudo. */
#ifndef BUZZER_BIPE_MS
#define BUZZER_BIPE_MS 80u
#endif
#ifndef BUZZER_PERDA_MS
#define BUZZER_PERDA_MS 3000u /* mais que o RR de 40 bpm (1,5 s), com folga */
#endif

#ifndef BUZZER_SEM_DEDO_MS
#define BUZZER_SEM_DEDO_MS 3000u
#endif

void buzzer_init(void);

/* A cadeia detectou um batimento (cadeia_saida_t.bateu). */
void buzzer_bateu(const ppg_qualidade_t *qualidade, uint32_t agora_ms);

/* Uma vez por volta do laço: atualiza o pino. */
void buzzer_servico(const ppg_qualidade_t *qualidade, uint32_t agora_ms);

#endif /* BUZZER_H */
