/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Noto Sans SC"', 'Inter', 'Aptos', '"Segoe UI Variable"', 'ui-sans-serif', 'system-ui'],
        display: ['"Noto Serif SC"', '"Source Han Serif SC"', 'Aptos Display', 'Georgia', 'serif'],
        mono: ['JetBrains Mono', 'Cascadia Code', 'ui-monospace', 'SFMono-Regular'],
      },
      colors: {
        brand: {
          50: '#edf6f5',
          100: '#d7eae8',
          200: '#b7d1ce',
          300: '#8fb8b4',
          400: '#60938f',
          500: '#356c68',
          600: '#285956',
          700: '#214946',
        },
        bg: {
          page: '#f1f2ef',
          panel: '#fafbf8',
          card: '#fffefa',
          subtle: '#e3e7e2',
        },
        text: {
          strong: '#1f211f',
          normal: '#454741',
          muted: '#74746c',
        }
      }
    },
  },
  plugins: [],
}
