/* display: o SSD1306 na I2C3. Ver display.h. */
#include "display.h"

#include <math.h>

#include "app.h"
#include "serial.h"

#define ENDERECO_HAL (DISPLAY_ENDERECO << 1) /* a HAL quer o endereço já deslocado */
#define TIMEOUT_MS 5u /* uma página leva 3,1 ms (medido); sobra pra um ACK lento */
#define FALHAS_SEGUIDAS_MAX 3u

#define CTRL_COMANDOS 0x00u /* o que vem depois são comandos */
#define CTRL_DADOS 0x40u    /* o que vem depois são pixels */

static I2C_HandleTypeDef *i2c;
static oled_t oled; /* ~3 KB */
static bool ativo;
static uint8_t falhas;
static uint32_t t_quadro;   /* ms do último quadro desenhado */
static uint32_t t_inicio;   /* ms em que o display ligou */
static bool quadro_pendente; /* o quadro desenhado ainda tem páginas por mandar */
#if APP_SERIAL_TELA
static uint32_t t_espelho; /* ms do último reenvio da tela inteira */
#endif

/* Barramento ocupado (SDA preso em baixo, por exemplo): a HAL esperaria 25 ms fixos pelo
   BUSY antes de desistir, acima do TIMEOUT_MS. Aqui espera no máximo ~2 ms (o BUSY de um
   envio que acabou de terminar some em microssegundos, depois do STOP) e conta como falha. */
#define LIVRE_MS 2u
static bool livre(void)
{
    uint32_t t0 = HAL_GetTick();
    while (__HAL_I2C_GET_FLAG(i2c, I2C_FLAG_BUSY) != RESET)
        if ((uint32_t)(HAL_GetTick() - t0) >= LIVRE_MS)
            return false;
    return true;
}

static bool comandos(const uint8_t *c, uint16_t n)
{
    return livre() && HAL_I2C_Mem_Write(i2c, ENDERECO_HAL, CTRL_COMANDOS, I2C_MEMADD_SIZE_8BIT,
                             (uint8_t *)(uintptr_t)c, n, TIMEOUT_MS) == HAL_OK;
}

/* Posiciona na página (modo de endereçamento por página: B0+página, coluna 0) e manda os 128 bytes. */
static bool envia_pagina(uint8_t pagina, const uint8_t *dados)
{
    const uint8_t pos[3] = {(uint8_t)(0xB0u | pagina), 0x00u, 0x10u};
    return comandos(pos, sizeof pos) && livre() &&
           HAL_I2C_Mem_Write(i2c, ENDERECO_HAL, CTRL_DADOS, I2C_MEMADD_SIZE_8BIT,
                             (uint8_t *)(uintptr_t)dados, OLED_W, TIMEOUT_MS) == HAL_OK;
}

/* Conta as falhas; depois de FALHAS_SEGUIDAS_MAX o display se desliga. A I2C é reiniciada
   a cada falha, pra um erro dela (barramento preso) não deixar o resto da placa sem I2C3. */
static void trata(bool ok)
{
    if (ok) {
        falhas = 0;
        return;
    }
    (void)HAL_I2C_DeInit(i2c);
    (void)HAL_I2C_Init(i2c);
    if (++falhas >= FALHAS_SEGUIDAS_MAX)
        ativo = false;
}

/* A página foi pro chip. Com SERIAL_TELA, manda também a cópia pela serial (linha d,); se a
   linha não couber no buffer da serial, a página se perde e volta no próximo reenvio. Sem a
   opção é só o oled_pagina_enviada (um macro, pro firmware sair igual ao de antes). */
#if APP_SERIAL_TELA
static void enviada(uint8_t pagina, const uint8_t *dados)
{
    char linha[OLED_LINHA_TELA_TAM];
    unsigned n = oled_linha_tela(pagina, dados, linha);
    (void)serial_escreve(linha, n);
    oled_pagina_enviada(&oled, pagina);
}
#else
#define enviada(pagina, dados) oled_pagina_enviada(&oled, (pagina))
#endif

/* Manda de uma vez tudo o que falta (bloqueia: só pro boot e pros erros). */
static void envia_tudo(void)
{
    uint8_t pagina;
    const uint8_t *dados;
    while (ativo && oled_proxima_pagina(&oled, &pagina, &dados)) {
        bool ok = envia_pagina(pagina, dados);
        trata(ok);
        if (ok)
            enviada(pagina, dados);
    }
}

bool display_init(I2C_HandleTypeDef *hi2c)
{
    static const uint8_t INICIO[] = {
        0xAE,       /* display apagado */
        0xD5, 0x80, /* relógio */
        0xA8, 0x3F, /* 64 linhas */
        0xD3, 0x00, /* sem deslocamento vertical */
        0x40,       /* primeira linha da memória no topo */
        0x8D, 0x14, /* bomba de carga ligada (o módulo não tem a alta tensão pronta) */
        0x20, 0x02, /* endereçamento por página */
#if DISPLAY_ORIENTACAO_NORMAL
        0xA1, 0xC8, /* segmentos e linhas remapeados */
#else
        0xA0, 0xC0,
#endif
        0xDA, 0x12, /* pinos COM de um painel 128x64 */
        0x81, 0xCF, /* contraste */
        0xD9, 0xF1, /* pré-carga */
        0xDB, 0x40, /* tensão do VCOMH */
        0xA4,       /* mostra a memória */
        0xA6,       /* sem inverter */
        0x2E,       /* sem rolagem */
    };
    static const uint8_t ACENDE[] = {0xAF};
    static const uint8_t ZEROS[OLED_W] = {0};
    i2c = hi2c;
    ativo = false;
    falhas = 0;
    quadro_pendente = false;
    oled_init(&oled);
    if (!livre() || HAL_I2C_IsDeviceReady(i2c, ENDERECO_HAL, 3, TIMEOUT_MS) != HAL_OK)
        return false;
    if (!comandos(INICIO, sizeof INICIO))
        return false;
    /* Limpa a memória do chip antes de acender (senão aparece lixo do último uso). */
    for (uint8_t p = 0; p < OLED_PAGINAS; p++)
        if (!envia_pagina(p, ZEROS))
            return false;
    if (!comandos(ACENDE, sizeof ACENDE))
        return false;
    ativo = true;
    t_inicio = HAL_GetTick();
    t_quadro = t_inicio;
#if APP_SERIAL_TELA
    t_espelho = t_inicio;
#endif
    return true;
}

bool display_ativo(void)
{
    return ativo;
}

void display_tela_inicio(const oled_etapa_t etapas[3], bool aguarde)
{
    if (!ativo)
        return;
    oled_tela_inicio(&oled, etapas, aguarde);
    envia_tudo();
    if (aguarde)
        t_inicio = HAL_GetTick(); /* o AGUARDE fica no ar DISPLAY_AGUARDE_MS a partir daqui */
}

void display_tela_erro(oled_erro_t erro)
{
    if (!ativo)
        return;
    oled_tela_erro(&oled, erro);
    envia_tudo();
}

void display_amostra(float ir_filtrado)
{
    if (!isfinite(ir_filtrado))
        return; /* um NaN travaria a escala da onda (max/min nunca mais saem dele) */
    oled_amostra(&oled, -ir_filtrado);
}

void display_servico(const ppg_resultados_t *r, uint32_t agora_ms)
{
    if (!ativo)
        return;

    if (quadro_pendente) {
        uint8_t pagina;
        const uint8_t *dados;
        if (oled_proxima_pagina(&oled, &pagina, &dados)) {
            bool ok = envia_pagina(pagina, dados); /* uma página por volta: ~3 ms */
            trata(ok);
            if (ok)
                enviada(pagina, dados);
            return;
        }
        quadro_pendente = false;
    }

#if APP_SERIAL_TELA
    /* A cada ~10 s as 8 páginas voltam a ser "não enviadas": vão de novo ao chip (~24 ms de I2C,
       uma por volta) e à serial, pro PC fechar uma tela inteira mesmo ligando no meio. */
    if ((uint32_t)(agora_ms - t_espelho) >= DISPLAY_ESPELHO_MS) {
        t_espelho = agora_ms;
        oled_invalida(&oled);
        quadro_pendente = true;
        return;
    }
#endif

    if ((uint32_t)(agora_ms - t_inicio) >= DISPLAY_AGUARDE_MS &&
        (uint32_t)(agora_ms - t_quadro) >= DISPLAY_QUADRO_MS) {
        t_quadro = agora_ms;
        oled_desenha(&oled, r, agora_ms);
        quadro_pendente = true;
    }
}
