/* Turnia — barra de navegación inferior compartida.
   Cargar al final del <body>. Marca sola la pestaña activa según el archivo abierto. */

(function () {
  var ICONOS = {
    hoy: '<rect x="3" y="4.5" width="18" height="16" rx="3"></rect><path d="M8 2.5v4M16 2.5v4M3 10h18"></path><circle cx="12" cy="15" r="1.6" fill="currentColor" stroke="none"></circle>',
    citas: '<path d="M17 20.5v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"></path><circle cx="9.5" cy="7" r="4"></circle><path d="M18 8.5h4M20 6.5v4"></path>',
    caja: '<rect x="2.5" y="6" width="19" height="13" rx="3"></rect><path d="M2.5 10.5h19M6.5 15h3"></path>',
    inventario: '<path d="M21 8.5v7a2 2 0 0 1-1 1.7l-7 4a2 2 0 0 1-2 0l-7-4a2 2 0 0 1-1-1.7v-7a2 2 0 0 1 1-1.7l7-4a2 2 0 0 1 2 0l7 4A2 2 0 0 1 21 8.5Z"></path><path d="M3.5 7.5L12 12.5l8.5-5M12 21.5v-9"></path>',
    ajustes: '<circle cx="12" cy="12" r="3.2"></circle><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-2.9 1.2v.2a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-3-1.2l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0-1.2-2.9H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.2-3l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 2.9-1.2V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 3 1.2l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0 1.2 2.9H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"></path>'
  };

  var TABS = [
    { href: 'app.html',           label: 'Hoy',        icono: 'hoy' },
    { href: 'citas.html',         label: 'Citas',      icono: 'citas' },
    { href: 'caja.html',          label: 'Caja',       icono: 'caja' },
    { href: 'inventario.html',    label: 'Inventario', icono: 'inventario' },
    { href: 'configuracion.html', label: 'Ajustes',    icono: 'ajustes' }
  ];

  var actual = (location.pathname.split('/').pop() || 'app.html').toLowerCase();

  var items = TABS.map(function (t) {
    var activo = t.href === actual;
    return '<li><a href="' + t.href + '"' + (activo ? ' aria-current="page"' : '') +
      ' class="flex flex-col items-center gap-1 py-2.5 transition ' +
      (activo ? 'text-brand-dark' : 'text-brand-darkest/45 hover:text-brand-dark') + '">' +
      '<svg class="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
      'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + ICONOS[t.icono] + '</svg>' +
      '<span class="text-[10px] ' + (activo ? 'font-semibold' : 'font-medium') + '">' + t.label + '</span>' +
      '</a></li>';
  }).join('');

  document.body.insertAdjacentHTML('beforeend',
    '<nav aria-label="Navegación principal" class="fixed inset-x-0 bottom-0 z-40 border-t border-white/50 ' +
    'bg-white/80 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl backdrop-saturate-150">' +
    '<ul class="mx-auto grid max-w-md grid-cols-5">' + items + '</ul></nav>');
})();
