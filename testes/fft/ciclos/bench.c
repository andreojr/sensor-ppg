/* Programa de medição da FFT no emulador (ciclos.py): duas entradas, uma pro
 * fft_init e outra pro fft_potencia, cada uma terminando num BKPT. Não vai pro
 * firmware: só o ciclos.py compila isso. */
#include "fft/fft.h"

fft_t f;
float x[1024];
float trabalho[1024];
volatile unsigned n_cfg; /* o ciclos.py escreve o tamanho aqui */
volatile unsigned ok;    /* e lê aqui se o fft_init aceitou */

void entra_init(void)
{
    ok = fft_init(&f, (uint16_t)n_cfg);
    __asm volatile("bkpt #0");
}

void entra_fft(void)
{
    fft_potencia(&f, x, trabalho);
    __asm volatile("bkpt #0");
}

/* Tabela de vetores mínima: pilha e o "reset" (entra_init). */
__attribute__((section(".vetores"), used)) void (*const vetores[])(void) = {
    (void (*)(void))0x20020000,
    entra_init,
};
