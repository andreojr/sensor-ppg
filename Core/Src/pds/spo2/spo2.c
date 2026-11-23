/*
 * spo2: ver spo2.h. Constantes e ordem das contas iguais às de spo2.py; mudou lá, muda aqui
 * (e regenere os vetores de testes/spo2/).
 */
#include "spo2/spo2.h"

#include <math.h>

#define ALFA 0.02f
#define DC_MIN 10000.0f
#define DC_VARIACAO_MAX 1.5f
#define R_MIN 0.2f
#define R_MAX 1.6f
#define CURVA_A 110.0f
#define CURVA_B 25.0f

void spo2_init(spo2_t *s)
{
    s->tem_dc = false;
    s->dc[0] = s->dc[1] = 0.0f;
    s->cont = 0;
    for (uint32_t j = 0; j < 4u; j++)
        s->bloco[j] = 0.0f;
    s->maior = 0.0f;
    for (uint32_t k = 0; k < SPO2_BLOCOS; k++) {
        for (uint32_t j = 0; j < 4u; j++)
            s->blocos[k][j] = 0.0f;
        s->maiores[k] = 0.0f;
    }
    s->idx = 0;
    s->cheios = 0;
    s->r = 0.0f;
}

float spo2_r(const spo2_t *s)
{
    return s->r;
}

static void estima(spo2_t *s, ppg_spo2_t *saida)
{
    /* Soma da janela, do bloco mais velho (o que vai ser sobrescrito) ao mais novo. */
    float soma[4] = {0.0f, 0.0f, 0.0f, 0.0f};
    for (uint32_t k = 0; k < SPO2_BLOCOS; k++) {
        const float *b = s->blocos[(s->idx + k) % SPO2_BLOCOS];
        for (uint32_t j = 0; j < 4u; j++)
            soma[j] += b[j];
    }
    const float n = (float)SPO2_JANELA;

    /* O DC de cada segundo: todos passam do mínimo e não variam demais. */
    bool dcs_ok = true;
    for (uint32_t canal = 0; canal < 2u; canal++) {
        float menor = s->blocos[0][canal] / (float)SPO2_HOP;
        float maior = menor;
        for (uint32_t k = 1; k < SPO2_BLOCOS; k++) {
            float dc_bloco = s->blocos[k][canal] / (float)SPO2_HOP;
            menor = dc_bloco < menor ? dc_bloco : menor;
            maior = dc_bloco > maior ? dc_bloco : maior;
        }
        dcs_ok = dcs_ok && menor >= DC_MIN && maior <= DC_VARIACAO_MAX * menor;
    }
    /* Algum canal perto do topo do ADC em algum segundo: o pulso pode estar cortado. */
    for (uint32_t k = 0; k < SPO2_BLOCOS; k++)
        dcs_ok = dcs_ok && s->maiores[k] < SPO2_SATURA;

    const float dc_ir = soma[0] / n, dc_vm = soma[1] / n;
    const float ac_ir = sqrtf(soma[2] / n), ac_vm = sqrtf(soma[3] / n);
    if (!(dcs_ok && ac_ir > 0.0f)) {
        s->r = 0.0f;
        saida->valido = false;
        saida->spo2_pct = 0.0f;
        return;
    }

    const float r = (ac_vm / dc_vm) / (ac_ir / dc_ir);
    float spo2 = CURVA_A - CURVA_B * r;
    spo2 = spo2 < 0.0f ? 0.0f : (spo2 > 100.0f ? 100.0f : spo2);
    s->r = r;
    saida->valido = r >= R_MIN && r <= R_MAX;
    saida->spo2_pct = saida->valido ? spo2 : 0.0f;
}

bool spo2_processa(spo2_t *s, const ppg_amostra_t *bruto, ppg_spo2_t *saida)
{
    const float x[2] = {bruto->ir, bruto->vermelho};
    if (!(isfinite(x[0]) && isfinite(x[1])))
        return false; /* descartada: não entra em nenhuma conta */
    if (!s->tem_dc) {
        s->dc[0] = x[0];
        s->dc[1] = x[1];
        s->tem_dc = true;
    }
    for (uint32_t c = 0; c < 2u; c++) {
        s->dc[c] = s->dc[c] + ALFA * (x[c] - s->dc[c]);
        const float ac = x[c] - s->dc[c];
        s->bloco[c] += x[c];
        s->bloco[2u + c] += ac * ac;
        s->maior = x[c] > s->maior ? x[c] : s->maior;
    }

    if (++s->cont < SPO2_HOP)
        return false;
    for (uint32_t j = 0; j < 4u; j++) {
        s->blocos[s->idx][j] = s->bloco[j];
        s->bloco[j] = 0.0f;
    }
    s->maiores[s->idx] = s->maior;
    s->maior = 0.0f;
    s->idx = s->idx + 1u == SPO2_BLOCOS ? 0u : s->idx + 1u;
    if (s->cheios < SPO2_BLOCOS)
        s->cheios++;
    s->cont = 0;
    if (s->cheios < SPO2_BLOCOS)
        return false;
    estima(s, saida);
    return true;
}
