"""Interfaz de línea de comandos del módulo.

    python -m modules.sanciones_uaf.cli build \
        --workspace /ruta/a/los/radares \
        --html docs/modulo_sanciones_uaf.html \
        --bundle docs/data/modulo_sanciones_uaf_v1.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .adapters import DEFAULT_WORKSPACE
from .bundle import build_bundle
from .render import render_html, write_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sanciones_uaf", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Construye el bundle y el HTML autocontenido.")
    b.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE,
                   help="Directorio que contiene los repositorios Radar_*.")
    b.add_argument("--html", type=Path, default=Path("docs/modulo_sanciones_uaf.html"))
    b.add_argument("--bundle", type=Path, default=Path("docs/data/modulo_sanciones_uaf_v1.json"))
    b.add_argument("--no-html", action="store_true", help="Sólo emite el bundle JSON.")

    c = sub.add_parser("check", help="Verifica los puertos de entrada sin escribir nada.")
    c.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)

    args = parser.parse_args(argv)

    if args.cmd == "check":
        from .adapters import collect_input

        payload = collect_input(args.workspace)
        for ps in payload.port_status:
            print(f"[{ps.status:8}] {ps.port_id:24} {ps.records:>8} registros — {ps.detail}")
        blocking = [p for p in payload.port_status
                    if p.port_id == "PORT_SANCIONES_EVENTS" and p.status == "ABSENT"]
        return 1 if blocking else 0

    bundle = build_bundle(workspace=args.workspace)
    out_bundle = write_bundle(bundle, args.bundle)
    print(f"bundle  → {out_bundle} ({out_bundle.stat().st_size / 1024:,.0f} KB)")
    if not args.no_html:
        out_html = render_html(bundle, args.html)
        print(f"html    → {out_html} ({out_html.stat().st_size / 1024:,.0f} KB)")

    k = bundle["kpis"]
    print(json.dumps({
        "sujetos": k["sujetos_totales"],
        "N1_inscritos_sancionados": k["n1_sancionados"],
        "N2_potenciales": k["n2_potenciales"],
        "N0_fuera": k["n0_fuera"],
        "tasa_N1": k["n1_tasa"],
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
