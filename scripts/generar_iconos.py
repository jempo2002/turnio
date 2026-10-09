"""Genera los iconos de la app (favicon y PWA) a partir del isotipo.

Tomado de scripts/generar_favicons.py de jemPOS: se dibuja con Pillow en vez
de rasterizar static/img/icono.svg, para no sumar cairosvg. Las formas
replican el SVG (el calendario con check del landing, rejilla de 24 sobre una
placa de 36). Pillow no va en requirements.txt: solo hace falta para correr
este script, y los PNG se suben al repo.

  favicon.ico              16+32+48  la peticion implicita a /favicon.ico
  icono-192.png            192       manifest (Android) y <link rel="icon">
  icono-512.png            512       manifest: pantalla de bienvenida de Android
  icono-maskable-512.png   512       manifest, purpose "maskable": placa a sangre,
                                     el dibujo dentro de la zona segura (80 %)
  apple-touch-icon.png     180       iOS, sin canal alfa (Safari lo pinta negro)

    pip install Pillow && python scripts/generar_iconos.py
"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw

DESTINO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "img")

MARCA = (23, 116, 142, 255)     # brand-dark (#17748E), frontend/tailwind.config.js
BLANCO = (255, 255, 255, 255)
LIENZO = 1024                   # se dibuja grande y se reduce con LANCZOS


def _dibujar(a_sangre: bool, glifo: float) -> Image.Image:
    """Placa de color con el calendario. `glifo`: fraccion del lienzo que
    ocupa la rejilla de 24 del dibujo."""
    img = Image.new("RGBA", (LIENZO, LIENZO), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if a_sangre:
        d.rectangle([0, 0, LIENZO, LIENZO], fill=MARCA)
    else:
        d.rounded_rectangle([0, 0, LIENZO - 1, LIENZO - 1], radius=int(LIENZO * 8 / 36), fill=MARCA)

    e = LIENZO * glifo / 24
    o = (LIENZO - 24 * e) / 2
    def p(x, y):
        return (o + x * e, o + y * e)
    ancho = max(1, round(2 * e))
    d.rounded_rectangle([*p(3, 4.5), *p(21, 20.5)], radius=round(3 * e), outline=BLANCO, width=ancho)
    for linea in ((p(8, 2.5), p(8, 6.5)), (p(16, 2.5), p(16, 6.5)), (p(3, 10), p(21, 10))):
        d.line(linea, fill=BLANCO, width=ancho)
    d.line([p(9.5, 14.5), p(11.5, 16.5), p(15, 12.5)], fill=BLANCO, width=ancho, joint="curve")
    # Puntas redondas, como stroke-linecap="round" del SVG.
    r = ancho / 2
    for x, y in (p(8, 2.5), p(8, 6.5), p(16, 2.5), p(16, 6.5), p(9.5, 14.5), p(15, 12.5)):
        d.ellipse([x - r, y - r, x + r, y + r], fill=BLANCO)
    return img


def main() -> int:
    os.makedirs(DESTINO, exist_ok=True)
    creados = []

    def guardar(img: Image.Image, nombre: str, lado: int, **kwargs) -> None:
        ruta = os.path.join(DESTINO, nombre)
        img.resize((lado, lado), Image.LANCZOS).save(ruta, optimize=True, **kwargs)
        creados.append((nombre, os.path.getsize(ruta)))

    normal = _dibujar(a_sangre=False, glifo=24 / 36)
    # Zona segura de un icono maskable: circulo del 80 % del lado.
    maskable = _dibujar(a_sangre=True, glifo=0.5)

    guardar(normal, "favicon.ico", 48, format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    guardar(normal, "icono-192.png", 192, format="PNG")
    guardar(normal, "icono-512.png", 512, format="PNG")
    guardar(maskable, "icono-maskable-512.png", 512, format="PNG")
    guardar(_dibujar(a_sangre=True, glifo=0.58).convert("RGB"), "apple-touch-icon.png", 180, format="PNG")

    for nombre, peso in creados:
        print(f"  {peso:>7} B  static/img/{nombre}")
    print(f"OK: {len(creados)} archivos en static/img/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
