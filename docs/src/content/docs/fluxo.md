---
title: Fluxo de trabalho
description: Como um item sai do Python e chega na placa.
---

O detalhe está no
[CONTRIBUTING.md](https://github.com/andreojr/sensor-ppg/blob/main/CONTRIBUTING.md).
Resumo:

## Cada item passa por 5 passos (um PR cada)

1. **Python** (`analise/`): protótipo validado no PhysioNet, com o ECG como
   gabarito.
2. **C** (`Core/*/pds/<módulo>/`): porte sem HAL.
3. **Teste no PC** (`testes/<módulo>/`): o C bate com os vetores gerados pelo
   Python.
4. **Placa com a fonte falsa**: trecho do PhysioNet tocado como se fosse o
   sensor.
5. **Sensor real**.

## Regras de PR

- A `main` é protegida: só entra por PR, com o CI verde.
- **1 aprovação de code owner.** No seu módulo, quem aprova é o seu revisor
  fixo (A é revisado por C, B por A, C por B).
- **Até ~400 linhas** alteradas, sem contar arquivo gerado.
- **Mudou um módulo, muda a página dele aqui** (`docs/src/content/docs/modulos/`).
- Merge por squash.

## Gestão

- **Tasks**: [GitHub Project](https://github.com/users/andreojr/projects/1),
  uma issue por task, com prazo e marco.
- **Compromissos com hora**: agenda compartilhada do grupo.
