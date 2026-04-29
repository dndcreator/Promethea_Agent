/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef5ff',
          100: '#dbeafe',
          500: '#1a73e8',
          600: '#1558b7',
          700: '#12499a',
        },
        bg: {
          page: '#f4f7fb',
          panel: '#f8fafd',
          card: '#ffffff',
          subtle: '#f1f5f9',
        },
        text: {
          strong: '#0f172a',
          normal: '#334155',
          muted: '#64748b',
        }
      }
    },
  },
  plugins: [],
}
