/*
 * ppg.h: interface combinada entre os módulos de PDS (v1).
 *
 * Regras (ver CONTRIBUTING.md):
 *  - Nada em pds/ inclui HAL nem main.h. Só C padrão.
 *  - Includes relativos à raiz pds: #include "comum/ppg.h".
 *  - Mudança neste arquivo precisa do ok dos outros dois integrantes.
 *
 * A cadeia:
 *
 *   sensor --> decimacao --> bruto --> filtro --> filtrado --> picos --> batimento --> hrv
 *                              |                      |
 *                              +--> spo2              +--> espectral
 *                              +--> qualidade
 *                              +--> respiracao
 *
 * Este arquivo define a cara do que passa em cada seta a partir da saída da
 * decimação. O que entra na decimação (taxa e formato do sensor) é assunto do
 * próprio módulo decimacao/ e fica fora daqui.
 */
#ifndef PDS_COMUM_PPG_H
#define PDS_COMUM_PPG_H

#include <stdbool.h>
#include <stdint.h>

/* ---- Taxa e tempo ---------------------------------------------------------- */

/*
 * Taxa de TODAS as saídas da cadeia, em Hz. É a única taxa deste arquivo.
 * A taxa do sensor (400 Hz na placa, 500 Hz no PhysioNet) é parâmetro de
 * decimacao_init(), não constante daqui.
 */
#define PPG_FS_HZ 100u

/*
 * Atraso, em amostras a PPG_FS_HZ, entre a entrada do filtro (módulo filtro/)
 * e a saída "filtrado". Pode ser fracionário (FIR com número par de
 * coeficientes, IIR). O filtro repete na saída o n da amostra de entrada; quem
 * detecta o instante do pico subtrai este valor. O dono do módulo filtro/
 * atualiza quando mudar o filtro.
 */
#define PPG_ATRASO_AMOSTRAS 0.0f

/* ---- Amostra --------------------------------------------------------------- */

/*
 * Uma amostra dos dois canais. O mesmo tipo serve para os dois pontos de
 * saída da cadeia:
 *  - bruto:    saída da decimação (decimacao/), COM o DC.
 *              Usado por filtro/, spo2/, qualidade/ e respiracao/.
 *  - filtrado: saída do filtro (filtro/), passa-faixa 0,5 a 4 Hz, média zero.
 *              Usado por picos/ e espectral/.
 *
 * Unidade: contagens do ADC de 18 bits do MAX30102 (0 a 262143), em float.
 * Nenhum módulo converte pra outra escala. Com o dedo, o DC fica na casa de
 * 100 mil e o pulso é de 0,2 a 2% disso. Quem lê o sensor garante que ir e
 * vermelho são mesmo o IR e o vermelho (os LEDs podem vir trocados).
 *
 * n é a posição da amostra na fila a PPG_FS_HZ, contada a partir da primeira
 * amostra que saiu da decimação (n = 0). Tempo em segundos = n / PPG_FS_HZ.
 * Antes da decimação não existe n.
 */
typedef struct {
    uint32_t n;
    float ir;
    float vermelho;
} ppg_amostra_t;

/* ---- Resultados ------------------------------------------------------------ */

/*
 * Cada resultado tem "valido": false até o módulo ter confiança (janela ainda
 * não encheu, sinal ruim, etc.). O display mostra "--" quando valido é false.
 */

/*
 * Um batimento detectado (picos/). A fonte falsa entrega as marcas do ECG
 * neste mesmo tipo, com fracao = 0 e rr_valido conforme a regra abaixo.
 */
typedef struct {
    bool valido;
    uint32_t n_pico;    /* amostra do pico, já corrigida de PPG_ATRASO_AMOSTRAS */
    float fracao;       /* [0, 1): posição do pico entre n_pico e n_pico + 1,
                           por interpolação. 0 se o módulo não interpola.
                           Instante em segundos = (n_pico + fracao) / PPG_FS_HZ. */
    bool rr_valido;     /* false no primeiro batimento e sempre que o intervalo
                           atravessa um batimento perdido ou rejeitado. HRV só
                           usa rr_ms com rr_valido true. */
    float rr_ms;        /* intervalo até o batimento anterior */
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

/* spo2/. Separa AC e DC dos dois canais a partir do bruto. */
typedef struct {
    bool valido;
    float spo2_pct;
} ppg_spo2_t;

/* respiracao/ */
typedef struct {
    bool valido;
    float rpm;          /* respirações por minuto */
} ppg_respiracao_t;

/*
 * qualidade/. Só o laço principal lê este resultado: com usavel false, ele
 * mostra "--" e descarta os batimentos do trecho. picos/ e hrv/ não dependem
 * da qualidade.
 */
typedef struct {
    bool valido;
    bool dedo_presente;
    float indice;       /* 0 = inutilizável, 1 = ótimo */
    bool usavel;        /* dedo_presente && indice acima do limiar do módulo */
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

/* ---- Molde dos módulos ----------------------------------------------------- */

/*
 * Sem malloc e sem variável global. O estado fica numa struct que quem chama
 * aloca. Cada módulo expõe:
 *
 *   void <m>_init(<m>_t *m, ...);     zera o estado; chamar de novo reinicia
 *   bool <m>_processa(<m>_t *m, const <entrada> *e, <saida> *s);
 *
 * processa() devolve true quando escreveu em *s. Módulos que não soltam saída
 * a cada entrada (decimacao/ só a cada fator amostras, picos/ só quando há
 * batimento) devolvem false nas demais chamadas, e *s não é tocado.
 *
 * Exemplo:
 *
 *   typedef struct { ... } filtro_t;
 *   void filtro_init(filtro_t *f);
 *   bool filtro_processa(filtro_t *f, const ppg_amostra_t *bruto,
 *                        ppg_amostra_t *filtrado);
 */

#endif /* PDS_COMUM_PPG_H */
