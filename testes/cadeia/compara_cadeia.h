/*
 * compara_cadeia.h: confere, amostra a amostra, as saídas da cadeia com o vetor
 * testes/cadeia/vetores/physionet.h (referência em Python). Sem printf e sem
 * malloc: serve no teste do PC e na bancada da placa (-DBANCADA_CADEIA=ON).
 *
 *   compara_cadeia_t c;
 *   compara_cadeia_init(&c);
 *   ... a cada amostra: cadeia_processa(...); compara_cadeia_amostra(&c, &s);
 *   uint32_t fora = compara_cadeia_fim(&c);   0 = tudo igual
 */
#ifndef TESTES_CADEIA_COMPARA_CADEIA_H
#define TESTES_CADEIA_COMPARA_CADEIA_H

#include <math.h>
#include <stdint.h>

#include "cadeia/cadeia.h"
#include "vetores/physionet.h"

typedef struct {
    uint32_t nb, ne, nh, nr, nt;  /* quantas de cada já chegaram */
    uint32_t fora;                /* saídas diferentes do vetor */
    uint32_t saidas;              /* saídas conferidas */
} compara_cadeia_t;

static inline void compara_cadeia_init(compara_cadeia_t *c)
{
    c->nb = c->ne = c->nh = c->nr = c->nt = c->fora = c->saidas = 0u;
}

static inline uint32_t compara_cadeia_difere(float a, float b)
{
    return !(fabsf(a - b) <= PHYSIONET_TOL); /* NaN também */
}

static inline void compara_cadeia_amostra(compara_cadeia_t *c, const cadeia_saida_t *s)
{
    uint32_t n = s->filtrado.n;
    if (s->bateu) {
        uint32_t k = c->nb++;
        c->fora += k >= PHYSIONET_BAT_N_PICO_N ||
                   s->batimento.n_pico != (uint32_t)physionet_bat_n_pico[k] ||
                   (int32_t)s->batimento.rr_valido != physionet_bat_rr_valido[k] ||
                   (int32_t)s->bpm.valido != physionet_bat_bpm_valido[k] ||
                   compara_cadeia_difere(s->batimento.fracao, physionet_bat_fracao[k]) ||
                   compara_cadeia_difere(s->batimento.rr_ms, physionet_bat_rr_ms[k]) ||
                   compara_cadeia_difere(s->bpm.valido ? s->bpm.bpm : 0.0f, physionet_bat_bpm[k]);
        c->saidas++;
    }
    for (uint32_t i = 0; i < s->n_hrv; i++) {
        uint32_t k = c->nh++;
        const cadeia_hrv_t *h = &s->hrv[i];
        c->fora += k >= PHYSIONET_HRV_N_PICO_N || h->n_pico != (uint32_t)physionet_hrv_n_pico[k] ||
                   (int32_t)h->hrv.valido != physionet_hrv_valido[k] ||
                   (int32_t)h->rr_usado != physionet_hrv_rr_usado[k] ||
                   compara_cadeia_difere(h->hrv.sdnn_ms, physionet_hrv_sdnn[k]) ||
                   compara_cadeia_difere(h->hrv.rmssd_ms, physionet_hrv_rmssd[k]);
        c->saidas++;
    }
    if (s->espectral) {
        uint32_t k = c->ne++;
        c->fora += k >= PHYSIONET_ESP_N_N || n != (uint32_t)physionet_esp_n[k] ||
                   (int32_t)s->bpm_espectral.valido != physionet_esp_valido[k] ||
                   compara_cadeia_difere(s->bpm_espectral.bpm, physionet_esp_bpm[k]);
        c->saidas++;
    }
    if (s->respirou) {
        uint32_t k = c->nr++;
        c->fora += k >= PHYSIONET_RESP_N_N || n != (uint32_t)physionet_resp_n[k] ||
                   (int32_t)s->respiracao.valido != physionet_resp_valido[k] ||
                   compara_cadeia_difere(s->respiracao.rpm, physionet_resp_rpm[k]);
        c->saidas++;
    }
    if (s->julgou) {
        uint32_t k = c->nt++;
        c->fora += k >= PHYSIONET_TELA_N_N || n != (uint32_t)physionet_tela_n[k] ||
                   (int32_t)s->mostra != physionet_tela_mostra[k] ||
                   compara_cadeia_difere(s->mostra ? s->bpm.bpm : 0.0f, physionet_tela_bpm[k]);
        c->saidas++;
    }
}

/* Soma as que faltaram (o vetor tem mais saídas do que chegaram). */
static inline uint32_t compara_cadeia_fim(const compara_cadeia_t *c)
{
    uint32_t falta = 0;
    falta += c->nb < PHYSIONET_BAT_N_PICO_N ? PHYSIONET_BAT_N_PICO_N - c->nb : 0u;
    falta += c->nh < PHYSIONET_HRV_N_PICO_N ? PHYSIONET_HRV_N_PICO_N - c->nh : 0u;
    falta += c->ne < PHYSIONET_ESP_N_N ? PHYSIONET_ESP_N_N - c->ne : 0u;
    falta += c->nr < PHYSIONET_RESP_N_N ? PHYSIONET_RESP_N_N - c->nr : 0u;
    falta += c->nt < PHYSIONET_TELA_N_N ? PHYSIONET_TELA_N_N - c->nt : 0u;
    return c->fora + falta;
}

#endif /* TESTES_CADEIA_COMPARA_CADEIA_H */
