/* Programa de medição do spo2 no emulador (ciclos.py): processa UMA amostra do vetor do teste no PC
 * e termina num BKPT. Não vai pro firmware: só o ciclos.py compila isso. */
#include "spo2/spo2.h"
#include "spo2/vetores/sem_dedo.h"

spo2_t s;
volatile unsigned indice; /* o ciclos.py escreve aqui a amostra a processar */
volatile unsigned ok;
volatile unsigned saiu;   /* 1 se esta amostra fechou uma saída */
volatile unsigned valido;
volatile float spo2_pct;
volatile float r;

/* O firmware copia o .data da flash pra RAM no boot; aqui, à mão (a libm tem dados iniciados). */
extern unsigned _sidata, _sdata, _edata;

void entra_init(void)
{
    for (unsigned *origem = &_sidata, *destino = &_sdata; destino < &_edata;)
        *destino++ = *origem++;
    spo2_init(&s);
    ok = 1;
    __asm volatile("bkpt #0");
}

void entra_amostra(void)
{
    ppg_amostra_t x = {indice, sem_dedo_ir[indice], sem_dedo_vermelho[indice]};
    ppg_spo2_t o = {false, 0.0f};
    saiu = spo2_processa(&s, &x, &o);
    valido = o.valido;
    spo2_pct = o.spo2_pct;
    r = spo2_r(&s);
    __asm volatile("bkpt #0");
}

__attribute__((section(".vetores"), used)) void (*const vetores[])(void) = {
    (void (*)(void))0x20020000,
    entra_init,
};
