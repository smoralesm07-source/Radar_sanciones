"""Renderizado del módulo a HTML autocontenido.

La plantilla declara un punto de montaje ``RadarSancionesUAF.mount(el, bundle)``.
El HTML autocontenido inyecta el bundle y se auto-monta; el cockpit IFL puede
cargar el mismo JS y montar el módulo en cualquier contenedor.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

TEMPLATE = Path(__file__).parent / "templates" / "module.html"
PLACEHOLDER = "/*__BUNDLE__*/null"


def render_html(bundle: dict[str, Any], output: str | Path,
                template: str | Path | None = None) -> Path:
    """Escribe el HTML autocontenido con el bundle embebido."""
    tpl_path = Path(template) if template else TEMPLATE
    html = tpl_path.read_text(encoding="utf-8")
    if PLACEHOLDER not in html:
        raise ValueError(f"La plantilla {tpl_path} no declara el marcador {PLACEHOLDER}")
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    # Evita cerrar el <script> desde dentro de la cadena JSON.
    payload = payload.replace("</", "<\\/")
    html = html.replace(PLACEHOLDER, payload)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def write_bundle(bundle: dict[str, Any], output: str | Path) -> Path:
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
