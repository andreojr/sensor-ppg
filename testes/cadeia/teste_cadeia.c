/*
 * Teste da cadeia no PC: o bruto do vetor (90 s do PhysioNet, gerado por
 * `uv run python -m analise.cadeia --vetores`) passa por cadeia_processa e
 * todas as saídas batem com a referência em Python. Mais: relógio nulo, relógio
 * falso (ciclos) e várias saídas de HRV na mesma amostra.
 */
#include <stdint.h>
#include <stdio.h>

#include "cadeia/cadeia.h"
#include "confere.h"
#include "vetores/physionet.h"

#define MAX 256u

static int32_t bat_n_pico[MAX], bat_rr_valido[MAX], bat_bpm_valido[MAX];
static float bat_fracao[MAX], bat_rr_ms[MAX], bat_bpm[MAX];
static int32_t esp_n[MAX], esp_valido[MAX];
static float esp_bpm[MAX];
static int32_t hrv_n_pico[MAX], hrv_valido[MAX], hrv_rr_usado[MAX];
static float hrv_sdnn[MAX], hrv_rmssd[MAX];
static int32_t resp_n[MAX], resp_valido[MAX];
static float resp_rpm[MAX];
static int32_t tela_n[MAX], tela_mostra[MAX];
static float tela_bpm[MAX];

static cadeia_t cadeia; /* ~20 KB: static */

static uint32_t tempo_falso;
static uint32_t relogio_falso(void)
{
    tempo_falso += 10u;
    return tempo_falso;
}

/* Conta quantas vezes passou do MAX (falha) em vez de escrever fora. */
static int cheio;
#define POE(k) ((k) < MAX ? 1 : (cheio++, 0))

static int vetor(void)
{
    printf("-- physionet\n");
    if (!cadeia_init(&cadeia, NULL)) {
        printf("cadeia_init falhou\n");
        return 1;
    }
    uint32_t nb = 0, ne = 0, nh = 0, nr = 0, nt = 0, hrv_juntos = 0;
    int fora_de_ordem = 0;
    for (uint32_t i = 0; i < PHYSIONET_IR_N; i++) {
        ppg_amostra_t bruto = {i, physionet_ir[i], physionet_vermelho[i]};
        cadeia_saida_t s;
        cadeia_processa(&cadeia, &bruto, &s);
        if (s.filtrado.n != i)
            fora_de_ordem++;
        if (s.bateu && POE(nb)) {
            bat_n_pico[nb] = (int32_t)s.batimento.n_pico;
            bat_fracao[nb] = s.batimento.fracao;
            bat_rr_valido[nb] = s.batimento.rr_valido;
            bat_rr_ms[nb] = s.batimento.rr_ms;
            bat_bpm_valido[nb] = s.bpm.valido;
            bat_bpm[nb] = s.bpm.valido ? s.bpm.bpm : 0.0f;
            nb++;
        }
        for (uint32_t k = 0; k < s.n_hrv; k++) {
            if (k > 0 && s.hrv[k].n_pico <= s.hrv[k - 1u].n_pico)
                fora_de_ordem++;
            if (POE(nh)) {
                hrv_n_pico[nh] = (int32_t)s.hrv[k].n_pico;
                hrv_valido[nh] = s.hrv[k].hrv.valido;
                hrv_sdnn[nh] = s.hrv[k].hrv.sdnn_ms;
                hrv_rmssd[nh] = s.hrv[k].hrv.rmssd_ms;
                hrv_rr_usado[nh] = s.hrv[k].rr_usado;
                nh++;
            }
        }
        if (s.n_hrv > 1u)
            hrv_juntos++;
        if (s.espectral && POE(ne)) {
            esp_n[ne] = (int32_t)s.filtrado.n;
            esp_valido[ne] = s.bpm_espectral.valido;
            esp_bpm[ne] = s.bpm_espectral.bpm;
            ne++;
        }
        if (s.respirou && POE(nr)) {
            resp_n[nr] = (int32_t)i;
            resp_valido[nr] = s.respiracao.valido;
            resp_rpm[nr] = s.respiracao.rpm;
            nr++;
        }
        if (s.julgou && POE(nt)) {
            tela_n[nt] = (int32_t)i;
            tela_mostra[nt] = s.mostra;
            tela_bpm[nt] = s.mostra ? s.bpm.bpm : 0.0f;
            nt++;
        }
    }

    int f = cheio + fora_de_ordem;
#define TAMANHO(nome, obtido, N)                                                              \
    if ((obtido) != (N)) {                                                                    \
        printf("%s: %lu saídas, esperadas %lu\n", nome, (unsigned long)(obtido),              \
               (unsigned long)(N));                                                           \
        f++;                                                                                  \
    }
    TAMANHO("batimentos", nb, PHYSIONET_BAT_N_PICO_N)
    TAMANHO("espectral", ne, PHYSIONET_ESP_N_N)
    TAMANHO("hrv", nh, PHYSIONET_HRV_N_PICO_N)
    TAMANHO("respiracao", nr, PHYSIONET_RESP_N_N)
    TAMANHO("tela", nt, PHYSIONET_TELA_N_N)
    if (f)
        return f;
    const float tol = PHYSIONET_TOL;
    f += confere_int("bat_n_pico", bat_n_pico, physionet_bat_n_pico, nb);
    f += confere_float("bat_fracao", bat_fracao, physionet_bat_fracao, nb, tol);
    f += confere_int("bat_rr_valido", bat_rr_valido, physionet_bat_rr_valido, nb);
    f += confere_float("bat_rr_ms", bat_rr_ms, physionet_bat_rr_ms, nb, tol);
    f += confere_int("bat_bpm_valido", bat_bpm_valido, physionet_bat_bpm_valido, nb);
    f += confere_float("bat_bpm", bat_bpm, physionet_bat_bpm, nb, tol);
    f += confere_int("esp_n", esp_n, physionet_esp_n, ne);
    f += confere_int("esp_valido", esp_valido, physionet_esp_valido, ne);
    f += confere_float("esp_bpm", esp_bpm, physionet_esp_bpm, ne, tol);
    f += confere_int("hrv_n_pico", hrv_n_pico, physionet_hrv_n_pico, nh);
    f += confere_int("hrv_valido", hrv_valido, physionet_hrv_valido, nh);
    f += confere_float("hrv_sdnn", hrv_sdnn, physionet_hrv_sdnn, nh, tol);
    f += confere_float("hrv_rmssd", hrv_rmssd, physionet_hrv_rmssd, nh, tol);
    f += confere_int("hrv_rr_usado", hrv_rr_usado, physionet_hrv_rr_usado, nh);
    f += confere_int("resp_n", resp_n, physionet_resp_n, nr);
    f += confere_int("resp_valido", resp_valido, physionet_resp_valido, nr);
    f += confere_float("resp_rpm", resp_rpm, physionet_resp_rpm, nr, tol);
    f += confere_int("tela_n", tela_n, physionet_tela_n, nt);
    f += confere_int("tela_mostra", tela_mostra, physionet_tela_mostra, nt);
    f += confere_float("tela_bpm", tela_bpm, physionet_tela_bpm, nt, tol);

    /* Ficha: o display lê o último BPM e a última decisão da regra. */
    const ppg_resultados_t *r = cadeia_resultados(&cadeia);
    if (r->bpm_picos.valido != (tela_mostra[nt - 1u] != 0) || r->spo2.valido) {
        printf("ficha: bpm_picos.valido %d (última tela %d), spo2.valido %d\n",
               r->bpm_picos.valido, tela_mostra[nt - 1u], r->spo2.valido);
        f++;
    }
    if (r->ultimo_batimento.n_pico != (uint32_t)bat_n_pico[nb - 1u]) {
        printf("ficha: ultimo_batimento %lu, esperado %ld\n",
               (unsigned long)r->ultimo_batimento.n_pico, (long)bat_n_pico[nb - 1u]);
        f++;
    }
    /* Relógio nulo: não mede. */
    if (cadeia.ciclos.total.conta != 0u || cadeia.ciclos.filtro.conta != 0u) {
        printf("relógio NULL mediu ciclos\n");
        f++;
    }
    /* A 72 bpm a qualidade solta 1 ou 2 batimentos por julgamento. */
    printf("amostras com mais de uma saída de HRV: %lu\n", (unsigned long)hrv_juntos);
    if (hrv_juntos == 0u) {
        printf("nenhuma amostra com mais de uma saída de HRV\n");
        f++;
    }
    return f;
}

static int ciclos(void)
{
    printf("-- relógio falso\n");
    if (!cadeia_init(&cadeia, relogio_falso))
        return 1;
    const uint32_t amostras = 300u;
    for (uint32_t i = 0; i < amostras; i++) {
        ppg_amostra_t bruto = {i, physionet_ir[i], physionet_vermelho[i]};
        cadeia_saida_t s;
        cadeia_processa(&cadeia, &bruto, &s);
    }
    const cadeia_ciclos_t *c = &cadeia.ciclos;
    int f = 0;
    if (c->filtro.conta != amostras || c->picos.conta != amostras ||
        c->espectral.conta != amostras || c->respiracao.conta != amostras ||
        c->qualidade.conta != amostras || c->total.conta != amostras) {
        printf("contas: filtro %lu total %lu (esperado %lu)\n", (unsigned long)c->filtro.conta,
               (unsigned long)c->total.conta, (unsigned long)amostras);
        f++;
    }
    if (c->filtro.max != 10u || c->total.soma == 0u || c->total.max < 10u * 5u) {
        printf("ciclos: filtro max %lu, total max %lu\n", (unsigned long)c->filtro.max,
               (unsigned long)c->total.max);
        f++;
    }
    return f;
}

int main(void)
{
    int f = vetor();
    f += ciclos();
    printf("%s\n", f ? "FALHOU" : "OK");
    return f ? 1 : 0;
}
