/*
 * bancada_cadeia.h: a cadeia inteira na placa com o vetor do PhysioNet
 * (-DBANCADA_CADEIA=ON).
 *
 * Na partida, antes do sensor, passa os 90 s do vetor testes/cadeia/vetores/
 * physionet.h (o mesmo do teste no PC) pela cadeia, confere cada saída com o
 * Python e mede os ciclos de cada módulo e da cadeia por amostra (DWT):
 *
 *   # bancada cadeia: 478 saidas, 0 fora da tolerancia
 *   # bancada filtro: ciclos med ... max ... (orcamento ...)
 *   ...
 *   # bancada cadeia: ciclos por amostra med X max Y (orcamento 51000 / 960000): OK
 */
#ifndef BANCADA_CADEIA_H
#define BANCADA_CADEIA_H

#include <stdbool.h>

#include "cadeia/cadeia.h"

#ifdef BANCADA_CADEIA
/* Usa a cadeia de quem chama (a do app, pra não gastar outros ~20 KB de RAM); quem
   chama faz o cadeia_init de novo depois. true se passou. */
bool bancada_cadeia(cadeia_t *c);
#endif

#endif /* BANCADA_CADEIA_H */
