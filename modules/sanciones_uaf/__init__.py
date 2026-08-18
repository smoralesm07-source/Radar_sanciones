"""Módulo acoplable **Radar Sanciones ↔ UAF**.

Cruza las sanciones publicadas por los supervisores prudenciales contra el
perímetro de sujetos obligados de la UAF, en dos niveles:

* Nivel 1 — sujetos obligados inscritos que figuran en alguna sanción.
* Nivel 2 — potenciales sujetos obligados (actividad vigente en SII sin
  inscripción UAF) que presentan marca de sanción.

Uso mínimo::

    from modules.sanciones_uaf import build_bundle, render_html

    bundle = build_bundle()
    render_html(bundle, "docs/modulo_sanciones_uaf.html")
"""

from .bundle import build_bundle
from .contracts import BUNDLE_SCHEMA, MODULE_ID, MODULE_VERSION, PORTS, ModuleInput
from .render import render_html

__all__ = [
    "BUNDLE_SCHEMA",
    "MODULE_ID",
    "MODULE_VERSION",
    "PORTS",
    "ModuleInput",
    "build_bundle",
    "render_html",
]

__version__ = MODULE_VERSION
