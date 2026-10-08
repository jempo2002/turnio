/* Turnio — datos compartidos entre pantallas. Cargar justo después de theme.js.
   ponytail: localStorage hace de base de datos de demo (un solo día, un solo dispositivo).
   Cuando exista backend, window.datos se llena desde la API y guardar() hace el POST. */

(function () {
  var CLAVE = 'turnio-datos-v4';   /* subir la versión cuando cambie la forma de los datos */
  var SESION = 'turnio-sesion';

  /* Cada profesional tiene su propia agenda: una fila por hora, libre salvo lo que se indique. */
  var HORAS = ['08:00', '09:00', '10:00', '11:00', '12:00', '13:00', '14:00', '15:00', '16:00', '17:00', '18:00', '19:00'];
  var ALMUERZO = { cliente: 'Almuerzo', servicio: 'No reservable online', estado: 'bloqueada' };

  function agenda(barbero, ocupadas) {
    return HORAS.map(function (h) {
      return Object.assign({ id: barbero + '-' + h, hora: h, barbero: barbero, cliente: '', servicio: '', precio: 0, tel: '', estado: 'disponible' }, ocupadas[h]);
    });
  }

  var SEMILLA = {
    citas: agenda('Carlos', {
      '08:00': { cliente: 'Andrés Mejía',    servicio: 'Corte + barba',      precio: 25000, tel: '573001112233', estado: 'completada' },
      '10:00': { cliente: 'Julián Pardo',    servicio: 'Corte clásico',      precio: 20000, tel: '573003334455', estado: 'reservada' },
      '12:00': { cliente: 'Mateo Guzmán',    servicio: 'Corte + cejas',      precio: 22000, tel: '573004445566', estado: 'reservada' },
      '13:00': ALMUERZO,
      '14:00': { cliente: 'Santiago Lozano', servicio: 'Perfilado de barba', precio: 15000, tel: '573005556677', estado: 'reservada' },
      '16:00': { cliente: 'Nicolás Vargas',  servicio: 'Corte + barba',      precio: 25000, tel: '573006667788', estado: 'reservada' },
      '18:00': { cliente: 'Daniel Ospina',   servicio: 'Fade + diseño',      precio: 30000, tel: '573007778899', estado: 'reservada' }
    }).concat(agenda('Junior', {
      '09:00': { cliente: 'Kevin Ríos',      servicio: 'Fade',               precio: 18000, tel: '573002223344', estado: 'completada' },
      '10:00': { cliente: 'Felipe Castaño',  servicio: 'Corte clásico',      precio: 20000, tel: '573008889900', estado: 'reservada' },
      '13:00': ALMUERZO,
      '15:00': { cliente: 'Tomás Herrera',   servicio: 'Fade',               precio: 18000, tel: '573009990011', estado: 'reservada' },
      '16:00': { cliente: 'Camilo Duque',    servicio: 'Corte + barba',      precio: 25000, tel: '573001230045', estado: 'reservada' }
    })),

    /* Códigos de barras de demostración (EAN-13). 'vendidos' ordena la vitrina de Venta rápida. */
    productos: [
      { codigo: '7701234000011', emoji: '🍺', nombre: 'Cerveza en lata', unidades: 18, compra: 3000,  venta: 5000,  vendidos: 42 },
      { codigo: '7701234000028', emoji: '💧', nombre: 'Agua 500 ml',     unidades: 4,  compra: 1200,  venta: 2000,  vendidos: 31 },
      { codigo: '7701234000035', emoji: '🍪', nombre: 'Snack surtido',   unidades: 11, compra: 1800,  venta: 3000,  vendidos: 18 },
      { codigo: '7701234000042', emoji: '🥤', nombre: 'Gaseosa',         unidades: 2,  compra: 2200,  venta: 3500,  vendidos: 25 },
      { codigo: '7701234000059', emoji: '🧴', nombre: 'Cera moldeadora', unidades: 7,  compra: 11000, venta: 18000, vendidos: 9 },
      { codigo: '7701234000066', emoji: '☕', nombre: 'Café',            unidades: 0,  compra: 1000,  venta: 2500,  vendidos: 37 },
      { codigo: '7701234000073', emoji: '🧴', nombre: 'Gel fijador',     unidades: 9,  compra: 6000,  venta: 10000, vendidos: 4 },
      { codigo: '7701234000080', emoji: '🍟', nombre: 'Papas fritas',    unidades: 14, compra: 1500,  venta: 2500,  vendidos: 6 }
    ],

    /* pagoBarbero = monto fijo que recibe quien atiende; el resto del precio es del local */
    servicios: [
      { nombre: 'Corte clásico',      duracion: 45, precio: 20000, pagoBarbero: 13000 },
      { nombre: 'Corte + barba',      duracion: 60, precio: 25000, pagoBarbero: 15000 },
      { nombre: 'Perfilado de barba', duracion: 30, precio: 15000, pagoBarbero: 10000 },
      { nombre: 'Fade',               duracion: 45, precio: 18000, pagoBarbero: 12000 },
      { nombre: 'Corte + cejas',      duracion: 45, precio: 22000, pagoBarbero: 14000 },
      { nombre: 'Fade + diseño',      duracion: 60, precio: 30000, pagoBarbero: 19000 },
      { nombre: 'Cejas',              duracion: 15, precio: 6000,  pagoBarbero: 4000 }
    ],

    /* 'correo' identifica al profesional al iniciar sesión. Nunca se pinta en la vista de clientes. */
    barberos: [
      { nombre: 'Carlos', correo: 'carlos@elcuartel.co' },
      { nombre: 'Junior', correo: 'junior@elcuartel.co' }
    ],

    /* 'cita' = id del turno que originó el cobro (permite deshacerlo desde Citas).
       'paga' = lo que ese cobro le deja al barbero, fijado al momento de cobrar. */
    movimientos: [
      { tipo: 'ingreso', concepto: 'Corte + barba · Andrés M.', monto: 25000, metodo: 'efectivo',      barbero: 'Carlos', cita: 'Carlos-08:00', paga: 15000 },
      { tipo: 'ingreso', concepto: 'Fade · Kevin R.',           monto: 18000, metodo: 'transferencia', barbero: 'Junior', cita: 'Junior-09:00', paga: 12000 },
      { tipo: 'ingreso', concepto: 'Cerveza x2 + snack',        monto: 13000, metodo: 'efectivo',      barbero: null },
      { tipo: 'ingreso', concepto: 'Cera para cabello',         monto: 18000, metodo: 'transferencia', barbero: null },
      { tipo: 'salida',  concepto: 'Cuchillas y talco',         monto: 35000, metodo: 'efectivo',      barbero: null }
    ]
  };

  function leer() {
    try { return JSON.parse(localStorage.getItem(CLAVE)); } catch (e) { return null; /* modo privado o dato corrupto */ }
  }

  window.datos = leer() || SEMILLA;

  window.guardar = function () {
    try { localStorage.setItem(CLAVE, JSON.stringify(window.datos)); } catch (e) { /* sin almacenamiento: sigue en memoria */ }
  };

  /* Tiempo real entre pestañas: cuando otra pestaña guarda, el navegador avisa con 'storage'.
     Se rellenan las mismas listas (las pantallas guardan referencias a ellas) y cada pantalla
     repinta al oír 'turnio:datos'.
     ponytail: solo sincroniza pestañas del mismo navegador. Con backend: Supabase Realtime sobre appointments. */
  window.addEventListener('storage', function (e) {
    if (e.key !== CLAVE) return;
    var nuevo = leer();
    if (!nuevo) return;
    Object.keys(nuevo).forEach(function (k) {
      window.datos[k].length = 0;
      Array.prototype.push.apply(window.datos[k], nuevo[k]);
    });
    document.dispatchEvent(new Event('turnio:datos'));
  });

  /* ── Sesión ──
     ponytail: demo sin backend. El nombre guardado aquí lo puede cambiar cualquiera desde el navegador,
     así que solo sirve para la demo. En producción quien cobra lo decide el JWT en el servidor
     (POST /api/appointments/:id/complete), no un dato del cliente. */
  window.entrar = function (correo) {
    var b = window.datos.barberos.find(function (x) { return x.correo === String(correo).trim().toLowerCase(); });
    try { localStorage.setItem(SESION, (b || window.datos.barberos[0]).nombre); } catch (e) {}
  };

  window.salir = function () {
    try { localStorage.removeItem(SESION); } catch (e) {}
  };

  /* Nombre del profesional con la sesión abierta. Sin sesión (panel de demo): el primero. */
  window.sesion = function () {
    var n = null;
    try { n = localStorage.getItem(SESION); } catch (e) {}
    var b = window.datos.barberos.find(function (x) { return x.nombre === n; }) || window.datos.barberos[0];
    return b.nombre;
  };
})();
