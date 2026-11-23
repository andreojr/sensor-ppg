/* Programa de medição do display no emulador (ciclos.py): desenha cada tela e conta as
 * páginas que mudam de um quadro pro seguinte. Não vai pro firmware. */
#include <string.h>

#include "oled/oled.h"

oled_t o;
ppg_resultados_t r;
volatile unsigned cenario; /* 0 principal, 1 resumo, 2 alvo, 3 sem dedo, 4 sinal ruim */
volatile unsigned ok;
volatile unsigned paginas; /* páginas que faltavam mandar */
volatile unsigned empurra; /* quantas amostras novas entram antes do próximo quadro */
static unsigned n_amostras;

static float amostra(unsigned i)
{
    float f = (float)(i % 80u) / 80.0f; /* um dente de serra de 0,8 s, parecido com um pulso */
    return f < 0.2f ? 5.0f * f : 1.0f - 1.25f * (f - 0.2f);
}

/* O firmware copia o .data da flash pra RAM no boot; aqui, à mão (a libm tem dados iniciados). */
extern unsigned _sidata, _sdata, _edata;

void entra_init(void)
{
    for (unsigned *origem = &_sidata, *destino = &_sdata; destino < &_edata;)
        *destino++ = *origem++;
    oled_init(&o);
    for (n_amostras = 0; n_amostras < 300u; n_amostras++)
        oled_amostra(&o, amostra(n_amostras));
    ok = 1;
    __asm volatile("bkpt #0");
}

void entra_desenha(void)
{
    uint32_t t = 0;
    memset(&r, 0, sizeof r);
    r.bpm_picos.valido = true;
    r.bpm_picos.bpm = 72.0f;
    r.qualidade.valido = true;
    r.qualidade.dedo_presente = true;
    r.qualidade.usavel = true;
    r.qualidade.indice = 0.82f;
    switch (cenario) {
    case 1: t = OLED_PRINCIPAL_MS; break;
    case 2:
        r.spo2.valido = true;
        r.spo2.spo2_pct = 97.0f;
        t = OLED_PRINCIPAL_MS + OLED_RESUMO_MS;
        break;
    case 3: r.qualidade.dedo_presente = false; break;
    case 4: r.qualidade.usavel = false; break;
    default: break;
    }
    for (unsigned i = 0; i < empurra; i++, n_amostras++)
        oled_amostra(&o, amostra(n_amostras));
    oled_desenha(&o, &r, t);
    __asm volatile("bkpt #0");
}

/* Manda (de mentira) tudo o que falta e diz quantas páginas eram. */
void entra_paginas(void)
{
    uint8_t p;
    const uint8_t *d;
    unsigned n = 0;
    while (oled_proxima_pagina(&o, &p, &d)) {
        oled_pagina_enviada(&o, p);
        n++;
    }
    paginas = n;
    __asm volatile("bkpt #0");
}

__attribute__((section(".vetores"), used)) void (*const vetores[])(void) = {
    (void (*)(void))0x20020000,
    entra_init,
};
