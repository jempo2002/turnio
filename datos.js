/* Turnio — datos compartidos entre pantallas. Cargar justo después de theme.js.
   ponytail: localStorage hace de base de datos de demo (un solo día, un solo dispositivo).
   Cuando exista backend, window.datos se llena desde la API y guardar() hace el POST. */

(function () {
  var CLAVE = 'turnio-datos-v3';   /* subir la versión cuando cambie la forma de los datos */

  var SEMILLA = {
    citas: [
      { hora: '08:00', cliente: 'Andrés Mejía',    servicio: 'Corte + barba',      precio: 25000, tel: '573001112233', estado: 'completada' },
      { hora: '09:00', cliente: 'Kevin Ríos',      servicio: 'Fade',               precio: 18000, tel: '573002223344', estado: 'completada' },
      { hora: '10:00', cliente: 'Julián Pardo',    servicio: 'Corte clásico',      precio: 20000, tel: '573003334455', estado: 'reservada' },
      { hora: '11:00', cliente: '',                servicio: '',                   precio: 0,     tel: '',            estado: 'disponible' },
      { hora: '12:00', cliente: 'Mateo Guzmán',    servicio: 'Corte + cejas',      precio: 22000, tel: '573004445566', estado: 'reservada' },
      { hora: '13:00', cliente: 'Almuerzo',        servicio: 'No reservable online', precio: 0,   tel: '',            estado: 'bloqueada' },
      { hora: '14:00', cliente: 'Santiago Lozano', servicio: 'Perfilado de barba', precio: 15000, tel: '573005556677', estado: 'reservada' },
      { hora: '15:00', cliente: '',                servicio: '',                   precio: 0,     tel: '',            estado: 'disponible' },
      { hora: '16:00', cliente: 'Nicolás Vargas',  servicio: 'Corte + barba',      precio: 25000, tel: '573006667788', estado: 'reservada' },
      { hora: '17:00', cliente: '',                servicio: '',                   precio: 0,     tel: '',            estado: 'disponible' },
      { hora: '18:00', cliente: 'Daniel Ospina',   servicio: 'Fade + diseño',      precio: 30000, tel: '573007778899', estado: 'reservada' },
      { hora: '19:00', cliente: '',                servicio: '',                   precio: 0,     tel: '',            estado: 'disponible' }
    ],

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

    barberos: [
      { nombre: 'Carlos' },
      { nombre: 'Junior' }
    ],

    /* 'cita' = hora del turno que originó el cobro (permite deshacerlo desde Citas).
       'paga' = lo que ese cobro le deja al barbero, fijado al momento de cobrar. */
    movimientos: [
      { tipo: 'ingreso', concepto: 'Corte + barba · Andrés M.', monto: 25000, metodo: 'efectivo',      barbero: 'Carlos', cita: '08:00', paga: 15000 },
      { tipo: 'ingreso', concepto: 'Fade · Kevin R.',           monto: 18000, metodo: 'transferencia', barbero: 'Junior', cita: '09:00', paga: 12000 },
      { tipo: 'ingreso', concepto: 'Cerveza x2 + snack',        monto: 13000, metodo: 'efectivo',      barbero: null },
      { tipo: 'ingreso', concepto: 'Cera para cabello',         monto: 18000, metodo: 'transferencia', barbero: null },
      { tipo: 'salida',  concepto: 'Cuchillas y talco',         monto: 35000, metodo: 'efectivo',      barbero: null }
    ]
  };

  var d = null;
  try { d = JSON.parse(localStorage.getItem(CLAVE)); } catch (e) { /* modo privado o dato corrupto: se usa la semilla */ }
  window.datos = d || SEMILLA;

  window.guardar = function () {
    try { localStorage.setItem(CLAVE, JSON.stringify(window.datos)); } catch (e) { /* sin almacenamiento: sigue en memoria */ }
  };
})();
