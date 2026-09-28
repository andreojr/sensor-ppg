## O quê

<!-- Uma ou duas frases. Qual issue fecha: "Fecha #N". -->

## Passo do fluxo

- [ ] 1. Protótipo em Python validado no PhysioNet
- [ ] 2. Porte pra C
- [ ] 3. Teste no PC contra os vetores de referência
- [ ] 4. Na placa com a fonte falsa
- [ ] 5. Integração com o sensor real
- [ ] Fora do PDS (firmware, CI, docs)

## Como validei

<!-- Números: erro contra a referência, gráfico, saída do teste. -->

## Checklist

- [ ] Nada em `pds/` inclui HAL ou `main.h`
- [ ] Documentação do módulo atualizada em `docs/`
- [ ] Até ~400 linhas alteradas (sem contar gerado)
- [ ] Se mexi no `ppg.h`: os outros dois concordaram antes
