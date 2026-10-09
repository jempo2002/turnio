/* Landing (T9): lo que era JS inline de index.html. */
/* Aparición suave al hacer scroll. Solo opacity y transform (los anima la GPU, no recalculan layout).
   Sin JS, sin IntersectionObserver o con "reducir movimiento" activado, todo queda visible tal cual. */
(function () {
  if (!('IntersectionObserver' in window) || matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  var io = new IntersectionObserver(function (entradas) {
    entradas.forEach(function (e) {
      if (!e.isIntersecting) return;
      io.unobserve(e.target);
      e.target.style.opacity = '';
      e.target.animate(
        [{ opacity: 0, transform: 'translateY(16px)' }, { opacity: 1, transform: 'none' }],
        { duration: 500, easing: 'cubic-bezier(.2,.7,.2,1)', delay: Number(e.target.dataset.reveal) || 0, fill: 'backwards' }
      );
    });
  }, { threshold: 0.15 });

  document.querySelectorAll('[data-reveal]').forEach(function (el) {
    if (el.getBoundingClientRect().top < innerHeight) return;   /* ya está a la vista al cargar: no se esconde */
    el.style.opacity = '0';
    io.observe(el);
  });
})();

/* Selector de periodo de los planes (como el de jemPOS): cambia el valor
   mensual equivalente y la nota de cada tarjeta. Sin JS queda el mensual. */
(function () {
  var cop = function (n) { return '$' + n.toLocaleString('es-CO'); };
  var meses = { 3: 'cada 3 meses', 6: 'cada 6 meses', 12: 'al año' };
  var botones = document.querySelectorAll('[data-periodos] [data-periodo]');
  botones.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var m = btn.dataset.periodo;
      botones.forEach(function (b) { b.setAttribute('aria-selected', b === btn ? 'true' : 'false'); });
      document.querySelectorAll('[data-plan]').forEach(function (card) {
        var p = JSON.parse(card.dataset.plan)[m];
        var nota = card.querySelector('[data-nota]');
        card.querySelector('[data-monto]').textContent = cop(p.mes);
        if (m === '1') { nota.textContent = nota.dataset.notaMensual; return; }
        var ahorro = m === '6' ? '1 mes gratis' : 'ahorras ' + cop(p.ahorro);
        nota.textContent = 'Pagas ' + cop(p.total) + ' ' + meses[m] + ': ' + ahorro + '.';
      });
    });
  });
})();
