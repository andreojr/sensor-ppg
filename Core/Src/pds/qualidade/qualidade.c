/* qualidade.c: detector de sinal ruim. Ver qualidade.h. */
#include "qualidade/qualidade.h"

#include <math.h>
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
    for (uint32_t i = 0; i < 2u; i++) {
        float y = SOS[i][0] * x + q->z[2u * i];
        q->z[2u * i] = SOS[i][1] * x - SOS[i][3] * y + q->z[2u * i + 1u];
        q->z[2u * i + 1u] = SOS[i][2] * x - SOS[i][4] * y;
        x = y;
    }
    return x;
}

/*
 * Um pedaço da conta do ritmo sobre a foto, por amostra:
 *   passo 0       média, e tira a média da foto
 *   passo 1       energia
 *   passos 2..29  um atraso cada (ATRASO_MIN..ATRASO_MAX), guarda o maior r
 */
#define RITMO_PASSOS (2u + QUALIDADE_RITMO_ATRASO_MAX - QUALIDADE_RITMO_ATRASO_MIN + 1u)

static void ritmo_passo(qualidade_t *q)
{
    if (!q->tem_foto || q->passo >= RITMO_PASSOS)
        return;
    float *z = q->foto;
    if (q->passo == 0u) {
        float soma = 0.0f;
        for (uint32_t i = 0; i < QUALIDADE_RITMO_N; i++)
            soma += z[i];
        float media = soma / (float)QUALIDADE_RITMO_N;
        for (uint32_t i = 0; i < QUALIDADE_RITMO_N; i++)
            z[i] -= media;
    } else if (q->passo == 1u) {
        float e = 0.0f;
        for (uint32_t i = 0; i < QUALIDADE_RITMO_N; i++)
            e += z[i] * z[i];
        q->energia = e;
        q->maior_r = -INFINITY;
    } else if (q->energia > 0.0f) {
        uint32_t k = QUALIDADE_RITMO_ATRASO_MIN + q->passo - 2u;
        float r = 0.0f;
        for (uint32_t i = k; i < QUALIDADE_RITMO_N; i++)
            r += z[i] * z[i - k];
        q->maior_r = fmaxf(q->maior_r, r / q->energia);
    }
    q->passo++;
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
    memset(q, 0, sizeof *q);
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
        q->anel[q->pos] = q->soma4 / (float)QUALIDADE_RITMO_DECIMA;
        q->pos = (q->pos + 1u) % QUALIDADE_RITMO_N;
        if (q->cheio < QUALIDADE_RITMO_N)
            q->cheio++;
        q->soma4 = 0.0f;
        q->conta4 = 0;
    }
    ritmo_passo(q);
    if (++q->conta < QUALIDADE_BLOCO)
        return false;

    q->conta = 0;
    /* A conta sobre a foto do bloco anterior terminou nas primeiras amostras deste. */
    bool tem_ritmo = q->tem_foto && q->passo >= RITMO_PASSOS;
    float ritmo = q->energia > 0.0f ? q->maior_r : 0.0f;
    q->tem_foto = q->cheio == QUALIDADE_RITMO_N;
    if (q->tem_foto) {
        for (uint32_t i = 0; i < QUALIDADE_RITMO_N; i++)
            q->foto[i] = q->anel[(q->pos + i) % QUALIDADE_RITMO_N];
        q->passo = 0;
    }
    bool cheia = q->tem_anterior;
    if (cheia)
        janela(q, s, tem_ritmo, ritmo);
    q->anterior = q->atual;
    q->tem_anterior = true;
    bloco_zera(&q->atual);
    return cheia;
}
