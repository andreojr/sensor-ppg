/*
 * Teste das linhas da serial: o mesmo texto que o main.c da v0.3 mandava
 * (o analise.captura lê essas linhas).
 */
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
    s.julgou = true;
    s.mostra = true;
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
          "t,1500,1,7385\n");
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
    ppg_amostra_t bruto = {7u, 1.0f, 2.0f};
    char buf[LINHAS_MAX];
    linhas_cadeia(&s, &bruto, false, buf, sizeof buf);
    igual("tela apagada", buf, "b,7,1.00,2.00\nt,7,0,0\n");
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
    todas();
    so_bruto_e_tela_apagada();
    buffer_pequeno();
    cru();
    printf("%s\n", falhas ? "FALHOU" : "OK");
    return falhas ? 1 : 0;
}
