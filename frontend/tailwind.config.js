const brand = {
  ink: '#020323',
  canvas: '#f7f7f7',
  white: '#ffffff',
};

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: ["class"],
  content: [
    "./src/**/*.{js,jsx,ts,tsx}", // Legacy paths
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        "2xl": "1400px",
      },
    },
    extend: {
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', 'Fira Sans', 'Droid Sans', 'Helvetica Neue', 'sans-serif'],
      },
      colors: {
        // Default brand palette
        brand: {
          DEFAULT: brand.ink,
          ink: brand.ink,
          canvas: brand.canvas,
          white: brand.white,
          50: brand.canvas,
          100: '#ececf0',
          200: '#d7d7df',
          300: '#b7b8c8',
          400: '#85879e',
          500: '#4d506d',
          600: '#202443',
          700: '#11142f',
          800: '#090b29',
          900: '#050622',
          950: brand.ink,
          foreground: brand.white,
        },
        'brand-foreground': brand.white,

        // Primary now maps to the official brand ink.
        primary: {
          DEFAULT: brand.ink,
          50: brand.canvas,
          100: '#ececf0',
          200: '#d7d7df',
          300: '#b7b8c8',
          400: '#85879e',
          500: '#4d506d',
          600: brand.ink,
          700: brand.ink,
          800: brand.ink,
          900: brand.ink,
          950: brand.ink,
          foreground: brand.white,
        },
        'primary-foreground': brand.white,

        // Secondary is a quiet light surface for neutral actions.
        secondary: {
          DEFAULT: brand.canvas,
          50: brand.white,
          100: brand.canvas,
          200: '#ececf0',
          300: '#d7d7df',
          400: '#b7b8c8',
          500: brand.canvas,
          600: '#d7d7df',
          700: '#85879e',
          800: '#4d506d',
          900: brand.ink,
          foreground: brand.ink,
        },
        'secondary-foreground': brand.ink,

        // Destructive - Vermelho para ações perigosas
        destructive: {
          DEFAULT: 'var(--error)',
          foreground: brand.white,
        },
        'destructive-foreground': brand.white,

        // Accent is the subtle brand hover/focus surface.
        accent: {
          DEFAULT: brand.canvas,
          50: brand.white,
          100: brand.canvas,
          200: '#ececf0',
          300: '#d7d7df',
          400: '#b7b8c8',
          500: brand.canvas,
          600: brand.ink,
          700: brand.ink,
          800: brand.ink,
          900: brand.ink,
          foreground: brand.ink,
        },
        'accent-foreground': brand.ink,

        // Background e foreground gerais
        background: 'var(--surface-secondary)',
        foreground: 'var(--text-primary)',
        card: 'var(--surface-primary)',
        'card-foreground': 'var(--text-primary)',
        muted: 'var(--surface-secondary)',
        'muted-foreground': 'var(--text-secondary)',

        // Input e ring para focus states
        input: 'var(--border-default)',
        ring: 'var(--border-focus)',

        // Mist - official light background
        mist: brand.canvas,
        'card-border': 'var(--card-border)',
      },
      boxShadow: {
        flat: '0 1px 2px rgba(2, 3, 35, 0.06)',
        'flat-md': '0 8px 24px rgba(2, 3, 35, 0.08)',
        'flat-lg': '0 16px 40px rgba(2, 3, 35, 0.1)',
      },
    },
  },
  plugins: [],
};
