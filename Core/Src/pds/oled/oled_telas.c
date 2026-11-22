/*
 * oled: as telas e a escolha de qual mostrar. Ver oled.h. Cada tela repete a de
 * analise/src/analise/oled.py (as artboards do design), coordenada por coordenada.
 */
#include "oled/oled.h"

/* ---- Números pra texto (sem printf: o nano.specs não imprime float, e o PDS não usa stdio) --- */

/* x arredondado (o meio vai pra cima) e limitado a max; -1 se não é um número >= 0. */
static int arredonda(float x, int max)
{
    if (!(x >= 0.0f))
        return -1;
    if (x >= (float)max)
        return max;
    return (int)(x + 0.5f);
}

/* v >= 0 vira o texto com algarismos; v < 0 vira "--". buf: pelo menos 12 bytes. */
static char *numero(char *buf, int v)
{
    if (v < 0) {
        buf[0] = '-';
        buf[1] = '-';
        buf[2] = '\0';
        return buf;
    }
    char tmp[11];
    int n = 0;
    do {
        tmp[n++] = (char)('0' + v % 10);
        v /= 10;
    } while (v != 0 && n < 10);
    int i = 0;
    while (n > 0)
        buf[i++] = tmp[--n];
    buf[i] = '\0';
    return buf;
}

/* Copia s em dst a partir de i e devolve o novo i. */
static int anexa(char *dst, int i, const char *s)
{
    while (*s != '\0')
        dst[i++] = *s++;
    dst[i] = '\0';
    return i;
}

/* "<rotulo> <valor>" */
static char *rotulo_valor(char *dst, const char *rotulo, const char *valor)
{
    int i = anexa(dst, 0, rotulo);
    i = anexa(dst, i, " ");
    anexa(dst, i, valor);
    return dst;
}

/* "<valor><sufixo>", ou "--" se o valor não existe. */
static char *com_sufixo(char *dst, int v, const char *sufixo)
{
    numero(dst, v);
    if (v >= 0) {
        int n = 0;
        while (dst[n] != '\0')
            n++;
        anexa(dst, n, sufixo);
    }
    return dst;
}

/* ---- Valores que vêm do ppg_resultados_t -------------------------------------------------- */

/* As 5 barras: indice (0 a 1) x 5; sem qualidade válida, nenhuma. */
static int barras_q(const ppg_resultados_t *r)
{
    int q = r->qualidade.valido ? arredonda(r->qualidade.indice * 5.0f, 5) : 0;
    return q < 0 ? 0 : q;
}

/* O BPM da tela principal: -1 ("--") se não for válido ou, com a qualidade válida, não for usável. */
static int bpm_principal(const ppg_resultados_t *r)
{
    bool confia = r->bpm_picos.valido && (!r->qualidade.valido || r->qualidade.usavel);
    return confia ? arredonda(r->bpm_picos.bpm, 999) : -1;
}

static int bpm_valor(const ppg_bpm_t *b)
{
    return b->valido ? arredonda(b->bpm, 999) : -1;
}

static int alvo_disponivel(const ppg_resultados_t *r)
{
    return r->spo2.valido || r->respiracao.valido;
}

/* ---- Telas --------------------------------------------------------------------------------- */

void oled_topo(oled_t *o, int bpm, bool coracao, int q)
{
    char s[12];
    oled_texto_dir(o, 36, 0, numero(s, bpm), 2, true);
    if (coracao)
        oled_texto(o, 40, 0, "*", 1, true);
    oled_texto(o, 40, 8, "BPM", 1, true);
    oled_barras(o, 81, 0, 16, 7, 3, q);
}

void oled_tela_principal(oled_t *o, int bpm, bool coracao, int q)
{
    oled_limpa(o);
    oled_topo(o, bpm, coracao, q);
    oled_onda_quadro(o, 0, 17, 128, 47);
}

void oled_tela_resumo(oled_t *o, const ppg_resultados_t *r, unsigned total)
{
    char s[24], t[24];
    oled_limpa(o);
    oled_retangulo(o, 0, 0, 128, 8, true, true);
    oled_texto(o, 1, 0, "RESUMO", 1, false);
    oled_texto_dir(o, 127, 0, total >= 3u ? "2/3" : "2/2", 1, false);

    int sdnn = r->hrv.valido ? arredonda(r->hrv.sdnn_ms, 999) : -1;
    int rmssd = r->hrv.valido ? arredonda(r->hrv.rmssd_ms, 999) : -1;
    int lf_hf = r->hrv.lf_hf_valido ? arredonda(r->hrv.lf_hf * 10.0f, 999) : -1;
    int qual = r->qualidade.valido ? arredonda(r->qualidade.indice * 100.0f, 100) : -1;

    static const char *const ROTULOS[6] = {"BPM PICOS", "BPM FFT", "SDNN", "RMSSD", "LF/HF",
                                           "QUALIDADE"};
    for (int i = 0; i < 6; i++) {
        const char *valor;
        switch (i) {
        case 0: valor = numero(s, bpm_valor(&r->bpm_picos)); break;
        case 1: valor = numero(s, bpm_valor(&r->bpm_espectral)); break;
        case 2: valor = com_sufixo(s, sdnn, " MS"); break;
        case 3: valor = com_sufixo(s, rmssd, " MS"); break;
        case 4:
            if (lf_hf >= 0) { /* ponto fixo: 14 vira "1.4" */
                char a[12], b[12];
                int k = anexa(s, 0, numero(a, lf_hf / 10));
                k = anexa(s, k, ".");
                anexa(s, k, numero(b, lf_hf % 10));
                valor = s;
            } else {
                valor = numero(s, -1);
            }
            break;
        default: valor = com_sufixo(s, qual, "%"); break;
        }
        oled_texto(o, 0, 8 * (i + 1), ROTULOS[i], 1, true);
        oled_texto_dir(o, 128, 8 * (i + 1), valor, 1, true);
    }

    int spo2 = r->spo2.valido ? arredonda(r->spo2.spo2_pct, 100) : -1;
    int resp = r->respiracao.valido ? arredonda(r->respiracao.rpm, 99) : -1;
    oled_texto(o, 0, 56, rotulo_valor(s, "SPO2", numero(t, spo2)), 1, true);
    oled_texto_dir(o, 128, 56, rotulo_valor(s, "RESP", numero(t, resp)), 1, true);
}

void oled_tela_sem_dedo(oled_t *o, int q)
{
    oled_limpa(o);
    oled_topo(o, -1, false, q);
    oled_texto_centro(o, 24, "SEM DEDO", 2, true);
    oled_texto_centro(o, 48, "APOIE O DEDO E", 1, true);
    oled_texto_centro(o, 56, "FIQUE PARADO", 1, true);
}

void oled_tela_sinal_ruim(oled_t *o, int q)
{
    oled_limpa(o);
    oled_topo(o, -1, false, q);
    oled_retangulo(o, 0, 16, 128, 8, true, true);
    oled_texto_centro(o, 16, "SINAL RUIM: NAO MEXA", 1, false);
    oled_onda_quadro(o, 0, 25, 128, 39);
}

void oled_tela_alvo(oled_t *o, const ppg_resultados_t *r)
{
    char s[24], t[24];
    int spo2 = r->spo2.valido ? arredonda(r->spo2.spo2_pct, 100) : -1;
    int resp = r->respiracao.valido ? arredonda(r->respiracao.rpm, 99) : -1;
    int qual = r->qualidade.valido ? arredonda(r->qualidade.indice * 100.0f, 100) : -1;
    oled_limpa(o);
    oled_texto_dir(o, 36, 0, numero(s, spo2), 2, true);
    oled_texto(o, 40, 0, "SPO2", 1, true);
    oled_texto(o, 40, 8, "%", 1, true);
    oled_texto_dir(o, 100, 0, numero(s, resp), 2, true);
    oled_texto(o, 102, 0, "RESP", 1, true);
    oled_texto(o, 102, 8, "/MIN", 1, true);
    oled_texto(o, 0, 24, rotulo_valor(s, "BPM", numero(t, bpm_valor(&r->bpm_picos))), 1, true);
    oled_texto_dir(o, 128, 24, rotulo_valor(s, "SINAL", com_sufixo(t, qual, "%")), 1, true);
    oled_onda_quadro(o, 0, 32, 128, 32);
}

void oled_tela_inicio(oled_t *o, const oled_etapa_t etapas[3], bool aguarde)
{
    static const char *const NOMES[3] = {"MAX30102", "DECIMACAO", "FILTRO"};
    static const int LINHAS[3] = {32, 40, 48};
    static const char *const ESTADOS[3] = {"...", "OK", "ERRO"};
    oled_limpa(o);
    oled_texto_centro(o, 0, "SENSOR PPG", 2, true);
    oled_texto_centro(o, 16, "ENGG54 - UFBA", 1, true);
    for (int i = 0; i < 3; i++) {
        oled_texto(o, 0, LINHAS[i], NOMES[i], 1, true);
        oled_texto_dir(o, 128, LINHAS[i], ESTADOS[etapas[i]], 1, true);
    }
    if (aguarde)
        oled_texto_centro(o, 56, "AGUARDE", 1, true);
}

void oled_tela_erro(oled_t *o, oled_erro_t erro)
{
    static const char *const TEXTOS[2][4] = {
        {"SENSOR NAO RESPONDE", "NA I2C1 (END. 0X57)", "CONFIRA SCL SDA VIN", "E APERTE RESET"},
        {"DECIMACAO SEM FILTRO", "PARA ESSA TAXA DO", "MAX30102. VEJA A", "SERIAL E APERTE RESET"},
    };
    const char *const *t = TEXTOS[erro == OLED_ERRO_DECIMACAO ? 1 : 0];
    oled_limpa(o);
    oled_retangulo(o, 0, 0, 128, 16, true, true);
    oled_texto_centro(o, 1, "ERRO", 2, false);
    oled_texto_centro(o, 24, t[0], 1, true);
    oled_texto_centro(o, 32, t[1], 1, true);
    oled_texto_centro(o, 48, t[2], 1, true);
    oled_texto_centro(o, 56, t[3], 1, true);
}

/* ---- Rodízio ------------------------------------------------------------------------------- */

oled_tela_t oled_escolhe(const ppg_resultados_t *r, uint32_t agora_ms)
{
    if (r->qualidade.valido && !r->qualidade.dedo_presente)
        return OLED_TELA_SEM_DEDO;
    if (r->qualidade.valido && !r->qualidade.usavel)
        return OLED_TELA_SINAL_RUIM;

    uint32_t ciclo = OLED_PRINCIPAL_MS + OLED_RESUMO_MS + (alvo_disponivel(r) ? OLED_ALVO_MS : 0u);
    uint32_t fase = agora_ms % ciclo;
    if (fase < OLED_PRINCIPAL_MS)
        return OLED_TELA_PRINCIPAL;
    if (fase < OLED_PRINCIPAL_MS + OLED_RESUMO_MS)
        return OLED_TELA_RESUMO;
    return OLED_TELA_ALVO;
}

void oled_desenha(oled_t *o, const ppg_resultados_t *r, uint32_t agora_ms)
{
    /* O coração acende com um batimento novo e apaga OLED_CORACAO_MS depois. */
    const ppg_batimento_t *b = &r->ultimo_batimento;
    if (b->valido && (!o->tem_pico || b->n_pico != o->n_pico_visto)) {
        o->tem_pico = true;
        o->n_pico_visto = b->n_pico;
        o->coracao_aceso = true;
        o->coracao_t0 = agora_ms;
    }
    if (o->coracao_aceso && (uint32_t)(agora_ms - o->coracao_t0) >= OLED_CORACAO_MS)
        o->coracao_aceso = false;

    int q = barras_q(r);
    switch (oled_escolhe(r, agora_ms)) {
    case OLED_TELA_SEM_DEDO:
        oled_tela_sem_dedo(o, q);
        break;
    case OLED_TELA_SINAL_RUIM:
        oled_tela_sinal_ruim(o, q);
        break;
    case OLED_TELA_RESUMO:
        oled_tela_resumo(o, r, alvo_disponivel(r) ? 3u : 2u);
        break;
    case OLED_TELA_ALVO:
        oled_tela_alvo(o, r);
        break;
    default:
        oled_tela_principal(o, bpm_principal(r), o->coracao_aceso, q);
        break;
    }
}
