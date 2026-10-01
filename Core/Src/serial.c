/*
 * serial.c: envio pela USART1 com DMA (ver serial.h).
 */
#include "serial.h"

#include <string.h>

/* 32 amostras × ~25 caracteres cabem com folga. */
#define BUF_TAM 1024u

static UART_HandleTypeDef *uart;
static uint8_t buf[2][BUF_TAM];
static uint32_t usado;   /* bytes em buf[enchendo] */
static uint32_t enchendo;
static volatile bool ocupado;

void serial_init(UART_HandleTypeDef *huart)
{
    uart = huart;
    usado = 0;
    enchendo = 0;
    ocupado = false;
}

bool serial_escreve(const char *dados, uint32_t n)
{
    if (n > BUF_TAM - usado) {
        return false;
    }
    memcpy(&buf[enchendo][usado], dados, n);
    usado += n;
    return true;
}

void serial_envia(void)
{
    if (ocupado || usado == 0) {
        return;
    }
    ocupado = true;
    if (HAL_UART_Transmit_DMA(uart, buf[enchendo], (uint16_t)usado) != HAL_OK) {
        ocupado = false;
        return;
    }
    enchendo ^= 1u;
    usado = 0;
}

void HAL_UART_TxCpltCallback(UART_HandleTypeDef *huart)
{
    if (huart == uart) {
        ocupado = false;
    }
}
