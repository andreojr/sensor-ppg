/* bancada_cadeia.c: a cadeia na placa com o vetor do PhysioNet. Ver bancada_cadeia.h. */
#include "bancada_cadeia.h"

#ifdef BANCADA_CADEIA

#include <stdio.h>

#include "bancada.h"
#include "bancada_hrv.h"
#include "bancada_qualidade.h"
#include "monitor.h"
#include "serial.h"
/* O mesmo vetor e o mesmo comparador do teste no PC (testes/ no include path). */
#include "cadeia/compara_cadeia.h"

bool bancada_cadeia(cadeia_t *c)
{
    ciclos_liga();
    if (!cadeia_init(c, ciclos_agora))
        return false;
    compara_cadeia_t cmp;
    compara_cadeia_init(&cmp);
    for (uint32_t i = 0; i < PHYSIONET_IR_N; i++) {
        ppg_amostra_t bruto = {i, physionet_ir[i], physionet_vermelho[i]};
        static cadeia_saida_t s; /* fora da pilha */
        cadeia_processa(c, &bruto, &s);
        compara_cadeia_amostra(&cmp, &s);
    }
    uint32_t fora = compara_cadeia_fim(&cmp);

    cadeia_ciclos_t *k = &c->ciclos;
    uint32_t media = (uint32_t)(k->total.soma / (k->total.conta ? k->total.conta : 1u));
    uint32_t pior = k->total.max;
    /* O pior caso acima de um período não reprova: a fila absorve (firmware.md, "Se
       estourar"). Só é registrado na linha final. */
    bool ok = fora == 0u && media <= MONITOR_ORCAMENTO_CADEIA;
    bool pior_cabe = pior <= MONITOR_ORCAMENTO_CADEIA_MAX;

    char linha[128];
    int n = snprintf(linha, sizeof linha, "# bancada cadeia: %lu saidas, %lu fora da tolerancia\n",
                     (unsigned long)cmp.saidas, (unsigned long)fora);
    serial_escreve(linha, (uint32_t)n);
    ciclos_relata(&k->filtro, "bancada filtro", BANCADA_ORCAMENTO_FILTRO);
    ciclos_relata(&k->picos, "bancada picos", BANCADA_ORCAMENTO_PICOS);
    ciclos_relata_max(&k->espectral, "bancada espectral", BANCADA_ORCAMENTO_ESPECTRAL,
                      BANCADA_ORCAMENTO_ESPECTRAL_MAX);
    ciclos_relata(&k->hrv, "bancada hrv", BANCADA_ORCAMENTO_HRV);
    ciclos_relata_max(&k->hrv_freq, "bancada lf/hf", BANCADA_ORCAMENTO_HRV_FREQ_MED,
                      BANCADA_ORCAMENTO_HRV_FREQ_PASSO);
    ciclos_relata(&k->respiracao, "bancada respiracao", BANCADA_ORCAMENTO_RESPIRACAO);
    ciclos_relata(&k->spo2, "bancada spo2", BANCADA_ORCAMENTO_SPO2);
    ciclos_relata(&k->qualidade, "bancada qualidade", BANCADA_ORCAMENTO_QUALIDADE);
    n = snprintf(linha, sizeof linha,
                 "# bancada cadeia: ciclos por amostra med %lu max %lu (orcamento %lu / %lu%s): %s\n",
                 (unsigned long)media, (unsigned long)pior,
                 (unsigned long)MONITOR_ORCAMENTO_CADEIA,
                 (unsigned long)MONITOR_ORCAMENTO_CADEIA_MAX,
                 pior_cabe ? "" : ", max acima: so registrado", ok ? "OK" : "FALHOU");
    serial_escreve(linha, (uint32_t)n);
    serial_envia();
    return ok;
}

#endif /* BANCADA_CADEIA */
