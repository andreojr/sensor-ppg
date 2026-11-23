/*
 * oled: primitivas, onda e controle de páginas. Ver oled.h. As telas estão em oled_telas.c.
 * As contas da onda são as de analise/src/analise/oled.py, na mesma ordem e em float.
 */
#include "oled/oled.h"

#include <math.h>
#include <string.h>

#include "oled/oled_fonte.h"

#define ESCALA_ENCOLHE 0.05f /* quanto a escala da onda volta pro lado a cada quadro */
#define ONDA_FOLGA 0.08f     /* folga em cima e embaixo da onda */

void oled_init(oled_t *o)
{
    memset(o, 0, sizeof *o);
    o->nunca_enviada = 0xFFu;
    o->ultima_pagina = OLED_PAGINAS - 1u; /* a busca começa na página 0 */
}

void oled_invalida(oled_t *o)
{
    o->nunca_enviada = 0xFFu;
}

void oled_limpa(oled_t *o)
{
    memset(o->fb, 0, sizeof o->fb);
}

void oled_pixel(oled_t *o, int x, int y, bool v)
{
    if (x < 0 || y < 0 || x >= (int)OLED_W || y >= (int)OLED_H)
        return;
    uint8_t bit = (uint8_t)(1u << (y & 7));
    if (v)
        o->fb[y >> 3][x] |= bit;
    else
        o->fb[y >> 3][x] &= (uint8_t)~bit;
}

void oled_retangulo(oled_t *o, int x, int y, int w, int h, bool cheio, bool v)
{
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            if (cheio || i == 0 || j == 0 || i == w - 1 || j == h - 1)
                oled_pixel(o, x + i, y + j, v);
}

static int abs_int(int x)
{
    return x < 0 ? -x : x;
}

void oled_linha(oled_t *o, int x0, int y0, int x1, int y1)
{
    int dx = abs_int(x1 - x0), sx = x0 < x1 ? 1 : -1;
    int dy = -abs_int(y1 - y0), sy = y0 < y1 ? 1 : -1;
    int e = dx + dy;
    for (;;) {
        oled_pixel(o, x0, y0, true);
        if (x0 == x1 && y0 == y1)
            break;
        int e2 = 2 * e;
        if (e2 >= dy) {
            e += dy;
            x0 += sx;
        }
        if (e2 <= dx) {
            e += dx;
            y0 += sy;
        }
    }
}

/* As 7 linhas da letra; minúscula vira maiúscula e o que não está na fonte vira '?'. */
static const uint8_t *glifo(char c)
{
    if (c >= 'a' && c <= 'z')
        c = (char)(c - 'a' + 'A');
    unsigned interrogacao = 0;
    for (unsigned i = 0; i < OLED_FONTE_N; i++) {
        if (OLED_FONTE_CHAVES[i] == c)
            return OLED_FONTE[i];
        if (OLED_FONTE_CHAVES[i] == '?')
            interrogacao = i;
    }
    return OLED_FONTE[interrogacao];
}

static int comprimento(const char *s)
{
    int n = 0;
    while (s[n] != '\0')
        n++;
    return n;
}

int oled_texto(oled_t *o, int x, int y, const char *s, int k, bool v)
{
    for (; *s != '\0'; s++) {
        const uint8_t *g = glifo(*s);
        for (int r = 0; r < 7; r++)
            for (int c = 0; c < 5; c++)
                if ((g[r] >> (4 - c)) & 1u)
                    oled_retangulo(o, x + c * k, y + r * k, k, k, true, v);
        x += 6 * k;
    }
    return x;
}

int oled_texto_dir(oled_t *o, int x_dir, int y, const char *s, int k, bool v)
{
    return oled_texto(o, x_dir - comprimento(s) * 6 * k + k, y, s, k, v);
}

int oled_texto_centro(oled_t *o, int y, const char *s, int k, bool v)
{
    int w = comprimento(s) * 6 * k - k;
    return oled_texto(o, ((int)OLED_W - w) / 2, y, s, k, v);
}

void oled_barras(oled_t *o, int x, int y, int alt, int w, int gap, int q)
{
    static const int ALTURAS[5] = {4, 7, 10, 13, 16};
    for (int b = 0; b < 5; b++) {
        /* Math.round do design: o meio vai pra cima. */
        int bh = (int)floorf((float)(ALTURAS[b] * alt) / 16.0f + 0.5f);
        if (bh < 2)
            bh = 2;
        int bx = x + b * (w + gap);
        if (b < q)
            oled_retangulo(o, bx, y + alt - bh, w, bh, true, true);
        else
            oled_retangulo(o, bx, y + alt - 1, w, 1, true, true);
    }
}

void oled_onda(oled_t *o, int x0, int y0, int w, int h, const float *v, uint32_t n, float mn,
               float mx)
{
    if (n > (uint32_t)w)
        n = (uint32_t)w;
    if (n == 0)
        return;
    float faixa = mx - mn;
    if (faixa == 0.0f)
        faixa = 1.0f;
    float folga = faixa * ONDA_FOLGA;
    mn -= folga;
    faixa += 2.0f * folga;

    int py = 0;
    for (uint32_t i = 0; i < n; i++) {
        float t = ((v[i] - mn) * (float)(h - 1)) / faixa;
        int y = y0 + (h - 1) - (int)floorf(t + 0.5f);
        if (i == 0)
            oled_pixel(o, x0, y, true);
        else
            oled_linha(o, x0 + (int)i - 1, py, x0 + (int)i, y);
        py = y;
    }
}

void oled_amostra(oled_t *o, float v)
{
    o->onda[o->onda_i] = v;
    o->onda_i = (uint16_t)(o->onda_i + 1u == OLED_ONDA_N ? 0u : o->onda_i + 1u);
    if (o->onda_n < OLED_ONDA_N)
        o->onda_n++;
}

void oled_onda_quadro(oled_t *o, int x0, int y0, int w, int h)
{
    float col[OLED_W];
    if (w > (int)OLED_W)
        w = (int)OLED_W;
    /* As 2*w amostras mais novas, da mais velha pra mais nova (ou as que já há). */
    uint32_t quer = 2u * (uint32_t)w;
    uint32_t tem = o->onda_n < quer ? o->onda_n : quer;
    uint32_t colunas = tem / 2u;
    if (colunas == 0u)
        return;
    uint32_t velha = (o->onda_i + OLED_ONDA_N - 2u * colunas) % OLED_ONDA_N;
    float mn = 0.0f, mx = 0.0f;
    for (uint32_t c = 0; c < colunas; c++) {
        float a = o->onda[(velha + 2u * c) % OLED_ONDA_N];
        float b = o->onda[(velha + 2u * c + 1u) % OLED_ONDA_N];
        col[c] = (a + b) * 0.5f;
        if (c == 0u || col[c] < mn)
            mn = col[c];
        if (c == 0u || col[c] > mx)
            mx = col[c];
    }

    /* A escala cresce na hora e encolhe devagar, pra onda não "respirar" a cada batida. */
    if (!o->esc_ok) {
        o->esc_min = mn;
        o->esc_max = mx;
        o->esc_ok = true;
    } else {
        o->esc_max = mx > o->esc_max ? mx : o->esc_max + ESCALA_ENCOLHE * (mx - o->esc_max);
        o->esc_min = mn < o->esc_min ? mn : o->esc_min + ESCALA_ENCOLHE * (mn - o->esc_min);
    }
    /* Antes de encher, a onda começa pela direita (a mais nova fica sempre no canto). */
    oled_onda(o, x0 + w - (int)colunas, y0, w, h, col, colunas, o->esc_min, o->esc_max);
}

bool oled_proxima_pagina(oled_t *o, uint8_t *pagina, const uint8_t **dados)
{
    for (unsigned i = 1; i <= OLED_PAGINAS; i++) {
        unsigned p = (o->ultima_pagina + i) % OLED_PAGINAS;
        if (((o->nunca_enviada >> p) & 1u) || memcmp(o->fb[p], o->enviado[p], OLED_W) != 0) {
            *pagina = (uint8_t)p;
            *dados = o->fb[p];
            return true;
        }
    }
    return false;
}

void oled_pagina_enviada(oled_t *o, uint8_t pagina)
{
    if (pagina >= OLED_PAGINAS)
        return;
    memcpy(o->enviado[pagina], o->fb[pagina], OLED_W);
    o->nunca_enviada &= (uint8_t)~(1u << pagina);
    o->ultima_pagina = pagina;
}
