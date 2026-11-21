/*
 * fft: espectro de potência de um sinal real, em float.
 *
 * É uma camada fina sobre a FFT real do CMSIS-DSP (Drivers/CMSIS/DSP, v1.16.2).
 * Quem usa (o espectral) inclui só este arquivo, nunca um cabeçalho do CMSIS:
 * se um dia a FFT mudar, só o fft.c muda.
 *
 * Sem HAL, sem malloc, sem global. O estado fica numa struct que quem chama
 * aloca (fft_t), como nos outros módulos.
 *
 * Uso:
 *
 *   fft_t f;
 *   float x[1024];        a janela (n amostras reais)
 *   float trabalho[1024]; área de trabalho, n floats
 *
 *   fft_init(&f, 1024);   uma vez
 *   ... preenche x ...
 *   fft_potencia(&f, x, trabalho);
 *   // x[0] a x[512] agora é |X[k]|^2, a potência na frequência k * fs / n
 *
 * Tamanhos compilados (potências de 2): 256, 512 e 1024 por padrão. Cada um
 * leva as suas tabelas pra flash (uns 4 KB cada), então só os ligados entram.
 * Pra ligar ou desligar um tamanho: -DFFT_COM_2048=1, -DFFT_COM_256=0, etc.
 */
#ifndef PDS_FFT_FFT_H
#define PDS_FFT_FFT_H

#include <stdbool.h>
#include <stdint.h>

/*
 * Estado da FFT. O conteúdo é do CMSIS e não deve ser lido: o vetor só reserva
 * espaço (o fft.c confere em tempo de compilação que cabe).
 */
typedef struct {
    uint64_t cmsis[8];
    uint16_t n;
} fft_t;

/*
 * Prepara a FFT de n pontos reais. Devolve false se n não é um dos tamanhos
 * compilados; nesse caso o fft_t não pode ser usado.
 */
bool fft_init(fft_t *f, uint16_t n);

/* Tamanho (pontos reais) com que o fft_t foi iniciado. */
uint16_t fft_n(const fft_t *f);

/*
 * Espectro de potência |X[k]|^2 de x[0..n-1], pra k = 0 a n/2: o resultado
 * (n/2 + 1 valores) fica em x[0..n/2]. A FFT não é normalizada (igual à do
 * NumPy). x e trabalho têm n floats cada e os dois são sobrescritos.
 */
void fft_potencia(const fft_t *f, float *x, float *trabalho);

#endif /* PDS_FFT_FFT_H */
