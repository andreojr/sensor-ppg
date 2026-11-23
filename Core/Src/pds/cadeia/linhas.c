/* linhas.c: ver linhas.h. Texto igual ao dos envia_*() do main.c da v0.3. */
#include "cadeia/linhas.h"

#include <stdio.h>

/* Parte inteira e fração separadas: v * 100 perto de 2,6e7 já perde os centésimos
   no float. */
int linhas_centesimos(char *s, size_t tam, float v)
{
    long inteira = (long)v;
    float fracao = v - (float)inteira; /* exata, mesmo sinal de v */
    long c = inteira * 100L + (long)(fracao * 100.0f + (v < 0.0f ? -0.5f : 0.5f));
    unsigned long a = (unsigned long)(c < 0 ? -c : c);
    return snprintf(s, tam, "%s%lu.%02lu", c < 0 ? "-" : "", a / 100u, a % 100u);
}

/* Acrescenta a linha se ela couber inteira (com o \0). */
typedef struct {
    char *buf;
    size_t tam;
    size_t usado;
    bool parou;
} saida_t;

static void poe(saida_t *o, const char *linha, int n)
{
    if (o->parou || n < 0 || o->usado + (size_t)n + 1u > o->tam) {
        o->parou = true;
        return;
    }
    for (int i = 0; i <= n; i++) /* com o \0 */
        o->buf[o->usado + (size_t)i] = linha[i];
    o->usado += (size_t)n;
}

static void ppg(saida_t *o, char tipo, const ppg_amostra_t *a)
{
    char ir[24], vermelho[24], linha[64];
    linhas_centesimos(ir, sizeof ir, a->ir);
    linhas_centesimos(vermelho, sizeof vermelho, a->vermelho);
    poe(o, linha, snprintf(linha, sizeof linha, "%c,%lu,%s,%s\n", tipo, (unsigned long)a->n, ir,
                           vermelho));
}

static void batimento(saida_t *o, const ppg_batimento_t *b, const ppg_bpm_t *v)
{
    char rr[24], bpm[24], linha[96];
    unsigned long f = (unsigned long)(b->fracao * 10000.0f + 0.5f); /* fracao em [0, 1) */
    linhas_centesimos(rr, sizeof rr, b->rr_ms);
    linhas_centesimos(bpm, sizeof bpm, v->valido ? v->bpm : 0.0f);
    poe(o, linha, snprintf(linha, sizeof linha, "p,%lu,%lu.%04lu,%d,%s,%d,%s\n",
                           (unsigned long)b->n_pico, f / 10000u, f % 10000u, b->rr_valido ? 1 : 0,
                           rr, v->valido ? 1 : 0, bpm));
}

static void hrv(saida_t *o, const cadeia_hrv_t *h)
{
    char sdnn[24], rmssd[24], linha[80];
    linhas_centesimos(sdnn, sizeof sdnn, h->hrv.sdnn_ms);
    linhas_centesimos(rmssd, sizeof rmssd, h->hrv.rmssd_ms);
    poe(o, linha, snprintf(linha, sizeof linha, "h,%lu,%d,%s,%s,%d\n", (unsigned long)h->n_pico,
                           h->hrv.valido ? 1 : 0, sdnn, rmssd, h->rr_usado ? 1 : 0));
}

static void espectral(saida_t *o, uint32_t n, const ppg_bpm_t *v)
{
    char bpm[24], linha[64];
    linhas_centesimos(bpm, sizeof bpm, v->valido ? v->bpm : 0.0f);
    poe(o, linha, snprintf(linha, sizeof linha, "e,%lu,%d,%s\n", (unsigned long)n,
                           v->valido ? 1 : 0, bpm));
}

static void respiracao(saida_t *o, uint32_t n, const ppg_respiracao_t *r)
{
    char rpm[24], linha[48];
    linhas_centesimos(rpm, sizeof rpm, r->rpm);
    poe(o, linha, snprintf(linha, sizeof linha, "r,%lu,%s,%u\n", (unsigned long)n, rpm,
                           r->valido ? 1u : 0u));
}

static void tela(saida_t *o, uint32_t n, bool mostra, const ppg_bpm_t *v)
{
    char linha[48];
    poe(o, linha, snprintf(linha, sizeof linha, "t,%lu,%d,%lu\n", (unsigned long)n, mostra ? 1 : 0,
                           mostra ? (unsigned long)(v->bpm * 100.0f + 0.5f) : 0ul));
}

size_t linhas_cadeia(const cadeia_saida_t *s, const ppg_amostra_t *bruto, bool completa,
                     char *buf, size_t tam)
{
    saida_t o = {buf, tam, 0u, tam == 0u};
    if (tam > 0u)
        buf[0] = '\0';
    ppg(&o, 'b', bruto);
    if (completa)
        ppg(&o, 'f', &s->filtrado);
    if (s->bateu)
        batimento(&o, &s->batimento, &s->bpm);
    for (uint32_t k = 0; k < s->n_hrv; k++)
        hrv(&o, &s->hrv[k]);
    if (s->espectral)
        espectral(&o, s->filtrado.n, &s->bpm_espectral);
    if (s->respirou)
        respiracao(&o, bruto->n, &s->respiracao);
    if (s->julgou)
        tela(&o, bruto->n, s->mostra, &s->bpm);
    return o.usado;
}

size_t linhas_cru(uint32_t n, uint32_t ir, uint32_t vermelho, char *buf, size_t tam)
{
    saida_t o = {buf, tam, 0u, tam == 0u};
    char linha[40];
    poe(&o, linha, snprintf(linha, sizeof linha, "%lu,%lu,%lu\n", (unsigned long)n,
                            (unsigned long)ir, (unsigned long)vermelho));
    return o.usado;
}
