/* Programa de medição do espectral no emulador (ciclos.py espectral): uma entrada pro
 * espectral_init e outra que processa UMA amostra do vetor do teste no PC e termina num
 * BKPT. Não vai pro firmware: só o ciclos.py compila isso. */
#include "espectral/espectral.h"
#include "espectral/vetores/s2_walk.h"

espectral_t e;
volatile unsigned indice; /* o ciclos.py escreve a amostra a processar aqui */
volatile unsigned ok;     /* lido depois do espectral_init */
volatile unsigned saiu;   /* 1 se esta amostra fechou uma saída */
volatile unsigned valido;
volatile float bpm;
volatile float prominencia;

/* O firmware copia o .data da flash pra RAM no boot; aqui, à mão (a libm tem dados iniciados). */
extern unsigned _sidata, _sdata, _edata;

void entra_init(void)
{
    for (unsigned *origem = &_sidata, *destino = &_sdata; destino < &_edata;)
        *destino++ = *origem++;
    ok = espectral_init(&e);
    __asm volatile("bkpt #0");
}

void entra_amostra(void)
{
    ppg_amostra_t x = {indice, s2_walk_entrada[indice], 0.0f};
    ppg_bpm_t s = {false, 0.0f};
    saiu = espectral_processa(&e, &x, &s);
    valido = s.valido;
    bpm = s.bpm;
    prominencia = espectral_prominencia(&e);
    __asm volatile("bkpt #0");
}

/* Tabela de vetores mínima: pilha e o "reset" (entra_init). */
__attribute__((section(".vetores"), used)) void (*const vetores[])(void) = {
    (void (*)(void))0x20020000,
    entra_init,
};
