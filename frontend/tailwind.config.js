/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Apollo-era HUD palette
        'space-bg': '#000000',
        'space-bg-light': '#080706',
        'space-blue': '#ee1212',
        'space-cyan': '#e4b592',
        'space-purple': '#dad0c8',
        'space-green': '#dad0c8',
        'space-orange': '#ee1212',
        'space-text': '#fff3ea',
        'space-text-dim': '#a49b92',
      },
      fontFamily: {
        'outfit': ['Space Grotesk', 'Outfit', 'sans-serif'],
        'jetbrains': ['IBM Plex Mono', 'JetBrains Mono', 'monospace'],
      },
      animation: {
        'fade-up': 'fadeUp 0.5s ease-out both',
        'float': 'float 3s ease-in-out infinite',
        'glow-pulse': 'glowPulse 2s ease-in-out infinite',
        'rocket-rise': 'rocketRise 3s ease-in forwards',
        'twinkle': 'twinkle 3s ease-in-out infinite',
        'nebula-drift': 'nebulaDrift 20s ease-in-out infinite',
      },
      keyframes: {
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(20px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0px)' },
          '50%': { transform: 'translateY(-15px)' },
        },
        glowPulse: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.5' },
        },
        rocketRise: {
          '0%': { transform: 'translateY(0) scale(1)' },
          '100%': { transform: 'translateY(-200px) scale(0.7)' },
        },
        twinkle: {
          '0%, 100%': { opacity: '0.3' },
          '50%': { opacity: '1' },
        },
        nebulaDrift: {
          '0%, 100%': { transform: 'translate(0, 0) scale(1)' },
          '50%': { transform: 'translate(20px, 30px) scale(1.1)' },
        },
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [],
}
