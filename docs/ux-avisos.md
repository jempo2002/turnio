# Reglas de avisos y guías (UX/UI)

Toda alerta, error, confirmación o mensaje vacío de Turnio sigue estas reglas, en el panel, en las pantallas de cuenta (login, registro, equipo, sedes) y en la página pública de reservas. La idea es la misma de un onboarding: la persona nunca queda adivinando qué pasó ni qué hacer.

## 1. Qué dice un aviso

1. **Qué pasó + qué hacer.** Un título corto (máximo 6 palabras) con lo que pasó y una línea con el siguiente paso. "Sin conexión · Revisa el internet del celular y vuelve a intentarlo. No se guardó nada."
2. **Lenguaje de la calle, sin jerga.** Nada de "error 500", "inválido", "ID", "request", "token". Se dice "Ese horario ya está ocupado", no "Conflicto 409".
3. **Tú, amable y sin culpar.** "Escribe tu WhatsApp completo", no "Teléfono incorrecto". Si la falla es nuestra, se dice: "No es tu culpa".
4. **Concreto.** Con el dato que sirve: la hora que se cruza, cuántas unidades quedan, el tope del plan y cuánto cuesta subir.
5. **Una sola acción sugerida.** Si hay un arreglo directo, el aviso trae el botón: Reintentar, Recargar, Ver mi plan, Escribir por WhatsApp.
6. **Ortografía completa**, con tildes y signos de apertura.

## 2. Cómo se ve

| Tipo | Cuándo | Color e icono | Dura |
|---|---|---|---|
| `exito` | Algo se guardó | Verde, ✓ | 3 s y se va solo |
| `info` | Un dato útil, sin problema | Azul de la marca, i | 4,5 s |
| `aviso` | Hay que hacer algo pero nada falló (plan, sesión, esperar) | Ámbar, triángulo | 7 s |
| `error` | No se pudo hacer lo que pidió | Rojo, círculo con ! | 8 s, con botón para cerrar |

- Siempre **icono + texto**: el color solo nunca basta (daltonismo, sol en la pantalla).
- Los avisos flotantes salen **arriba**, para no tapar la barra inferior ni los botones del pulgar.
- Áreas táctiles de 44 px como mínimo; texto secundario con contraste de 4,5:1 o más (`text-brand-darkest/70`).
- Los errores usan `role="alert"` (el lector de pantalla los lee de inmediato); el resto, `role="status"`.

## 3. Dónde va cada mensaje

- **Error de un campo:** debajo del campo, en rojo, con el campo marcado y el foco puesto ahí (`T.marcarCampo`). El aviso flotante lo acompaña, no lo reemplaza.
- **Error al cargar una sección:** la tarjeta ocupa el lugar de la sección y trae "Reintentar" (`T.errorCarga`).
- **Error de una acción:** aviso flotante con qué pasó y qué hacer (`T.fallo`).
- **Pantalla o lista vacía:** se dice por qué está vacía y cuál es el primer paso ("Todavía no hay servicios. Toca «Servicio» para crear el primero.").

## 4. Confirmaciones

- Solo para lo que borra, anula o no tiene vuelta atrás.
- El título es una pregunta con el verbo ("¿Anular esta venta?"); el detalle dice **qué va a pasar** (qué cambia en caja, en la agenda, en el inventario).
- Si no se puede deshacer, se dice: `T.confirmar(titulo, detalle, 'Anular venta', {deshacer: false})`.
- El botón dice la acción ("Borrar salida"), nunca "Aceptar" o "Sí". "Cancelar" siempre está y es el foco inicial.
- Acciones normales (no destructivas) usan `{peligro: false}`: botón azul, no rojo.

## 5. Guías de bienvenida (onboarding)

- Cada pantalla principal tiene una guía corta la primera vez (`T.guia`): máximo 3 pasos, en una tarjeta al inicio, con "Saltar guía".
- Cada paso explica **para qué sirve** algo y **cómo se usa**, en una o dos frases.
- No vuelve a salir en ese dispositivo. En Ajustes, "Ver las guías otra vez" las devuelve.
- La página pública de reservas guía al cliente con los pasos numerados y una ayuda en cada paso (qué falta elegir); no necesita tarjeta.

## 6. Dónde está el código

- `static/js/panel/turnio.js`: `explicar()` (de error HTTP a título + qué hacer, probado en `test-calculo.js`), `T.aviso`, `T.toast`, `T.fallo`, `T.errorCarga`, `T.marcarCampo`, `T.confirmar`, `T.guia`.
- `static/css/avisos.css`: estilos del aviso, la confirmación, el error de campo, la guía y los mensajes del servidor. CSS plano: lo cargan todas las pantallas.
- `static/js/app.js`: usa esas mismas funciones en las pantallas de cuenta y equipo (sedes, equipo, panel Master). Las confirmaciones se piden con `data-confirmar` (pregunta), `data-detalle` (qué va a pasar), `data-boton` y `data-peligro="no"`.
- `templates/_flashes.html`: los mensajes que manda el servidor al recargar (login, registro, contraseña).
- Mensajes del servidor: `app/utils/validation.py` ("Escribe el precio.", "Acorta el nombre: máximo 60 caracteres.") y cada servicio. Escríbelos ya listos para mostrar, siguiendo la sección 1.
