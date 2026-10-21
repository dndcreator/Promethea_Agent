/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', '"Segoe UI Variable"', '"Microsoft YaHei"', '"Noto Sans SC"', 'ui-sans-serif', 'system-ui'],
        display: ['Inter', '"Segoe UI Variable"', '"Microsoft YaHei"', 'ui-sans-serif', 'system-ui'],
        mono: ['JetBrains Mono', 'Cascadia Code', 'ui-monospace', 'SFMono-Regular'],
      },
      colors: {
        brand: {
          50: '#f3f3f4',
          100: '#e8e9eb',
          200: '#d2d4d8',
          300: '#adb0b7',
          400: '#838792',
          500: '#555a64',
          600: '#383c44',
          700: '#292c32',
          800: '#1e2126',
        },
        bg: {
          page: '#f3f4f5',
          panel: '#f9f9fa',
          card: '#ffffff',
          subtle: '#e8e9ec',
        },
        border: { soft: '#e4e5e8' },
        text: {
          strong: '#23262d',
          normal: '#494e58',
          muted: '#7b808a',
        }
      }
    },
  },
  plugins: [],
}
