/* sensor.c: ver sensor.h. A leitura e as perdidas são as do main.c da v0.3. */
#include "sensor.h"

#include <stdio.h>

#include "app.h"
#include "bancada.h"
#include "cadeia/linhas.h"
#include "decimacao/decimacao.h"
#include "max30102.h"
#include "serial.h"

#define SENSOR_SEM_DADOS_MS 1000u

static volatile bool tem_dado;
static fila_t *fila;
static decimacao_t decimacao;               /* sensor -> bruto a PPG_FS_HZ */
static uint32_t indice;                     /* nº da amostra a MAX30102_FS_HZ desde o início */
static max30102_amostra_t anterior;         /* repetida no lugar das perdidas */
static volatile max30102_amostra_t ultima;  /* pra olhar no Live Watch do debugger */
static sensor_medidas_t medidas;
static bool leu;                            /* já houve uma leitura (pro intervalo) */
static I2C_HandleTypeDef *i2c_sensor;
static uint32_t t_dado_ms;                  /* ms da última leitura com amostras */
static uint32_t t_leitura;                  /* DWT da última leitura */

sensor_erro_t sensor_init(I2C_HandleTypeDef *hi2c, fila_t *f)
{
    fila = f;
    i2c_sensor = hi2c;
    fila_init(fila);
    if (max30102_init(hi2c) != HAL_OK)
        return SENSOR_ERRO_SEM_RESPOSTA;
    t_dado_ms = HAL_GetTick();
    if (!decimacao_init(&decimacao, MAX30102_FS_HZ))
        return SENSOR_ERRO_SEM_FILTRO;
    return SENSOR_OK;
}

void sensor_int(void)
{
    tem_dado = true;
}

sensor_medidas_t *sensor_medidas(void)
{
    return &medidas;
}

static void decima(const max30102_amostra_t *amostra)
{
    decimacao_entrada_t e = {amostra->ir, amostra->vermelho};
    ppg_amostra_t bruto;
    uint32_t t0 = ciclos_agora();
    bool saiu = decimacao_processa(&decimacao, &e, &bruto);
    ciclos_conta(&medidas.decimacao, ciclos_agora() - t0);
    if (saiu)
        fila_poe(fila, &bruto); /* cheia: descarta e conta (fila->cheia) */
}

/* Sem amostras por SENSOR_SEM_DADOS_MS (o MAX30102 parou ou resetou sozinho): reconfigura o
   sensor (reset + configuração completa, acende os LEDs). Se a I2C1 não responde, reinicia a
   I2C1 e tenta de novo 1 s depois, sem desistir. A cadeia não é reiniciada: o trecho sem
   sinal sai como qualidade ruim. Não solta um SDA preso pelo sensor (ver firmware.md). */
static bool recupera(void)
{
    if (HAL_GetTick() - t_dado_ms < SENSOR_SEM_DADOS_MS)
        return false;
    t_dado_ms = HAL_GetTick();
    if (max30102_init(i2c_sensor) == HAL_OK) {
        tem_dado = false;
    } else {
        (void)HAL_I2C_DeInit(i2c_sensor);
        (void)HAL_I2C_Init(i2c_sensor);
    }
    return true;
}

void sensor_tarefa(void)
{
    if (recupera())
        return;
    /* O pino também é olhado: se uma leitura falhar, o INT fica baixo e não vem
       outra borda de descida. */
    if (!tem_dado && HAL_GPIO_ReadPin(SENSOR_INT_GPIO_Port, SENSOR_INT_Pin) != GPIO_PIN_RESET)
        return;
    tem_dado = false;

    uint32_t agora = ciclos_agora();
    if (leu && agora - t_leitura > medidas.maior_intervalo)
        medidas.maior_intervalo = agora - t_leitura;
    leu = true;
    t_leitura = agora;

    static max30102_amostra_t amostras[MAX30102_FIFO_TAM];
    uint32_t n;
    uint32_t perdidas;
    char linha[48];
    if (max30102_le_fifo(amostras, &n, &perdidas) != HAL_OK)
        return;
    for (uint32_t i = 0; i < n; i++) {
        if (APP_SERIAL_COMPLETA) {
            size_t tam = linhas_cru(indice, amostras[i].ir, amostras[i].vermelho, linha,
                                    sizeof linha);
            serial_escreve(linha, (uint32_t)tam);
        }
        decima(&amostras[i]);
        anterior = amostras[i];
        indice++;
    }
    /* Sem rollover, a FIFO cheia descarta as amostras novas: as perdidas vêm
       depois das que foram lidas. A decimação recebe a última amostra no lugar
       delas, e o n (cru e bruto) continua alinhado com o tempo do sensor. */
    if (perdidas > 0) {
        int tam = snprintf(linha, sizeof linha, "# perdidas: %lu\n", (unsigned long)perdidas);
        serial_escreve(linha, (uint32_t)tam);
        for (uint32_t i = 0; indice > 0 && i < perdidas; i++)
            decima(&anterior);
        indice += perdidas;
        medidas.perdidas += perdidas;
    }
    if (n > 0) {
        t_dado_ms = HAL_GetTick();
        ultima.ir = amostras[n - 1].ir;
        ultima.vermelho = amostras[n - 1].vermelho;
    }
}
