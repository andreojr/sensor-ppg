/*
 * Teste da qualidade no PC: a saída do C bate com a do protótipo em Python
 * (vetores gerados por `uv run python -m analise.qualidade --vetores`), mais
 * casos de borda feitos aqui.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "confere.h"
#include "qualidade/qualidade.h"
#include "vetores/bordas.h"
#include "vetores/physionet.h"

#define SAIDAS_MAX 64u

/* Um caso de vetor: entrada e saídas esperadas do Python. */
typedef struct {
    const char *nome;
    uint32_t n_entrada;
    const int32_t *n;
    const float *ir, *vermelho;
    uint32_t n_saidas;
    const int32_t *saida_n, *valido, *dedo, *usavel, *motivo;
    const float *indice, *dc, *pi, *aspereza, *razao, *ritmo;
    float tol;
} caso_t;

/* Erro relativo ao valor esperado (pi e dc têm escalas bem diferentes). */
static int confere_rel(const char *nome, const float *obtido, const float *esperado, uint32_t n,
                       float tol)
{
    float escalado[SAIDAS_MAX];
    float um[SAIDAS_MAX];
    for (uint32_t i = 0; i < n; i++) {
        float escala = fmaxf(fabsf(esperado[i]), 1.0f);
        escalado[i] = obtido[i] / escala;
        um[i] = esperado[i] / escala;
    }
    return confere_float(nome, escalado, um, n, tol);
}

static int roda_caso(const caso_t *c)
{
    printf("-- %s\n", c->nome);
    static int32_t n[SAIDAS_MAX], valido[SAIDAS_MAX], dedo[SAIDAS_MAX], usavel[SAIDAS_MAX],
        motivo[SAIDAS_MAX];
    static float indice[SAIDAS_MAX], dc[SAIDAS_MAX], pi[SAIDAS_MAX], asp[SAIDAS_MAX],
        razao[SAIDAS_MAX], ritmo[SAIDAS_MAX];
    qualidade_t q;
    qualidade_init(&q);
    uint32_t k = 0;
    for (uint32_t i = 0; i < c->n_entrada; i++) {
        ppg_amostra_t e = {(uint32_t)c->n[i], c->ir[i], c->vermelho[i]};
        ppg_qualidade_t s;
        if (!qualidade_processa(&q, &e, &s))
            continue;
        if (k >= SAIDAS_MAX) {
            printf("saídas demais\n");
            return 1;
        }
        n[k] = (int32_t)e.n;
        valido[k] = s.valido;
        dedo[k] = s.dedo_presente;
        usavel[k] = s.usavel;
        motivo[k] = (int32_t)q.motivo;
        indice[k] = s.indice;
        dc[k] = q.dc_ir;
        pi[k] = q.pi;
        asp[k] = q.aspereza;
        razao[k] = q.razao;
        ritmo[k++] = q.ritmo;
    }
    if (k != c->n_saidas) {
        printf("%u saídas, esperado %u\n", (unsigned)k, (unsigned)c->n_saidas);
        return 1;
    }
    return confere_int("n", n, c->saida_n, k) + confere_int("valido", valido, c->valido, k) +
           confere_int("dedo", dedo, c->dedo, k) + confere_int("usavel", usavel, c->usavel, k) +
           confere_int("motivo", motivo, c->motivo, k) +
           confere_float("indice", indice, c->indice, k, 1e-6f) +
           confere_rel("dc", dc, c->dc, k, c->tol) + confere_rel("pi", pi, c->pi, k, c->tol) +
           confere_rel("aspereza", asp, c->aspereza, k, c->tol) +
           confere_rel("razao", razao, c->razao, k, c->tol) +
           confere_rel("ritmo", ritmo, c->ritmo, k, c->tol);
}

/* Sinal sintético: DC + senoide de 1,2 Hz, um pulso limpo. */
static ppg_amostra_t limpo(uint32_t n, float dc, float amp)
{
    float v = dc + amp * sinf(2.0f * 3.14159265f * 1.2f * (float)n / (float)PPG_FS_HZ);
    ppg_amostra_t e = {n, v, v};
    return e;
}

/* Início: nada sai antes de 2 s; *s intocado; depois uma saída por segundo. As 3
   primeiras ainda não têm 4 s de ritmo (SEM_RITMO); usável na 6ª. */
static int inicio(void)
{
    qualidade_t q;
    qualidade_init(&q);
    int falhas = 0;
    uint32_t saidas = 0;
    for (uint32_t i = 0; i < 9u * PPG_FS_HZ; i++) {
        ppg_amostra_t e = limpo(i, 100000.0f, 500.0f);
        ppg_qualidade_t s;
        memset(&s, 0xAB, sizeof s);
        ppg_qualidade_t antes = s;
        bool saiu = qualidade_processa(&q, &e, &s);
        bool deveria = i + 1u >= QUALIDADE_JANELA && (i + 1u) % QUALIDADE_BLOCO == 0;
        if (saiu != deveria || (!saiu && memcmp(&s, &antes, sizeof s) != 0)) {
            printf("início: amostra %u saiu=%d\n", (unsigned)i, saiu);
            falhas++;
        }
        if (!saiu)
            continue;
        /* 3 sem ritmo, depois janelas boas seguidas: 1/3, 2/3, 1; usável na 6ª saída. */
        saidas++;
        uint32_t boas = saidas > 3u ? saidas - 3u : 0u;
        float esperado = boas >= 3u ? 1.0f : (float)boas / 3.0f;
        uint32_t motivo = saidas <= 3u ? QUALIDADE_SEM_RITMO : 0u;
        if (!s.valido || !s.dedo_presente || fabsf(s.indice - esperado) > 1e-6f ||
            s.usavel != (boas >= 3u) || q.motivo != motivo || (saidas > 3u && !(q.ritmo >= 0.5f))) {
            printf("início: saída %u indice %.3f usavel %d motivo %u\n", (unsigned)saidas,
                   (double)s.indice, s.usavel, (unsigned)q.motivo);
            falhas++;
        }
    }
    printf("início: %u saídas, %d falhas\n", (unsigned)saidas, falhas);
    return falhas + (saidas != 8u);
}

/* Continua o n de onde parou, com nível fixo e pulso de amplitude amp; devolve a última saída. */
static ppg_qualidade_t constante(qualidade_t *q, float ir, float vm, float amp, uint32_t segundos)
{
    ppg_qualidade_t s = {0};
    uint32_t n0 = q->tem_n ? q->prox_n : 0u;
    for (uint32_t i = n0; i < n0 + segundos * PPG_FS_HZ; i++) {
        ppg_amostra_t e = limpo(i, ir, amp);
        e.vermelho = vm + (e.ir - ir);
        qualidade_processa(q, &e, &s);
    }
    return s;
}

static int estados(void)
{
    int falhas = 0;
    qualidade_t q;

    qualidade_init(&q); /* sem dedo: nível do sensor real */
    ppg_qualidade_t s = constante(&q, 1500.0f, 1500.0f, 5.0f, 5);
    if (s.dedo_presente || s.usavel || s.indice != 0.0f || !(q.motivo & QUALIDADE_SEM_DEDO)) {
        printf("sem dedo: dedo %d usavel %d motivo %u\n", s.dedo_presente, s.usavel,
               (unsigned)q.motivo);
        falhas++;
    }

    /* O dedo precisa dos dois canais: um só com nível de dedo não basta. */
    qualidade_init(&q);
    s = constante(&q, 100000.0f, 1500.0f, 500.0f, 5);
    if (s.dedo_presente || s.usavel || !(q.motivo & QUALIDADE_SEM_DEDO)) {
        printf("só o IR: dedo %d usavel %d motivo %u\n", s.dedo_presente, s.usavel,
               (unsigned)q.motivo);
        falhas++;
    }
    qualidade_init(&q);
    s = constante(&q, 1500.0f, 100000.0f, 5.0f, 5);
    if (s.dedo_presente || s.usavel || !(q.motivo & QUALIDADE_SEM_DEDO)) {
        printf("só o vermelho: dedo %d usavel %d motivo %u\n", s.dedo_presente, s.usavel,
               (unsigned)q.motivo);
        falhas++;
    }

    qualidade_init(&q); /* saturado: topo do ADC */
    s = constante(&q, 255000.0f, 200000.0f, 500.0f, 5);
    if (s.usavel || !(q.motivo & QUALIDADE_SATURADO)) {
        printf("saturado: usavel %d motivo %u\n", s.usavel, (unsigned)q.motivo);
        falhas++;
    }
    qualidade_init(&q); /* só o vermelho no topo também conta */
    s = constante(&q, 200000.0f, 255000.0f, 500.0f, 5);
    if (s.usavel || !(q.motivo & QUALIDADE_SATURADO)) {
        printf("vermelho saturado: usavel %d motivo %u\n", s.usavel, (unsigned)q.motivo);
        falhas++;
    }

    qualidade_init(&q); /* dedo sem pulso: pi abaixo do mínimo */
    s = constante(&q, 100000.0f, 100000.0f, 5.0f, 5);
    if (s.usavel || !s.dedo_presente || !(q.motivo & QUALIDADE_PULSO_FRACO)) {
        printf("sem pulso: usavel %d motivo %u\n", s.usavel, (unsigned)q.motivo);
        falhas++;
    }

    qualidade_init(&q); /* pulso de 8% do DC: movimento */
    s = constante(&q, 100000.0f, 100000.0f, 4000.0f, 5);
    if (s.usavel || !(q.motivo & QUALIDADE_MOVIMENTO)) {
        printf("pulso enorme: usavel %d motivo %u\n", s.usavel, (unsigned)q.motivo);
        falhas++;
    }

    /* Pulso que triplica de repente: razão > RAZAO_MAX. */
    qualidade_init(&q);
    s = constante(&q, 100000.0f, 100000.0f, 300.0f, 8); /* usável a partir do 7º s */
    bool antes = s.usavel;
    s = constante(&q, 100000.0f, 100000.0f, 900.0f, 2);
    if (!antes || s.usavel || !(q.motivo & QUALIDADE_MOVIMENTO) || !(q.razao > 2.0f)) {
        printf("pulso triplica: antes %d usavel %d motivo %u razao %.2f\n", antes, s.usavel,
               (unsigned)q.motivo, (double)q.razao);
        falhas++;
    }
    /* Se o pulso fica grande, depois de RUINS_ESQUECE janelas ruins a referência é
       esquecida, reaprendida e o sinal volta a ser usável. */
    s = constante(&q, 100000.0f, 100000.0f, 900.0f, QUALIDADE_RUINS_ESQUECE + 4u);
    if (!s.usavel || q.motivo != 0u) {
        printf("referência esquecida: usavel %d motivo %u\n", s.usavel, (unsigned)q.motivo);
        falhas++;
    }
    /* Sinal constante com dedo: energia zero no ritmo, sem NaN. */
    qualidade_init(&q);
    s = constante(&q, 100000.0f, 100000.0f, 0.0f, 8);
    if (s.usavel || !(q.motivo & QUALIDADE_SEM_RITMO) || q.ritmo != 0.0f) {
        printf("constante: usavel %d motivo %u ritmo %f\n", s.usavel, (unsigned)q.motivo,
               (double)q.ritmo);
        falhas++;
    }

    /* A referência só é esquecida na RUINS_ESQUECE-ésima janela ruim seguida, não antes. */
    qualidade_init(&q);
    (void)constante(&q, 100000.0f, 100000.0f, 500.0f, 6);
    bool tinha_ref = q.tem_ref;
    uint32_t n0 = q.prox_n;
    for (uint32_t i = n0; i < n0 + (QUALIDADE_RUINS_ESQUECE + 4u) * PPG_FS_HZ; i++) {
        ppg_amostra_t e = limpo(i, 100000.0f, 5.0f); /* sem pulso: janela ruim */
        e.vermelho = e.ir;
        if (!qualidade_processa(&q, &e, &s))
            continue;
        bool esperado = q.ruins < QUALIDADE_RUINS_ESQUECE;
        if (q.ruins > 0u && q.tem_ref != esperado) {
            printf("esquece: %u ruins, tem_ref %d\n", (unsigned)q.ruins, q.tem_ref);
            falhas++;
        }
    }
    if (!tinha_ref || q.tem_ref) {
        printf("esquece: tinha %d, tem no fim %d\n", tinha_ref, q.tem_ref);
        falhas++;
    }
    printf("estados: %d falhas\n", falhas);
    return falhas;
}

/* Reinício: init de novo, n que pula e amostra NaN recomeçam a janela. */
static int reinicio(void)
{
    int falhas = 0;
    qualidade_t q;
    ppg_qualidade_t s;
    qualidade_init(&q);
    (void)constante(&q, 100000.0f, 100000.0f, 500.0f, 5);

    qualidade_init(&q);
    if (q.tem_n || q.conta != 0u || q.boas != 0u || q.tem_ref) {
        printf("init não zerou\n");
        falhas++;
    }

    /* n pula: a próxima saída só 2 s depois do pulo. */
    uint32_t primeira = 0;
    for (uint32_t i = 0; i < 6u * PPG_FS_HZ; i++) {
        uint32_t n = i < 150u ? i : i + 37u;
        ppg_amostra_t e = limpo(n, 100000.0f, 500.0f);
        if (qualidade_processa(&q, &e, &s) && !primeira)
            primeira = i;
    }
    if (primeira != 150u + QUALIDADE_JANELA - 1u) {
        printf("pulo no n: primeira saída na amostra %u\n", (unsigned)primeira);
        falhas++;
    }

    /* NaN: descartada e recomeça. */
    qualidade_init(&q);
    primeira = 0;
    for (uint32_t i = 0; i < 6u * PPG_FS_HZ; i++) {
        ppg_amostra_t e = limpo(i, 100000.0f, 500.0f);
        if (i == 120u)
            e.ir = NAN;
        if (qualidade_processa(&q, &e, &s) && !primeira)
            primeira = i;
    }
    if (primeira != 121u + QUALIDADE_JANELA - 1u) {
        printf("NaN: primeira saída na amostra %u\n", (unsigned)primeira);
        falhas++;
    }
    /* Reinício com os 4 s do ritmo cheios: as 3 saídas seguintes não têm ritmo. */
    qualidade_init(&q);
    (void)constante(&q, 100000.0f, 100000.0f, 500.0f, 10);
    uint32_t n0 = q.prox_n + 50u, sem = 0, saidas = 0;
    for (uint32_t i = n0; i < n0 + 5u * PPG_FS_HZ; i++) {
        ppg_amostra_t e = limpo(i, 100000.0f, 500.0f);
        if (qualidade_processa(&q, &e, &s) && saidas++ < 3u)
            sem += (q.motivo & QUALIDADE_SEM_RITMO) && q.ritmo == 0.0f && !s.usavel;
    }
    if (sem != 3u) {
        printf("reinício com ritmo cheio: %u de 3 sem ritmo\n", (unsigned)sem);
        falhas++;
    }


    /* NaN só no vermelho também recomeça. */
    qualidade_init(&q);
    primeira = 0;
    for (uint32_t i = 0; i < 6u * PPG_FS_HZ; i++) {
        ppg_amostra_t e = limpo(i, 100000.0f, 500.0f);
        if (i == 120u)
            e.vermelho = NAN;
        if (qualidade_processa(&q, &e, &s) && !primeira)
            primeira = i;
    }
    if (primeira != 121u + QUALIDADE_JANELA - 1u) {
        printf("NaN no vermelho: primeira saída na amostra %u\n", (unsigned)primeira);
        falhas++;
    }
    printf("reinício: %d falhas\n", falhas);
    return falhas;
}

/* A decisão do BPM confiável: mesmos casos de test_bpm_confiavel no Python. */
static int decisao(void)
{
    struct {
        bool usavel, valido, tem;
        uint32_t n, n_pico;
        bool mostra;
    } casos[] = {
        {true, true, true, 1000u, 900u, true},   {true, false, true, 1000u, 900u, false},
        {false, true, true, 1000u, 900u, false}, {false, false, true, 1000u, 900u, false},
        {true, true, false, 100u, 0u, false},   {true, true, true, 1000u, 700u, true},
        {true, true, true, 1001u, 700u, false},  {true, true, true, 1000u, 1080u, false},
        {true, true, true, 50u, 0xFFFFFFCEu, true},
    };
    int falhas = (QUALIDADE_BATIMENTO_VALE != 3u * PPG_FS_HZ);
    for (uint32_t i = 0; i < sizeof casos / sizeof casos[0]; i++) {
        ppg_qualidade_t q = {.valido = true, .dedo_presente = true, .indice = 1.0f,
                             .usavel = casos[i].usavel};
        ppg_bpm_t b = {.valido = casos[i].valido, .bpm = 60.0f};
        bool m = qualidade_bpm_confiavel(&q, &b, casos[i].tem, casos[i].n, casos[i].n_pico);
        if (m != casos[i].mostra) {
            printf("decisão: caso %u deu %d\n", (unsigned)i, m);
            falhas++;
        }
    }
    printf("decisão: %d falhas\n", falhas);
    return falhas;
}

int main(void)
{
    const caso_t physionet = {
        "physionet", PHYSIONET_N_N, physionet_n, physionet_ir, physionet_vermelho,
        PHYSIONET_SAIDA_N_N, physionet_saida_n, physionet_saida_valido, physionet_saida_dedo,
        physionet_saida_usavel, physionet_saida_motivo, physionet_saida_indice,
        physionet_saida_dc, physionet_saida_pi, physionet_saida_aspereza, physionet_saida_razao,
        physionet_saida_ritmo, PHYSIONET_TOL};
    const caso_t bordas = {
        "bordas", BORDAS_N_N, bordas_n, bordas_ir, bordas_vermelho, BORDAS_SAIDA_N_N,
        bordas_saida_n, bordas_saida_valido, bordas_saida_dedo, bordas_saida_usavel,
        bordas_saida_motivo, bordas_saida_indice, bordas_saida_dc, bordas_saida_pi,
        bordas_saida_aspereza, bordas_saida_razao, bordas_saida_ritmo, BORDAS_TOL};

    int falhas = roda_caso(&physionet) + roda_caso(&bordas) + inicio() + estados() + reinicio() +
                 decisao();
    printf(falhas ? "FALHOU (%d)\n" : "OK\n", falhas);
    return falhas ? 1 : 0;
}
