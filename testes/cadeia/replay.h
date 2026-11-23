/*
 * replay.h: as cruas de uma captura (n,ir,vermelho a 400 Hz) de novo pela
 * decimação e pela cadeia, no PC, escrevendo as mesmas linhas que a placa
 * (com SERIAL_COMPLETA: b, f e os resultados).
 *
 * Faz com o n o que a placa faz com as perdidas: um salto no n vira a última
 * amostra repetida no lugar das que faltam (a decimação segue alinhada com o
 * tempo do sensor). Um n que volta pra trás é a placa resetando: tudo recomeça.
 *
 * Usado pelo replay_cadeia (linha de comando) e pelo teste_replay.
 */
#ifndef TESTES_CADEIA_REPLAY_H
#define TESTES_CADEIA_REPLAY_H

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "cadeia/cadeia.h"
#include "cadeia/linhas.h"
#include "decimacao/decimacao.h"

#define REPLAY_FS_SENSOR_HZ 400u /* MAX30102_FS_HZ (max30102.h, que inclui HAL) */

typedef struct {
    decimacao_t decimacao;
    cadeia_t cadeia;
    bool iniciado;      /* já chegou uma crua desde o (re)início */
    uint32_t prox;      /* n esperado da próxima crua */
    decimacao_entrada_t anterior;
} replay_t;

static inline bool replay_init(replay_t *r)
{
    r->iniciado = false;
    r->prox = 0;
    return decimacao_init(&r->decimacao, REPLAY_FS_SENSOR_HZ) && cadeia_init(&r->cadeia, NULL);
}

static inline void replay_decima(replay_t *r, const decimacao_entrada_t *e, FILE *out)
{
    ppg_amostra_t bruto;
    if (!decimacao_processa(&r->decimacao, e, &bruto))
        return;
    cadeia_saida_t s;
    cadeia_processa(&r->cadeia, &bruto, &s);
    char buf[LINHAS_MAX];
    size_t n = linhas_cadeia(&s, &bruto, true, buf, sizeof buf);
    fwrite(buf, 1, n, out);
}

/* Uma crua. false se o reinício (n pra trás) falhar. */
static inline bool replay_amostra(replay_t *r, uint32_t n, uint32_t ir, uint32_t vm, FILE *out)
{
    if (r->iniciado && n < r->prox && !replay_init(r))
        return false;
    if (r->iniciado)
        for (; r->prox < n; r->prox++)
            replay_decima(r, &r->anterior, out);
    decimacao_entrada_t e = {ir, vm};
    replay_decima(r, &e, out);
    r->anterior = e;
    r->iniciado = true;
    r->prox = n + 1u;
    return true;
}

#endif /* TESTES_CADEIA_REPLAY_H */
