import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./src/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: '#1E2832',
          light: '#2C3A4A',
          dark: '#141B23',
        },
        ember: {
          DEFAULT: '#D4622A',
          dark: '#BC561F',
          light: '#FBE8DC',
          muted: '#A34C1E',
        },
        parchment: {
          DEFAULT: '#F5F0E6',
          dark: '#EDE6D6',
        },
      },
      fontFamily: {
        sans: ['Space Grotesk', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};

export default config;
