/*
 * replay_cadeia: lê as cruas de uma captura (o <nome>.csv do analise.captura:
 * "n,ir,vermelho") da entrada padrão e escreve na saída as linhas que a placa
 * mandaria (b, f, p, h, e, r, t). Ver replay.h.
 *
 *   build/testes/replay_cadeia < dados/captura.csv
 *
 * Com --bruto, lê o bruto a 100 Hz que a placa mandou (as linhas b, do
 * <nome>_bruto.csv: "n,ir,vermelho", desde o reset, n contínuo) e passa direto pela
 * cadeia, sem a decimação: confere a cadeia mesmo quando a serial perdeu cruas.
 *
 * Quem compara com o que a placa mandou: uv run python -m analise.cadeia --replay.
 */
#include <stdio.h>
#include <string.h>

#include "cadeia/replay.h"

static replay_t r;

static int so_cadeia(void)
{
    if (!cadeia_init(&r.cadeia, NULL))
        return 1;
    char linha[128];
    static char buf[LINHAS_MAX];
    while (fgets(linha, sizeof linha, stdin)) {
        unsigned long n;
        float ir, vm;
        if (sscanf(linha, "%lu,%f,%f", &n, &ir, &vm) != 3)
            continue;
        ppg_amostra_t bruto = {(uint32_t)n, ir, vm};
        cadeia_saida_t s;
        cadeia_processa(&r.cadeia, &bruto, &s);
        fwrite(buf, 1, linhas_cadeia(&s, &bruto, true, buf, sizeof buf), stdout);
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc > 1 && strcmp(argv[1], "--bruto") == 0)
        return so_cadeia();
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
