/*
 * ppg.h: interface combinada entre os módulos de PDS.
 *
 * Regras (ver CONTRIBUTING.md):
 *  - Nada em pds/ inclui HAL nem main.h. Só C padrão.
 *  - Includes relativos à raiz pds: #include "comum/ppg.h".
 *  - Mudança neste arquivo precisa do ok dos outros dois integrantes.
 */
#ifndef PDS_COMUM_PPG_H
#define PDS_COMUM_PPG_H

#include <stdbool.h>
#include <stdint.h>

/* Taxa das saídas "bruto" e "filtrado" da cadeia, em Hz. */
#define PPG_FS_HZ 100u

/*
 * Atraso, em amostras, entre a entrada do filtro (módulo filtro/) e a saída
 * "filtrado". Quem detecta o instante do pico subtrai este valor.
 * O dono do módulo filtro/ atualiza quando mudar o filtro.
 */
#define PPG_ATRASO_AMOSTRAS 0u

/*
 * Uma amostra dos dois canais. O mesmo tipo serve para os dois pontos de
 * saída da cadeia:
 *  - bruto:    saída da decimação (decimacao/), a PPG_FS_HZ, COM o DC.
 *              Usado por spo2/, qualidade/ e respiracao/.
 *  - filtrado: saída do filtro (filtro/), passa-faixa 0,5 a 4 Hz, sem DC.
 *              Usado por picos/ e espectral/.
 * n é o índice da amostra a PPG_FS_HZ desde o início da aquisição; tempo em
 * segundos = n / PPG_FS_HZ.
 */
typedef struct {
    uint32_t n;
    float ir;
    float vermelho;
} ppg_amostra_t;

/* ---- Resultados. Cada um tem "valido": false até o módulo ter confiança. ---- */

/* Um batimento detectado (picos/). */
typedef struct {
    bool valido;
    uint32_t n_pico;   /* índice da amostra do pico, já corrigido do atraso */
    float rr_ms;       /* intervalo até o batimento anterior */
} ppg_batimento_t;

typedef struct {
    bool valido;
    float bpm;
} ppg_bpm_t;

/* hrv/ */
typedef struct {
    bool valido;
    float sdnn_ms;
    float rmssd_ms;
    bool lf_hf_valido;  /* LF/HF precisa de janela longa (minutos) */
    float lf_hf;
} ppg_hrv_t;

/* spo2/ */
typedef struct {
    bool valido;
    float spo2_pct;
} ppg_spo2_t;

/* respiracao/ */
typedef struct {
    bool valido;
    float rpm;          /* respirações por minuto */
} ppg_respiracao_t;

/* qualidade/ */
typedef struct {
    bool valido;
    bool dedo_presente;
    float indice;       /* 0 = inutilizável, 1 = ótimo */
} ppg_qualidade_t;

/* Tudo o que o laço principal e o display leem. */
typedef struct {
    ppg_batimento_t ultimo_batimento;
    ppg_bpm_t bpm_picos;      /* picos/ */
    ppg_bpm_t bpm_espectral;  /* espectral/ */
    ppg_hrv_t hrv;
    ppg_spo2_t spo2;
    ppg_respiracao_t respiracao;
    ppg_qualidade_t qualidade;
} ppg_resultados_t;

#endif /* PDS_COMUM_PPG_H */
