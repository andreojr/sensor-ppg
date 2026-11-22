/*
 * qualidade.h: detector de sinal ruim (dedo ausente, mal posicionado, mexendo).
 *
 * Recebe o bruto (saída da decimação, com DC) uma amostra por vez e, a cada
 * QUALIDADE_BLOCO amostras (1 s), devolve se os últimos 2 s dão pra usar.
 *
 * A janela tem 2 blocos de 1 s e anda de 1 em 1 s. O IR passa por um
 * passa-altas de 1ª ordem (y = ir - média exponencial, alfa QUALIDADE_ALFA),
 * que deixa só a parte que pulsa. Por janela:
 *
 *   dc         média do bruto de cada canal
 *   maior      maior amostra dos dois canais (bruto)
 *   altura     máx(y) - mín(y)
 *   pi         altura / dc do IR (índice de perfusão)
 *   aspereza   soma de |y[n] - y[n-1]| / altura
 *   razao      altura / altura de referência (média das últimas janelas boas)
 *   ritmo      maior autocorrelação normalizada dos últimos 4 s (IR num
 *              passa-faixa 0,5-4 Hz, reduzido a 25 Hz) nos atrasos de 0,4 a
 *              1,5 s: se o sinal se repete no ritmo de um coração. A conta é
 *              feita sobre os 4 s que fecharam o bloco anterior (que ficam
 *              parados no buffer enquanto o bloco atual escreve), em
 *              QUALIDADE_RITMO_POR_AMOSTRA passos por amostra (cabe no orçamento).
 *
 * Janela boa: dc dos dois canais >= QUALIDADE_DC_MIN, maior < QUALIDADE_SATURA,
 * pi entre PI_MIN e PI_MAX, aspereza entre ASPEREZA_MIN e ASPEREZA_MAX, razao
 * entre RAZAO_MIN e RAZAO_MAX (se já há referência), ritmo >= RITMO_MIN (sem 4 s
 * de sinal desde o início ou o reinício, não há ritmo: janela ruim). O porquê de cada limiar
 * está em docs/src/content/docs/modulos/qualidade.md.
 *
 * Saída (ppg_qualidade_t):
 *   valido         a janela de 2 s encheu desde o início ou o último reinício
 *   dedo_presente  dc dos dois canais >= QUALIDADE_DC_MIN
 *   indice         janelas boas seguidas / QUALIDADE_JANELAS_ACEITA, até 1.
 *                  Uma janela ruim zera.
 *   usavel         dedo_presente && indice >= QUALIDADE_LIMIAR (ou seja,
 *                  QUALIDADE_JANELAS_ACEITA janelas boas seguidas)
 *
 * Reinicia sozinho se o n não for o seguinte do anterior (amostra perdida ou
 * n voltando) e com amostra NaN/infinita (essa é descartada).
 * As mesmas regras do protótipo analise/src/analise/qualidade.py.
 */
#ifndef PDS_QUALIDADE_QUALIDADE_H
#define PDS_QUALIDADE_QUALIDADE_H

#include <stdbool.h>
#include <stdint.h>

#include "comum/ppg.h"

#define QUALIDADE_BLOCO PPG_FS_HZ          /* 1 s: uma saída por bloco */
#define QUALIDADE_JANELA (2u * QUALIDADE_BLOCO)
#define QUALIDADE_ALFA 0.02f               /* 1 / (0,5 s x 100 Hz): corte ~0,32 Hz */
#define QUALIDADE_DC_MIN 10000.0f          /* contagens; sem dedo ~1500, com dedo > 60 mil */
#define QUALIDADE_SATURA 250000.0f         /* ~95% do topo do ADC (262143) */
#define QUALIDADE_PI_MIN 0.0005f           /* 0,05% */
#define QUALIDADE_PI_MAX 0.05f             /* 5% */
#define QUALIDADE_ASPEREZA_MIN 1.5f       /* abaixo: só sobe ou só desce (deriva) */
#define QUALIDADE_ASPEREZA_MAX 12.0f
#define QUALIDADE_RAZAO_MIN 0.4f
#define QUALIDADE_RAZAO_MAX 2.0f
#define QUALIDADE_PESO_REF 0.25f           /* a referência anda 1/4 a cada janela boa */
#define QUALIDADE_JANELAS_ACEITA 3u        /* janelas boas seguidas pra ser usável */
#define QUALIDADE_RUINS_ESQUECE 10u        /* janelas ruins seguidas pra esquecer a referência */
#define QUALIDADE_LIMIAR 1.0f              /* indice >= limiar: usável */
#define QUALIDADE_RITMO_MIN 0.45f          /* com o picos como 2º teste; ver a doc */
#define QUALIDADE_RITMO_DECIMA 4u          /* 100 -> 25 Hz (média de 4) */
#define QUALIDADE_RITMO_N 100u             /* 4 s a 25 Hz */
#define QUALIDADE_RITMO_ATRASO_MIN 10u     /* 0,4 s: 150 bpm */
#define QUALIDADE_RITMO_ATRASO_MAX 37u     /* 1,48 s: ~41 bpm */
/* Buffer: os 4 s parados + os 25 pontos que chegam durante um bloco. */
#define QUALIDADE_RITMO_ANEL (QUALIDADE_RITMO_N + QUALIDADE_BLOCO / QUALIDADE_RITMO_DECIMA)
#define QUALIDADE_RITMO_POR_AMOSTRA 25u    /* passos da conta por amostra (~2 340 por bloco) */

/* Por que a última janela foi ruim (bits de qualidade_t.motivo; 0 = boa). */
#define QUALIDADE_SEM_DEDO 1u
#define QUALIDADE_SATURADO 2u
#define QUALIDADE_PULSO_FRACO 4u   /* pi < PI_MIN ou razao < RAZAO_MIN */
#define QUALIDADE_MOVIMENTO 8u     /* pi > PI_MAX, razao > RAZAO_MAX ou aspereza < MIN */
#define QUALIDADE_RUIDO 16u        /* aspereza > ASPEREZA_MAX */
#define QUALIDADE_SEM_RITMO 32u    /* ritmo < RITMO_MIN ou ainda sem 4 s */

/* O que se acumula em 1 s. */
typedef struct {
    float soma_ir;
    float soma_vm;
    float maior;   /* maior amostra dos dois canais */
    float min_y;   /* y = IR depois do passa-altas */
    float max_y;
    float tv_y;    /* soma de |y[n] - y[n-1]| */
} qualidade_bloco_t;

typedef struct {
    bool tem_n;
    uint32_t prox_n;
    float media;           /* média exponencial do IR */
    float ultimo_y;
    uint32_t conta;        /* amostras no bloco atual */
    qualidade_bloco_t atual;
    qualidade_bloco_t anterior;
    bool tem_anterior;
    uint32_t boas;         /* janelas boas seguidas, até JANELAS_ACEITA */
    uint32_t ruins;        /* janelas ruins seguidas, até RUINS_ESQUECE */
    bool tem_ref;
    float ref;             /* altura de referência */

    /* Ritmo. */
    float x0;              /* 1ª amostra desde o reinício: o passa-faixa parte do zero */
    float z[4];            /* estados das 2 seções do passa-faixa */
    float soma4;
    uint32_t conta4;
    uint32_t pos;
    uint32_t cheio;
    bool tem_foto;         /* há 4 s parados em anel[ini..ini+N) */
    uint32_t ini;
    uint32_t etapa;        /* 0 média, 1 energia, 2.. um atraso cada */
    uint32_t i;
    float acc;
    float media_r;         /* média da janela parada */
    float energia;
    float maior_r;
    bool pronto;           /* a conta sobre a janela parada terminou */

    /* Diagnóstico da última janela (pra serial e testes). */
    uint32_t motivo;
    float dc_ir;
    float pi;
    float aspereza;
    float razao;           /* 0 se não havia referência */
    float ritmo;           /* 0 se não havia 4 s de sinal */

    /* Por último: qualidade_init não zera (só se lê o que cheio garante escrito).
       Passa-faixa a 25 Hz, buffer circular guardado em dobro (cada ponto em pos e
       pos + ANEL), pra janela de 4 s ser sempre contígua. */
    float anel[2u * QUALIDADE_RITMO_ANEL];
} qualidade_t;

/* Zera o estado. Chamar de novo reinicia. */
void qualidade_init(qualidade_t *q);

/*
 * Uma amostra do bruto. Devolve true e escreve *s no fim de cada bloco, a
 * partir do segundo (janela cheia); false (e *s intocado) nas demais.
 */
bool qualidade_processa(qualidade_t *q, const ppg_amostra_t *bruto, ppg_qualidade_t *s);

/*
 * A decisão do BPM confiável: a tela mostra o BPM do picos só se a qualidade
 * diz que dá pra usar (q->usavel), o picos diz que o ritmo é regular
 * (b->valido) e o último batimento (n_ultimo_pico) tem no máximo
 * QUALIDADE_BATIMENTO_VALE amostras em relação a n (o n da última saída da
 * qualidade). Um batimento "à frente" de n (pelos atrasos) conta como recente.
 */
#define QUALIDADE_BATIMENTO_VALE (3u * PPG_FS_HZ) /* p, sai ~1,3 s depois; RR até 1,5 s */
bool qualidade_bpm_confiavel(const ppg_qualidade_t *q, const ppg_bpm_t *b, bool tem_batimento,
                             uint32_t n, uint32_t n_ultimo_pico);

#endif /* PDS_QUALIDADE_QUALIDADE_H */
