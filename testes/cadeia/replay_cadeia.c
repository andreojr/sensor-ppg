/*
 * replay_cadeia: lê as cruas de uma captura (o <nome>.csv do analise.captura:
 * "n,ir,vermelho") da entrada padrão e escreve na saída as linhas que a placa
 * mandaria (b, f, p, h, e, r, t). Ver replay.h.
 *
 *   build/testes/replay_cadeia < dados/captura.csv
 *
 * Quem compara com o que a placa mandou: uv run python -m analise.cadeia --replay.
 */
#include <stdio.h>

#include "cadeia/replay.h"

static replay_t r;

int main(void)
{
    if (!replay_init(&r)) {
        fprintf(stderr, "replay: init falhou\n");
        return 1;
    }
    char linha[128];
    while (fgets(linha, sizeof linha, stdin)) {
        unsigned long n, ir, vm;
        if (sscanf(linha, "%lu,%lu,%lu", &n, &ir, &vm) != 3)
            continue; /* cabeçalho, comentário */
        if (!replay_amostra(&r, (uint32_t)n, (uint32_t)ir, (uint32_t)vm, stdout))
            return 1;
    }
    return 0;
}
