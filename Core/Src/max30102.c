/*
 * max30102.c: leitura do MAX30102 (ver max30102.h e docs/.../firmware.md).
 */
#include "max30102.h"

#define ENDERECO (0x57u << 1) /* endereço de 7 bits, deslocado pra HAL */
#define TIMEOUT_MS 50u        /* FIFO cheia: 192 bytes a 100 kHz ≈ 18 ms */

/* Registradores */
#define REG_INT_STATUS1 0x00u
#define REG_INT_ENABLE1 0x02u
#define REG_FIFO_WR_PTR 0x04u /* 0x04 a 0x06: WR_PTR, OVF_COUNTER, RD_PTR */
#define REG_FIFO_DATA 0x07u
#define REG_FIFO_CONFIG 0x08u
#define REG_MODE_CONFIG 0x09u
#define REG_SPO2_CONFIG 0x0Au
#define REG_LED1_PA 0x0Cu /* vermelho */
#define REG_LED2_PA 0x0Du /* IR */
#define REG_PART_ID 0xFFu

#define PART_ID 0x15u

/* Valores */
#define MODE_RESET 0x40u
#define MODE_SPO2 0x03u
/* SMP_AVE = 1 (sem média), sem rollover, INT com 15 vagas = 17 amostras. */
#define FIFO_CONFIG 0x0Fu
/* ADC_RGE = 4096 nA (01), SR = 400 Hz (011), LED_PW = 411 us, 18 bits (11). */
#define SPO2_CONFIG ((0x1u << 5) | (0x3u << 2) | 0x3u)
/* Corrente dos LEDs: 0x24 × 0,2 mA = 7,2 mA. */
#define LED_PA 0x24u
#define INT_A_FULL 0x80u

#define BYTES_POR_AMOSTRA 6u /* 3 do vermelho, 3 do IR */
#define MASCARA_18_BITS 0x3FFFFu
#define PTR_MASCARA 0x1Fu

static I2C_HandleTypeDef *i2c;

static HAL_StatusTypeDef escreve(uint8_t reg, uint8_t valor)
{
    return HAL_I2C_Mem_Write(i2c, ENDERECO, reg, I2C_MEMADD_SIZE_8BIT, &valor, 1,
                             TIMEOUT_MS);
}

static HAL_StatusTypeDef le(uint8_t reg, uint8_t *dados, uint16_t n)
{
    return HAL_I2C_Mem_Read(i2c, ENDERECO, reg, I2C_MEMADD_SIZE_8BIT, dados, n,
                            TIMEOUT_MS);
}

static uint32_t amostra_de(const uint8_t *p)
{
    return (((uint32_t)p[0] << 16) | ((uint32_t)p[1] << 8) | p[2]) & MASCARA_18_BITS;
}

HAL_StatusTypeDef max30102_init(I2C_HandleTypeDef *hi2c)
{
    uint8_t valor;
    i2c = hi2c;

    if (le(REG_PART_ID, &valor, 1) != HAL_OK || valor != PART_ID)
    {
        return HAL_ERROR;
    }

    /* Reset: o bit volta a 0 sozinho quando termina. */
    if (escreve(REG_MODE_CONFIG, MODE_RESET) != HAL_OK)
    {
        return HAL_ERROR;
    }
    uint32_t inicio = HAL_GetTick();
    do
    {
        if (HAL_GetTick() - inicio > 100u || le(REG_MODE_CONFIG, &valor, 1) != HAL_OK)
        {
            return HAL_ERROR;
        }
    } while (valor & MODE_RESET);

    /* Solta o INT de power-ready, zera os ponteiros da FIFO e configura. */
    const uint8_t config[][2] = {
        {REG_FIFO_WR_PTR, 0},
        {REG_FIFO_WR_PTR + 1u, 0}, /* OVF_COUNTER */
        {REG_FIFO_WR_PTR + 2u, 0}, /* FIFO_RD_PTR */
        {REG_FIFO_CONFIG, FIFO_CONFIG},
        {REG_SPO2_CONFIG, SPO2_CONFIG},
        {REG_LED1_PA, LED_PA},
        {REG_LED2_PA, LED_PA},
        {REG_INT_ENABLE1, INT_A_FULL},
        {REG_MODE_CONFIG, MODE_SPO2}, /* por último: começa a amostrar */
    };
    if (le(REG_INT_STATUS1, &valor, 1) != HAL_OK)
    {
        return HAL_ERROR;
    }
    for (uint32_t i = 0; i < sizeof config / sizeof config[0]; i++)
    {
        if (escreve(config[i][0], config[i][1]) != HAL_OK)
        {
            return HAL_ERROR;
        }
    }
    return HAL_OK;
}

HAL_StatusTypeDef max30102_le_fifo(max30102_amostra_t amostras[MAX30102_FIFO_TAM],
                                   uint32_t *n, uint32_t *perdidas)
{
    static uint8_t bytes[MAX30102_FIFO_TAM * BYTES_POR_AMOSTRA];
    uint8_t status;
    uint8_t ptr[3];

    *n = 0;
    *perdidas = 0;

    /* Ler o status solta o INT. */
    if (le(REG_INT_STATUS1, &status, 1) != HAL_OK || le(REG_FIFO_WR_PTR, ptr, 3) != HAL_OK)
    {
        return HAL_ERROR;
    }
    uint32_t escrita = ptr[0] & PTR_MASCARA;
    uint32_t ovf = ptr[1] & PTR_MASCARA;
    uint32_t leitura = ptr[2] & PTR_MASCARA;

    /* Ponteiros iguais: FIFO vazia, ou cheia se houve overflow. */
    uint32_t disponiveis = (escrita - leitura) & PTR_MASCARA;
    if (disponiveis == 0 && ovf != 0)
    {
        disponiveis = MAX30102_FIFO_TAM;
    }
    if (disponiveis == 0)
    {
        return HAL_OK;
    }

    /* O FIFO_DATA não autoincrementa: uma leitura longa tira várias amostras. */
    if (le(REG_FIFO_DATA, bytes, (uint16_t)(disponiveis * BYTES_POR_AMOSTRA)) != HAL_OK)
    {
        return HAL_ERROR;
    }
    for (uint32_t i = 0; i < disponiveis; i++)
    {
        const uint8_t *p = &bytes[i * BYTES_POR_AMOSTRA];
        amostras[i].vermelho = amostra_de(p); /* modo SpO2: LED1 (vermelho) vem primeiro */
        amostras[i].ir = amostra_de(p + 3);
    }
    *n = disponiveis;
    *perdidas = ovf;
    return HAL_OK;
}
