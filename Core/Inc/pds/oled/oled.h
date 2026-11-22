/*
 * oled: as telas do display OLED (SSD1306 128 x 64), sem falar com o chip.
 *
 * Desenha numa memória de imagem igual à do SSD1306 (8 páginas de 128 colunas, 1
 * byte por coluna, o bit 0 é a linha de cima da página) e diz quais páginas mudaram
 * e precisam ir pelo I2C. Quem fala com o chip é o display.c (HAL); este módulo é C
 * puro, sem HAL, sem malloc, sem global, e roda no PC.
 *
 * Porte de analise/src/analise/oled.py (o design do display): fonte 5x7 em células de
 * 6x8, só maiúsculas, algarismos e alguns sinais (minúscula vira maiúscula; o resto
 * vira '?'), e as telas. Os vetores de testes/oled/ saem do Python.
 *
 * Uso:
 *
 *   static oled_t o;                       ~3 KB: fora da pilha
 *   oled_init(&o);
 *   oled_amostra(&o, -ir_filtrado);        a 100 Hz (o IR cai quando o pulso sobe: inverta)
 *   oled_desenha(&o, &resultados, ms);     a cada quadro, no laço principal
 *   while (oled_proxima_pagina(&o, &pg, &dados)) {   envia 'dados' (128 bytes) na página pg
 *       ...; oled_pagina_enviada(&o, pg);
 *   }
 */
#ifndef PDS_OLED_OLED_H
#define PDS_OLED_OLED_H

#include <stdbool.h>
#include <stdint.h>

#include "comum/ppg.h"

#define OLED_W 128u
#define OLED_H 64u
#define OLED_PAGINAS 8u    /* OLED_H / 8 */
#define OLED_ONDA_N 256u   /* amostras guardadas pra onda: 2 por coluna = 2,56 s a 100 Hz */

/* Quanto o coração fica aceso depois de um batimento novo. */
#define OLED_CORACAO_MS 150u

/* Quanto cada tela fica no ar no rodízio (não há botão: o design não define um). */
#define OLED_PRINCIPAL_MS 8000u
#define OLED_RESUMO_MS 4000u
#define OLED_ALVO_MS 4000u

typedef struct {
    uint8_t fb[OLED_PAGINAS][OLED_W];       /* o que a tela deve mostrar */
    uint8_t enviado[OLED_PAGINAS][OLED_W];  /* o que o chip já tem */
    uint8_t nunca_enviada;                  /* bit p = a página p ainda não foi enviada */
    uint8_t ultima_pagina;                  /* a próxima busca começa depois dela */
    float onda[OLED_ONDA_N];                /* as últimas amostras, circular */
    uint16_t onda_i;                        /* onde entra a próxima */
    uint16_t onda_n;                        /* quantas já entraram, até OLED_ONDA_N */
    float esc_min;                          /* escala da onda: cresce na hora, encolhe devagar */
    float esc_max;
    bool esc_ok;
    bool tem_pico;                          /* já viu um batimento */
    uint32_t n_pico_visto;
    bool coracao_aceso;
    uint32_t coracao_t0;                    /* ms em que o coração acendeu */
} oled_t;

/* Qual tela o rodízio mostra. */
typedef enum {
    OLED_TELA_PRINCIPAL,
    OLED_TELA_RESUMO,
    OLED_TELA_ALVO,       /* SpO2 e respiração, só quando algum dos dois tem valor */
    OLED_TELA_SEM_DEDO,   /* qualidade válida e sem dedo: ganha de todas */
    OLED_TELA_SINAL_RUIM  /* dedo, mas qualidade não usável */
} oled_tela_t;

typedef enum { OLED_ETAPA_PENDENTE, OLED_ETAPA_OK, OLED_ETAPA_ERRO } oled_etapa_t;
typedef enum { OLED_ERRO_SENSOR, OLED_ERRO_DECIMACAO } oled_erro_t;

/* Zera tudo e marca as 8 páginas como não enviadas. */
void oled_init(oled_t *o);

/* ---- Primitivas (as do design; coordenadas em pixels, fora da tela é ignorado) ------- */

void oled_limpa(oled_t *o);
void oled_pixel(oled_t *o, int x, int y, bool v);
void oled_retangulo(oled_t *o, int x, int y, int w, int h, bool cheio, bool v);
void oled_linha(oled_t *o, int x0, int y0, int x1, int y1);

/*
 * Texto: k = 1 dá células 6x8, k = 2 dá 12x16 (cada pixel dobrado). v = false apaga (texto
 * invertido sobre uma faixa acesa). Devolve o x depois da última letra.
 */
int oled_texto(oled_t *o, int x, int y, const char *s, int k, bool v);
/* Termina em x_dir (a última célula, sem o espaço da direita). */
int oled_texto_dir(oled_t *o, int x_dir, int y, const char *s, int k, bool v);
int oled_texto_centro(oled_t *o, int y, const char *s, int k, bool v);

/* 5 barras de qualidade, as q primeiras cheias; a vazia é um traço de 1 px na base. */
void oled_barras(oled_t *o, int x, int y, int alt, int w, int gap, int q);

/*
 * Onda com escala automática: v[0..n-1] (uma coluna cada) entre mn e mx, com 8% de folga em
 * cima e embaixo; pontos vizinhos ligados por reta. n <= w.
 */
void oled_onda(oled_t *o, int x0, int y0, int w, int h, const float *v, uint32_t n, float mn,
               float mx);

/* ---- A onda e as telas ---------------------------------------------------------------- */

/* Uma amostra do sinal filtrado, a 100 Hz, na ordem em que o sinal será mostrado. */
void oled_amostra(oled_t *o, float v);

/*
 * Desenha a onda guardada em (x0, y0, w, h): 2 amostras por coluna (a média das duas), a
 * mais nova na direita; antes de encher, a onda começa pela direita. A escala acompanha:
 * cresce na hora e encolhe 5% por quadro.
 */
void oled_onda_quadro(oled_t *o, int x0, int y0, int w, int h);

/* Faixa de cima (páginas 0 e 1): BPM (bpm < 0 = "--"), coração, "BPM" e as 5 barras de qualidade. */
void oled_topo(oled_t *o, int bpm, bool coracao, int q);

void oled_tela_principal(oled_t *o, int bpm, bool coracao, int q);
/* total = quantas telas há no rodízio (2 ou 3), pro "2/N" do cabeçalho. */
void oled_tela_resumo(oled_t *o, const ppg_resultados_t *r, unsigned total);
void oled_tela_sem_dedo(oled_t *o, int q);
void oled_tela_sinal_ruim(oled_t *o, int q);
void oled_tela_alvo(oled_t *o, const ppg_resultados_t *r);
void oled_tela_inicio(oled_t *o, const oled_etapa_t etapas[3], bool aguarde);
void oled_tela_erro(oled_t *o, oled_erro_t erro);

/* ---- Rodízio e envio -------------------------------------------------------------------- */

/*
 * Qual tela mostrar agora. Sem dedo e sinal ruim ganham das outras (só se a qualidade for
 * válida: sem o módulo de qualidade, ou antes de ele encher, vale o rodízio). O rodízio vai
 * de principal a resumo (e alvo, se SpO2 ou respiração tiverem valor) conforme agora_ms.
 */
oled_tela_t oled_escolhe(const ppg_resultados_t *r, uint32_t agora_ms);

/*
 * Escolhe a tela, desenha em o->fb e atualiza o coração (acende com um batimento novo e apaga
 * OLED_CORACAO_MS depois). BPM mostra "--" se bpm_picos não for válido ou, com a qualidade
 * válida, se ela não for usável.
 */
void oled_desenha(oled_t *o, const ppg_resultados_t *r, uint32_t agora_ms);

/*
 * A próxima página que o chip ainda não tem igual (a primeira busca vai de uma em uma, em
 * roda, pra nenhuma ficar pra trás). false se está tudo enviado.
 */
bool oled_proxima_pagina(oled_t *o, uint8_t *pagina, const uint8_t **dados);

/* Chamar depois de enviar a página com sucesso. */
void oled_pagina_enviada(oled_t *o, uint8_t pagina);

/* O chip foi reiniciado: todas as páginas voltam a precisar de envio. */
void oled_invalida(oled_t *o);

#endif /* PDS_OLED_OLED_H */
