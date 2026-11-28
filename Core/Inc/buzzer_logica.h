/*
 * buzzer_logica: quando o buzzer soa (#152). C puro, sem HAL: o tempo entra como parâmetro
 * (ms do sistema), então roda e é testada no PC (testes/buzzer/). Fica fora de pds/: não é
 * PDS, é a regra de alarme em cima do que a cadeia já entrega (batimento e qualidade).
 *
 * Como monitor hospitalar:
 *  - bipe curto (bipe_ms) a cada batimento detectado;
 *  - tom contínuo enquanto o batimento estiver PERDIDO COM O DEDO NO SENSOR: faz perda_ms
 *    que nenhum batimento é detectado, ou o sinal foi julgado ruim (dedo presente, mas não
 *    usável). Só para quando o batimento volta (ou o dedo sai);
 *  - dedo retirado (qualidade julgou sem dedo): tom só por sem_dedo_ms e depois cala, até o
 *    dedo voltar e o primeiro batimento rearmar o monitor;
 *  - volta a detectar (batimento com sinal usável): o tom para e o bipe recomeça.
 *
 * Fica silencioso até o primeiro batimento (placa ligada sem dedo não apita) e se bipe_ms,
 * perda_ms ou sem_dedo_ms for 0 (parâmetro faltando).
 */
#ifndef BUZZER_LOGICA_H
#define BUZZER_LOGICA_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    uint32_t bipe_ms;
    uint32_t perda_ms;
    uint32_t sem_dedo_ms;
    bool armado;        /* já houve um batimento com sinal usável */
    bool bipando;
    bool alarme_sem_dedo; /* o dedo saiu e o tom de aviso está contando */
    uint32_t t_alarme;    /* ms em que o dedo saiu */
    uint32_t t_ultimo;  /* ms do último batimento aceito */
    uint32_t t_bipe;    /* ms do início do bipe */
} buzzer_logica_t;

void buzzer_logica_init(buzzer_logica_t *b, uint32_t bipe_ms, uint32_t perda_ms,
                        uint32_t sem_dedo_ms);

/* A cadeia detectou um batimento em agora_ms. sinal_ruim: a qualidade julgou não usável
   (com sinal ruim o batimento é ignorado: pode ser ruído). */
void buzzer_logica_bateu(buzzer_logica_t *b, uint32_t agora_ms, bool sinal_ruim);

/* Chamar a cada volta do laço. sem_dedo: a qualidade julgou que não há dedo; sinal_ruim: julgou
   o sinal não usável (inclui sem dedo). true = o buzzer deve soar agora. */
bool buzzer_logica_soa(buzzer_logica_t *b, uint32_t agora_ms, bool sem_dedo, bool sinal_ruim);

#endif /* BUZZER_LOGICA_H */
