// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

export default defineConfig({
  site: 'https://andreojr.github.io',
  base: '/sensor-ppg',
  markdown: {
    remarkPlugins: [remarkMath],
    rehypePlugins: [rehypeKatex],
  },
  integrations: [
    starlight({
      title: 'sensor-ppg',
      description: 'PDS de fotopletismografia em tempo real (ENGG54, UFBA)',
      defaultLocale: 'root',
      locales: { root: { label: 'Português', lang: 'pt-BR' } },
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/andreojr/sensor-ppg' }],
      head: [
        {
          tag: 'link',
          attrs: {
            rel: 'stylesheet',
            href: 'https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css',
          },
        },
      ],
      sidebar: [
        { label: 'Visão geral', link: '/' },
        { label: 'Interface (ppg.h)', slug: 'interface' },
        { label: 'Fluxo de trabalho', slug: 'fluxo' },
        { label: 'Módulos de PDS', items: [{ autogenerate: { directory: 'modulos' } }] },
        { label: 'Firmware', slug: 'firmware' },
      ],
    }),
  ],
});
