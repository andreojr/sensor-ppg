/*
 * display: o OLED SSD1306 (I2C3) na placa. Fala com o chip pela HAL; quem desenha é o
 * módulo oled/ (C puro, testado no PC). Ver docs/src/content/docs/firmware.md.
 *
 * Uma página (128 bytes, ~3 ms a 400 kHz) por volta do laço principal: o laço tem 37,5 ms
 * de folga pra ler a FIFO do sensor depois do INT, e uma página só tira ~3 ms disso.
 * Se o display não responde ou falha 3 vezes seguidas, ele se desliga e o resto da placa
 * segue sem ele.
 */
#ifndef DISPLAY_H
#define DISPLAY_H

#include <stdbool.h>
#include <stdint.h>

#include "main.h"
#include "oled/oled.h"

/* Endereço I2C de 7 bits. SUPOSIÇÃO: 0x3C (alguns módulos vêm com 0x3D, resistor atrás). */
#ifndef DISPLAY_ENDERECO
#define DISPLAY_ENDERECO 0x3Cu
#endif

/*
 * Orientação. SUPOSIÇÃO: a mais comum (segmentos e linhas remapeados, A1 e C8). Se a imagem
 * sair de cabeça pra baixo, compile com -DDISPLAY_ORIENTACAO_NORMAL=0.
 */
#ifndef DISPLAY_ORIENTACAO_NORMAL
#define DISPLAY_ORIENTACAO_NORMAL 1
#endif

/* A tela de inicialização fica no ar pelo menos este tempo antes das telas normais. */
#define DISPLAY_AGUARDE_MS 2000u

/* Quadros por segundo: o design pede 20 a 400 kHz. */
#define DISPLAY_QUADRO_MS 50u

/*
 * Confere se o chip responde e manda a sequência de inicialização. false se não respondeu
 * (o resto da API passa a não fazer nada).
 */
bool display_init(I2C_HandleTypeDef *hi2c);

bool display_ativo(void);

/* Tela de inicialização e telas de erro: bloqueiam até mandar tudo (até 8 páginas, ~25 ms). */
void display_tela_inicio(const oled_etapa_t etapas[3], bool aguarde);
void display_tela_erro(oled_erro_t erro);

/* Uma amostra do sinal filtrado (IR), a 100 Hz. O sinal é invertido aqui: no IR, sangue a
   mais é luz a menos, e o pulso sairia de cabeça pra baixo. A confirmar na placa. */
void display_amostra(float ir_filtrado);

/*
 * Chamar a cada volta do laço principal. Se há páginas de um quadro por mandar, manda uma;
 * senão, passado DISPLAY_QUADRO_MS, desenha o próximo quadro com os resultados.
 */
void display_servico(const ppg_resultados_t *r, uint32_t agora_ms);

#endif /* DISPLAY_H */
