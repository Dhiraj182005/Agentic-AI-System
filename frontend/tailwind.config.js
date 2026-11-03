/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Navy-tinted neutral scale: every existing gray-* class picks up the
      // MAVES palette without per-page changes.
      colors: {
        gray: {
          50: '#f5f7fc',
          100: '#e8ecf7',
          200: '#d3d9ee',
          300: '#b3bcdc',
          400: '#8c97bf',
          500: '#66729c',
          600: '#454f78',
          700: '#2c3459',
          800: '#1b2242',
          900: '#111731',
          950: '#090d20',
        },
      },
      boxShadow: {
        card: '0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.5)',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'fade-in-up': {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'progress-sweep': {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 260ms ease-out both',
        'fade-in-up': 'fade-in-up 320ms ease-out both',
        'progress-sweep': 'progress-sweep 1.4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
