/* spo2: a saída do C bate com a do protótipo Python (vetores de analise.spo2), e o módulo se
 * comporta nos casos que o Python também testa: R conhecido, canais trocados, sem pulso, NaN,
 * dedo que sai no meio da janela, saturação, reinício. */
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "confere.h"
#include "qualidade/qualidade.h"
#include "spo2/spo2.h"
#include "vetores/s1_sit.h"
#include "vetores/sem_dedo.h"

#define MAX_SAIDAS 64u
#define PI_F 3.14159265358979323846f

static int falhas;

#define CHECA(cond, msg)                                              \
    do {                                                              \
        if (!(cond)) {                                                \
            printf("FALHOU: %s (linha %d)\n", msg, __LINE__);         \
            falhas++;                                                 \
        }                                                             \
    } while (0)

typedef struct {
    int32_t valido[MAX_SAIDAS];
    float spo2[MAX_SAIDAS];
    float r[MAX_SAIDAS];
    uint32_t amostra[MAX_SAIDAS]; /* índice da amostra que fechou cada saída */
    uint32_t n;
} saidas_t;

static void roda(spo2_t *s, const float *ir, const float *vm, uint32_t n_amostras, saidas_t *o)
{
    o->n = 0;
    for (uint32_t i = 0; i < n_amostras; i++) {
        ppg_amostra_t x = {.n = i, .ir = ir[i], .vermelho = vm[i]};
        ppg_spo2_t saida;
        if (!spo2_processa(s, &x, &saida))
            continue;
        if (o->n < MAX_SAIDAS) {
            o->valido[o->n] = saida.valido ? 1 : 0;
            o->spo2[o->n] = saida.spo2_pct;
            o->r[o->n] = spo2_r(s);
            o->amostra[o->n] = i;
        }
        o->n++;
    }
}

typedef struct {
    const char *nome;
    const float *ir, *vm;
    uint32_t n_entrada, n_saidas;
    const int32_t *valido;
    const float *spo2, *r;
    float tol;
} caso_t;

static int confere_caso(const caso_t *c)
{
    static spo2_t s;
    static saidas_t o;
    spo2_init(&s);
    roda(&s, c->ir, c->vm, c->n_entrada, &o);
    printf("== %s: %u saidas (esperado %u), a primeira na amostra %u\n", c->nome, (unsigned)o.n,
           (unsigned)c->n_saidas, (unsigned)o.amostra[0]);
    if (o.n != c->n_saidas || o.n > MAX_SAIDAS)
        return 1;
    int f = o.amostra[0] != SPO2_JANELA - 1u;
    f += confere_int("valido", o.valido, c->valido, o.n) +
         confere_float("spo2", o.spo2, c->spo2, o.n, c->tol) +
         confere_float("r", o.r, c->r, o.n, c->tol);

    /* Reiniciar tem que dar o mesmo resultado. */
    static saidas_t o2;
    spo2_init(&s);
    roda(&s, c->ir, c->vm, c->n_entrada, &o2);
    f += confere_int("valido (reiniciado)", o2.valido, o.valido, o.n) +
         confere_float("spo2 (reiniciado)", o2.spo2, o.spo2, o.n, 0.0f);
    return f;
}

/* IR e vermelho sintéticos: AC/DC do IR é 1% e o do vermelho é r_real vezes isso. */
static void sintetico(float *ir, float *vm, uint32_t n, float r_real, float dc_ir, float dc_vm)
{
    for (uint32_t i = 0; i < n; i++) {
        float pulso = sinf(2.0f * PI_F * 1.2f * (float)i / 100.0f);
        ir[i] = dc_ir * (1.0f + 0.01f * pulso);
        vm[i] = dc_vm * (1.0f + 0.01f * r_real * pulso);
    }
}

static float ir_s[2000], vm_s[2000];

static void comportamento(void)
{
    static spo2_t s;
    static saidas_t o;

    /* R conhecido: o módulo acha o R e a reta 110 - 25 R. */
    static const float R[] = {0.4f, 0.5f, 0.8f, 1.0f, 1.4f};
    for (unsigned k = 0; k < sizeof R / sizeof R[0]; k++) {
        sintetico(ir_s, vm_s, 2000, R[k], 80000.0f, 78000.0f);
        spo2_init(&s);
        roda(&s, ir_s, vm_s, 2000, &o);
        bool ok = o.n == 13u;
        for (uint32_t i = 0; i < o.n; i++) {
            float esperado = 110.0f - 25.0f * R[k];
            ok = ok && o.valido[i] && fabsf(o.r[i] - R[k]) < 0.01f * R[k] &&
                 fabsf(o.spo2[i] - (esperado > 100.0f ? 100.0f : esperado)) < 0.5f;
        }
        CHECA(ok, "acha o R conhecido e a reta");
    }

    /* Saídas a cada segundo a partir da amostra 800. */
    bool ritmo = o.amostra[0] == 799u;
    for (uint32_t i = 1; i < o.n; i++)
        ritmo = ritmo && o.amostra[i] - o.amostra[i - 1u] == 100u;
    CHECA(ritmo, "primeira saída na amostra 800 e depois uma por segundo");

    /* Canais trocados: R de 0,5 vira 2,0, acima do R_MAX. */
    sintetico(ir_s, vm_s, 2000, 0.5f, 80000.0f, 78000.0f);
    spo2_init(&s);
    roda(&s, vm_s, ir_s, 2000, &o);
    bool algum = false;
    for (uint32_t i = 0; i < o.n; i++)
        algum = algum || o.valido[i];
    CHECA(o.n > 0 && !algum, "canais trocados ficam inválidos");

    /* R abaixo do mínimo e sem dedo (DC baixo). */
    sintetico(ir_s, vm_s, 2000, 0.1f, 80000.0f, 78000.0f);
    spo2_init(&s);
    roda(&s, ir_s, vm_s, 2000, &o);
    algum = false;
    for (uint32_t i = 0; i < o.n; i++)
        algum = algum || o.valido[i];
    CHECA(o.n > 0 && !algum, "R abaixo do mínimo é inválido");
    sintetico(ir_s, vm_s, 2000, 0.5f, 5000.0f, 5000.0f);
    spo2_init(&s);
    roda(&s, ir_s, vm_s, 2000, &o);
    algum = false;
    bool zero = true;
    for (uint32_t i = 0; i < o.n; i++) {
        algum = algum || o.valido[i];
        zero = zero && o.spo2[i] == 0.0f;
    }
    CHECA(o.n > 0 && !algum && zero, "DC baixo (sem dedo) é inválido e sai 0");

    /* Sem pulso nenhum: não divide por zero. */
    for (uint32_t i = 0; i < 2000u; i++)
        ir_s[i] = vm_s[i] = 80000.0f;
    spo2_init(&s);
    roda(&s, ir_s, vm_s, 2000, &o);
    algum = false;
    bool finito = true;
    for (uint32_t i = 0; i < o.n; i++) {
        algum = algum || o.valido[i];
        finito = finito && isfinite(o.spo2[i]) && isfinite(o.r[i]);
    }
    CHECA(o.n > 0 && !algum && finito, "sem pulso é inválido e sem NaN");

    /* Dedo que sai no meio: nenhuma janela que já pega a queda pode ser válida. */
    sintetico(ir_s, vm_s, 2000, 0.5f, 80000.0f, 78000.0f);
    for (uint32_t i = 1000; i < 2000u; i++)
        ir_s[i] = vm_s[i] = 1500.0f;
    spo2_init(&s);
    roda(&s, ir_s, vm_s, 2000, &o);
    bool antes = false, depois = false;
    for (uint32_t i = 0; i < o.n; i++) {
        if (o.amostra[i] < 1000u)
            antes = antes || o.valido[i];
        else
            depois = depois || o.valido[i];
    }
    CHECA(antes && !depois, "dedo que sai no meio da janela não vira valor errado");

    /* DC que cai pela metade (bem acima do mínimo): variação demais entre os segundos. */
    sintetico(ir_s, vm_s, 2000, 0.5f, 80000.0f, 78000.0f);
    for (uint32_t i = 1000; i < 2000u; i++) {
        ir_s[i] *= 0.5f;
        vm_s[i] *= 0.5f;
    }
    spo2_init(&s);
    roda(&s, ir_s, vm_s, 2000, &o);
    depois = false;
    for (uint32_t i = 0; i < o.n; i++)
        if (o.amostra[i] >= 1000u && o.amostra[i] < 1000u + SPO2_JANELA - SPO2_HOP)
            depois = depois || o.valido[i];
    CHECA(!depois, "DC que varia demais entre os segundos é inválido");

    /* Saturação: o mesmo limite da qualidade, em qualquer um dos canais. */
    CHECA(SPO2_SATURA == QUALIDADE_SATURA, "SPO2_SATURA igual ao QUALIDADE_SATURA");
    for (int canal = 0; canal < 2; canal++) {
        sintetico(ir_s, vm_s, 2000, 0.5f, canal == 0 ? 260000.0f : 80000.0f,
                  canal == 1 ? 260000.0f : 78000.0f);
        for (uint32_t i = 0; i < 2000u; i++) { /* o ADC corta em 262143 */
            ir_s[i] = ir_s[i] > 262143.0f ? 262143.0f : ir_s[i];
            vm_s[i] = vm_s[i] > 262143.0f ? 262143.0f : vm_s[i];
        }
        spo2_init(&s);
        roda(&s, ir_s, vm_s, 2000, &o);
        algum = false;
        zero = true;
        for (uint32_t i = 0; i < o.n; i++) {
            algum = algum || o.valido[i];
            zero = zero && o.spo2[i] == 0.0f;
        }
        CHECA(o.n > 0 && !algum && zero, canal == 0 ? "IR saturado é inválido"
                                                   : "vermelho saturado é inválido");
    }

    /* Um segundo só passa do limite: só as janelas que o pegam ficam inválidas. */
    sintetico(ir_s, vm_s, 2000, 0.5f, 247000.0f, 78000.0f);
    for (uint32_t i = 1000; i < 1000u + SPO2_HOP; i++)
        ir_s[i] += 1000.0f;
    spo2_init(&s);
    roda(&s, ir_s, vm_s, 2000, &o);
    bool certo = o.n > 0u;
    for (uint32_t i = 0; i < o.n; i++) {
        bool pega = o.amostra[i] >= 1000u && o.amostra[i] < 1000u + SPO2_JANELA;
        certo = certo && o.valido[i] == !pega;
    }
    CHECA(certo, "um segundo saturado invalida só as janelas que o pegam");

    /* NaN e infinito são descartados: não sobra NaN nas saídas. */
    sintetico(ir_s, vm_s, 2000, 0.5f, 80000.0f, 78000.0f);
    ir_s[1000] = 0.0f / 0.0f;
    vm_s[1500] = 1.0f / 0.0f;
    spo2_init(&s);
    roda(&s, ir_s, vm_s, 2000, &o);
    finito = true;
    bool todas = true;
    for (uint32_t i = 0; i < o.n; i++) {
        finito = finito && isfinite(o.spo2[i]) && isfinite(o.r[i]);
        todas = todas && o.valido[i];
    }
    CHECA(o.n > 0 && finito && todas, "amostra não finita é descartada");
}

int main(void)
{
    const caso_t casos[] = {
        {"s1_sit", s1_sit_ir, s1_sit_vermelho, S1_SIT_IR_N, S1_SIT_VALIDO_N, s1_sit_valido,
         s1_sit_spo2, s1_sit_r, S1_SIT_TOL},
        {"sem_dedo", sem_dedo_ir, sem_dedo_vermelho, SEM_DEDO_IR_N, SEM_DEDO_VALIDO_N,
         sem_dedo_valido, sem_dedo_spo2, sem_dedo_r, SEM_DEDO_TOL},
    };
    for (uint32_t i = 0; i < sizeof casos / sizeof casos[0]; i++)
        falhas += confere_caso(&casos[i]);
    comportamento();
    return falhas ? 1 : 0;
}
