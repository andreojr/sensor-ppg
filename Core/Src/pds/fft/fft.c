/*
 * fft: ver fft.h. É o único arquivo do projeto que enxerga o CMSIS-DSP.
 */
#include "fft/fft.h"

#include "dsp/transform_functions.h"

/* Tamanhos compilados. Cada um traz as tabelas dele pra flash. */
#ifndef FFT_COM_256
#define FFT_COM_256 1
#endif
#ifndef FFT_COM_512
#define FFT_COM_512 1
#endif
#ifndef FFT_COM_1024
#define FFT_COM_1024 1
#endif
#ifndef FFT_COM_2048
#define FFT_COM_2048 0
#endif

_Static_assert(sizeof(arm_rfft_fast_instance_f32) <= sizeof(((fft_t *)0)->cmsis),
               "fft_t.cmsis pequeno demais pra instância do CMSIS");
_Static_assert(_Alignof(arm_rfft_fast_instance_f32) <= _Alignof(uint64_t),
               "alinhamento da instância do CMSIS maior que o do fft_t");

static arm_rfft_fast_instance_f32 *instancia(fft_t *f)
{
    return (arm_rfft_fast_instance_f32 *)(void *)f->cmsis;
}

static const arm_rfft_fast_instance_f32 *instancia_const(const fft_t *f)
{
    return (const arm_rfft_fast_instance_f32 *)(const void *)f->cmsis;
}

bool fft_init(fft_t *f, uint16_t n)
{
    /* A inicialização de cada tamanho é chamada pelo nome (e não a genérica
       arm_rfft_fast_init_f32): assim o linker só leva as tabelas dos tamanhos ligados. */
    arm_status r = ARM_MATH_ARGUMENT_ERROR;
    switch (n) {
#if FFT_COM_256
    case 256:
        r = arm_rfft_fast_init_256_f32(instancia(f));
        break;
#endif
#if FFT_COM_512
    case 512:
        r = arm_rfft_fast_init_512_f32(instancia(f));
        break;
#endif
#if FFT_COM_1024
    case 1024:
        r = arm_rfft_fast_init_1024_f32(instancia(f));
        break;
#endif
#if FFT_COM_2048
    case 2048:
        r = arm_rfft_fast_init_2048_f32(instancia(f));
        break;
#endif
    default:
        break;
    }
    f->n = r == ARM_MATH_SUCCESS ? n : 0u;
    return r == ARM_MATH_SUCCESS;
}

uint16_t fft_n(const fft_t *f)
{
    return f->n;
}

void fft_potencia(const fft_t *f, float *x, float *trabalho)
{
    const uint16_t n = f->n;
    const uint16_t metade = (uint16_t)(n / 2u);

    /* Saída do CMSIS, empacotada: [Re0, Re(n/2), Re1, Im1, Re2, Im2, ...].
       O CMSIS usa x como rascunho, então x é sobrescrito. */
    arm_rfft_fast_f32(instancia_const(f), x, trabalho, 0u);

    x[0] = trabalho[0] * trabalho[0];
    x[metade] = trabalho[1] * trabalho[1];
    for (uint16_t k = 1u; k < metade; k++) {
        const float re = trabalho[2u * k];
        const float im = trabalho[2u * k + 1u];
        x[k] = re * re + im * im;
    }
}
