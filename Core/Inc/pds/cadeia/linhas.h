/*
 * linhas.h: o texto que a placa manda pela serial, sem HAL.
 *
 * Os formatos são os da v0.3 (analise/src/analise/captura.py lê essas linhas):
 *   n,ir,vermelho                         cru, a 400 Hz (só com SERIAL_COMPLETA)
 *   b,n,ir,vermelho                       bruto a 100 Hz
 *   f,n,ir,vermelho                       filtrado (só com SERIAL_COMPLETA)
 *   p,n_pico,fracao,rr_valido,rr_ms,bpm_valido,bpm
 *   h,n_pico,valido,sdnn,rmssd,rr_usado
 *   e,n,bpm_valido,bpm
 *   r,n,rpm,valido
 *   t,n,mostra,bpm x100
 * Números com 2 casas (fracao com 4), sem printf de float (o nano.specs não tem).
 * Fica aqui, e não no app, pra o replay no PC escrever o mesmo texto que a placa.
 */
#ifndef PDS_CADEIA_LINHAS_H
#define PDS_CADEIA_LINHAS_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "cadeia/cadeia.h"

/* Cabe uma amostra com tudo: b, f, p, CADEIA_HRV_MAX linhas h, e, r e t. */
#define LINHAS_MAX 1024u

/* v com 2 casas e sinal, ex. "-0.25". Devolve o tamanho (como o snprintf). */
int linhas_centesimos(char *s, size_t tam, float v);

/* As linhas de uma amostra da cadeia, nesta ordem: b, f (só completa), p, cada h, e,
   r, t. Só entram linhas inteiras: a que não cabe em tam fica de fora (e as
   seguintes também). Devolve os bytes escritos, sem o \0. */
size_t linhas_cadeia(const cadeia_saida_t *s, const ppg_amostra_t *bruto, bool completa,
                     char *buf, size_t tam);

/* Uma amostra crua do sensor: "n,ir,vermelho\n". */
size_t linhas_cru(uint32_t n, uint32_t ir, uint32_t vermelho, char *buf, size_t tam);

#endif /* PDS_CADEIA_LINHAS_H */
