/* hrv.c: SDNN e RMSSD numa janela deslizante. Ver hrv.h. */
#include "hrv/hrv.h"

#include <math.h>
#include <string.h>

void hrv_init(hrv_t *h)
{
    memset(h, 0, sizeof *h);
}

/* Índice na fila do i-ésimo mais antigo. */
static uint32_t posicao(const hrv_t *h, uint32_t i)
{
    return (h->inicio + i) % HRV_CAP;
}

static void tira_mais_antigo(hrv_t *h)
{
    h->inicio = (h->inicio + 1u) % HRV_CAP;
    h->conta--;
}

static bool aceita(const ppg_batimento_t *b)
{
    /* isfinite primeiro: NaN falha qualquer comparação, mas infinito não. */
    return b->rr_valido && isfinite(b->rr_ms) && b->rr_ms >= HRV_RR_MIN_MS &&
           b->rr_ms <= HRV_RR_MAX_MS;
}

static void resultado(const hrv_t *h, ppg_hrv_t *s)
{
    float soma = 0.0f;
    float soma_dif2 = 0.0f;
    uint32_t n_dif = 0;
    for (uint32_t i = 0; i < h->conta; i++) {
        uint32_t p = posicao(h, i);
        soma += h->rr[p];
        if (h->dif_ok[p]) {
            soma_dif2 += h->dif[p] * h->dif[p];
            n_dif++;
        }
    }

    s->lf_hf_valido = false;
    s->lf_hf = 0.0f;
    bool cobre = soma >= HRV_COBERTURA_MIN * (float)HRV_JANELA_S * 1000.0f;
    if (!cobre || n_dif < HRV_MIN_DIF) {
        s->valido = false;
        s->sdnn_ms = 0.0f;
        s->rmssd_ms = 0.0f;
        return;
    }

    /* Duas passadas: primeiro a média, depois os desvios. Em float, somar os
       quadrados dos RR (~10^6 cada) e subtrair perderia os dígitos do desvio. */
    float media = soma / (float)h->conta;
    float soma_desv2 = 0.0f;
    for (uint32_t i = 0; i < h->conta; i++) {
        float d = h->rr[posicao(h, i)] - media;
        soma_desv2 += d * d;
    }
    s->valido = true;
    s->sdnn_ms = sqrtf(soma_desv2 / (float)(h->conta - 1u));
    s->rmssd_ms = sqrtf(soma_dif2 / (float)n_dif);
}

bool hrv_processa(hrv_t *h, const ppg_batimento_t *b, ppg_hrv_t *s)
{
    if (!b->valido)
        return false;
    if (h->tem_n && b->n_pico < h->ultimo_n)
        hrv_init(h); /* a fonte recomeçou */
    h->tem_n = true;
    h->ultimo_n = b->n_pico;

    /* Sai da janela o que ficou velho, antes de entrar o novo. */
    while (h->conta > 0 && b->n_pico - h->n[h->inicio] >= HRV_JANELA_AMOSTRAS)
        tira_mais_antigo(h);

    if (aceita(b)) {
        if (h->conta == HRV_CAP)
            tira_mais_antigo(h);
        uint32_t p = posicao(h, h->conta);
        h->n[p] = b->n_pico;
        h->rr[p] = b->rr_ms;
        h->dif_ok[p] = h->tem_rr;
        h->dif[p] = h->tem_rr ? b->rr_ms - h->rr_anterior : 0.0f;
        h->conta++;
        h->tem_rr = true;
        h->rr_anterior = b->rr_ms;
    } else {
        h->tem_rr = false;
    }

    resultado(h, s);
    return true;
}
