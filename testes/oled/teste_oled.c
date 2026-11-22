/* oled: as telas do C saem byte a byte iguais às do Python (o design do display), e o
 * controle de páginas, o rodízio, o coração e a escala da onda se comportam. */
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "confere.h"
#include "oled/oled.h"
#include "vetores/alvo.h"
#include "vetores/erro_decimacao.h"
#include "vetores/erro_sensor.h"
#include "vetores/fonte.h"
#include "vetores/inicio.h"
#include "vetores/principal.h"
#include "vetores/principal_sem_valor.h"
#include "vetores/resumo.h"
#include "vetores/sem_dedo.h"
#include "vetores/sinal_ruim.h"

static int falhas;

#define CHECA(cond, msg)                                                        \
    do {                                                                        \
        if (!(cond)) {                                                          \
            printf("FALHOU: %s (linha %d)\n", msg, __LINE__);                   \
            falhas++;                                                           \
        }                                                                       \
    } while (0)

/* ---- Auxiliares -------------------------------------------------------------------------- */

static void enche(oled_t *o, const float *onda)
{
    for (uint32_t i = 0; i < OLED_ONDA_N; i++)
        oled_amostra(o, onda[i]);
}

static int compara(const char *nome, const oled_t *o, const int32_t *esperado)
{
    int32_t obtido[OLED_PAGINAS * OLED_W];
    for (uint32_t p = 0; p < OLED_PAGINAS; p++)
        for (uint32_t c = 0; c < OLED_W; c++)
            obtido[p * OLED_W + c] = o->fb[p][c];
    printf("== %s\n", nome);
    return confere_int(nome, obtido, esperado, OLED_PAGINAS * OLED_W);
}

static int conta(const oled_t *o, int x0, int y0, int w, int h)
{
    int n = 0;
    for (int y = y0; y < y0 + h; y++)
        for (int x = x0; x < x0 + w; x++)
            n += (o->fb[y >> 3][x] >> (y & 7)) & 1;
    return n;
}

static int total(const oled_t *o)
{
    return conta(o, 0, 0, (int)OLED_W, (int)OLED_H);
}

static ppg_resultados_t normal(void)
{
    ppg_resultados_t r;
    memset(&r, 0, sizeof r);
    r.bpm_picos.valido = true;
    r.bpm_picos.bpm = 72.0f;
    r.qualidade.valido = true;
    r.qualidade.dedo_presente = true;
    r.qualidade.usavel = true;
    r.qualidade.indice = 1.0f;
    return r;
}

/* ---- As telas contra os vetores do Python -------------------------------------------------- */

static int telas_do_design(void)
{
    static oled_t o;
    int f = 0;

    oled_init(&o);
    enche(&o, fonte_onda);
    oled_limpa(&o);
    oled_texto(&o, 0, 0, "FONTE 6X8: 21 COLUNAS", 1, true);
    oled_texto(&o, 0, 8, "ABCDEFGHIJKLMNOPQRSTU", 1, true);
    oled_texto(&o, 1, 16, "0123456789", 2, true);
    oled_texto(&o, 0, 32, "PAGINA = 8 LINHAS PX", 1, true);
    oled_onda_quadro(&o, 0, 41, 128, 23);
    f += compara("fonte", &o, fonte_fb);

    oled_init(&o);
    enche(&o, principal_onda);
    oled_tela_principal(&o, 72, true, 4);
    f += compara("principal", &o, principal_fb);

    oled_init(&o);
    enche(&o, principal_sem_valor_onda);
    oled_tela_principal(&o, -1, false, 2);
    f += compara("principal_sem_valor", &o, principal_sem_valor_fb);

    ppg_resultados_t r = normal();
    r.bpm_espectral.valido = true;
    r.bpm_espectral.bpm = 71.0f;
    r.hrv.valido = true;
    r.hrv.sdnn_ms = 48.0f;
    r.hrv.rmssd_ms = 35.0f;
    r.qualidade.indice = 0.82f;
    oled_init(&o);
    oled_tela_resumo(&o, &r, 2);
    f += compara("resumo", &o, resumo_fb);

    oled_init(&o);
    oled_tela_sem_dedo(&o, 0);
    f += compara("sem_dedo", &o, sem_dedo_fb);

    oled_init(&o);
    enche(&o, sinal_ruim_onda);
    oled_tela_sinal_ruim(&o, 1);
    f += compara("sinal_ruim", &o, sinal_ruim_fb);

    const oled_etapa_t etapas[3] = {OLED_ETAPA_OK, OLED_ETAPA_OK, OLED_ETAPA_PENDENTE};
    oled_init(&o);
    oled_tela_inicio(&o, etapas, true);
    f += compara("inicio", &o, inicio_fb);

    oled_init(&o);
    oled_tela_erro(&o, OLED_ERRO_SENSOR);
    f += compara("erro_sensor", &o, erro_sensor_fb);

    oled_init(&o);
    oled_tela_erro(&o, OLED_ERRO_DECIMACAO);
    f += compara("erro_decimacao", &o, erro_decimacao_fb);

    r = normal();
    r.spo2.valido = true;
    r.spo2.spo2_pct = 97.0f;
    r.respiracao.valido = true;
    r.respiracao.rpm = 16.0f;
    r.qualidade.indice = 0.82f;
    oled_init(&o);
    enche(&o, alvo_onda);
    oled_tela_alvo(&o, &r);
    f += compara("alvo", &o, alvo_fb);
    return f;
}

/* ---- Comportamento -------------------------------------------------------------------------- */

static void formato_e_recorte(void)
{
    static oled_t o;
    oled_init(&o);
    oled_pixel(&o, 0, 0, true);
    oled_pixel(&o, 5, 3, true);
    oled_pixel(&o, 127, 63, true);
    oled_pixel(&o, 10, 8, true);
    CHECA(o.fb[0][0] == 0x01 && o.fb[0][5] == 0x08, "bit 0 é a linha de cima da página");
    CHECA(o.fb[7][127] == 0x80, "último pixel na página 7, bit 7");
    CHECA(o.fb[1][10] == 0x01, "a linha 8 é a primeira da página 1");
    oled_pixel(&o, 5, 3, false);
    CHECA(o.fb[0][5] == 0x00, "apagar limpa só o bit");

    /* Fora da tela é ignorado, sem estragar o resto. */
    oled_limpa(&o);
    oled_pixel(&o, -1, 0, true);
    oled_pixel(&o, 0, -1, true);
    oled_pixel(&o, 128, 0, true);
    oled_pixel(&o, 0, 64, true);
    oled_texto(&o, 120, 60, "ABCDEFGH", 2, true);
    oled_texto(&o, -20, -4, "ABCDEFGH", 2, true);
    oled_retangulo(&o, -5, -5, 300, 300, true, false);
    CHECA(total(&o) == 0, "tudo fora da tela ou apagado");

    /* Minúscula vira maiúscula; o que não está na fonte vira '?'. */
    static oled_t p;
    oled_init(&p);
    oled_texto(&o, 0, 0, "ABC 12", 1, true);
    oled_texto(&p, 0, 0, "abc 12", 1, true);
    CHECA(memcmp(o.fb, p.fb, sizeof o.fb) == 0, "minúscula = maiúscula");
    oled_limpa(&o);
    oled_limpa(&p);
    oled_texto(&o, 0, 0, "?", 1, true);
    oled_texto(&p, 0, 0, "\xC3\xA7", 1, true); /* 'ç' em UTF-8 são 2 bytes: viram 2 '?' */
    CHECA(conta(&p, 0, 0, 6, 8) == conta(&o, 0, 0, 6, 8), "o desconhecido é um '?'");
    CHECA(conta(&p, 6, 0, 6, 8) == conta(&o, 0, 0, 6, 8), "o segundo byte também");
}

static void envio_por_pagina(void)
{
    static oled_t o;
    uint8_t pg;
    const uint8_t *dados;
    oled_init(&o);

    /* Recém-iniciado: as 8 páginas faltam, da 0 à 7, mesmo com a memória toda zerada. */
    for (uint8_t esperado = 0; esperado < OLED_PAGINAS; esperado++) {
        CHECA(oled_proxima_pagina(&o, &pg, &dados) && pg == esperado, "páginas 0 a 7 em ordem");
        CHECA(dados == o.fb[pg], "os dados são a página da memória");
        oled_pagina_enviada(&o, pg);
    }
    CHECA(!oled_proxima_pagina(&o, &pg, &dados), "tudo enviado");

    /* Mexer num pixel pede só a página dele. */
    oled_pixel(&o, 30, 20, true); /* linha 20: página 2 */
    CHECA(oled_proxima_pagina(&o, &pg, &dados) && pg == 2, "só a página 2 mudou");
    oled_pagina_enviada(&o, 2);
    CHECA(!oled_proxima_pagina(&o, &pg, &dados), "de novo tudo enviado");

    /* A busca anda em roda: depois da 5, a 6 antes da 1, mesmo que a 1 também tenha mudado. */
    oled_pixel(&o, 0, 8, true);  /* página 1 */
    oled_pixel(&o, 0, 48, true); /* página 6 */
    oled_pagina_enviada(&o, 5);  /* simula: acabou de mandar a 5 */
    CHECA(oled_proxima_pagina(&o, &pg, &dados) && pg == 6, "depois da 5 vem a 6");
    oled_pagina_enviada(&o, 6);
    CHECA(oled_proxima_pagina(&o, &pg, &dados) && pg == 1, "e depois a 1");

    /* Chip reiniciado: todas voltam. */
    oled_pagina_enviada(&o, 1);
    oled_invalida(&o);
    unsigned n = 0;
    while (oled_proxima_pagina(&o, &pg, &dados)) {
        oled_pagina_enviada(&o, pg);
        n++;
    }
    CHECA(n == OLED_PAGINAS, "invalida manda as 8 de novo");
}

static void rodizio_e_prioridades(void)
{
    ppg_resultados_t r = normal();
    r.qualidade.valido = false; /* sem o módulo de qualidade, vale só o rodízio */
    CHECA(oled_escolhe(&r, 0) == OLED_TELA_PRINCIPAL, "começa pela principal");
    CHECA(oled_escolhe(&r, OLED_PRINCIPAL_MS - 1u) == OLED_TELA_PRINCIPAL, "principal até o fim");
    CHECA(oled_escolhe(&r, OLED_PRINCIPAL_MS) == OLED_TELA_RESUMO, "depois o resumo");
    CHECA(oled_escolhe(&r, OLED_PRINCIPAL_MS + OLED_RESUMO_MS) == OLED_TELA_PRINCIPAL,
          "sem alvo, volta pra principal");

    r.spo2.valido = true; /* com SpO2 ou respiração, entra a terceira tela */
    CHECA(oled_escolhe(&r, OLED_PRINCIPAL_MS + OLED_RESUMO_MS) == OLED_TELA_ALVO, "com alvo: alvo");
    CHECA(oled_escolhe(&r, OLED_PRINCIPAL_MS + OLED_RESUMO_MS + OLED_ALVO_MS) == OLED_TELA_PRINCIPAL,
          "e volta");
    r.spo2.valido = false;
    r.respiracao.valido = true;
    CHECA(oled_escolhe(&r, OLED_PRINCIPAL_MS + OLED_RESUMO_MS) == OLED_TELA_ALVO,
          "só a respiração também abre o alvo");

    /* Sem dedo e sinal ruim ganham do rodízio, a qualquer hora, mas só com a qualidade válida. */
    r = normal();
    r.qualidade.dedo_presente = false;
    CHECA(oled_escolhe(&r, 0) == OLED_TELA_SEM_DEDO && oled_escolhe(&r, 9000) == OLED_TELA_SEM_DEDO,
          "sem dedo ganha de tudo");
    r = normal();
    r.qualidade.usavel = false;
    CHECA(oled_escolhe(&r, 0) == OLED_TELA_SINAL_RUIM && oled_escolhe(&r, 9000) == OLED_TELA_SINAL_RUIM,
          "sinal ruim ganha de tudo");
    r.qualidade.valido = false;
    CHECA(oled_escolhe(&r, 0) == OLED_TELA_PRINCIPAL, "qualidade não válida não decide nada");
}

static void coracao_e_bpm(void)
{
    static oled_t o;
    ppg_resultados_t r = normal();
    oled_init(&o);

    oled_desenha(&o, &r, 1000);
    CHECA(conta(&o, 40, 0, 6, 8) == 0, "sem batimento visto, sem coração");

    r.ultimo_batimento.valido = true;
    r.ultimo_batimento.n_pico = 500;
    oled_desenha(&o, &r, 2000);
    CHECA(conta(&o, 40, 0, 6, 8) > 0, "batimento novo acende o coração");
    oled_desenha(&o, &r, 2000 + OLED_CORACAO_MS - 1u);
    CHECA(conta(&o, 40, 0, 6, 8) > 0, "ainda aceso um pouco antes");
    oled_desenha(&o, &r, 2000 + OLED_CORACAO_MS);
    CHECA(conta(&o, 40, 0, 6, 8) == 0, "apaga depois de OLED_CORACAO_MS");
    oled_desenha(&o, &r, 2500);
    CHECA(conta(&o, 40, 0, 6, 8) == 0, "o mesmo batimento não acende de novo");
    r.ultimo_batimento.n_pico = 580;
    oled_desenha(&o, &r, 3000);
    CHECA(conta(&o, 40, 0, 6, 8) > 0, "outro batimento acende de novo");

    /* O relógio de milissegundos dá a volta (uint32). */
    oled_init(&o);
    r.ultimo_batimento.n_pico = 1;
    oled_desenha(&o, &r, 0xFFFFFFF0u);
    CHECA(conta(&o, 40, 0, 6, 8) > 0, "aceso perto da volta do relógio");
    oled_desenha(&o, &r, 0xFFFFFFF0u + OLED_CORACAO_MS);
    CHECA(conta(&o, 40, 0, 6, 8) == 0, "e apaga depois da volta");

    /* BPM "--" se não for válido; com a qualidade válida, também se não for usável. */
    oled_init(&o);
    r = normal();
    oled_desenha(&o, &r, 0);
    int com_bpm = conta(&o, 0, 0, 36, 16);
    CHECA(com_bpm > 0, "BPM 72 aparece");
    r.bpm_picos.valido = false;
    oled_desenha(&o, &r, 0);
    int sem_bpm = conta(&o, 0, 0, 36, 16);
    CHECA(sem_bpm > 0 && sem_bpm < com_bpm, "'--' tem menos pixels que '72'");
    r = normal();
    r.bpm_picos.bpm = 0.0f / 0.0f; /* NaN */
    oled_desenha(&o, &r, 0);
    CHECA(conta(&o, 0, 0, 36, 16) == sem_bpm, "NaN vira '--'");
    r.bpm_picos.bpm = 1234.0f;
    oled_desenha(&o, &r, 0);
    CHECA(conta(&o, 36, 0, 4, 16) == 0, "BPM absurdo cabe nos 3 algarismos (999)");
}

static void escala_da_onda(void)
{
    static oled_t o;
    oled_init(&o);
    for (unsigned i = 0; i < OLED_ONDA_N; i++)
        oled_amostra(&o, i == 100 ? 10.0f : 0.0f);
    oled_tela_principal(&o, 72, false, 3);
    CHECA(o.esc_ok && o.esc_max == 5.0f && o.esc_min == 0.0f,
          "a primeira escala é o mínimo e o máximo das colunas (a média de 2 amostras)");

    /* O pico sai da janela: a escala encolhe 5% por quadro, não de uma vez. */
    for (unsigned i = 0; i < OLED_ONDA_N; i++)
        oled_amostra(&o, 0.0f);
    oled_tela_principal(&o, 72, false, 3);
    CHECA(o.esc_max > 4.7f && o.esc_max < 4.8f, "encolheu 5% (5,0 vira 4,75)");
    for (int k = 0; k < 200; k++)
        oled_tela_principal(&o, 72, false, 3);
    CHECA(o.esc_max < 0.01f, "e depois de muitos quadros chega em 0");

    /* Pulso maior que a escala: ela cresce na hora. */
    for (unsigned i = 0; i < OLED_ONDA_N; i++)
        oled_amostra(&o, 100.0f);
    oled_tela_principal(&o, 72, false, 3);
    CHECA(o.esc_max == 100.0f, "cresce na hora");
}

static void onda_antes_de_encher(void)
{
    static oled_t o;
    oled_init(&o);
    for (unsigned i = 0; i < 64; i++) /* 64 amostras = 32 colunas */
        oled_amostra(&o, (float)(i % 8));
    oled_tela_principal(&o, 72, false, 3);
    CHECA(conta(&o, 0, 17, 96, 47) == 0, "a esquerda fica vazia");
    CHECA(conta(&o, 96, 17, 32, 47) > 0, "a onda começa pela direita");

    /* Sem nenhuma amostra, a onda não desenha nada e não quebra. */
    oled_init(&o);
    oled_tela_principal(&o, 72, false, 3);
    CHECA(conta(&o, 0, 17, 128, 47) == 0, "sem amostras, sem onda");
}

static void anel_da_onda(void)
{
    /* Depois de mais de 256 amostras, vale só o que é mais novo: dá no mesmo que ter entrado só isso. */
    static oled_t a, b;
    oled_init(&a);
    oled_init(&b);
    for (unsigned i = 0; i < 700; i++)
        oled_amostra(&a, (float)((i * 7u) % 23u));
    for (unsigned i = 700 - OLED_ONDA_N; i < 700; i++)
        oled_amostra(&b, (float)((i * 7u) % 23u));
    oled_tela_principal(&a, 60, false, 2);
    oled_tela_principal(&b, 60, false, 2);
    CHECA(memcmp(a.fb, b.fb, sizeof a.fb) == 0, "o anel descarta as mais velhas");
}

static void resultados_estranhos(void)
{
    static oled_t o;
    ppg_resultados_t r;
    memset(&r, 0, sizeof r);
    oled_init(&o);

    /* Tudo sem valor: o resumo mostra "--" e não quebra; nada além da fonte é desenhado. */
    oled_tela_resumo(&o, &r, 2);
    CHECA(total(&o) > 0, "resumo vazio desenha");

    /* Valores gigantes, negativos e NaN não estouram a linha nem derrubam. */
    r.bpm_picos.valido = r.bpm_espectral.valido = true;
    r.bpm_picos.bpm = 1e30f;
    r.bpm_espectral.bpm = -5.0f;
    r.hrv.valido = r.hrv.lf_hf_valido = true;
    r.hrv.sdnn_ms = 0.0f / 0.0f;
    r.hrv.rmssd_ms = 12345.0f;
    r.hrv.lf_hf = 1e9f;
    r.qualidade.valido = true;
    r.qualidade.indice = 7.0f;
    r.spo2.valido = r.respiracao.valido = true;
    r.spo2.spo2_pct = 140.0f;
    r.respiracao.rpm = 1e9f;
    oled_tela_resumo(&o, &r, 3);
    oled_tela_alvo(&o, &r);
    CHECA(total(&o) > 0, "valores absurdos não derrubam");
    r.qualidade.indice = -1.0f;
    oled_desenha(&o, &r, 0);
    CHECA(total(&o) > 0, "índice negativo não derruba");
}

int main(void)
{
    falhas += telas_do_design();
    formato_e_recorte();
    envio_por_pagina();
    rodizio_e_prioridades();
    coracao_e_bpm();
    escala_da_onda();
    onda_antes_de_encher();
    anel_da_onda();
    resultados_estranhos();
    return falhas ? 1 : 0;
}
