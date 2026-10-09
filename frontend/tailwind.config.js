/* Tailwind del panel (T7). Antes vivia en theme.js para el CDN; compilado,
   la CSP estricta de app/security.py no cambia (sin 'unsafe-eval' ni estilos
   inline). Recompilar con `npm run css` al tocar clases en las plantillas o
   en static/js/panel/. */
module.exports = {
  content: ['../templates/panel/**/*.html', '../templates/publico/**/*.html', '../templates/auth/login.html', '../static/js/panel/**/*.js', '../static/js/publico/**/*.js'],
  theme: {
    extend: {
      colors: {
        brand: {
          lightest: '#E8F4F8',   /* tinte del acento: chips y fondos suaves */
          light:    '#D9E2E8',   /* bordes */
          DEFAULT:  '#54C2DD',   /* foco y detalles */
          dark:     '#17748E',   /* acento: 5.3:1 sobre blanco */
          darkest:  '#1B2B36'    /* texto */
        }
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Inter', 'Helvetica Neue', 'Arial', 'sans-serif']
      },
      boxShadow: {
        soft: '0 1px 2px rgba(15,23,42,.05), 0 8px 24px -16px rgba(15,23,42,.18)',
        lift: '0 2px 4px rgba(15,23,42,.06), 0 20px 40px -16px rgba(15,23,42,.28)'
      }
    }
  }
};
