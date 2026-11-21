/* bancada.c: ciclos e conferência do PDS na placa. Ver bancada.h. */
#include "bancada.h"

void ciclos_liga(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

#ifdef BANCADA_DECIMACAO

#include <math.h>
#include <stdio.h>

#include "decimacao/decimacao.h"
#include "serial.h"
/* O mesmo vetor do teste no PC (testes/ entra no include path com a opção). */
#include "decimacao/vetores/sensor_400hz.h"

bool bancada_decimacao(void)
{
    static decimacao_t d; /* ~1 KiB: fora da pilha */
    if (!decimacao_init(&d, 400u)) {
        static const char erro[] = "# bancada decimacao: sem filtro para 400 Hz: FALHOU\n";
        serial_escreve(erro, sizeof erro - 1u);
        serial_envia();
        return false;
    }

    uint32_t saidas = 0, fora = 0, max_ciclos = 0;
    uint64_t soma_ciclos = 0;
    float pior = 0.0f;
    for (uint32_t i = 0; i < SENSOR_400HZ_IR_N; i++) {
        decimacao_entrada_t e = {(uint32_t)sensor_400hz_ir[i], (uint32_t)sensor_400hz_vermelho[i]};
        ppg_amostra_t s;
        uint32_t t0 = ciclos_agora();
        bool saiu = decimacao_processa(&d, &e, &s);
        uint32_t dt = ciclos_agora() - t0;
        soma_ciclos += dt;
        if (dt > max_ciclos)
            max_ciclos = dt;
        if (!saiu)
            continue;
        if (saidas < SENSOR_400HZ_ESPERADO_IR_N && s.n == saidas) {
            float erro = fmaxf(fabsf(s.ir - sensor_400hz_esperado_ir[saidas]),
                               fabsf(s.vermelho - sensor_400hz_esperado_vermelho[saidas]));
            if (erro > pior)
                pior = erro;
            fora += !(erro <= SENSOR_400HZ_TOL);
        } else {
            fora++;
        }
        saidas++;
    }

    uint32_t media = (uint32_t)(soma_ciclos / SENSOR_400HZ_IR_N);
    bool ok = saidas == SENSOR_400HZ_ESPERADO_IR_N && fora == 0 &&
              media <= BANCADA_ORCAMENTO_DECIMACAO;
    char linha[160];
    int n = snprintf(linha, sizeof linha,
                     "# bancada decimacao: %lu saidas (esperado %lu), %lu fora da tolerancia, "
                     "erro max %lu milesimos\n",
                     (unsigned long)saidas, (unsigned long)SENSOR_400HZ_ESPERADO_IR_N,
                     (unsigned long)fora, (unsigned long)(pior * 1000.0f + 0.5f));
    serial_escreve(linha, (uint32_t)n);
    n = snprintf(linha, sizeof linha,
                 "# bancada decimacao: ciclos por amostra med %lu max %lu (orcamento %lu): %s\n",
                 (unsigned long)media, (unsigned long)max_ciclos,
                 (unsigned long)BANCADA_ORCAMENTO_DECIMACAO, ok ? "OK" : "FALHOU");
    serial_escreve(linha, (uint32_t)n);
    serial_envia();
    return ok;
}

#endif /* BANCADA_DECIMACAO */
