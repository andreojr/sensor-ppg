/*
 * Teste das linhas da serial: o mesmo texto que o main.c da v0.3 mandava
 * (o analise.captura lê essas linhas).
 */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "cadeia/linhas.h"

static int falhas;

static void igual(const char *nome, const char *obtido, const char *esperado)
{
    if (strcmp(obtido, esperado) != 0) {
        printf("%s:\n  obtido   \"%s\"\n  esperado \"%s\"\n", nome, obtido, esperado);
        falhas++;
    }
}

static void centesimos(void)
{
    char s[24];
    linhas_centesimos(s, sizeof s, 812.5f);
    igual("812.5", s, "812.50");
    linhas_centesimos(s, sizeof s, -0.25f);
    igual("-0.25", s, "-0.25");
    linhas_centesimos(s, sizeof s, -1.005f); /* -1.00499999...: arredonda pra -1.00 */
    igual("-1.005", s, "-1.00");
    linhas_centesimos(s, sizeof s, 131072.25f);
    igual("131072.25", s, "131072.25");
}

static void milesimos(void)
{
    char s[24];
    linhas_milesimos(s, sizeof s, 1.2345678f);
    igual("1.2345678", s, "1.235");
    linhas_milesimos(s, sizeof s, 0.05f);
    igual("0.05", s, "0.050");
    linhas_milesimos(s, sizeof s, 12.0f);
    igual("12", s, "12.000");
    linhas_milesimos(s, sizeof s, -0.0004f);
    igual("-0.0004", s, "0.000");
}

static cadeia_saida_t saida_cheia(void)
{
    cadeia_saida_t s;
    memset(&s, 0, sizeof s);
    s.filtrado = (ppg_amostra_t){1500u, -12.5f, 3.25f};
    s.bateu = true;
    s.batimento = (ppg_batimento_t){true, 1234u, 0.25f, true, 812.5f};
    s.bpm = (ppg_bpm_t){true, 73.85f};
    s.n_hrv = 2;
    s.hrv[0] = (cadeia_hrv_t){1100u, {true, 41.5f, 30.25f, false, 0.0f}, true};
    s.hrv[1] = (cadeia_hrv_t){1180u, {false, 0.0f, 0.0f, false, 0.0f}, false};
    s.espectral = true;
    s.bpm_espectral = (ppg_bpm_t){false, 0.0f};
    s.respirou = true;
    s.respiracao = (ppg_respiracao_t){true, 15.2f};
    s.oxigenou = true;
    s.spo2 = (ppg_spo2_t){true, 96.36f};
    s.spo2_r = 0.5464f;
    s.julgou = true;
    s.mostra = true;
    s.calculou_lf_hf = true;
    s.lf_hf_valido = true;
    s.lf_hf = 1.2345678f;
    return s;
}

static void todas(void)
{
    cadeia_saida_t s = saida_cheia();
    ppg_amostra_t bruto = {1500u, 131072.25f, 140000.0f};
    char buf[LINHAS_MAX];
    size_t n = linhas_cadeia(&s, &bruto, true, buf, sizeof buf);
    igual("completa", buf,
          "b,1500,131072.25,140000.00\n"
          "f,1500,-12.50,3.25\n"
          "p,1234,0.2500,1,812.50,1,73.85\n"
          "h,1100,1,41.50,30.25,1\n"
          "h,1180,0,0.00,0.00,0\n"
          "e,1500,0,0.00\n"
          "r,1500,15.20,1\n"
          "s,1500,1,96.36,0.546\n"
          "t,1500,1,7385\n"
          "l,1500,1,1.235\n");
    if (n != strlen(buf)) {
        printf("devolveu %zu, escreveu %zu\n", n, strlen(buf));
        falhas++;
    }
    n = linhas_cadeia(&s, &bruto, false, buf, sizeof buf);
    if (strstr(buf, "f,") != NULL) {
        printf("sem completa saiu f,\n");
        falhas++;
    }
}

static void so_bruto_e_tela_apagada(void)
{
    cadeia_saida_t s;
    memset(&s, 0, sizeof s);
    s.julgou = true;
    s.mostra = false;
    s.bpm = (ppg_bpm_t){true, 70.0f};
    s.calculou_lf_hf = true;
    s.lf_hf_valido = false;
    s.lf_hf = 3.5f; /* inválido sai 0 */
    ppg_amostra_t bruto = {7u, 1.0f, 2.0f};
    char buf[LINHAS_MAX];
    linhas_cadeia(&s, &bruto, false, buf, sizeof buf);
    igual("tela e LF/HF apagados", buf, "b,7,1.00,2.00\nt,7,0,0\nl,7,0,0.000\n");
}

/* O R da linha s: limitado a 999.999 (um R enorme seria UB ao virar unsigned long), negativo
   e NaN saem 0, e os normais não mudam. */
static void r_limitado(void)
{
    const struct {
        float r;
        const char *esperado;
    } casos[] = {
        {0.5464f, "s,9,0,0.00,0.546\n"}, {999.0f, "s,9,0,0.00,999.000\n"},
        {1.0e12f, "s,9,0,0.00,999.999\n"}, {INFINITY, "s,9,0,0.00,999.999\n"},
        {-2.0f, "s,9,0,0.00,0.000\n"},     {NAN, "s,9,0,0.00,0.000\n"},
    };
    for (size_t k = 0; k < sizeof casos / sizeof casos[0]; k++) {
        cadeia_saida_t s;
        memset(&s, 0, sizeof s);
        s.oxigenou = true;
        s.spo2 = (ppg_spo2_t){false, 0.0f};
        s.spo2_r = casos[k].r;
        ppg_amostra_t bruto = {9u, 1.0f, 2.0f};
        char buf[LINHAS_MAX];
        linhas_cadeia(&s, &bruto, false, buf, sizeof buf);
        const char *linha = strstr(buf, "s,");
        igual("r limitado", linha ? linha : "", casos[k].esperado);
    }
}

/* O LF/HF da linha l: limitado a 999.999 (acima de ~2,1e6 estouraria o long), os normais
   não mudam e o negativo sai como antes. */
static void lf_hf_limitado(void)
{
    const struct {
        float v;
        const char *esperado;
    } casos[] = {
        {1.2345678f, "l,9,1,1.235\n"},   {999.0f, "l,9,1,999.000\n"},
        {1.0e12f, "l,9,1,999.999\n"},    {INFINITY, "l,9,1,999.999\n"},
        {-0.25f, "l,9,1,-0.250\n"},
    };
    for (size_t k = 0; k < sizeof casos / sizeof casos[0]; k++) {
        cadeia_saida_t s;
        memset(&s, 0, sizeof s);
        s.calculou_lf_hf = true;
        s.lf_hf_valido = true;
        s.lf_hf = casos[k].v;
        ppg_amostra_t bruto = {9u, 1.0f, 2.0f};
        char buf[LINHAS_MAX];
        linhas_cadeia(&s, &bruto, false, buf, sizeof buf);
        const char *linha = strstr(buf, "l,");
        igual("lf/hf limitado", linha ? linha : "", casos[k].esperado);
    }
}

static void buffer_pequeno(void)
{
    cadeia_saida_t s = saida_cheia();
    ppg_amostra_t bruto = {1500u, 131072.25f, 140000.0f};
    char buf[40];
    memset(buf, 'x', sizeof buf);
    size_t n = linhas_cadeia(&s, &bruto, true, buf, 30u);
    /* Só cabe a linha "b," (27 bytes + \0): as outras ficam de fora, inteiras. */
    if (n != 27u || buf[30] != 'x' || strcmp(buf, "b,1500,131072.25,140000.00\n") != 0) {
        printf("buffer pequeno: n %zu, \"%s\"\n", n, buf);
        falhas++;
    }
}

static void cru(void)
{
    char buf[40];
    size_t n = linhas_cru(42u, 131072u, 140001u, buf, sizeof buf);
    igual("cru", buf, "42,131072,140001\n");
    if (n != strlen(buf))
        falhas++;
}

int main(void)
{
    centesimos();
    milesimos();
    todas();
    so_bruto_e_tela_apagada();
    r_limitado();
    lf_hf_limitado();
    buffer_pequeno();
    cru();
    printf("%s\n", falhas ? "FALHOU" : "OK");
    return falhas ? 1 : 0;
}
