"""Protótipo do módulo spo2: saturação de oxigênio pela razão das razões, em janela deslizante.

Entrada: o bruto (saída da decimação, COM o DC) dos dois canais a FS_HZ, uma amostra por
vez. A cada HOP_S, com a janela cheia, sai um ppg_spo2_t.

Método:
  1. Cada canal passa por um passa-altas de 1ª ordem (média exponencial ALFA, a mesma ideia do
     módulo qualidade): dc = dc + ALFA * (x - dc), ac = x - dc. Isso tira o DC e a deriva e
     deixa só o que pulsa.
  2. Em cada segundo (bloco) acumulam-se a soma de x e a soma de ac². A janela são os últimos
     JANELA_S blocos.
  3. Na janela: DC = média de x; AC = raiz da média de ac² (o RMS, que não depende de achar
     picos nem de o pulso ter forma boa).
  4. R = (AC_vermelho / DC_vermelho) / (AC_ir / DC_ir): a razão das razões. A hemoglobina com
     e sem oxigênio absorve o vermelho de um jeito e o infravermelho de outro, então R sobe
     quando o sangue tem menos oxigênio.
  5. SpO2 = CURVA_A - CURVA_B * R (reta empírica, limitada a 0 a 100%).

O resultado é uma ESTIMATIVA: a curva é a reta usual de livro, e não foi calibrada com um
oxímetro de referência (o PhysioNet não traz SpO2). Sem a calibração, o valor serve pra ver a
tendência e a ordem de grandeza (95 a 100% em pessoas saudáveis), não como medida clínica.

valido: janela cheia; DC dos dois canais >= DC_MIN em CADA segundo da janela (tem dedo o tempo
todo); o DC não varia mais que DC_VARIACAO_MAX vezes entre os segundos (se o dedo sai ou aperta no
meio da janela, o degrau vira um AC enorme nos dois canais, o R fica perto de 1 e o resultado seria
um valor plausível e errado); AC do IR > 0; e R dentro de [R_MIN, R_MAX] (a faixa que a fisiologia
permite). Não olha movimento nem ruído: quem decide se o trecho presta é o módulo qualidade (o laço
principal só mostra o SpO2 com qualidade.usavel).

O código é em fluxo e em float32 de propósito: o porte pra C (Core/Src/pds/spo2/spo2.c) segue
linha a linha, e os vetores de referência saem daqui.

Uso (da pasta analise/):
  uv run python -m analise.spo2_validacao     validação nos registros do PhysioNet
  uv run python -m analise.spo2               vetores pro teste em C (testes/spo2/vetores/)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from analise import FS_HZ

F32 = np.float32

JANELA_S = 8
HOP_S = 1
ALFA = 0.02  # média exponencial do DC: constante de tempo de 50 amostras (0,5 s), corte ~0,3 Hz
DC_MIN = 10000.0  # contagens; sem dedo ~1500, com dedo > 60 mil (o mesmo limite do qualidade)
R_MIN = 0.2
R_MAX = 1.6  # R = 0,2 daria 105% e R = 1,6 daria 70%: fora disso não é sangue
DC_VARIACAO_MAX = 1.5  # maior DC por segundo / menor DC por segundo, em cada canal
CURVA_A = 110.0  # SpO2 = A - B * R
CURVA_B = 25.0
TOL_VETOR = 1e-3  # tolerância dos floats no teste em C (spo2 e r)

HOP = HOP_S * FS_HZ
BLOCOS = JANELA_S // HOP_S
JANELA = JANELA_S * FS_HZ


@dataclass(frozen=True)
class Saida:
    """ppg_spo2_t mais o instante (n da última amostra da janela) e o R."""

    n: int
    valido: bool
    spo2: float
    r: float


class Spo2:
    def __init__(self) -> None:
        self.reinicia()

    def reinicia(self) -> None:
        """spo2_init."""
        self.n = 0
        self.tem_dc = False
        self.dc_ir = F32(0)
        self.dc_vm = F32(0)
        self.cont = 0  # amostras do bloco em andamento
        self.b = [F32(0)] * 4  # soma de x e de ac² do bloco: ir, vm, ir, vm
        self.blocos = [[F32(0)] * 4 for _ in range(BLOCOS)]
        self.idx = 0  # onde entra o próximo bloco
        self.cheios = 0

    def processa(self, ir: float, vermelho: float) -> Saida | None:
        """spo2_processa: devolve o resultado a cada HOP, com a janela cheia."""
        ir, vm = F32(ir), F32(vermelho)
        if not (np.isfinite(ir) and np.isfinite(vm)):
            return None  # amostra descartada: não entra em nenhuma conta
        if not self.tem_dc:
            self.dc_ir, self.dc_vm, self.tem_dc = ir, vm, True
        self.dc_ir = F32(self.dc_ir + F32(F32(ALFA) * F32(ir - self.dc_ir)))
        self.dc_vm = F32(self.dc_vm + F32(F32(ALFA) * F32(vm - self.dc_vm)))
        ac_ir = F32(ir - self.dc_ir)
        ac_vm = F32(vm - self.dc_vm)
        b = self.b
        b[0] = F32(b[0] + ir)
        b[1] = F32(b[1] + vm)
        b[2] = F32(b[2] + F32(ac_ir * ac_ir))
        b[3] = F32(b[3] + F32(ac_vm * ac_vm))
        self.n += 1
        self.cont += 1
        if self.cont < HOP:
            return None

        self.blocos[self.idx] = list(b)
        self.idx = (self.idx + 1) % BLOCOS
        self.cheios = min(self.cheios + 1, BLOCOS)
        self.cont = 0
        self.b = [F32(0)] * 4
        if self.cheios < BLOCOS:
            return None
        return self._estima()

    def _estima(self) -> Saida:
        # Soma da janela do bloco mais velho (o que vai ser sobrescrito) ao mais novo.
        s = [F32(0)] * 4
        for k in range(BLOCOS):
            bloco = self.blocos[(self.idx + k) % BLOCOS]
            for j in range(4):
                s[j] = F32(s[j] + bloco[j])
        n = F32(JANELA)
        # O DC de cada segundo: todos têm que passar do mínimo e não variar demais.
        dcs_ok = True
        for canal in (0, 1):
            menor = maior = None
            for k in range(BLOCOS):
                dc_bloco = F32(self.blocos[k][canal] / F32(HOP))
                menor = dc_bloco if menor is None else min(menor, dc_bloco)
                maior = dc_bloco if maior is None else max(maior, dc_bloco)
            dcs_ok = dcs_ok and bool(
                menor >= F32(DC_MIN) and maior <= F32(F32(DC_VARIACAO_MAX) * menor)
            )
        dc_ir, dc_vm = F32(s[0] / n), F32(s[1] / n)
        ac_ir, ac_vm = F32(np.sqrt(F32(s[2] / n))), F32(np.sqrt(F32(s[3] / n)))

        n_fim = self.n - 1
        if not (dcs_ok and ac_ir > F32(0)):
            return Saida(n_fim, False, 0.0, 0.0)
        r = F32(F32(ac_vm / dc_vm) / F32(ac_ir / dc_ir))
        valido = F32(R_MIN) <= r <= F32(R_MAX)
        spo2 = F32(F32(CURVA_A) - F32(F32(CURVA_B) * r))
        spo2 = min(max(spo2, F32(0)), F32(100))
        # Inválido sai com spo2 0, como o picos_bpm(): o display mostra "--".
        return Saida(n_fim, bool(valido), float(spo2) if valido else 0.0, float(r))


def estima(ir: np.ndarray, vermelho: np.ndarray) -> list[Saida]:
    """Roda o módulo num trecho e devolve todas as saídas."""
    s = Spo2()
    return [r for a, v in zip(ir, vermelho, strict=True) if (r := s.processa(a, v)) is not None]


CASOS = (
    ("s1_sit", "limpo, sentado: 40 s do bruto"),
    ("sem_dedo", "25 s do s1_sit e depois 15 s sem dedo (DC baixo): janelas inválidas"),
)
VETOR_DURACAO_S = 40.0
SEM_DEDO_A_PARTIR_DE_S = 25.0
DC_SEM_DEDO = 1500.0


def entrada_do_caso(nome: str) -> tuple[np.ndarray, np.ndarray]:
    """O bruto (IR e vermelho) de um caso dos vetores; precisa do PhysioNet em cache."""
    from analise import fonte_falsa, physionet

    f = fonte_falsa.gera(physionet.carrega("s1_sit"), 30.0, VETOR_DURACAO_S)
    ir = f.bruto_ir.astype(np.float32).copy()
    vm = f.bruto_vermelho.astype(np.float32).copy()
    if nome == "sem_dedo":
        a = round(SEM_DEDO_A_PARTIR_DE_S * FS_HZ)
        rng = np.random.default_rng(27)
        ir[a:] = DC_SEM_DEDO + rng.normal(0, 4, len(ir) - a).astype(np.float32)
        vm[a:] = DC_SEM_DEDO + rng.normal(0, 4, len(vm) - a).astype(np.float32)
    return ir, vm


def gera_vetores(testes: Path | None = None) -> list[Path]:
    """Grava testes/spo2/vetores/<caso>.h: a entrada e o que o C tem que devolver."""
    from analise import vetores

    saidas = []
    for nome, descricao in CASOS:
        ir, vm = entrada_do_caso(nome)
        r = estima(ir, vm)
        arrays = {
            "ir": ir,
            "vermelho": vm,
            "valido": [x.valido for x in r],
            "spo2": [x.spo2 for x in r],
            "r": [x.r for x in r],
        }
        extra = {"testes": testes} if testes else {}
        saidas.append(
            vetores.gera_vetor("spo2", nome, arrays, tol=TOL_VETOR, descricao=descricao, **extra)
        )
    return saidas


if __name__ == "__main__":
    for caminho in gera_vetores():
        print(caminho)
