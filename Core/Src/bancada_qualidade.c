/* bancada_qualidade.c: a qualidade na placa. Ver bancada_qualidade.h. */
#include "bancada_qualidade.h"

#ifdef BANCADA_QUALIDADE

#include <math.h>
#include <stdio.h>

#include "bancada.h"
#include "serial.h"
/* O mesmo vetor do teste no PC (testes/ entra no include path com a opção). */
#include "qualidade/vetores/bordas.h"

/* Inteiro arredondado, sem printf de float. */
static long arredonda(float v)
{
    return (long)(v + (v < 0.0f ? -0.5f : 0.5f));
}

int qualidade_linha(char *linha, size_t tam, uint32_t n, const ppg_qualidade_t *s,
                    const qualidade_t *q)
{
    return snprintf(linha, tam, "q,%lu,%d,%d,%ld,%lu,%ld,%ld,%ld,%ld,%ld\n", (unsigned long)n,
                    s->dedo_presente, s->usavel, arredonda(s->indice * 1000.0f),
                    (unsigned long)q->motivo, arredonda(q->dc_ir), arredonda(q->pi * 1e5f),
                    arredonda(q->aspereza * 100.0f), arredonda(q->razao * 100.0f),
                    arredonda(q->ritmo * 1000.0f));
}

/* Erro relativo, como no teste do PC. */
static float erro_rel(float obtido, float esperado)
{
    return fabsf(obtido - esperado) / fmaxf(fabsf(esperado), 1.0f);
}

bool bancada_qualidade(void)
{
    ciclos_liga(); /* bancada.h; pode rodar antes do ciclos_liga() do main */

    static qualidade_t q; /* 964 B: fora da pilha */
    qualidade_init(&q);

    uint32_t saidas = 0, fora = 0, max_ciclos = 0, usaveis = 0;
    uint64_t soma_ciclos = 0;
    float pior = 0.0f;
    for (uint32_t i = 0; i < BORDAS_N_N; i++) {
        ppg_amostra_t e = {(uint32_t)bordas_n[i], bordas_ir[i], bordas_vermelho[i]};
        ppg_qualidade_t s;
        uint32_t t0 = ciclos_agora();
        bool saiu = qualidade_processa(&q, &e, &s);
        uint32_t dt = ciclos_agora() - t0;
        soma_ciclos += dt;
        if (dt > max_ciclos)
            max_ciclos = dt;
        if (!saiu)
            continue;
        if (saidas >= BORDAS_SAIDA_N_N) {
            fora++;
            continue;
        }
        uint32_t k = saidas++;
        float erro = fmaxf(fmaxf(erro_rel(q.pi, bordas_saida_pi[k]),
                                 erro_rel(q.aspereza, bordas_saida_aspereza[k])),
                           fmaxf(fmaxf(erro_rel(q.razao, bordas_saida_razao[k]),
                                       erro_rel(q.dc_ir, bordas_saida_dc[k])),
                                 erro_rel(q.ritmo, bordas_saida_ritmo[k])));
        if (erro > pior)
            pior = erro;
        fora += (int32_t)e.n != bordas_saida_n[k] || (int32_t)s.usavel != bordas_saida_usavel[k] ||
                (int32_t)s.dedo_presente != bordas_saida_dedo[k] ||
                (int32_t)q.motivo != bordas_saida_motivo[k] ||
                fabsf(s.indice - bordas_saida_indice[k]) > 1e-6f || !(erro <= BORDAS_TOL);
        usaveis += s.usavel;
    }

    uint32_t media = (uint32_t)(soma_ciclos / BORDAS_N_N);
    bool ok = saidas == BORDAS_SAIDA_N_N && fora == 0 && max_ciclos <= BANCADA_ORCAMENTO_QUALIDADE;
    char linha[160];
    int n = snprintf(linha, sizeof linha,
                     "# bancada qualidade: %lu saidas (esperado %lu), %lu usaveis, %lu fora da "
                     "tolerancia, erro rel max %lu milionesimos\n",
                     (unsigned long)saidas, (unsigned long)BORDAS_SAIDA_N_N,
                     (unsigned long)usaveis, (unsigned long)fora,
                     (unsigned long)(pior * 1e6f + 0.5f));
    serial_escreve(linha, (uint32_t)n);
    n = snprintf(linha, sizeof linha,
                 "# bancada qualidade: ciclos por amostra med %lu max %lu (orcamento %lu): %s\n",
                 (unsigned long)media, (unsigned long)max_ciclos,
                 (unsigned long)BANCADA_ORCAMENTO_QUALIDADE, ok ? "OK" : "FALHOU");
    serial_escreve(linha, (uint32_t)n);
    serial_envia();
    return ok;
}

#endif /* BANCADA_QUALIDADE */
