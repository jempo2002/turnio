from __future__ import annotations

from flask import Blueprint, g, redirect, url_for

from app.utils.decorators import login_required

core = Blueprint("core", __name__)


@core.get("/inicio")
@login_required
def inicio():
    # Enlaces viejos y marcadores: el negocio entra por su agenda (T7). Lo que
    # mostraba esta pagina (el plan y sus funciones) esta en Ajustes.
    if g.es_master:
        return redirect(url_for("master.panel"))
    return redirect(url_for("panel.citas"))
