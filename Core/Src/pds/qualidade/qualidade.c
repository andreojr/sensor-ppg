/* qualidade.c: detector de sinal ruim. Ver qualidade.h. */
#include "qualidade/qualidade.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

/* Passa-faixa 0,5-4 Hz: Butterworth 2ª ordem em 2 seções (b0 b1 b2 a1 a2), o
   passa-altas primeiro. Os mesmos números de RITMO_SOS em qualidade.py. */
static const float SOS[2][5] = {
    {1.0f, -2.0f, 1.0f, -1.9585309426687274f, 0.9597079331261205f},
    {0.01043241337109341f, 0.02086482674218683f, 0.01043241337109341f, -1.717844586580564f,
     0.7634885625932664f},
};

static float passa_faixa(qualidade_t *q, float x)
{
    float *z = q->z;
    float y = SOS[0][0] * x + z[0];
    z[0] = SOS[0][1] * x - SOS[0][3] * y + z[1];
    z[1] = SOS[0][2] * x - SOS[0][4] * y;
    x = y;
    y = SOS[1][0] * x + z[2];
    z[2] = SOS[1][1] * x - SOS[1][3] * y + z[3];
    z[3] = SOS[1][2] * x - SOS[1][4] * y;
    return y;
}

/*
 * Até QUALIDADE_RITMO_POR_AMOSTRA passos da conta do ritmo sobre a janela
 * parada w = anel[ini..ini+N):
 *   etapa 0       média m
 *   etapa 1       energia: soma de (w - m)^2
 *   etapa 2..29   um atraso k cada: soma de (w[i] - m)(w[i-k] - m) / energia,
 *                 guarda o maior
 */
#define RITMO_ETAPAS (2u + QUALIDADE_RITMO_ATRASO_MAX - QUALIDADE_RITMO_ATRASO_MIN + 1u)

static void ritmo_passos(qualidade_t *q)
{
    if (!q->tem_foto || q->pronto)
        return;
    /* Em locais: no build Debug (-O0), cada q-> no laço é uma ida à memória. */
    const float *w = &q->anel[q->ini];
    const uint32_t N = QUALIDADE_RITMO_N;
    uint32_t etapa = q->etapa, i = q->i, resta = QUALIDADE_RITMO_POR_AMOSTRA;
    float acc = q->acc, m = q->media_r;
    while (resta > 0u) {
        uint32_t fim = N - i < resta ? N : i + resta;
        resta -= fim - i;
        if (etapa == 0u) {
            for (; i < fim; i++)
                acc += w[i];
            if (i < N)
                break;
            m = acc / (float)N;
            q->media_r = m;
            acc = 0.0f;
            i = 0;
            etapa = 1u;
        } else if (etapa == 1u) {
            for (; i < fim; i++) {
                float d = w[i] - m;
                acc += d * d;
            }
            if (i < N)
                break;
            q->energia = acc;
            q->maior_r = -INFINITY;
            acc = 0.0f;
            etapa = 2u;
            i = QUALIDADE_RITMO_ATRASO_MIN;
            if (q->energia <= 0.0f) {
                q->pronto = true;
                break;
            }
        } else {
            uint32_t k = QUALIDADE_RITMO_ATRASO_MIN + etapa - 2u;
            const float *wk = w - k;
            for (; i < fim; i++)
                acc += (w[i] - m) * (wk[i] - m);
            if (i < N)
                break;
            q->maior_r = fmaxf(q->maior_r, acc / q->energia);
            acc = 0.0f;
            if (++etapa == RITMO_ETAPAS) {
                q->pronto = true;
                break;
            }
            i = k + 1u;
        }
    }
    q->etapa = etapa;
    q->i = i;
    q->acc = acc;
}

static void bloco_zera(qualidade_bloco_t *b)
{
    b->soma_ir = 0.0f;
    b->soma_vm = 0.0f;
    b->maior = -INFINITY;
    b->min_y = INFINITY;
    b->max_y = -INFINITY;
    b->tv_y = 0.0f;
}

void qualidade_init(qualidade_t *q)
{
    memset(q, 0, offsetof(qualidade_t, anel)); /* o anel (1 KB) não precisa */
    bloco_zera(&q->atual);
    bloco_zera(&q->anterior);
}

/* Fecha a janela (bloco anterior + atual) e decide. */
static void janela(qualidade_t *q, ppg_qualidade_t *s, bool tem_ritmo, float ritmo)
{
    const qualidade_bloco_t *a = &q->anterior, *b = &q->atual;
    float dc_ir = (a->soma_ir + b->soma_ir) / (float)QUALIDADE_JANELA;
    float dc_vm = (a->soma_vm + b->soma_vm) / (float)QUALIDADE_JANELA;
    float altura = fmaxf(a->max_y, b->max_y) - fminf(a->min_y, b->min_y);
    float maior = fmaxf(a->maior, b->maior);
    bool dedo = dc_ir >= QUALIDADE_DC_MIN && dc_vm >= QUALIDADE_DC_MIN;
    float pi = dc_ir > 0.0f ? altura / dc_ir : 0.0f;
    float aspereza = altura > 0.0f ? (a->tv_y + b->tv_y) / altura : 0.0f;
    float razao = q->tem_ref ? altura / q->ref : 0.0f;

    uint32_t motivo = 0;
    if (!dedo)
        motivo |= QUALIDADE_SEM_DEDO;
    if (maior >= QUALIDADE_SATURA)
        motivo |= QUALIDADE_SATURADO;
    if (dedo) {
        if (pi < QUALIDADE_PI_MIN || (q->tem_ref && razao < QUALIDADE_RAZAO_MIN))
            motivo |= QUALIDADE_PULSO_FRACO;
        if (pi > QUALIDADE_PI_MAX || razao > QUALIDADE_RAZAO_MAX ||
            aspereza < QUALIDADE_ASPEREZA_MIN)
            motivo |= QUALIDADE_MOVIMENTO;
        if (aspereza > QUALIDADE_ASPEREZA_MAX)
            motivo |= QUALIDADE_RUIDO;
        if (!tem_ritmo || ritmo < QUALIDADE_RITMO_MIN)
            motivo |= QUALIDADE_SEM_RITMO;
    }

    if (motivo) {
        q->boas = 0;
        if (q->ruins < QUALIDADE_RUINS_ESQUECE)
            q->ruins++;
        if (q->ruins >= QUALIDADE_RUINS_ESQUECE)
            q->tem_ref = false;
    } else {
        if (q->boas < QUALIDADE_JANELAS_ACEITA)
            q->boas++;
        q->ruins = 0;
        q->ref = q->tem_ref ? q->ref + QUALIDADE_PESO_REF * (altura - q->ref) : altura;
        q->tem_ref = true;
    }

    q->motivo = motivo;
    q->dc_ir = dc_ir;
    q->pi = pi;
    q->aspereza = aspereza;
    q->razao = razao;
    q->ritmo = tem_ritmo ? ritmo : 0.0f;

    s->valido = true;
    s->dedo_presente = dedo;
    s->indice = (float)q->boas / (float)QUALIDADE_JANELAS_ACEITA;
    s->usavel = dedo && s->indice >= QUALIDADE_LIMIAR;
}

bool qualidade_processa(qualidade_t *q, const ppg_amostra_t *bruto, ppg_qualidade_t *s)
{
    float ir = bruto->ir, vm = bruto->vermelho;
    if (!isfinite(ir) || !isfinite(vm)) {
        qualidade_init(q);
        return false;
    }
    if (q->tem_n && bruto->n != q->prox_n) /* amostra perdida ou n voltou */
        qualidade_init(q);
    if (!q->tem_n) {
        q->media = ir;
        q->x0 = ir;
    }

    q->media += QUALIDADE_ALFA * (ir - q->media);
    float y = ir - q->media;
    qualidade_bloco_t *b = &q->atual;
    if (q->tem_n)
        b->tv_y += fabsf(y - q->ultimo_y);
    q->tem_n = true;
    q->prox_n = bruto->n + 1u;
    q->ultimo_y = y;
    b->soma_ir += ir;
    b->soma_vm += vm;
    b->maior = fmaxf(b->maior, fmaxf(ir, vm));
    b->min_y = fminf(b->min_y, y);
    b->max_y = fmaxf(b->max_y, y);
    q->soma4 += passa_faixa(q, ir - q->x0);
    if (++q->conta4 == QUALIDADE_RITMO_DECIMA) {
        float v = q->soma4 / (float)QUALIDADE_RITMO_DECIMA;
        q->anel[q->pos] = v;
        q->anel[q->pos + QUALIDADE_RITMO_ANEL] = v;
        if (++q->pos == QUALIDADE_RITMO_ANEL)
            q->pos = 0;
        if (q->cheio < QUALIDADE_RITMO_N)
            q->cheio++;
        q->soma4 = 0.0f;
        q->conta4 = 0;
    }
    if (++q->conta < QUALIDADE_BLOCO) {
        ritmo_passos(q); /* a amostra que fecha o bloco não faz conta do ritmo */
        return false;
    }

    q->conta = 0;
    /* A conta sobre a janela parada no fim do bloco anterior já terminou. */
    bool tem_ritmo = q->tem_foto && q->pronto;
    float ritmo = q->energia > 0.0f ? q->maior_r : 0.0f;
    q->tem_foto = q->cheio == QUALIDADE_RITMO_N;
    if (q->tem_foto) { /* os N pontos mais novos, que o próximo bloco não sobrescreve */
        q->ini = (q->pos + QUALIDADE_RITMO_ANEL - QUALIDADE_RITMO_N) % QUALIDADE_RITMO_ANEL;
        q->etapa = 0;
        q->i = 0;
        q->acc = 0.0f;
        q->energia = 0.0f;
        q->pronto = false;
    }
    bool cheia = q->tem_anterior;
    if (cheia)
        janela(q, s, tem_ritmo, ritmo);
    q->anterior = q->atual;
    q->tem_anterior = true;
    bloco_zera(&q->atual);
    return cheia;
}

bool qualidade_bpm_confiavel(const ppg_qualidade_t *q, const ppg_bpm_t *b, bool tem_batimento,
                             uint32_t n, uint32_t n_ultimo_pico)
{
    uint32_t idade = n - n_ultimo_pico; /* certo na volta do uint32; n_pico > n vira enorme e bloqueia */
    return q->usavel && b->valido && tem_batimento && idade <= QUALIDADE_BATIMENTO_VALE;
}

bool qualidade_batimento_usavel(const ppg_qualidade_t *q, bool tem_julgamento,
                                uint32_t n_julgamento, uint32_t n)
{
    uint32_t idade = n - n_julgamento; /* certo na volta do uint32; "no futuro" bloqueia */
    return q->usavel && tem_julgamento && idade <= QUALIDADE_JULGAMENTO_VALE;
}
