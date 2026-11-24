/*
 * serial.c: envio pela USART1 com DMA (ver serial.h).
 */
#include "serial.h"

#include <string.h>

/* Pior leitura: FIFO cheia (32 linhas cruas × ~22 B), ~16 linhas b, e ~16 f,
   (× ~30 B, contando as repetidas no lugar das perdidas), # perdidas e os
   resumos dos ciclos: ~1,8 KB (as linhas p, do picos são uma por batimento,
   ~40 B, no máximo uma por leitura). 3 KiB cabem com folga.
   Com SERIAL_TELA entra também uma linha d, (261 B) por volta do laço, até uns 31 KB/s no
   teto (6 páginas a 20 quadros por segundo; a média medida da onda é ~3,9 páginas por quadro,
   ~20 KB/s); no tempo que o DMA leva pra esvaziar o outro buffer cheio (~67 ms) juntam-se até
   ~2,3 KB. Por isso 4 KiB nesse modo (+2 KiB de RAM, só com a opção). As amostras têm
   prioridade: a linha d, só entra se sobrar o pior bloco de amostras (serial_cabe, ~1,9 KB). */
#ifdef SERIAL_TELA
#define BUF_TAM 4096u
#else
#define BUF_TAM 3072u
#endif

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

bool serial_cabe(uint32_t n, uint32_t reserva)
{
    return n + reserva <= BUF_TAM - usado;
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
