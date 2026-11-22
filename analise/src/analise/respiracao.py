"""Respiração: frequência respiratória pela banda lenta (protótipo do Core/*/pds/respiracao/).

Entra o bruto a 100 Hz (com DC, só o IR), sai ppg_respiracao_t uma vez por
segundo. O C faz a mesma conta, passo a passo; Estimador é a mesma máquina de
estados em Python, e é dele que saem os vetores de referência.

Método (ver docs/src/content/docs/modulos/respiracao.md):

  1. Média de BLOCO = 25 amostras: a linha de base a FR_HZ = 4 Hz.
  2. Passa-faixa Butterworth (IIR, 2 biquads) de BANDA_FILTRO_HZ a 4 Hz: a
     "banda lenta". A fase não importa: só a frequência é medida.
  3. Janela de JANELA_S = 60 s (240 pontos) com Hann.
  4. Goertzel numa grade de 4,8 a 31,2 rpm (0,08 a 0,52 Hz, passo 0,005 Hz),
     pico com interpolação parabólica.
  5. Qualidade: fração da potência da grade a até 0,02 Hz do pico. Só é
     válido com qualidade >= QUALIDADE_MIN e com o pico fora das pontas da
     grade: pico na ponta quer dizer que a potência continua subindo fora da
     faixa (deriva, ondas de Mayer), e não que há uma respiração ali.

A referência no PhysioNet é a respiração derivada do ECG (EDR), por dois
caminhos independentes: a arritmia sinusal (RR) e a amplitude do R. Só contam
as janelas em que os dois concordam (até 2 rpm).

Uso (da pasta analise/):

  uv run python -m analise.respiracao                  validação no PhysioNet (sit)
  uv run python -m analise.respiracao --vetores        vetores do teste e coeficientes do C
  uv run python -m analise.respiracao --confere CSV    placa x Python, no CSV da captura
  uv run python -m analise.respiracao --metronomo CSV --rpm 6   contra o metrônomo
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import numpy as np
from scipy import signal

from analise import FS_HZ, decimacao

BLOCO = 25
FR_HZ = FS_HZ / BLOCO  # 4 Hz
BANDA_FILTRO_HZ = (0.07, 0.6)  # -3 dB fora da faixa medida: 6 rpm passa inteiro
GRADE_HZ = (0.08, 0.52, 0.005)  # 4,8 a 31,2 rpm, 89 frequências: 6 e 30 rpm ficam no meio
JANELA_S = 60
N_JANELA = int(JANELA_S * FR_HZ)  # 240
PASSO = int(FR_HZ)  # uma estimativa por segundo (a cada 4 pontos lentos)
VIZINHANCA_HZ = 0.02
QUALIDADE_MIN = 0.4

RAIZ = Path(__file__).resolve().parents[3]
COEF_H = RAIZ / "Core" / "Inc" / "pds" / "respiracao" / "respiracao_coef.h"


def grade() -> np.ndarray:
    ini, fim, passo = GRADE_HZ
    return ini + passo * np.arange(round((fim - ini) / passo) + 1)


@cache
def _sos() -> tuple[tuple[float, ...], ...]:
    sos = signal.butter(2, BANDA_FILTRO_HZ, btype="band", fs=FR_HZ, output="sos")
    return tuple(tuple(s) for s in sos)


def sos() -> np.ndarray:
    return np.array(_sos())


def hann() -> np.ndarray:
    return np.hanning(N_JANELA)


def espectro(janela: np.ndarray) -> tuple[float, float]:
    """(rpm, qualidade) de uma janela de N_JANELA pontos já filtrados.

    Goertzel em cada frequência da grade; o pico é refinado pela parábola dos
    três vizinhos. Pico numa ponta da grade dá qualidade 0. Mesma conta do C.
    """
    x = (janela - janela.mean()) * hann()
    f = grade()
    n = np.arange(len(x))
    p = np.abs(np.exp(-2j * np.pi * np.outer(f / FR_HZ, n)) @ x) ** 2
    k = int(np.argmax(p))
    if k == 0 or k == len(f) - 1:
        return 60 * f[k], 0.0  # pico na ponta: não é respiração
    a, b, c = p[k - 1], p[k], p[k + 1]
    den = a - 2 * b + c
    desvio = 0.5 * (a - c) / den if den != 0 else 0.0
    qualidade = p[np.abs(f - f[k]) <= VIZINHANCA_HZ + 1e-9].sum() / p.sum()
    return 60 * (f[k] + desvio * GRADE_HZ[2]), float(qualidade)


@dataclass
class Estimador:
    """A máquina de estados do respiracao_processa(), amostra a amostra."""

    soma: float = 0.0
    no_bloco: int = 0
    ref: float | None = None
    zi: np.ndarray = field(default_factory=lambda: np.zeros((2, 2)))
    lentos: list[float] = field(default_factory=list)
    desde: int = 0

    def processa(self, ir: float) -> tuple[bool, bool, float, float]:
        """(saiu, valido, rpm, qualidade). Sai uma estimativa a cada segundo."""
        if self.ref is None:
            self.ref = ir
        self.soma += ir - self.ref
        self.no_bloco += 1
        if self.no_bloco < BLOCO:
            return False, False, 0.0, 0.0
        media = self.soma / BLOCO
        self.soma, self.no_bloco = 0.0, 0
        y, self.zi = signal.sosfilt(sos(), [media], zi=self.zi)
        self.lentos = (self.lentos + [float(y[0])])[-N_JANELA:]
        self.desde += 1
        if self.desde < PASSO:
            return False, False, 0.0, 0.0
        self.desde = 0
        if len(self.lentos) < N_JANELA:
            return True, False, 0.0, 0.0
        rpm, q = espectro(np.array(self.lentos))
        return True, q >= QUALIDADE_MIN, rpm, q


def estima(ir: np.ndarray) -> np.ndarray:
    """Roda o Estimador no sinal todo. Linhas: (amostra de entrada, valido, rpm, qualidade)."""
    e = Estimador()
    saidas = []
    for i, v in enumerate(np.asarray(ir, dtype=np.float64)):
        saiu, valido, rpm, q = e.processa(v)
        if saiu:
            saidas.append((i, valido, rpm, q))
    return np.array(saidas).reshape(-1, 4)


# ---- Validação no PhysioNet (referência: respiração derivada do ECG) ---------


def _rpm_referencia(x: np.ndarray) -> float:
    """Pico do espectro de uma série a FR_HZ (EDR), na mesma grade."""
    return espectro(x)[0]


def edr(r) -> tuple[np.ndarray, np.ndarray]:
    """Respiração do ECG a FR_HZ: arritmia sinusal (RR) e amplitude do R."""
    sos_ref = signal.butter(2, BANDA_FILTRO_HZ, btype="band", fs=FR_HZ, output="sos")
    tg = np.arange(int(r.duracao_s * FR_HZ)) / FR_HZ
    t_r = r.t_picos_ecg
    rr = np.diff(t_r)
    amp = r.ecg[r.picos_ecg]
    rsa = signal.sosfiltfilt(sos_ref, np.interp(tg, t_r[1:], rr) - rr.mean())
    amplitude = signal.sosfiltfilt(sos_ref, np.interp(tg, t_r, amp) - amp.mean())
    return rsa, amplitude


@dataclass(frozen=True)
class Janela:
    registro: str
    ref_rpm: float
    rpm: float
    qualidade: float


def avalia(r, concordancia_rpm: float = 2.0) -> list[Janela]:
    """Uma janela por estimativa (1 s), só onde as duas EDR concordam."""
    bruto = decimacao.decima(r.ir, r.fs_hz)
    saidas = estima(bruto)
    rsa, amplitude = edr(r)
    janelas = []
    for i, _, rpm, q in saidas[np.isfinite(saidas[:, 2]) & (saidas[:, 2] > 0)]:
        # A janela da estimativa: os N_JANELA pontos lentos até a amostra i.
        fim = (int(i) + 1) // BLOCO
        ini = fim - N_JANELA
        if ini < int(20 * FR_HZ) or fim > len(rsa) - int(5 * FR_HZ):
            continue  # bordas da EDR (interpolação e filtfilt)
        r1, r2 = _rpm_referencia(rsa[ini:fim]), _rpm_referencia(amplitude[ini:fim])
        if abs(r1 - r2) <= concordancia_rpm:
            janelas.append(Janela(r.nome, (r1 + r2) / 2, float(rpm), float(q)))
    return janelas


def resumo(janelas: list[Janela], qualidade_min: float = QUALIDADE_MIN) -> dict:
    e = np.array([j.rpm - j.ref_rpm for j in janelas])
    q = np.array([j.qualidade for j in janelas])
    v = q >= qualidade_min
    return {
        "janelas": len(e),
        "validas_pct": 100 * v.mean(),
        "mae_todas": float(np.mean(np.abs(e))),
        "mae_validas": float(np.mean(np.abs(e[v]))),
        "ate2_validas_pct": float(100 * np.mean(np.abs(e[v]) <= 2)),
        "ate2_todas_pct": float(100 * np.mean(np.abs(e) <= 2)),
    }


def relatorio(nomes: list[str]) -> list[Janela]:
    from analise import physionet

    todas: list[Janela] = []
    for nome in nomes:
        todas += avalia(physionet.carrega(nome))
    refs = [j.ref_rpm for j in todas]
    print(f"{len(nomes)} registros, {len(todas)} janelas de {JANELA_S} s (passo 1 s) com as duas "
          f"EDR concordando; referência de {min(refs):.0f} a {max(refs):.0f} rpm")
    print(f"{'qualidade mín.':>15s} {'válidas':>8s} {'erro médio':>11s} {'até 2 rpm':>10s}")
    for qmin in (0.0, 0.3, QUALIDADE_MIN, 0.5):
        s = resumo(todas, qmin)
        print(f"{qmin:15.1f} {s['validas_pct']:7.0f}% {s['mae_validas']:8.2f} rpm "
              f"{s['ate2_validas_pct']:9.0f}%")
    return todas


# ---- Vetores do teste e coeficientes do C -----------------------------------


def coef_h() -> str:
    s = sos().astype(np.float32)
    h = hann().astype(np.float32)
    f = grade()
    cos2 = (2 * np.cos(2 * np.pi * f / FR_HZ)).astype(np.float32)

    def tabela(nome: str, v: np.ndarray) -> list[str]:
        linhas = [f"static const float {nome}[{len(v)}] = {{"]
        for i in range(0, len(v), 6):
            linhas.append("    " + ", ".join(f"{x!s}f" for x in v[i : i + 6]) + ",")
        return linhas + ["};", ""]

    linhas = [
        "/*",
        " * respiracao_coef.h: tabelas da respiração (banda lenta).",
        (f" * Passa-faixa Butterworth {BANDA_FILTRO_HZ[0]:g} a {BANDA_FILTRO_HZ[1]:g} Hz a "
         f"{FR_HZ:g} Hz (2 biquads: b0 b1 b2 a1 a2),"),
        f" * janela de Hann de {N_JANELA} pontos e a grade do Goertzel ({len(f)} frequências,",
        f" * {f[0]:g} a {f[-1]:g} Hz).",
        " * Gerado por analise/src/analise/respiracao.py (--vetores). Não edite à mão.",
        " * Só o respiracao.c inclui este arquivo.",
        " */",
        "#ifndef PDS_RESPIRACAO_COEF_H",
        "#define PDS_RESPIRACAO_COEF_H",
        "",
        f"#define RESPIRACAO_BLOCO {BLOCO}u",
        f"#define RESPIRACAO_N_JANELA {N_JANELA}u",
        f"#define RESPIRACAO_PASSO {PASSO}u",
        f"#define RESPIRACAO_N_GRADE {len(f)}u",
        f"#define RESPIRACAO_GRADE_INI_HZ {np.float32(f[0])!s}f",
        f"#define RESPIRACAO_GRADE_PASSO_HZ {np.float32(GRADE_HZ[2])!s}f",
        f"#define RESPIRACAO_VIZINHOS {round(VIZINHANCA_HZ / GRADE_HZ[2])}u",
        f"#define RESPIRACAO_QUALIDADE_MIN {np.float32(QUALIDADE_MIN)!s}f",
        "",
        "/* Biquads em cascata: {b0, b1, b2, a1, a2}, com a0 = 1. */",
        "static const float respiracao_sos[2][5] = {",
    ]
    for b0, b1, b2, _, a1, a2 in s:
        linhas.append(f"    {{{b0!s}f, {b1!s}f, {b2!s}f, {a1!s}f, {a2!s}f}},")
    linhas += ["};", ""]
    linhas += tabela("respiracao_hann", h)
    linhas += ["/* Goertzel: 2 cos(w) de cada frequência da grade. */"]
    linhas += tabela("respiracao_cos2", cos2)
    linhas += ["#endif /* PDS_RESPIRACAO_COEF_H */", ""]
    return "\n".join(linhas)


TOL_RPM = 0.05
TOL_QUALIDADE = 1e-3


def _vetor(ir: np.ndarray) -> dict[str, np.ndarray]:
    saidas = estima(ir)
    return {"ir": ir.astype(np.float32), "amostra": saidas[:, 0].astype(np.int64),
            "valido": saidas[:, 1].astype(np.int64), "rpm": saidas[:, 2],
            "qualidade": saidas[:, 3]}


def metronomo_sintetico(rpms=(6, 10, 15), minutos: float = 2.0, semente: int = 0) -> np.ndarray:
    """Bruto a 100 Hz de quem respira no metrônomo: pulso a 72 bpm, linha de base
    modulada na frequência de cada trecho, deriva lenta e ruído."""
    rng = np.random.default_rng(semente)
    n = int(minutos * 60 * FS_HZ)
    t = np.arange(n * len(rpms)) / FS_HZ
    resp = np.concatenate([np.sin(2 * np.pi * (rpm / 60) * t[:n]) for rpm in rpms])
    pulso = np.sin(2 * np.pi * 1.2 * t) + 0.3 * np.sin(2 * np.pi * 2.4 * t + 1)
    deriva = 300 * np.sin(2 * np.pi * 0.01 * t)
    x = 100_000 + 800 * pulso + 400 * resp + deriva + rng.normal(0, 30, len(t))
    return np.round(x, 3)


def gera_vetores(testes: Path | None = None, coef: Path = COEF_H,
                 physionet_: bool = True) -> list[Path]:
    from analise import physionet, vetores

    testes = testes or vetores.TESTES
    coef.parent.mkdir(parents=True, exist_ok=True)
    coef.write_text(coef_h(), encoding="utf-8", newline="\n")
    feitos = [coef, vetores.gera_vetor(
        "respiracao", "metronomo", _vetor(metronomo_sintetico()),
        TOL_RPM, testes=testes,
        descricao="Sintético: 2 min a 6, 10 e 15 rpm (bruto a 100 Hz, só IR).")]
    if physionet_:
        r = physionet.carrega("s1_sit").recorta(30, 330)
        ir = np.round(decimacao.decima(r.ir, r.fs_hz), 3)
        feitos.append(vetores.gera_vetor(
            "respiracao", "s1_sit", _vetor(ir), TOL_RPM, testes=testes,
            descricao="s1_sit de 30 a 330 s, bruto (IR) decimado pela nossa decimação."))
    return feitos


# ---- Placa x Python (sensor real) e metrônomo -------------------------------


AQUECE_S = 20  # captura no meio: transitório do filtro, depois da janela de 60 s


def confere_placa(bruto: np.ndarray, resp_placa: np.ndarray) -> dict:
    """Roda o Estimador no bruto (IR) que a placa mandou e compara com o que ela estimou.

    bruto: colunas n, ir, vermelho a 100 Hz (o _bruto.csv da captura).
    resp_placa: colunas n (do bruto que soltou a estimativa), rpm, valido.
    Captura aberta antes do reset: fica só o que veio depois do boot, e tudo
    tem que bater. Captura no meio: a placa agrupa o bruto em blocos de BLOCO
    e solta uma estimativa a cada BLOCO * PASSO amostras desde o n = 0; o
    Python começa no primeiro n múltiplo disso (os mesmos blocos) e só compara
    depois da janela de 60 s mais AQUECE_S de transitório do filtro.
    """
    from analise.picos import depois_do_reset

    bruto = depois_do_reset(bruto)
    resp_placa = depois_do_reset(resp_placa)
    # Linha perdida na serial (no PC, não na placa): fica o maior trecho
    # contínuo, comparado como captura no meio se não começar no n = 0.
    quebras = np.flatnonzero(np.diff(bruto[:, 0]) != 1) + 1
    trechos = np.split(bruto, quebras)
    bruto = max(trechos, key=len)
    n = bruto[:, 0].astype(np.int64)
    desde_boot = bool(n[0] == 0)
    ciclo = BLOCO * PASSO
    k0 = int((-n[0]) % ciclo)  # primeiro n alinhado com os blocos da placa
    n0 = int(n[0]) + k0
    a_partir = 0 if desde_boot else n0 + (JANELA_S + AQUECE_S) * FS_HZ
    py = estima(bruto[k0:, 1])
    por_n = {n0 + int(i): (bool(v), rpm) for i, v, rpm, _ in py}
    comparadas, diferentes, pior = 0, 0, 0.0
    for nn, rpm, valido in resp_placa:
        if int(nn) not in por_n or nn < a_partir:
            continue
        v_py, rpm_py = por_n[int(nn)]
        comparadas += 1
        diferentes += bool(valido) != v_py
        if v_py and valido:
            pior = max(pior, abs(rpm - rpm_py))
    return {"comparadas": comparadas, "valido_diferente": diferentes, "erro_max_rpm": pior,
            "desde_boot": desde_boot, "lacunas": len(trechos) - 1}


def confere_metronomo(resp_placa: np.ndarray, rpm_alvo: float, descarte_s: float = 60) -> dict:
    """Estimativas válidas da placa contra o ritmo do metrônomo (descarta o 1º minuto)."""
    from analise.picos import depois_do_reset

    resp_placa = depois_do_reset(resp_placa)
    n = resp_placa[:, 0]
    ok = (resp_placa[:, 2] > 0) & (n >= n[0] + descarte_s * FS_HZ)
    rpm = resp_placa[ok, 1]
    return {"estimativas": int((n >= n[0] + descarte_s * FS_HZ).sum()), "validas": int(ok.sum()),
            "mediana_rpm": float(np.median(rpm)) if len(rpm) else float("nan"),
            "erro_medio_rpm": float(np.mean(np.abs(rpm - rpm_alvo))) if len(rpm) else float("nan")}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--vetores", action="store_true", help="gera os vetores e o respiracao_coef.h")
    p.add_argument("--confere", type=Path, help="CSV da captura (com _bruto e _respiracao)")
    p.add_argument("--metronomo", type=Path, help="CSV da captura respirando no metrônomo")
    p.add_argument("--rpm", type=float, help="ritmo do metrônomo, em respirações por minuto")
    p.add_argument("--registros", default="sit", help="sit, walk, run ou lista s1_sit,s2_sit")
    args = p.parse_args(argv)

    if args.vetores:
        for caminho in gera_vetores():
            print(caminho)
        return
    if args.confere or args.metronomo:
        base = args.confere or args.metronomo
        arq = base.with_name(base.stem + "_respiracao.csv")
        resp = np.loadtxt(arq, delimiter=",", skiprows=1, ndmin=2) if arq.exists() else np.empty((0, 3))
        if len(resp) == 0:
            raise SystemExit(f"sem linhas r, em {arq.name}: a placa não mandou estimativas")
        if args.confere:
            bruto = np.loadtxt(base.with_name(base.stem + "_bruto.csv"), delimiter=",", skiprows=1)
            r = confere_placa(bruto, resp)
            if r["comparadas"] == 0:
                raise SystemExit(
                    f"nenhuma estimativa pra comparar: no meio, o --confere precisa de mais de "
                    f"{JANELA_S + AQUECE_S} s depois do 1º bloco alinhado (capture mais ou resete a placa)"
                )
            ok = r["comparadas"] > 0 and r["valido_diferente"] == 0 and r["erro_max_rpm"] <= 0.5
            modo = "desde o boot" if r["desde_boot"] else f"no meio (depois de {JANELA_S + AQUECE_S} s)"
            if r["lacunas"]:
                print(f"{r['lacunas']} lacuna(s) no bruto (linhas perdidas na serial): "
                      "comparo o maior trecho contínuo")
            print(f"captura {modo}: {r['comparadas']} estimativas comparadas; valido diferente em "
                  f"{r['valido_diferente']}; erro máximo {r['erro_max_rpm']:.3f} rpm: "
                  f"{'OK' if ok else 'DIVERGE'}")
        if args.metronomo:
            if args.rpm is None:
                p.error("--metronomo precisa de --rpm")
            r = confere_metronomo(resp, args.rpm)
            print(f"metrônomo {args.rpm:g} rpm: {r['validas']}/{r['estimativas']} estimativas "
                  f"válidas depois do 1º minuto, mediana {r['mediana_rpm']:.1f} rpm, erro médio "
                  f"{r['erro_medio_rpm']:.2f} rpm")
        return

    if args.registros in ("sit", "walk", "run"):
        nomes = [f"s{i}_{args.registros}" for i in range(1, 23)]
    else:
        nomes = args.registros.split(",")
    relatorio(nomes)


if __name__ == "__main__":
    main()
