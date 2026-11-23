/* monitor.c: ver monitor.h. */
#include "monitor.h"

#include <stdio.h>

#include "bancada.h"
#include "bancada_hrv.h"
#include "bancada_qualidade.h"
#include "sensor.h"
#include "serial.h"

#define TIQUES_SEGUNDO 100u
#define SEGUNDOS_CICLOS 10u

static volatile uint32_t tiques;
static uint32_t proximo;    /* tique do próximo relato de 1 s */
static uint32_t segundos;
static uint32_t amostras;
static ciclos_t volta;

void monitor_init(TIM_HandleTypeDef *htim)
{
    ciclos_liga();
    proximo = TIQUES_SEGUNDO;
    HAL_TIM_Base_Start_IT(htim);
}

void monitor_tique(void)
{
    tiques++;
}

void monitor_conta_amostra(void)
{
    amostras++;
}

void monitor_conta_volta(uint32_t ciclos)
{
    ciclos_conta(&volta, ciclos);
}

static void relata_ciclos(cadeia_t *c, sensor_medidas_t *m)
{
    cadeia_ciclos_t *k = &c->ciclos;
    ciclos_relata(&m->decimacao, "decimacao", BANCADA_ORCAMENTO_DECIMACAO);
    ciclos_relata(&k->filtro, "filtro", BANCADA_ORCAMENTO_FILTRO);
    ciclos_relata(&k->picos, "picos", BANCADA_ORCAMENTO_PICOS);
    ciclos_relata_max(&k->espectral, "espectral", BANCADA_ORCAMENTO_ESPECTRAL,
                      BANCADA_ORCAMENTO_ESPECTRAL_MAX);
    ciclos_relata(&k->hrv, "hrv", BANCADA_ORCAMENTO_HRV);
    ciclos_relata(&k->respiracao, "respiracao", BANCADA_ORCAMENTO_RESPIRACAO);
    ciclos_relata(&k->qualidade, "qualidade", BANCADA_ORCAMENTO_QUALIDADE);
    ciclos_relata_max(&k->total, "cadeia", MONITOR_ORCAMENTO_CADEIA, MONITOR_ORCAMENTO_CADEIA_MAX);
    ciclos_relata(&volta, "volta", MONITOR_ORCAMENTO_VOLTA);
    char linha[64];
    uint32_t ms = m->maior_intervalo / (SystemCoreClock / 1000u);
    int tam = snprintf(linha, sizeof linha, "# leitura: maior intervalo %lu ms (limite %u)\n",
                       (unsigned long)ms, MONITOR_LIMITE_LEITURA_MS);
    serial_escreve(linha, (uint32_t)tam);
    m->maior_intervalo = 0;
}

void monitor_tarefa(fila_t *fila, cadeia_t *c)
{
    if ((int32_t)(tiques - proximo) < 0)
        return;
    proximo += TIQUES_SEGUNDO;
    sensor_medidas_t *m = sensor_medidas();
    char linha[96];
    int tam = snprintf(linha, sizeof linha, "# laco: amostras %lu fila_max %lu fila_cheia %lu "
                       "perdidas %lu\n", (unsigned long)amostras, (unsigned long)fila->max,
                       (unsigned long)fila->cheia, (unsigned long)m->perdidas);
    serial_escreve(linha, (uint32_t)tam);
    amostras = 0;
    m->perdidas = 0;
    fila_zera_medidas(fila);
    if (++segundos % SEGUNDOS_CICLOS == 0u)
        relata_ciclos(c, m);
}
