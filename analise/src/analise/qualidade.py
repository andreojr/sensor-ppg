"""Protótipo do detector de sinal ruim (qualidade/), validação e vetores.

Entra o bruto (saída da decimação, a 100 Hz, com DC) e sai, uma vez por
segundo, se o sinal dos últimos 2 s dá pra usar. É a mesma conta do C
(Core/Src/pds/qualidade/qualidade.c), amostra a amostra.

A janela tem 2 s (dois blocos de 1 s) e anda de 1 em 1 s. O IR passa por um
passa-altas de 1ª ordem (tira a média exponencial de 0,5 s) que deixa só a
parte que pulsa. Em cada janela, números baratos de acumular amostra a amostra:

  dc         média do bruto (IR e vermelho). Com o dedo, dezenas de milhares
             de contagens; sem o dedo, ~1500.
  maior      maior amostra dos dois canais (perto do topo do ADC = saturado).
  altura     máx - mín do IR depois do passa-altas: a altura do pulso.
  pi         índice de perfusão, altura / dc. Pequeno demais = sem pulso;
             grande demais = movimento.
  aspereza   soma dos |y[n] - y[n-1]| (y = IR passa-altas) dividida pela
             altura. Um pulso limpo sobe e desce uma vez por batimento (4 a 7
             numa janela de 2 s); ruído sobe e desce a cada amostra (> 20).
  razao      altura / altura de referência (média das últimas janelas boas).
             O pulso não dobra de altura de um segundo pro outro; o
             movimento, sim.

Janela boa = dedo presente (dc dos dois canais >= DC_MIN), sem saturação
(maior < SATURA), pi entre PI_MIN e PI_MAX, aspereza entre ASPEREZA_MIN e
ASPEREZA_MAX e razao entre RAZAO_MIN e RAZAO_MAX (se já há referência).
Aspereza abaixo de ASPEREZA_MIN = o sinal só subiu ou só desceu na janela:
deriva ou transitório (o dedo acabou de entrar), não pulso.

Ritmo: o IR passa por um passa-faixa e é guardado a 25 Hz por 4 s; a cada
janela sai o maior pico da autocorrelação normalizada nos atrasos de um
batimento (~41 a 150 bpm). Pulso se repete (ritmo perto de 1); ruído na
mesma faixa, não. Abaixo de LIMIARES.ritmo_min liga o bit SEM_RITMO.

A decisão do BPM confiável (bpm_confiavel) junta os dois testes: a tela só
mostra o BPM do picos se a qualidade diz usável, o picos diz que o ritmo dos
batimentos é regular e o último batimento é recente.

Histerese: o índice é o número de janelas boas seguidas dividido por
JANELAS_ACEITA, limitado a 1. Uma janela ruim zera o índice; usável só
depois de JANELAS_ACEITA janelas boas seguidas. Rejeita rápido, aceita
devagar. A referência só aprende com janela boa e é esquecida depois de
RUINS_ESQUECE janelas ruins seguidas (o pulso pode ter mudado de verdade).

Uso:
  uv run python -m analise.qualidade              validação no PhysioNet
  uv run python -m analise.qualidade --vetores    vetores do teste em C
  uv run python -m analise.qualidade --figura ../docs/src/assets/qualidade.png
  uv run python -m analise.qualidade --distribuicao     de onde vêm os limiares
  uv run python -m analise.qualidade --limiares-ritmo   a troca do limiar do ritmo
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from analise import FS_HZ

BLOCO = FS_HZ               # 1 s: uma saída por bloco
BLOCOS_JANELA = 2           # janela de 2 s: cabe um batimento inteiro a 30 bpm
ADC_TOPO = 262_143.0        # 2^18 - 1
SEM_DEDO = 1500.0           # nível do sensor real sem o dedo (relatório 1)

# Motivos (bits), iguais aos QUALIDADE_* do C.
SEM_DEDO_BIT = 1
SATURADO_BIT = 2
PULSO_FRACO_BIT = 4
MOVIMENTO_BIT = 8
RUIDO_BIT = 16
SEM_RITMO_BIT = 32

# Ritmo: o IR num passa-faixa de 0,5 a 4 Hz (o passa-altas de 1ª ordem deixa
# respiração e deriva demais: no PhysioNet limpo, 8,5% das janelas ficavam abaixo
# de 0,5 contra 4,1% com este), reduzido a 25 Hz, autocorrelação em 4 s.
# Butterworth de 2ª ordem (scipy butter(2, [0.5, 4], "bandpass", fs=100)) em duas
# seções b0 b1 b2 a0 a1 a2, a do passa-altas primeiro (tira o DC antes).
RITMO_SOS = (
    (1.0, -2.0, 1.0, 1.0, -1.9585309426687274, 0.9597079331261205),
    (0.01043241337109341, 0.02086482674218683, 0.01043241337109341,
     1.0, -1.717844586580564, 0.7634885625932664),
)
RITMO_DECIMA = 4           # 100 -> 25 Hz (média de 4)
RITMO_N = 100              # 4 s a 25 Hz
RITMO_ATRASO_MIN = 10      # 0,4 s: 150 bpm
RITMO_ATRASO_MAX = 37      # 1,48 s: ~41 bpm


@dataclass(frozen=True)
class Limiares:
    """Parâmetros (os padrões são os de Core/Inc/pds/qualidade/qualidade.h)."""

    alfa: float = 0.02          # passa-altas: 1 / (0,5 s x 100 Hz), corte ~0,32 Hz
    dc_min: float = 10_000.0    # ~média geométrica de 1500 (sem dedo) e 65 mil
    satura: float = 250_000.0   # ~95% do topo do ADC de 18 bits
    pi_min: float = 0.0005
    pi_max: float = 0.05
    aspereza_min: float = 1.5
    aspereza_max: float = 12.0
    razao_min: float = 0.4
    razao_max: float = 2.0
    peso_ref: float = 0.25      # a referência anda 1/4 do caminho a cada janela boa
    janelas_aceita: int = 3
    ruins_esquece: int = 10
    ritmo_min: float = 0.45     # com o picos como 2º teste (etapa 3); ver a doc


LIMIARES = Limiares()


@dataclass
class Saida:
    """Uma saída do detector (uma por segundo, depois da primeira janela)."""

    n: int                  # n da última amostra da janela
    valido: bool
    dedo_presente: bool
    indice: float
    usavel: bool
    motivo: int             # 0 = janela boa
    dc_ir: float
    pi: float
    aspereza: float
    razao: float            # 0 se ainda não há referência
    ritmo: float = 0.0      # 0 se ainda não há 4 s de sinal


@dataclass
class _Bloco:
    soma_ir: float = 0.0
    soma_vm: float = 0.0
    maior: float = -math.inf   # maior amostra dos dois canais (bruto)
    min_y: float = math.inf    # y = IR depois do passa-altas
    max_y: float = -math.inf
    tv_y: float = 0.0          # soma de |y[n] - y[n-1]|


@dataclass
class Qualidade:
    """Estado do detector: o espelho do qualidade_t do C."""

    lim: Limiares = LIMIARES
    tem_n: bool = False
    prox_n: int = 0
    media: float = 0.0         # média exponencial do IR (o que o passa-altas tira)
    ultimo_y: float = 0.0
    conta: int = 0
    atual: _Bloco = field(default_factory=_Bloco)
    anterior: _Bloco | None = None
    boas: int = 0              # janelas boas seguidas
    ruins: int = 0             # janelas ruins seguidas
    tem_ref: bool = False
    ref: float = 0.0           # altura de referência
    x0: float = 0.0            # 1ª amostra desde o reinício (o filtro parte do zero)
    z: list[float] = field(default_factory=lambda: [0.0] * 4)  # estados das 2 seções
    anel: list[float] = field(default_factory=lambda: [0.0] * RITMO_N)  # y a 25 Hz
    pos: int = 0
    cheio: int = 0
    soma4: float = 0.0
    conta4: int = 0
    foto: list[float] | None = None  # os 4 s do fim do bloco anterior, do mais antigo

    def reinicia(self) -> None:
        self.__init__(self.lim)

    def processa(self, n: int, ir: float, vm: float) -> Saida | None:
        """Uma amostra. Devolve a saída no fim de cada bloco (com janela cheia)."""
        if not (math.isfinite(ir) and math.isfinite(vm)):
            self.reinicia()
            return None
        if self.tem_n and n != self.prox_n:  # amostra perdida ou n voltou: começa de novo
            self.reinicia()
        if not self.tem_n:
            self.media = ir
            self.x0 = ir
        self.media += self.lim.alfa * (ir - self.media)
        y = ir - self.media
        b = self.atual
        if self.tem_n:
            b.tv_y += abs(y - self.ultimo_y)
        self.tem_n, self.prox_n, self.ultimo_y = True, n + 1, y
        b.soma_ir += ir
        b.soma_vm += vm
        b.maior = max(b.maior, ir, vm)
        b.min_y = min(b.min_y, y)
        b.max_y = max(b.max_y, y)
        self.soma4 += self._passa_faixa(ir - self.x0)
        self.conta4 += 1
        if self.conta4 == RITMO_DECIMA:
            self.anel[self.pos] = self.soma4 / RITMO_DECIMA
            self.pos = (self.pos + 1) % RITMO_N
            self.cheio = min(self.cheio + 1, RITMO_N)
            self.soma4, self.conta4 = 0.0, 0
        self.conta += 1
        if self.conta < BLOCO:
            return None

        self.conta = 0
        ritmo = ritmo_de(np.asarray(self.foto)) if self.foto is not None else None
        self.foto = (self.anel[self.pos:] + self.anel[:self.pos]
                     if self.cheio == RITMO_N else None)
        anterior, self.anterior, self.atual = self.anterior, b, _Bloco()
        if anterior is None:  # janela ainda não encheu
            return None
        return self._janela(n, anterior, b, ritmo)

    def _passa_faixa(self, x: float) -> float:
        """As duas seções do RITMO_SOS em forma direta II transposta."""
        for i, (b0, b1, b2, _, a1, a2) in enumerate(RITMO_SOS):
            z1, z2 = self.z[2 * i], self.z[2 * i + 1]
            y = b0 * x + z1
            self.z[2 * i] = b1 * x - a1 * y + z2
            self.z[2 * i + 1] = b2 * x - a2 * y
            x = y
        return x

    def _janela(self, n: int, a: _Bloco, b: _Bloco, ritmo: float | None) -> Saida:
        lim = self.lim
        total = BLOCO * BLOCOS_JANELA
        dc_ir = (a.soma_ir + b.soma_ir) / total
        dc_vm = (a.soma_vm + b.soma_vm) / total
        altura = max(a.max_y, b.max_y) - min(a.min_y, b.min_y)
        maior = max(a.maior, b.maior)
        dedo = dc_ir >= lim.dc_min and dc_vm >= lim.dc_min
        pi = altura / dc_ir if dc_ir > 0 else 0.0
        aspereza = (a.tv_y + b.tv_y) / altura if altura > 0 else 0.0
        razao = altura / self.ref if self.tem_ref else 0.0

        motivo = 0
        if not dedo:
            motivo |= SEM_DEDO_BIT
        if maior >= lim.satura:
            motivo |= SATURADO_BIT
        if dedo:
            if pi < lim.pi_min or (self.tem_ref and razao < lim.razao_min):
                motivo |= PULSO_FRACO_BIT
            if pi > lim.pi_max or razao > lim.razao_max or aspereza < lim.aspereza_min:
                motivo |= MOVIMENTO_BIT
            if aspereza > lim.aspereza_max:
                motivo |= RUIDO_BIT
            if ritmo is None or ritmo < lim.ritmo_min:
                motivo |= SEM_RITMO_BIT

        if motivo:
            self.boas = 0
            self.ruins = min(self.ruins + 1, lim.ruins_esquece)
            if self.ruins >= lim.ruins_esquece:
                self.tem_ref = False
        else:
            self.boas = min(self.boas + 1, lim.janelas_aceita)
            self.ruins = 0
            self.ref = self.ref + lim.peso_ref * (altura - self.ref) if self.tem_ref else altura
            self.tem_ref = True
        indice = self.boas / lim.janelas_aceita
        usavel = dedo and self.boas >= lim.janelas_aceita
        return Saida(n, True, dedo, indice, usavel, motivo, dc_ir, pi, aspereza, razao,
                     0.0 if ritmo is None else ritmo)


def ritmo_de(z: np.ndarray) -> float:
    """Maior autocorrelação normalizada de z (sem a média) nos atrasos de um batimento."""
    z = np.asarray(z, dtype=float)
    z = z - z.mean()
    e = float(z @ z)
    if e == 0.0:
        return 0.0
    return max(float(z[k:] @ z[:-k]) / e for k in range(RITMO_ATRASO_MIN, RITMO_ATRASO_MAX + 1))


# ---- A decisão do BPM confiável (etapa 3) -----------------------------------------

# O último batimento vale por 3 s: o "p," sai ~1,3 s depois do pulso e, a 40 bpm,
# o RR é 1,5 s; com menos que isso a tela piscaria a cada batimento lento.
BATIMENTO_VALE = 3 * FS_HZ


def bpm_confiavel(usavel: bool, bpm_valido: bool, tem_batimento: bool, n: int,
                  n_pico: int) -> bool:
    """A tela mostra o BPM do picos só se a qualidade e o picos concordam e o último
    batimento é recente. Idade em uint32, como no C: certa na volta do contador, e um
    n_pico à frente de n (anomalia) dá idade enorme e bloqueia."""
    idade = (n - n_pico) % 2**32
    return usavel and bpm_valido and tem_batimento and idade <= BATIMENTO_VALE


# O último julgamento da qualidade vale por 2 s: sai um por segundo, então mais
# velho que isso quer dizer que ela recomeçou (n pulou, NaN) e ainda não julgou.
JULGAMENTO_VALE = 2 * FS_HZ


def batimento_usavel(usavel: bool, tem_julgamento: bool, n_julgamento: int, n: int) -> bool:
    """O RR de um batimento que sai agora (amostra n) entra no HRV só se o último
    julgamento da qualidade (na amostra n_julgamento) disse usável e é recente.

    O picos solta o batimento ~1,3 s depois do pulso, e a qualidade julga a cada 1 s
    os 2 s anteriores: o último julgamento cobre o pulso. Usável já exige 3 janelas
    boas seguidas, então cobre também o começo do RR (até 1,5 s antes). Idade em
    uint32, como no C."""
    idade = (n - n_julgamento) % 2**32
    return usavel and tem_julgamento and idade <= JULGAMENTO_VALE


def roda(ir: np.ndarray, vm: np.ndarray, n: np.ndarray | None = None,
         lim: Limiares = LIMIARES) -> list[Saida]:
    """Passa o sinal todo pelo detector e devolve as saídas."""
    q = Qualidade(lim)
    n = np.arange(len(ir)) if n is None else n
    saidas = []
    for k, a, b in zip(n.tolist(), np.asarray(ir, float).tolist(), np.asarray(vm, float).tolist()):
        s = q.processa(k, a, b)
        if s is not None:
            saidas.append(s)
    return saidas


# ---- Sinais degradados de propósito ---------------------------------------------


def tendencia(x: np.ndarray) -> np.ndarray:
    """Parte lenta do sinal (< 0,3 Hz: respiração e deriva), sem o pulso."""
    from scipy.signal import butter, sosfiltfilt

    return sosfiltfilt(butter(4, 0.3, fs=FS_HZ, output="sos"), x)


def degrada(tipo: str, ir: np.ndarray, vm: np.ndarray, rng: np.random.Generator,
            forca: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Fabrica um trecho ruim a partir de um trecho real a 100 Hz.

    ausente      nível do sensor real sem dedo (~1500) com ruído de poucas contagens.
    sem_pulso    só a tendência lenta, sem o pulso (dedo apertado demais, objeto).
    ruido        ruído branco de desvio = forca x desvio do pulso.
    saturado     ganho que leva o DC pra perto do topo; corta em 262143.
    sem_ritmo    tendência + ruído filtrado de 0,7 a 3,5 Hz com o desvio do pulso
                 (x forca): altura e aspereza de pulso, sem se repetir.
    movimento    solavancos (meio seno de 0,2 a 0,8 s) de altura forca x altura do
                 pulso, um a cada ~1,5 s, para cima ou para baixo.
    """
    m = len(ir)
    t_ir, t_vm = tendencia(ir), tendencia(vm)
    ac_ir, ac_vm = ir - t_ir, vm - t_vm
    if tipo == "ausente":
        return (SEM_DEDO + rng.normal(0, 5, m), SEM_DEDO + rng.normal(0, 5, m))
    if tipo == "sem_pulso":
        return t_ir + rng.normal(0, 2, m), t_vm + rng.normal(0, 2, m)
    if tipo == "ruido":
        return (ir + rng.normal(0, forca * ac_ir.std(), m),
                vm + rng.normal(0, forca * ac_vm.std(), m))
    if tipo == "saturado":
        g = 0.99 * ADC_TOPO / t_ir.mean()
        return np.minimum(ir * g, ADC_TOPO), np.minimum(vm * g, ADC_TOPO)
    if tipo == "sem_ritmo":
        from scipy.signal import butter, sosfiltfilt

        sos = butter(4, [0.7, 3.5], "bandpass", fs=FS_HZ, output="sos")
        z_ir = sosfiltfilt(sos, rng.normal(size=m))
        z_vm = sosfiltfilt(sos, rng.normal(size=m))
        return (t_ir + forca * ac_ir.std() * z_ir / z_ir.std(),
                t_vm + forca * ac_vm.std() * z_vm / z_vm.std())
    if tipo == "movimento":
        art = np.zeros(m)
        i = int(rng.integers(0, FS_HZ))
        while i < m:
            dur = int(rng.integers(FS_HZ // 5, 4 * FS_HZ // 5))
            sinal = rng.choice((-1.0, 1.0))
            trecho = np.sin(np.pi * np.arange(dur) / dur)[: m - i]
            art[i: i + dur] += sinal * trecho
            i += dur + int(rng.integers(FS_HZ // 2, 3 * FS_HZ // 2))
        altura_ir = np.percentile(ac_ir, 95) - np.percentile(ac_ir, 5)
        altura_vm = np.percentile(ac_vm, 95) - np.percentile(ac_vm, 5)
        return ir + forca * altura_ir * art, vm + forca * altura_vm * art
    raise ValueError(f"tipo desconhecido: {tipo}")


def no_sensor(ir: np.ndarray, vm: np.ndarray, dc_ir: float = 130_000.0,
              dc_vm: float = 137_000.0) -> tuple[np.ndarray, np.ndarray]:
    """O mesmo trecho no nível do nosso sensor com dedo (relatório 1), pulso relativo igual."""
    return ir * (dc_ir / ir.mean()), vm * (dc_vm / vm.mean())


# ---- Validação no PhysioNet ------------------------------------------------------

TIPOS = ("ausente", "sem_pulso", "ruido", "saturado", "movimento", "sem_ritmo")


def registro_100hz(nome: str) -> tuple[np.ndarray, np.ndarray]:
    """IR e vermelho do registro, decimados a 100 Hz como na placa."""
    from analise import decimacao, physionet

    r = physionet.carrega(nome)
    return decimacao.decima(r.ir, r.fs_hz), decimacao.decima(r.vermelho, r.fs_hz)


@dataclass
class Taxas:
    janelas: int = 0
    boas: int = 0       # janelas com motivo 0
    usaveis: int = 0    # saídas com usavel true

    def soma(self, saidas: list[Saida]) -> None:
        self.janelas += len(saidas)
        self.boas += sum(s.motivo == 0 for s in saidas)
        self.usaveis += sum(s.usavel for s in saidas)

    @property
    def p_boas(self) -> float:
        return self.boas / max(self.janelas, 1)

    @property
    def p_usaveis(self) -> float:
        return self.usaveis / max(self.janelas, 1)


DEFEITOS = (("ausente", 1.0), ("sem_pulso", 1.0), ("saturado", 1.0), ("ruido", 0.5),
            ("ruido", 1.0), ("ruido", 2.0), ("movimento", 1.0), ("movimento", 2.0),
            ("movimento", 4.0), ("sem_ritmo", 1.0))


def rotulo(tipo: str, forca: float) -> str:
    return f"{tipo} x{forca:g}" if tipo in ("ruido", "movimento") else tipo


def avalia(nomes: list[str], trecho_s: int = 20, semente: int = 19,
           lim: Limiares = LIMIARES) -> dict[str, Taxas]:
    """Taxas no limpo e nos defeitos fabricados.

    Limpo: o registro inteiro, no nível do PhysioNet e no do nosso sensor.
    Defeito: o registro em trechos de trecho_s; em cada um, a primeira metade
    fica limpa (o detector aprende a referência) e a segunda vira o defeito.
    Contam só as janelas inteiras dentro do defeito.
    """
    rng = np.random.default_rng(semente)
    taxas: dict[str, Taxas] = {}
    m, meio = trecho_s * FS_HZ, trecho_s * FS_HZ // 2
    for nome in nomes:
        ir, vm = registro_100hz(nome)
        taxas.setdefault("limpo", Taxas()).soma(roda(ir, vm, lim=lim))
        taxas.setdefault("limpo, nível do sensor", Taxas()).soma(roda(*no_sensor(ir, vm), lim=lim))
        for k in range(len(ir) // m):
            a, b = ir[k * m: (k + 1) * m], vm[k * m: (k + 1) * m]
            for tipo, forca in DEFEITOS:
                da, db = degrada(tipo, a[meio:], b[meio:], rng, forca)
                saidas = roda(np.r_[a[:meio], da], np.r_[b[:meio], db], lim=lim)
                dentro = [s for s in saidas if s.n - BLOCO * BLOCOS_JANELA + 1 >= meio]
                taxas.setdefault(rotulo(tipo, forca), Taxas()).soma(dentro)
            for tipo, forca in (("sem_pulso", 1.0), ("movimento", 4.0)):  # sem referência
                saidas = roda(*degrada(tipo, a, b, rng, forca), lim=lim)
                taxas.setdefault(rotulo(tipo, forca) + ", sem limpo antes", Taxas()).soma(saidas)
    return taxas


def latencias(nomes: list[str], semente: int = 7) -> dict[str, list[float]]:
    """Quanto tempo o detector leva pra reagir, em segundos.

    entra      dedo entra (rampa de 0,5 s a partir de ~1500) até a 1ª saída usável.
    detecta    início do defeito (movimento x4, ruído x1, sem pulso) até a 1ª saída
               não usável, partindo de sinal usável.
    volta      fim do movimento x4 até a 1ª saída usável de novo.
    """
    rng = np.random.default_rng(semente)
    lat: dict[str, list[float]] = {}

    def primeira(saidas: list[Saida], desde: int, usavel: bool) -> float:
        k = next((s.n for s in saidas if s.n >= desde and s.usavel == usavel), None)
        return math.nan if k is None else (k + 1 - desde) / FS_HZ

    for nome in nomes:
        ir, vm = registro_100hz(nome)
        for k in range(1, len(ir) // (40 * FS_HZ)):
            a, b = ir[k * 40 * FS_HZ: (k + 1) * 40 * FS_HZ], vm[k * 40 * FS_HZ: (k + 1) * 40 * FS_HZ]
            m = 10 * FS_HZ
            f = np.r_[np.zeros(m - FS_HZ // 2), np.linspace(0, 1, FS_HZ // 2), np.ones(len(a) - m)]
            entra = roda(SEM_DEDO + f * (a - SEM_DEDO), SEM_DEDO + f * (b - SEM_DEDO))
            lat.setdefault("entra", []).append(primeira(entra, m, True))
            for tipo, forca in (("movimento", 4.0), ("ruido", 1.0), ("sem_pulso", 1.0)):
                da, db = degrada(tipo, a[20 * FS_HZ: 25 * FS_HZ], b[20 * FS_HZ: 25 * FS_HZ],
                                 rng, forca)
                x, y = a.copy(), b.copy()
                x[20 * FS_HZ: 25 * FS_HZ], y[20 * FS_HZ: 25 * FS_HZ] = da, db
                saidas = roda(x, y)
                if not any(s.usavel for s in saidas if 18 * FS_HZ <= s.n < 20 * FS_HZ):
                    continue  # não estava usável antes do defeito
                lat.setdefault(f"detecta {rotulo(tipo, forca)}", []).append(
                    primeira(saidas, 20 * FS_HZ, False))
                if tipo == "movimento":
                    lat.setdefault("volta depois do movimento", []).append(
                        primeira(saidas, 25 * FS_HZ, True))
    return lat


def relatorio(nomes: list[str]) -> dict[str, Taxas]:
    taxas = avalia(nomes)
    print(f"{len(nomes)} registros; janelas de 2 s, uma por segundo")
    print(f"{'caso':28s} {'janelas':>8s} {'janela boa':>11s} {'usável':>8s}")
    for rotulo, t in taxas.items():
        print(f"{rotulo:28s} {t.janelas:8d} {100 * t.p_boas:10.1f}% {100 * t.p_usaveis:7.1f}%")
    print(f"\n{'latência (s)':28s} {'casos':>8s} {'mediana':>8s} {'pior':>6s} {'perdeu':>7s}")
    for rotulo_, v in latencias(nomes).items():
        a = np.array(v)
        ok = a[np.isfinite(a)]
        print(f"{rotulo_:28s} {len(a):8d} {np.median(ok):8.1f} {ok.max():6.1f} "
              f"{np.sum(~np.isfinite(a)):7d}")
    return taxas


# ---- Vetores do teste em C ------------------------------------------------------


def _arrays(saidas: list[Saida], entrada: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    return {
        **entrada,
        "saida_n": np.array([s.n for s in saidas]),
        "saida_valido": np.array([s.valido for s in saidas], dtype=np.int32),
        "saida_dedo": np.array([s.dedo_presente for s in saidas], dtype=np.int32),
        "saida_usavel": np.array([s.usavel for s in saidas], dtype=np.int32),
        "saida_motivo": np.array([s.motivo for s in saidas]),
        "saida_indice": np.array([s.indice for s in saidas]),
        "saida_dc": np.array([s.dc_ir for s in saidas]),
        "saida_pi": np.array([s.pi for s in saidas]),
        "saida_aspereza": np.array([s.aspereza for s in saidas]),
        "saida_razao": np.array([s.razao for s in saidas]),
        "saida_ritmo": np.array([s.ritmo for s in saidas]),
    }


def vetor_physionet(nome: str = "s1_sit", inicio_s: int = 60, dur_s: int = 30):
    """Caso 1: 30 s limpos de s1_sit, no nível do nosso sensor."""
    ir, vm = registro_100hz(nome)
    a, b = inicio_s * FS_HZ, (inicio_s + dur_s) * FS_HZ
    ir, vm = no_sensor(ir[a:b], vm[a:b])
    ir, vm = ir.astype(np.float32), vm.astype(np.float32)
    n = np.arange(len(ir))
    return _arrays(roda(ir, vm, n), {"n": n, "ir": ir, "vermelho": vm})


def sinal_bordas(nome: str = "s1_sit", semente: int = 5):
    """Caso 2: sequência montada com os defeitos e as bordas.

    sem dedo 4 s, dedo entra (rampa de 0,5 s), limpo 10 s, saturado 4 s,
    limpo 6 s, ruído 4 s, limpo 6 s, movimento 4 s, limpo 6 s, sem pulso 4 s,
    limpo 5 s, dedo sai (rampa 0,5 s) e 4 s sem dedo. No meio do primeiro
    trecho limpo, o n pula 50 amostras (reinício); n começa em 1000.
    """
    rng = np.random.default_rng(semente)
    ir, vm = registro_100hz(nome)
    ir, vm = no_sensor(ir[120 * FS_HZ: 200 * FS_HZ], vm[120 * FS_HZ: 200 * FS_HZ])
    partes_ir, partes_vm, pos = [], [], 0

    def pega(seg: float, tipo: str | None = None, forca: float = 1.0) -> None:
        nonlocal pos
        m = int(seg * FS_HZ)
        a, b = ir[pos: pos + m], vm[pos: pos + m]
        pos += m
        if tipo:
            a, b = degrada(tipo, a, b, rng, forca)
        partes_ir.append(a)
        partes_vm.append(b)

    def rampa(entra: bool) -> None:
        nonlocal pos
        m = FS_HZ // 2
        f = np.linspace(0, 1, m) if entra else np.linspace(1, 0, m)
        partes_ir.append(SEM_DEDO + f * (ir[pos: pos + m] - SEM_DEDO))
        partes_vm.append(SEM_DEDO + f * (vm[pos: pos + m] - SEM_DEDO))
        pos += m

    pega(4, "ausente")
    rampa(True)
    pega(10)
    pega(4, "saturado")
    pega(6)
    pega(4, "ruido", 2)
    pega(6)
    pega(4, "movimento", 4)
    pega(6)
    pega(4, "sem_pulso")
    pega(5)
    rampa(False)
    pega(4, "ausente")
    x_ir = np.concatenate(partes_ir).astype(np.float32)
    x_vm = np.concatenate(partes_vm).astype(np.float32)
    n = 1000 + np.arange(len(x_ir))
    n[int(9.5 * FS_HZ):] += 50  # amostras perdidas: o detector reinicia
    return n, x_ir, x_vm


def vetor_bordas():
    n, ir, vm = sinal_bordas()
    return _arrays(roda(ir, vm, n), {"n": n, "ir": ir, "vermelho": vm})


def gera_vetores(testes: Path | None = None) -> list[Path]:
    from analise import vetores

    testes = testes or vetores.TESTES
    return [
        vetores.gera_vetor("qualidade", "physionet", vetor_physionet(), tol=1e-3, testes=testes,
                           descricao="s1_sit de 60 a 90 s, no nível do sensor (IR 130 mil)."),
        vetores.gera_vetor("qualidade", "bordas", vetor_bordas(), tol=1e-3, testes=testes,
                           descricao="Dedo entra e sai, saturação, ruído, movimento, sem "
                                     "pulso e n que pula (ver sinal_bordas())."),
    ]


def distribuicao(nomes: list[str]) -> None:
    """De onde vêm os limiares: pi, aspereza e razão em todas as janelas do limpo."""
    pi, asp, raz, rit = [], [], [], []
    for nome in nomes:
        for s in roda(*registro_100hz(nome)):
            pi.append(s.pi)
            asp.append(s.aspereza)
            if s.razao > 0:
                raz.append(s.razao)
            if s.ritmo > 0:
                rit.append(s.ritmo)
    pi, asp, raz, rit = np.array(pi), np.array(asp), np.array(raz), np.array(rit)
    print(f"{len(pi)} janelas do limpo em {len(nomes)} registros")
    print(f"pi: min {100 * pi.min():.2f}%, p99 {100 * np.percentile(pi, 99):.2f}%, "
          f"max {100 * pi.max():.2f}%")
    print(f"aspereza: min {asp.min():.2f}, max {asp.max():.2f}")
    print(f"razão: p99,9 {np.percentile(raz, 99.9):.2f}")
    print(f"razão: p1 {np.percentile(raz, 1):.2f}")
    for lim in (LIMIARES.ritmo_min, 0.5):
        print(f"ritmo: {np.mean(rit < lim):.1%} das janelas abaixo de {lim:g}")


def limiares_ritmo(nomes: list[str], limiares=(0.40, 0.45, 0.50, 0.55, 0.60)) -> None:
    """A troca do limiar do ritmo: falso alarme no limpo contra o sem ritmo que passa."""
    print(f"{'ritmo >=':>9s} {'limpo ruim':>11s} {'limpo usável':>13s} {'sem ritmo usável':>17s}")
    for t in limiares:
        taxas = avalia(nomes, lim=replace(LIMIARES, ritmo_min=t))
        limpo, sem = taxas["limpo"], taxas["sem_ritmo"]
        print(f"{t:9.2f} {100 * (1 - limpo.p_boas):10.1f}% {100 * limpo.p_usaveis:12.1f}% "
              f"{100 * sem.p_usaveis:16.1f}%")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--vetores", action="store_true", help="gera os vetores do teste em C")
    p.add_argument("--figura", type=Path, help="grava a figura do vetor bordas")
    p.add_argument("--distribuicao", action="store_true",
                   help="pi, aspereza e razão no limpo (de onde vêm os limiares)")
    p.add_argument("--limiares-ritmo", action="store_true",
                   help="falso alarme e acerto pra cada limiar do ritmo (alguns minutos)")
    p.add_argument("registros", nargs="*", help="padrão: os 22 registros sit")
    args = p.parse_args(argv)
    if args.limiares_ritmo:
        limiares_ritmo(args.registros or [f"s{i}_sit" for i in range(1, 23)])
        return
    if args.distribuicao:
        distribuicao(args.registros or [f"s{i}_sit" for i in range(1, 23)])
        return
    if args.figura:
        from analise import plota_qualidade

        plota_qualidade.figura(args.figura)
        return
    if args.vetores:
        for caminho in gera_vetores():
            print(caminho)
        return
    relatorio(args.registros or [f"s{i}_sit" for i in range(1, 23)])


if __name__ == "__main__":
    main()
