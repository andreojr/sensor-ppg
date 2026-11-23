/*
 * picos: ver picos.h. Constantes e ordem das contas iguais às de picos.py;
 * mudou lá, muda aqui (e regenere os vetores de testes/picos/).
 */
#include "picos/picos.h"

#include <math.h>

#define ESPERA (2u * PPG_FS_HZ)       /* ESPERA_S = 2 s */
#define REFRAT (3u * PPG_FS_HZ / 10u) /* REFRAT_S = 0,3 s */
#define LIMIAR 0.3f
#define DECAI 0.9900498390197754f /* exp(-1 / (TAU_ENV_S * PPG_FS_HZ)) em float */
#define RR_MIN_MS 300.0f
#define RR_MAX_MS 2000.0f
#define RR_FAIXA_MIN 0.7 /* em double, como no Python */
#define RR_FAIXA_MAX 1.4
#define RR_ALFA 0.125f
#define REG_MINIMO 6u  /* dos PICOS_REG_JANELA batimentos, quantos têm que ser bons */
#define REG_TOL 0.15f  /* "perto da mediana": a menos de 15% dela */
#define MS_POR_AMOSTRA (1000.0f / (float)PPG_FS_HZ)

void picos_init(picos_t *p)
{
    p->n = 0;
    p->x1 = 0.0f;
    p->x2 = 0.0f;
    p->env = 0.0f;
    p->tem_ultimo = false;
    p->ultimo_n = 0;
    p->ultimo_base = 0;
    p->ultimo_fracao = 0.0f;
    p->tem_pendente = false;
    p->pend_base = 0;
    p->pend_n_pico = 0;
    p->pend_fracao = 0.0f;
    p->pend_altura = 0.0f;
    p->rr_tipico = 0.0f;
    for (uint32_t i = 0; i < PICOS_BPM_JANELA; i++)
        p->rrs[i] = 0.0f;
    p->n_rrs = 0;
    for (uint32_t i = 0; i < PICOS_REG_JANELA; i++) {
        p->hist_valido[i] = false;
        p->hist_rr[i] = 0.0f;
    }
    p->n_hist = 0;
}

static void guarda_hist(picos_t *p, bool valido, float rr_ms)
{
    if (p->n_hist == PICOS_REG_JANELA) {
        for (uint32_t i = 1; i < PICOS_REG_JANELA; i++) {
            p->hist_valido[i - 1] = p->hist_valido[i];
            p->hist_rr[i - 1] = p->hist_rr[i];
        }
        p->n_hist--;
    }
    p->hist_valido[p->n_hist] = valido;
    p->hist_rr[p->n_hist] = rr_ms;
    p->n_hist++;
}

static void guarda_rr(picos_t *p, float rr_ms)
{
    if (p->n_rrs == PICOS_BPM_JANELA) {
        for (uint32_t i = 1; i < PICOS_BPM_JANELA; i++)
            p->rrs[i - 1] = p->rrs[i];
        p->n_rrs--;
    }
    p->rrs[p->n_rrs++] = rr_ms;
}

/* Candidato em `base` (x[base] = y1, vizinhos y0 e y2). Fica pendente. */
static void candidato(picos_t *p, uint32_t base, float y0, float y1, float y2)
{
    /* Refratário no n da entrada, sem descontar o atraso (ultimo_n já vem descontado).
       Com n contínuo não dispara (o pendente só sai REFRAT depois); vale se houver
       buraco no n. Quem faz o refratário no dia a dia é a regra do pendente abaixo. */
    if (p->tem_ultimo && base - p->ultimo_base < REFRAT)
        return;
    /* Dentro do refratário do pendente, só vale um pico maior (a corcova do FIR
       antes do batimento perde pro pico verdadeiro). */
    if (p->tem_pendente && y1 <= p->pend_altura)
        return;

    /* Vértice da parábola por (base-1, y0), (base, y1), (base+1, y2). */
    /* O denominador só zera por arredondamento num platô (y1 == y2): aí o
       pico fica em base. */
    float den = y0 - 2.0f * y1 + y2;
    float d = den != 0.0f ? 0.5f * (y0 - y2) / den : 0.0f;
    if (!isfinite(d)) /* vizinho infinito: fica em base */
        d = 0.0f;
    float f = d - PPG_ATRASO_AMOSTRAS;
    float k = floorf(f);
    int32_t n_pico = (int32_t)base + (int32_t)k;
    float fracao = f - k;
    if (fracao >= 1.0f) { /* arredondamento do float */
        n_pico += 1;
        fracao = 0.0f;
    }
    if (n_pico < 0)
        n_pico = 0;

    p->tem_pendente = true;
    p->pend_base = base;
    p->pend_n_pico = (uint32_t)n_pico;
    p->pend_fracao = fracao;
    p->pend_altura = y1;
}

/* O pendente passou do refratário: vira batimento, com RR. */
static void emite(picos_t *p, ppg_batimento_t *saida)
{
    uint32_t n_pico = p->pend_n_pico;
    float fracao = p->pend_fracao;
    p->tem_pendente = false;

    bool rr_valido = false;
    float rr_ms = 0.0f;
    if (p->tem_ultimo) {
        rr_ms = (float)((double)((int32_t)n_pico - (int32_t)p->ultimo_n) + (double)fracao
                        - (double)p->ultimo_fracao) * MS_POR_AMOSTRA;
        if (rr_ms >= RR_MIN_MS && rr_ms <= RR_MAX_MS) {
            double tipico = (double)p->rr_tipico;
            rr_valido = tipico == 0.0 || (RR_FAIXA_MIN * tipico <= (double)rr_ms
                                          && (double)rr_ms <= RR_FAIXA_MAX * tipico);
            if (tipico == 0.0)
                p->rr_tipico = rr_ms;
            else
                p->rr_tipico = p->rr_tipico + RR_ALFA * (rr_ms - p->rr_tipico);
        }
        if (rr_valido)
            guarda_rr(p, rr_ms);
    }

    guarda_hist(p, rr_valido, rr_ms);
    p->tem_ultimo = true;
    p->ultimo_n = n_pico;
    p->ultimo_base = p->pend_base;
    p->ultimo_fracao = fracao;

    saida->valido = true;
    saida->n_pico = n_pico;
    saida->fracao = fracao;
    saida->rr_valido = rr_valido;
    saida->rr_ms = rr_ms;
}

bool picos_processa(picos_t *p, const ppg_amostra_t *filtrado, ppg_batimento_t *saida)
{
    float x = filtrado->ir;
    float decaido = p->env * DECAI;
    p->env = x > decaido ? x : decaido;

    /* Máximo local em x[n-1], visto com uma amostra de atraso. O n é o da
       cadeia (ppg.h); p->n só conta o aquecimento desde o init. */
    if (p->n >= ESPERA && filtrado->n > 0u && p->x1 > p->x2 && p->x1 >= x &&
        p->x1 > LIMIAR * p->env)
        candidato(p, filtrado->n - 1u, p->x2, p->x1, x);

    p->x2 = p->x1;
    p->x1 = x;
    p->n++;

    /* Passado o refratário sem aparecer candidato maior, o pendente vira batimento. */
    if (p->tem_pendente && filtrado->n - p->pend_base >= REFRAT) {
        emite(p, saida);
        return true;
    }
    return false;
}

/* Pelo menos REG_MINIMO dos últimos batimentos têm RR válido e perto da mediana dos RR válidos. */
static bool regular(const picos_t *p)
{
    if (p->n_hist < PICOS_REG_JANELA)
        return false;
    float val[PICOS_REG_JANELA];
    uint32_t n = 0;
    for (uint32_t i = 0; i < PICOS_REG_JANELA; i++)
        if (p->hist_valido[i])
            val[n++] = p->hist_rr[i];
    if (n < REG_MINIMO)
        return false;
    for (uint32_t i = 1; i < n; i++) { /* ordena (são só 8) */
        float v = val[i];
        uint32_t j = i;
        while (j > 0 && val[j - 1] > v) {
            val[j] = val[j - 1];
            j--;
        }
        val[j] = v;
    }
    float med = (n & 1u) ? val[n / 2u] : (val[n / 2u - 1u] + val[n / 2u]) * 0.5f;
    uint32_t bons = 0;
    for (uint32_t i = 0; i < n; i++)
        if (fabsf(val[i] - med) < REG_TOL * med)
            bons++;
    return bons >= REG_MINIMO;
}

void picos_bpm(const picos_t *p, ppg_bpm_t *saida)
{
    /* regular() exige REG_MINIMO RR válidos entre os últimos batimentos, e todos eles
       estão em rrs: não precisa checar um mínimo de RR à parte. */
    if (!regular(p)) {
        saida->valido = false;
        saida->bpm = 0.0f;
        return;
    }
    float soma = 0.0f;
    for (uint32_t i = 0; i < p->n_rrs; i++)
        soma += p->rrs[i];
    saida->valido = true;
    saida->bpm = 60000.0f / (soma / (float)p->n_rrs);
}
