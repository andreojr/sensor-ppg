/*
 * buzzer_logica: quando o buzzer soa (#152). C puro, sem HAL: o tempo entra como parâmetro
 * (ms do sistema), então roda e é testada no PC (testes/buzzer/). Fica fora de pds/: não é
 * PDS, é a regra de alarme em cima do que a cadeia já entrega (batimento e qualidade).
 *
 * Como monitor hospitalar:
 *  - bipe curto (bipe_ms) a cada batimento detectado;
 *  - tom contínuo enquanto o batimento estiver PERDIDO: faz perda_ms que nenhum batimento
 *    é detectado, ou a qualidade julgou o sinal não usável (sem dedo ou sinal ruim);
 *  - volta a detectar (batimento com sinal usável): o tom para e o bipe recomeça.
 *
 * Fica silencioso até o primeiro batimento (placa ligada sem dedo não apita) e se bipe_ms
 * ou perda_ms for 0 (parâmetro faltando).
 */
#ifndef BUZZER_LOGICA_H
#define BUZZER_LOGICA_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint32_t bipe_ms;
    uint32_t perda_ms;
    bool armado;        /* já houve um batimento com sinal usável */
    bool bipando;
    uint32_t t_ultimo;  /* ms do último batimento aceito */
    uint32_t t_bipe;    /* ms do início do bipe */
} buzzer_logica_t;

void buzzer_logica_init(buzzer_logica_t *b, uint32_t bipe_ms, uint32_t perda_ms);

/* A cadeia detectou um batimento em agora_ms. sinal_ruim: a qualidade julgou não usável
   (com sinal ruim o batimento é ignorado: pode ser ruído). */
void buzzer_logica_bateu(buzzer_logica_t *b, uint32_t agora_ms, bool sinal_ruim);

/* Chamar a cada volta do laço. true = o buzzer deve soar agora. */
bool buzzer_logica_soa(buzzer_logica_t *b, uint32_t agora_ms, bool sinal_ruim);

#endif /* BUZZER_LOGICA_H */
