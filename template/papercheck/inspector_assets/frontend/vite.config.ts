import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          math: ['katex', 'rehype-katex', 'remark-math'],
          markdown: ['react-markdown', 'remark-gfm'],
          ui: ['@radix-ui/themes'],
          motion: ['motion/react'],
        },
      },
    },
  },
});
