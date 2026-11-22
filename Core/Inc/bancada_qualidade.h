/*
 * bancada_qualidade.h: a qualidade na placa (passos 4 e 5).
 *
 * Só existe com -DBANCADA_QUALIDADE=ON no CMake.
 *
 * Passo 4, bancada_qualidade(): na partida, toca o vetor "bordas" (o mesmo do
 * teste no PC, testes/qualidade/vetores/bordas.h: dedo entra e sai,
 * saturação, ruído, movimento, sem pulso e n que pula) no
 * qualidade_processa(), confere com a saída do Python e mede os ciclos por
 * amostra. O resultado sai pela serial como comentário ("# bancada qualidade
 * ...").
 *
 * Passo 5, qualidade_linha(): no laço, a cada saída da qualidade sobre o
 * bruto do sensor, uma linha "q,n,dedo,usavel,indice,motivo,dc,pi,aspereza,razao"
 * (só inteiros: o printf do nano.specs não tem float). analise.captura grava
 * essas linhas em <nome>_qualidade.csv.
 */
#ifndef BANCADA_QUALIDADE_H
#define BANCADA_QUALIDADE_H

#include <stdbool.h>
#include <stddef.h>

#include "comum/ppg.h"
#include "qualidade/qualidade.h"

/*
 * Orçamento por amostra: 2000 ciclos (~21 us a 96 MHz), 0,2% da CPU a 100 Hz.
 * O pior caso é a amostra que fecha o bloco (as divisões da janela).
 */
#define BANCADA_ORCAMENTO_QUALIDADE 2000u

#ifdef BANCADA_QUALIDADE
/* Roda o vetor bordas na qualidade e manda o resultado pela serial. true se passou. */
bool bancada_qualidade(void);

/*
 * Escreve em linha a saída da qualidade (com o diagnóstico de q), sem float:
 *   q,<n>,<dedo>,<usavel>,<indice x1000>,<motivo>,<dc>,<pi x1e5>,<aspereza x100>,<razao x100>
 * pi x1e5 = milésimos de ponto percentual (400 = 0,400%). Devolve o tamanho.
 */
int qualidade_linha(char *linha, size_t tam, uint32_t n, const ppg_qualidade_t *s,
                    const qualidade_t *q);
#endif

#endif /* BANCADA_QUALIDADE_H */
