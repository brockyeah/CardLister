/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // Custom dark palette for the utilitarian look
        ink: {
          900: '#0b0f17',
          800: '#111827',
          700: '#1f2937',
          600: '#374151',
        },
      },
    },
  },
  plugins: [],
}
