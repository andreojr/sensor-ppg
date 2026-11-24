/* app.c: ver app.h. */
#include "app.h"

#include <stdio.h>

#include "bancada.h"
#include "bancada_cadeia.h"
#include "bancada_hrv.h"
#include "bancada_qualidade.h"
#include "cadeia/cadeia.h"
#include "cadeia/fila.h"
#include "cadeia/linhas.h"
#include "display.h"
#include "max30102.h"
#include "monitor.h"
#include "sensor.h"
#include "serial.h"

static fila_t fila;       /* sensor -> cadeia */
static cadeia_t cadeia;   /* ~41 KB (16 KB do LF/HF): static */
static TIM_HandleTypeDef *tim_regua;

/* Para a placa: avisa na serial (e na tela, se houver display) e cai no Error_Handler. */
static void para(const char *msg, uint32_t tam, bool na_tela, oled_erro_t erro)
{
    serial_escreve(msg, tam);
    serial_envia();
    if (na_tela)
        display_tela_erro(erro);
    HAL_Delay(50); /* o DMA termina antes de parar */
    Error_Handler();
}

static void cabecalho(void)
{
    char texto[640];
    int n = snprintf(texto, sizeof texto,
                     "# sensor-ppg: laco principal, serial %s\n"
                     "# MAX30102 %u Hz: n,ir,vermelho (so na completa)\n"
                     "# decimacao %u Hz: b,n,ir,vermelho\n"
                     "# filtro %u Hz, atraso %u: f,n,ir,vermelho (so na completa)\n"
                     "# picos: p,n_pico,fracao,rr_valido,rr_ms,bpm_valido,bpm\n"
                     "# espectral: e,n,bpm_valido,bpm\n"
                     "# hrv: h,n_pico,valido,sdnn,rmssd,rr_usado\n"
                     "# respiracao 1 Hz: r,n,rpm,valido\n"
                     "# spo2 (ESTIMADA, reta 110 - 25 R, sem calibracao): s,n,valido,spo2,r\n"
                     "# tela 1 Hz: t,n,mostra,bpm x100\n"
                     "# lf/hf a cada 5 s: l,n,valido,lf_hf\n"
                     "# laco 1 Hz (TIM2): amostras, fila_max, fila_cheia, perdidas\n",
                     APP_SERIAL_COMPLETA ? "completa" : "padrao", MAX30102_FS_HZ, PPG_FS_HZ,
                     PPG_FS_HZ, (unsigned)PPG_ATRASO_AMOSTRAS);
    serial_escreve(texto, (uint32_t)n);
}

void app_init(I2C_HandleTypeDef *sensor, I2C_HandleTypeDef *display, UART_HandleTypeDef *serial,
              TIM_HandleTypeDef *regua)
{
    tim_regua = regua;
    serial_init(serial);
    /* O display liga primeiro: ele conta o boot, inclusive o erro do sensor. */
    oled_etapa_t etapas[3] = {OLED_ETAPA_PENDENTE, OLED_ETAPA_PENDENTE, OLED_ETAPA_PENDENTE};
    if (display_init(display)) {
        display_tela_inicio(etapas, false);
    } else {
        static const char aviso[] = "# aviso: display nao respondeu na I2C3: segue sem ele\n";
        serial_escreve(aviso, sizeof aviso - 1u);
    }
#ifdef BANCADA_DISPLAY
    (void)bancada_display(); /* demonstração das telas, sem o sensor: não volta */
#endif
#ifdef BANCADA_HRV
    /* Fonte falsa no HRV, antes do sensor (roda mesmo sem o MAX30102). */
    (void)bancada_hrv();
#endif
#ifdef BANCADA_HRV_FREQ
    /* Idem para o LF/HF: 613 batimentos, alguns segundos. */
    (void)bancada_hrv_freq();
#endif
#ifdef BANCADA_QUALIDADE
    /* Vetor da qualidade, antes do sensor (roda mesmo sem o MAX30102). */
    (void)bancada_qualidade();
#endif
    switch (sensor_init(sensor, &fila)) {
    case SENSOR_ERRO_SEM_RESPOSTA: {
        static const char erro[] = "# erro: MAX30102 nao respondeu na I2C1\n";
        para(erro, sizeof erro - 1u, true, OLED_ERRO_SENSOR);
        break;
    }
    case SENSOR_ERRO_SEM_FILTRO: {
        static const char erro[] = "# erro: decimacao sem filtro para essa taxa do MAX30102\n";
        para(erro, sizeof erro - 1u, true, OLED_ERRO_DECIMACAO);
        break;
    }
    case SENSOR_OK:
        break;
    }
    etapas[0] = etapas[1] = OLED_ETAPA_OK; /* MAX30102 e DECIMACAO */
    display_tela_inicio(etapas, false);
    cabecalho();
    monitor_init(regua);
    /* Bancadas: fonte falsa em cada módulo, resultado (OK/FALHOU) na serial; a placa
       segue mesmo se falhar. As amostras do sensor desse intervalo podem sair como
       "# perdidas". */
#ifdef BANCADA_DECIMACAO
    (void)bancada_decimacao();
#endif
#ifdef BANCADA_FILTRO
    (void)bancada_filtro();
#endif
#ifdef BANCADA_PICOS
    (void)bancada_picos();
#endif
#ifdef BANCADA_ESPECTRAL
    (void)bancada_espectral();
#endif
#ifdef BANCADA_RESPIRACAO
    (void)bancada_respiracao();
#endif
#ifdef BANCADA_SPO2
    (void)bancada_spo2();
#endif
#ifdef BANCADA_CADEIA
    (void)bancada_cadeia(&cadeia); /* a cadeia é reiniciada logo abaixo */
#endif
    if (!cadeia_init(&cadeia, ciclos_agora)) {
        static const char erro[] = "# erro: FFT de 1024 pontos nao compilada (espectral)\n";
        etapas[2] = OLED_ETAPA_ERRO; /* não há tela de erro própria: marca a etapa */
        display_tela_inicio(etapas, false);
        para(erro, sizeof erro - 1u, false, OLED_ERRO_SENSOR);
    }
    etapas[2] = OLED_ETAPA_OK; /* FILTRO (a cadeia) */
    display_tela_inicio(etapas, true);
    monitor_comeca(); /* o TIM2 contou durante as bancadas: os relatos começam agora */
}

/* Esvazia a fila: cada bruto pela cadeia, as linhas na serial e a onda pro display. */
static void cadeia_tarefa(void)
{
    ppg_amostra_t bruto;
    while (fila_tira(&fila, &bruto)) {
        static cadeia_saida_t s; /* ~340 B: fora da pilha (mínima de 1 KiB) */
        cadeia_processa(&cadeia, &bruto, &s);
        monitor_conta_amostra();
        display_amostra(s.filtrado.ir);
        static char linhas[LINHAS_MAX];
        size_t n = linhas_cadeia(&s, &bruto, APP_SERIAL_COMPLETA, linhas, sizeof linhas);
        serial_escreve(linhas, (uint32_t)n);
#ifdef BANCADA_QUALIDADE
        if (s.julgou) {
            int tam = qualidade_linha(linhas, sizeof linhas, bruto.n, &s.qualidade,
                                      &cadeia.qualidade);
            serial_escreve(linhas, (uint32_t)tam);
        }
#endif
    }
}

void app_laco(void)
{
    uint32_t t0 = ciclos_agora();
    sensor_tarefa();
    cadeia_tarefa();
    display_servico(cadeia_resultados(&cadeia), HAL_GetTick());
    monitor_tarefa(&fila, &cadeia);
    serial_envia();
    monitor_conta_volta(ciclos_agora() - t0);
}

void HAL_GPIO_EXTI_Callback(uint16_t GPIO_Pin)
{
    if (GPIO_Pin == SENSOR_INT_Pin)
        sensor_int();
}

void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim)
{
    if (htim == tim_regua)
        monitor_tique();
}
