/*
 * cadeia.c: ver cadeia.h. A ordem e as regras são as do laço da v0.3 (a
 * decima() do main.c), sem a serial.
 */
#include "cadeia/cadeia.h"

#include <string.h>

/* Início de uma medida: 0 sem relógio (nada é contado). */
static uint32_t inicio(const cadeia_t *c)
{
    return c->relogio ? c->relogio() : 0u;
}

static void fim(const cadeia_t *c, ciclos_t *m, uint32_t t0)
{
    if (c->relogio)
        ciclos_conta(m, c->relogio() - t0);
}

bool cadeia_init(cadeia_t *c, cadeia_relogio_t relogio)
{
    memset(c, 0, sizeof *c);
    c->relogio = relogio;
    filtro_init(&c->filtro);
    picos_init(&c->picos);
    respiracao_init(&c->respiracao);
    spo2_init(&c->spo2);
    qualidade_init(&c->qualidade);
    qualidade_fila_init(&c->fila_hrv);
    hrv_init(&c->hrv);
    return espectral_init(&c->espectral);
}

/* Um batimento que saiu da fila vai pro HRV; rr_valido já diz se o RR entra. */
static void para_hrv(cadeia_t *c, const ppg_batimento_t *b, cadeia_saida_t *s)
{
    ppg_hrv_t h;
    uint32_t t0 = inicio(c);
    bool saiu = hrv_processa(&c->hrv, b, &h);
    fim(c, &c->ciclos.hrv, t0);
    if (saiu) {
        c->ficha.hrv = h;
        if (s->n_hrv < CADEIA_HRV_MAX) {
            s->hrv[s->n_hrv] = (cadeia_hrv_t){b->n_pico, h, b->rr_valido};
            s->n_hrv++;
        }
    }
}

void cadeia_processa(cadeia_t *c, const ppg_amostra_t *bruto, cadeia_saida_t *s)
{
    uint32_t t_total = inicio(c);
    s->bateu = s->espectral = s->respirou = s->oxigenou = s->julgou = s->mostra = false;
    s->n_hrv = 0;

    uint32_t t0 = inicio(c);
    filtro_processa(&c->filtro, bruto, &s->filtrado);
    fim(c, &c->ciclos.filtro, t0);

    t0 = inicio(c);
    s->bateu = picos_processa(&c->picos, &s->filtrado, &s->batimento);
    fim(c, &c->ciclos.picos, t0);
    if (s->bateu) {
        picos_bpm(&c->picos, &s->bpm);
        c->bpm_cru = s->bpm;
        c->tem_batimento = true;
        c->n_ultimo_pico = s->batimento.n_pico;
        c->ficha.ultimo_batimento = s->batimento;
        c->ficha.bpm_picos.bpm = s->bpm.bpm;
        /* BPM inválido (bpm 0) não pode ficar "válido" até o próximo julgamento; um
           válido novo espera a regra (no julgamento) pra acender. */
        if (!s->bpm.valido)
            c->ficha.bpm_picos.valido = false;
        /* O picos roda antes da qualidade nesta amostra: o julgamento "de antes" é o
           anterior; o desta amostra, se houver, é o "de depois". */
        bool antes = qualidade_batimento_usavel(&c->julgamento, c->tem_julgamento,
                                                c->n_julgamento, bruto->n);
        ppg_batimento_t velho;
        if (qualidade_fila_poe(&c->fila_hrv, &s->batimento, antes, &velho))
            para_hrv(c, &velho, s);
    }

    t0 = inicio(c);
    s->espectral = espectral_processa(&c->espectral, &s->filtrado, &s->bpm_espectral);
    fim(c, &c->ciclos.espectral, t0);
    if (s->espectral)
        c->ficha.bpm_espectral = s->bpm_espectral;

    t0 = inicio(c);
    s->respirou = respiracao_processa(&c->respiracao, bruto, &s->respiracao);
    fim(c, &c->ciclos.respiracao, t0);
    if (s->respirou)
        c->ficha.respiracao = s->respiracao;

    /* A SpO2 usa o bruto (com DC), não o filtrado. */
    t0 = inicio(c);
    s->oxigenou = spo2_processa(&c->spo2, bruto, &s->spo2);
    fim(c, &c->ciclos.spo2, t0);
    if (s->oxigenou) {
        s->spo2_r = spo2_r(&c->spo2);
        c->ficha.spo2 = s->spo2;
    }

    t0 = inicio(c);
    s->julgou = qualidade_processa(&c->qualidade, bruto, &s->qualidade);
    fim(c, &c->ciclos.qualidade, t0);
    if (s->julgou) {
        c->julgamento = s->qualidade;
        c->tem_julgamento = true;
        c->n_julgamento = bruto->n;
        c->ficha.qualidade = s->qualidade;
        ppg_batimento_t pronto;
        while (qualidade_fila_tira(&c->fila_hrv, &s->qualidade, &pronto))
            para_hrv(c, &pronto, s);
        s->mostra = qualidade_bpm_confiavel(&s->qualidade, &c->bpm_cru, c->tem_batimento,
                                            bruto->n, c->n_ultimo_pico);
        s->bpm = c->bpm_cru;
        c->ficha.bpm_picos.bpm = c->bpm_cru.bpm;
        c->ficha.bpm_picos.valido = s->mostra;
    }
    fim(c, &c->ciclos.total, t_total);
}

const ppg_resultados_t *cadeia_resultados(const cadeia_t *c)
{
    return &c->ficha;
}
