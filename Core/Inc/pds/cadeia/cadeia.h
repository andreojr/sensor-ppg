/*
 * cadeia.h: a cadeia de PDS inteira, a partir do bruto a PPG_FS_HZ.
 *
 * Chama os módulos na ordem do laço da placa (a mesma da referência em
 * analise/src/analise/cadeia.py):
 *
 *   bruto --> filtro --> picos --> espectral --> respiração --> spo2 --> qualidade
 *
 * e aplica as regras que ligam os módulos (ver qualidade.h):
 *  - batimento: entra na fila do HRV com o julgamento "de antes"; fila cheia solta o
 *    mais antigo direto pro HRV, com o RR de fora;
 *  - julgamento da qualidade: esvazia a fila no HRV e decide o BPM da tela
 *    (qualidade_bpm_confiavel).
 *
 * A respiração e a spo2 recebem o bruto (com DC), não o filtrado; a spo2 usa o IR e o
 * vermelho e não depende dos outros módulos.
 *
 * A decimação fica fora (quem lê o sensor decima e entrega o bruto aqui).
 *
 * Sem HAL: os ciclos de cada módulo são medidos por um relógio que quem chama passa
 * (o DWT na placa; NULL no PC = não mede).
 */
#ifndef PDS_CADEIA_CADEIA_H
#define PDS_CADEIA_CADEIA_H

#include <stdbool.h>
#include <stdint.h>

#include "cadeia/ciclos.h"
#include "comum/ppg.h"
#include "espectral/espectral.h"
#include "filtro/filtro.h"
#include "hrv/hrv.h"
#include "picos/picos.h"
#include "qualidade/qualidade.h"
#include "respiracao/respiracao.h"
#include "spo2/spo2.h"

/* Devolve um contador de ciclos que só sobe (dá a volta em uint32_t). */
typedef uint32_t (*cadeia_relogio_t)(void);

/* Saídas de HRV numa amostra: o que transbordou da fila no picos mais a fila toda
   no julgamento. */
#define CADEIA_HRV_MAX (QUALIDADE_FILA + 1u)

typedef struct {
    uint32_t n_pico;
    ppg_hrv_t hrv;
    bool rr_usado;      /* o RR deste batimento entrou no HRV */
} cadeia_hrv_t;

/* O que aconteceu numa amostra (pra serial e pro display). Só valem os campos
   cujo bool está true. */
typedef struct {
    ppg_amostra_t filtrado;              /* sempre */
    bool bateu;
    ppg_batimento_t batimento;
    ppg_bpm_t bpm;                       /* BPM do picos: o cru com batimento; o que a
                                            tela mostra (mostra) com julgamento */
    bool espectral;
    ppg_bpm_t bpm_espectral;
    bool respirou;
    ppg_respiracao_t respiracao;
    bool oxigenou;                       /* saiu uma SpO2 (estimada) */
    ppg_spo2_t spo2;
    float spo2_r;                        /* a razão das razões dessa saída */
    bool julgou;
    ppg_qualidade_t qualidade;
    bool mostra;                         /* a tela mostra o BPM do picos */
    uint32_t n_hrv;
    cadeia_hrv_t hrv[CADEIA_HRV_MAX];    /* na ordem em que saíram */
} cadeia_saida_t;

typedef struct {
    ciclos_t filtro, picos, espectral, respiracao, spo2, qualidade, hrv, total;
} cadeia_ciclos_t;

typedef struct {
    filtro_t filtro;
    picos_t picos;
    espectral_t espectral;
    respiracao_t respiracao;
    spo2_t spo2;
    qualidade_t qualidade;
    qualidade_fila_t fila_hrv;   /* batimentos esperando o julgamento de depois */
    hrv_t hrv;
    ppg_bpm_t bpm_cru;           /* o último BPM do picos (entra na regra) */
    bool tem_batimento;
    uint32_t n_ultimo_pico;
    ppg_qualidade_t julgamento;  /* o último da qualidade */
    bool tem_julgamento;
    uint32_t n_julgamento;
    ppg_resultados_t ficha;      /* o que o display lê */
    cadeia_ciclos_t ciclos;
    cadeia_relogio_t relogio;
} cadeia_t;

/* Zera tudo. false se o espectral não inicia (FFT de ESPECTRAL_NFFT não compilada). */
bool cadeia_init(cadeia_t *c, cadeia_relogio_t relogio);

/* Uma amostra do bruto pela cadeia; *s diz o que saiu. A ficha é atualizada aqui:
   bpm_picos.bpm acompanha o último batimento, e bpm_picos.valido é a última decisão
   de qualidade_bpm_confiavel (acende só quando a qualidade julga; apaga também num
   batimento com BPM inválido). */
void cadeia_processa(cadeia_t *c, const ppg_amostra_t *bruto, cadeia_saida_t *s);

/* A ficha, só leitura. A spo2 é uma ESTIMATIVA (sem calibração). */
const ppg_resultados_t *cadeia_resultados(const cadeia_t *c);

#endif /* PDS_CADEIA_CADEIA_H */
