import type { Config } from "tailwindcss";

export default {
  darkMode: ["class"],
  content: ["./pages/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./app/**/*.{ts,tsx}", "./src/**/*.{ts,tsx}"],
  prefix: "",
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
        sans: ['Ubuntu', 'sans-serif'],
        display: ['Oswald', 'sans-serif'],
      },
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // SA Team Colors
        chiefs: {
          gold: "hsl(var(--chiefs-gold))",
          black: "hsl(var(--chiefs-black))",
        },
        pirates: {
          white: "hsl(var(--pirates-white))",
          black: "hsl(var(--pirates-black))",
        },
        sundowns: {
          yellow: "hsl(var(--sundowns-yellow))",
          blue: "hsl(var(--sundowns-blue))",
        },
        // SA Flag Colors
        sa: {
          green: "hsl(var(--sa-green))",
          gold: "hsl(var(--sa-gold))",
          red: "hsl(var(--sa-red))",
          blue: "hsl(var(--sa-blue))",
          black: "hsl(var(--sa-black))",
          white: "hsl(var(--sa-white))",
        },
        stadium: {
          glow: "hsl(var(--stadium-glow))",
          pitch: "hsl(var(--pitch-green))",
          floodlight: "hsl(var(--floodlight))",
        },
        sidebar: {
          DEFAULT: "hsl(var(--sidebar-background))",
          foreground: "hsl(var(--sidebar-foreground))",
          primary: "hsl(var(--sidebar-primary))",
          "primary-foreground": "hsl(var(--sidebar-primary-foreground))",
          accent: "hsl(var(--sidebar-accent))",
          "accent-foreground": "hsl(var(--sidebar-accent-foreground))",
          border: "hsl(var(--sidebar-border))",
          ring: "hsl(var(--sidebar-ring))",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        "float": {
          "0%, 100%": { transform: "translateY(0px) rotate(0deg)" },
          "50%": { transform: "translateY(-20px) rotate(5deg)" },
        },
        "vuvuzela-blast": {
          "0%": { transform: "scale(1) rotate(-10deg)" },
          "25%": { transform: "scale(1.1) rotate(5deg)" },
          "50%": { transform: "scale(1) rotate(-5deg)" },
          "75%": { transform: "scale(1.05) rotate(3deg)" },
          "100%": { transform: "scale(1) rotate(-10deg)" },
        },
        "confetti-fall": {
          "0%": { transform: "translateY(-100vh) rotate(0deg)", opacity: "1" },
          "100%": { transform: "translateY(100vh) rotate(720deg)", opacity: "0" },
        },
        "bounce-celebrate": {
          "0%, 100%": { transform: "translateY(0) scale(1)" },
          "50%": { transform: "translateY(-30px) scale(1.1)" },
        },
        "pulse-glow": {
          "0%, 100%": { boxShadow: "0 0 20px hsl(45 100% 60% / 0.3)" },
          "50%": { boxShadow: "0 0 40px hsl(45 100% 60% / 0.6), 0 0 60px hsl(45 93% 47% / 0.3)" },
        },
        "crowd-wave": {
          "0%": { transform: "translateY(0)" },
          "25%": { transform: "translateY(-10px)" },
          "50%": { transform: "translateY(0)" },
          "75%": { transform: "translateY(-5px)" },
          "100%": { transform: "translateY(0)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
        "float": "float 3s ease-in-out infinite",
        "vuvuzela": "vuvuzela-blast 0.5s ease-in-out",
        "confetti": "confetti-fall 5s linear infinite",
        "bounce-celebrate": "bounce-celebrate 1s ease-in-out infinite",
        "pulse-glow": "pulse-glow 2s ease-in-out infinite",
        "crowd-wave": "crowd-wave 2s ease-in-out infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
} satisfies Config;
