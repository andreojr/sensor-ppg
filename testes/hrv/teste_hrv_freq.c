/*
 * Teste do LF/HF no PC: a saída do C bate com a do protótipo em Python
 * (vetores gerados por `uv run python -m analise.hrv_freq --vetores`), mais
 * casos de borda conferidos aqui mesmo.
 */
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "confere.h"
#include "hrv/hrv.h"
#include "hrv/hrv_freq.h"
#include "vetores/freq_bordas.h"
#include "vetores/freq_s1_sit.h"

#define BATIMENTOS_MAX 3000u
#define PI_D 3.14159265358979

static hrv_freq_t h;  /* ~16,4 KiB: fora da pilha */
static hrv_freq_t h2; /* a conta espalhada, ao lado da de uma vez */
static int32_t obt_escreveu[BATIMENTOS_MAX];
static int32_t obt_valido[BATIMENTOS_MAX];
static float obt_lf_hf[BATIMENTOS_MAX];

static int caso(const char *nome, uint32_t n, const int32_t *valido, const int32_t *n_pico,
                const float *fracao, const int32_t *rr_valido, const float *rr_ms,
                const int32_t *esp_escreveu, const int32_t *esp_valido, const float *esp_lf_hf,
                float tol)
{
    printf("-- %s\n", nome);
    if (n > BATIMENTOS_MAX) {
        printf("vetor grande demais\n");
        return 1;
    }
    hrv_freq_init(&h);
    uint32_t validos = 0;
    for (uint32_t i = 0; i < n; i++) {
        ppg_batimento_t b = {valido[i] != 0, (uint32_t)n_pico[i], fracao[i], rr_valido[i] != 0,
                             rr_ms[i]};
        ppg_hrv_t s = {0};
        obt_escreveu[i] = hrv_freq_processa(&h, &b, &s);
        obt_valido[i] = s.lf_hf_valido;
        obt_lf_hf[i] = s.lf_hf;
        validos += s.lf_hf_valido;
    }
    printf("%u batimentos, %u saídas válidas\n", (unsigned)n, (unsigned)validos);
    return confere_int("escreveu", obt_escreveu, esp_escreveu, n)
         + confere_int("lf_hf_valido", obt_valido, esp_valido, n)
         + confere_float("lf_hf", obt_lf_hf, esp_lf_hf, n, tol);
}

static int falha(const char *msg)
{
    printf("FALHOU: %s\n", msg);
    return 1;
}

/*
 * Batimentos com RR(t) = 900 + a_lf sen(2π 0,1 t) + a_hf sen(2π 0,25 t), por
 * `duracao_s`. `pula` > 0: a cada `pula` batimentos, um some (o seguinte chega
 * com rr_valido false). Devolve a última saída.
 */
static ppg_hrv_t senoidal(float duracao_s, float a_lf, float a_hf, uint32_t pula)
{
    hrv_freq_init(&h);
    ppg_hrv_t s = {0};
    double t = 0.0;
    bool perdeu = false;
    for (uint32_t k = 0; t < duracao_s; k++) {
        double rr = 900.0 + a_lf * sin(2 * PI_D * 0.1 * t) + a_hf * sin(2 * PI_D * 0.25 * t);
        t += rr / 1000.0;
        if (pula && k % pula == pula - 1u) {
            perdeu = true;
            continue;
        }
        double x = t * PPG_FS_HZ;
        ppg_batimento_t b = {true, (uint32_t)x, (float)(x - floor(x)), k > 0 && !perdeu,
                             (float)rr};
        perdeu = false;
        hrv_freq_processa(&h, &b, &s);
    }
    return s;
}

/* Conhecido: amplitude 40 em LF e 20 em HF dá LF/HF ~ (40/20)² = 4. */
static int senoide_conhecida(void)
{
    ppg_hrv_t s = senoidal(400.0f, 40.0f, 20.0f, 0u);
    if (!s.lf_hf_valido || fabsf(s.lf_hf - 4.0f) > 0.4f)
        return falha("senoides 40/20 não deram LF/HF ~4");
    ppg_hrv_t so_hf = senoidal(400.0f, 0.0f, 20.0f, 0u);
    if (!so_hf.lf_hf_valido || so_hf.lf_hf > 0.01f)
        return falha("só HF deu LF/HF > 0,01");
    printf("senoide conhecida: %.3f (esperado ~4), só HF %.5f ok\n", (double)s.lf_hf,
           (double)so_hf.lf_hf);
    return 0;
}

/*
 * Intervalos faltando. Cada batimento perdido tira dois RR (o dele e o
 * seguinte, que chega com rr_valido false). 1 em 40 perdido (5% dos RR) muda
 * pouco o LF/HF; 1 em 20 (10%) já derruba a cobertura abaixo de 90%.
 */
static int intervalos_faltando(void)
{
    ppg_hrv_t cheio = senoidal(400.0f, 40.0f, 20.0f, 0u);
    ppg_hrv_t furado = senoidal(400.0f, 40.0f, 20.0f, 40u);
    float razao = furado.lf_hf / cheio.lf_hf;
    if (!furado.lf_hf_valido || razao < 0.9f || razao > 1.1f)
        return falha("1 em 40 perdido mudou o LF/HF mais de 10%");
    if (senoidal(400.0f, 40.0f, 20.0f, 20u).lf_hf_valido)
        return falha("1 em 20 perdido deu válido");
    printf("intervalos faltando: razão %.3f ok\n", (double)razao);
    return 0;
}

/* Janela incompleta: até 270 s de RR, inválido; logo depois, válido. */
static int janela_incompleta(void)
{
    hrv_freq_init(&h);
    ppg_hrv_t s = {0};
    uint32_t n = 0;
    for (uint32_t k = 0; k < 400u; k++) {
        n += 100u;
        ppg_batimento_t b = {true, n, 0.0f, k > 0u, 1000.0f + (k % 2u ? 30.0f : -30.0f)};
        hrv_freq_processa(&h, &b, &s);
        /* k RR somam ~k segundos */
        if (k < 268u && s.lf_hf_valido)
            return falha("janela incompleta deu válido");
        if (k >= 272u && !s.lf_hf_valido)
            return falha("janela cheia não deu válido");
    }
    printf("janela incompleta: ok\n");
    return 0;
}

/* Poucos batimentos (a cobertura não fecha), e janela vazia: inválido, sem NaN. */
static int poucos_batimentos(void)
{
    hrv_freq_init(&h);
    ppg_hrv_t s = {true, 1.0f, 2.0f, true, 9.0f};
    for (uint32_t k = 0; k < 3u; k++) {
        ppg_batimento_t b = {true, 200u * (k + 1u), 0.0f, k > 0u, 2000.0f};
        if (!hrv_freq_processa(&h, &b, &s) || s.lf_hf_valido || s.lf_hf != 0.0f)
            return falha("3 batimentos deram válido");
    }
    if (s.sdnn_ms != 1.0f || s.rmssd_ms != 2.0f || !s.valido)
        return falha("hrv_freq_processa mexeu nos campos do HRV no tempo");
    printf("poucos batimentos: ok\n");
    return 0;
}

/* Batimento inválido: devolve false, saída e estado intocados. */
static int batimento_invalido(void)
{
    senoidal(400.0f, 40.0f, 20.0f, 0u);
    uint32_t conta = h.conta, ultimo = h.ultimo_n;
    ppg_hrv_t s = {true, 1.0f, 2.0f, true, 7.0f};
    ppg_batimento_t b = {false, ultimo + 90u, 0.0f, true, 900.0f};
    if (hrv_freq_processa(&h, &b, &s) || s.lf_hf != 7.0f || h.conta != conta ||
        h.ultimo_n != ultimo)
        return falha("batimento inválido mexeu no estado ou na saída");
    printf("batimento inválido: ok\n");
    return 0;
}

/* Mesmo instante do último RR: não entra (a spline dividiria por zero). */
static int mesmo_instante(void)
{
    senoidal(400.0f, 40.0f, 20.0f, 0u);
    uint32_t conta = h.conta;
    uint32_t u = (h.inicio + conta - 1u) % HRV_FREQ_CAP; /* o mais novo, na fila circular */
    ppg_batimento_t b = {true, h.n[u], h.fracao[u], true, 900.0f};
    ppg_hrv_t s;
    hrv_freq_processa(&h, &b, &s);
    if (h.conta != conta || !s.lf_hf_valido || !isfinite(s.lf_hf))
        return falha("RR no mesmo instante entrou ou estragou a saída");
    printf("mesmo instante: ok\n");
    return 0;
}

/*
 * Reinício: n voltando reinicia. Conferir só a janela não pega a falta do
 * hrv_freq_init() no reinício: com o n menor, b->n_pico - h->n[i] dá a volta no
 * uint32_t, fica enorme e a janela esvazia sozinha. O que só o init zera é a
 * conta em andamento: ela tem que ser largada (a janela copiada era da fonte
 * de antes).
 */
static int reinicio(void)
{
    ppg_hrv_t s = senoidal(400.0f, 40.0f, 20.0f, 0u);
    if (!s.lf_hf_valido)
        return falha("não ficou válido antes do reinício");
    hrv_freq_comeca(&h);
    ppg_hrv_t p = {0};
    hrv_freq_passo(&h, &p);
    ppg_batimento_t b = {true, 10u, 0.0f, true, 900.0f};
    hrv_freq_guarda(&h, &b);
    if (h.conta != 1u)
        return falha("n voltando não reiniciou a janela");
    if (hrv_freq_calculando(&h))
        return falha("n voltando não largou a conta em andamento");
    for (uint32_t k = 0; k < HRV_FREQ_PASSOS; k++)
        if (hrv_freq_passo(&h, &p))
            return falha("a conta de antes do reinício soltou resultado");
    hrv_freq_processa(&h, &b, &s);
    if (s.lf_hf_valido)
        return falha("depois do reinício deu válido");
    hrv_freq_init(&h);
    if (h.conta != 0u || h.tem_n || hrv_freq_calculando(&h))
        return falha("hrv_freq_init não zerou");
    printf("reinício: ok\n");
    return 0;
}

/*
 * A conta espalhada dá o mesmo float da de uma vez (bit a bit), no mesmo ponto,
 * mesmo com batimentos guardados no meio da conta; e sai sempre no
 * HRV_FREQ_PASSOS-ésimo passo. A cada `cada` batimentos começa uma conta em h2 e
 * guarda os batimentos seguintes enquanto ela anda, um passo por batimento.
 */
static int espalhada_igual(const char *nome, uint32_t n, const int32_t *valido,
                           const int32_t *n_pico, const float *fracao, const int32_t *rr_valido,
                           const float *rr_ms, uint32_t cada)
{
    hrv_freq_init(&h);
    hrv_freq_init(&h2);
    ppg_hrv_t esperado = {0}, obtido = {0};
    uint32_t passos = 0, contas = 0, validas = 0;
    for (uint32_t i = 0; i < n; i++) {
        ppg_batimento_t b = {valido[i] != 0, (uint32_t)n_pico[i], fracao[i], rr_valido[i] != 0,
                             rr_ms[i]};
        ppg_hrv_t s = {0};
        bool escreveu = hrv_freq_processa(&h, &b, &s);
        if (hrv_freq_guarda(&h2, &b) != escreveu)
            return falha("hrv_freq_guarda e hrv_freq_processa discordam do batimento");
        if (hrv_freq_calculando(&h2)) {
            passos++;
            if (hrv_freq_passo(&h2, &obtido)) {
                contas++;
                validas += obtido.lf_hf_valido;
                if (passos != HRV_FREQ_PASSOS)
                    return falha("a conta espalhada não saiu em HRV_FREQ_PASSOS passos");
                if (obtido.lf_hf_valido != esperado.lf_hf_valido ||
                    memcmp(&obtido.lf_hf, &esperado.lf_hf, sizeof obtido.lf_hf) != 0) {
                    printf("%s, batimento %u: espalhada %d %.9g, de uma vez %d %.9g\n", nome,
                           (unsigned)i, obtido.lf_hf_valido, (double)obtido.lf_hf,
                           esperado.lf_hf_valido, (double)esperado.lf_hf);
                    return falha("a conta espalhada deu outro número");
                }
            }
        } else if (escreveu && i % cada == 0u) {
            esperado = s; /* o que processa() deu neste batimento */
            hrv_freq_comeca(&h2);
            passos = 0;
        }
    }
    if (contas < 10u || validas == 0u)
        return falha("poucas contas espalhadas conferidas");
    printf("espalhada %s: %u contas (%u válidas) iguais bit a bit ok\n", nome, (unsigned)contas,
           (unsigned)validas);
    return 0;
}

/* Sem hrv_freq_comeca(), o passo não faz nada; o resultado sai uma vez só. */
static int passo_sem_conta(void)
{
    senoidal(400.0f, 40.0f, 20.0f, 0u);
    ppg_hrv_t s = {true, 1.0f, 2.0f, true, 7.0f};
    if (hrv_freq_calculando(&h) || hrv_freq_passo(&h, &s) || s.lf_hf != 7.0f)
        return falha("passo sem conta mexeu na saída");
    hrv_freq_comeca(&h);
    uint32_t k = 1;
    while (!hrv_freq_passo(&h, &s))
        k++;
    if (k != HRV_FREQ_PASSOS || !s.lf_hf_valido || s.sdnn_ms != 1.0f || !s.valido)
        return falha("conta espalhada: passos ou campos errados");
    s.lf_hf = 7.0f;
    if (hrv_freq_passo(&h, &s) || s.lf_hf != 7.0f)
        return falha("passo depois do resultado mexeu na saída");
    printf("passo sem conta: ok (%u passos)\n", (unsigned)k);
    return 0;
}

/*
 * hrv_freq_comeca() no meio de uma conta recomeça: a conta velha é largada, e a
 * nova (sobre a janela de agora, com um batimento a mais) sai depois de
 * HRV_FREQ_PASSOS passos contados do segundo comeca, igual bit a bit ao
 * hrv_freq_processa() desse batimento.
 */
static int recomeca(void)
{
    senoidal(400.0f, 40.0f, 20.0f, 0u);
    h2 = h; /* a mesma janela nos dois */
    hrv_freq_comeca(&h2);
    ppg_hrv_t p = {0};
    for (uint32_t k = 0; k < 5u; k++)
        if (hrv_freq_passo(&h2, &p))
            return falha("recomeça: a primeira conta saiu cedo demais");

    /* Um batimento a mais (RR bem diferente, pra a janela mudar de verdade). */
    uint32_t u = (h.inicio + h.conta - 1u) % HRV_FREQ_CAP;
    ppg_batimento_t b = {true, h.n[u] + 130u, 0.25f, true, 1300.0f};
    ppg_hrv_t esperado = {0};
    if (!hrv_freq_processa(&h, &b, &esperado) || !esperado.lf_hf_valido)
        return falha("recomeça: o batimento a mais não deu LF/HF válido");
    hrv_freq_guarda(&h2, &b);

    hrv_freq_comeca(&h2);
    uint32_t k = 1;
    while (!hrv_freq_passo(&h2, &p) && k <= HRV_FREQ_PASSOS)
        k++;
    if (k != HRV_FREQ_PASSOS)
        return falha("recomeça: a conta não recomeçou do primeiro passo");
    if (p.lf_hf_valido != esperado.lf_hf_valido ||
        memcmp(&p.lf_hf, &esperado.lf_hf, sizeof p.lf_hf) != 0)
        return falha("recomeça: saiu a conta da janela de antes");
    printf("recomeça: ok (%u passos depois do segundo comeca)\n", (unsigned)k);
    return 0;
}

/* hrv_freq_potencias sozinha: senoide no bin k cai na banda certa. */
static int potencias(void)
{
    static float y[HRV_FREQ_N_MAX];
    const uint32_t n = HRV_FREQ_N_MAX - 1u; /* 300 s a 2 Hz */
    const uint32_t ks[] = {20u, 80u};
    for (uint32_t c = 0; c < 2u; c++) {
        for (uint32_t j = 0; j < n; j++)
            y[j] = (float)sin(2 * PI_D * ks[c] * j / (double)n);
        float lf, hf;
        hrv_freq_potencias(y, n, &lf, &hf);
        /* Senoide de amplitude 1 num bin exato: |X|² = (n/2)². */
        float certa = c == 0u ? lf : hf, outra = c == 0u ? hf : lf;
        float esperado = (float)(n / 2u) * (float)(n / 2u);
        if (fabsf(certa / esperado - 1.0f) > 1e-3f || outra > 1e-3f * esperado)
            return falha("senoide no bin caiu na banda errada");
    }
    printf("potencias: ok\n");
    return 0;
}

/* Encadeado com o HRV no tempo, como no laço principal: os dois campos saem. */
static int encadeado(void)
{
    static hrv_t ht;
    hrv_init(&ht);
    hrv_freq_init(&h);
    ppg_hrv_t s = {0};
    uint32_t n = 0;
    for (uint32_t k = 0; k < 400u; k++) {
        float rr = 900.0f + 40.0f * sinf(2.0f * 3.14159265f * 0.1f * (float)k * 0.9f);
        n += (uint32_t)(rr / 10.0f + 0.5f);
        ppg_batimento_t b = {true, n, 0.0f, k > 0u, rr};
        hrv_processa(&ht, &b, &s);
        hrv_freq_processa(&h, &b, &s);
    }
    if (!s.valido || !s.lf_hf_valido || s.lf_hf < 10.0f)
        return falha("encadeado: HRV no tempo e LF/HF não saíram juntos");
    printf("encadeado: sdnn %.1f lf_hf %.1f ok\n", (double)s.sdnn_ms, (double)s.lf_hf);
    return 0;
}

int main(void)
{
    int falhas = 0;
    falhas += caso("freq_s1_sit", FREQ_S1_SIT_VALIDO_N, freq_s1_sit_valido, freq_s1_sit_n_pico,
                   freq_s1_sit_fracao, freq_s1_sit_rr_valido, freq_s1_sit_rr_ms,
                   freq_s1_sit_escreveu, freq_s1_sit_lf_hf_valido, freq_s1_sit_lf_hf,
                   FREQ_S1_SIT_TOL);
    falhas += caso("freq_bordas", FREQ_BORDAS_VALIDO_N, freq_bordas_valido, freq_bordas_n_pico,
                   freq_bordas_fracao, freq_bordas_rr_valido, freq_bordas_rr_ms,
                   freq_bordas_escreveu, freq_bordas_lf_hf_valido, freq_bordas_lf_hf,
                   FREQ_BORDAS_TOL);
    falhas += potencias();
    falhas += senoide_conhecida();
    falhas += intervalos_faltando();
    falhas += janela_incompleta();
    falhas += poucos_batimentos();
    falhas += batimento_invalido();
    falhas += mesmo_instante();
    falhas += reinicio();
    falhas += espalhada_igual("freq_s1_sit", FREQ_S1_SIT_VALIDO_N, freq_s1_sit_valido,
                              freq_s1_sit_n_pico, freq_s1_sit_fracao, freq_s1_sit_rr_valido,
                              freq_s1_sit_rr_ms, 7u);
    falhas += espalhada_igual("freq_bordas", FREQ_BORDAS_VALIDO_N, freq_bordas_valido,
                              freq_bordas_n_pico, freq_bordas_fracao, freq_bordas_rr_valido,
                              freq_bordas_rr_ms, 5u);
    falhas += passo_sem_conta();
    falhas += recomeca();
    falhas += encadeado();
    printf(falhas ? "FALHOU (%d)\n" : "OK\n", falhas);
    return falhas ? 1 : 0;
}
