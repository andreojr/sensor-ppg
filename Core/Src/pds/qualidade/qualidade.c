/* qualidade.c: detector de sinal ruim. Ver qualidade.h. */
#include "qualidade/qualidade.h"

#include <math.h>
#include <string.h>

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
    memset(q, 0, sizeof *q);
    bloco_zera(&q->atual);
    bloco_zera(&q->anterior);
}

/* Fecha a janela (bloco anterior + atual) e decide. */
static void janela(qualidade_t *q, ppg_qualidade_t *s)
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
    if (!q->tem_n)
        q->media = ir;

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
    if (++q->conta < QUALIDADE_BLOCO)
        return false;

    q->conta = 0;
    bool cheia = q->tem_anterior;
    if (cheia)
        janela(q, s);
    q->anterior = q->atual;
    q->tem_anterior = true;
    bloco_zera(&q->atual);
    return cheia;
}
