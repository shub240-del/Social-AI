import type { Config } from 'tailwindcss';

export default {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { 900: '#0b0e14', 800: '#11151f', 700: '#161b27', 600: '#232a3a' },
      },
    },
  },
  plugins: [],
} satisfies Config;
