from __future__ import annotations
import csv, io, os, re, tempfile, zipfile
from .common import SourceHealth, now_iso, norm_rut, sha256_bytes, UA
import requests

SOURCES={
 "names":"https://www.sii.cl/estadisticas/nominas/PUB_NOMBRES_PJ.zip",
 "activities":"https://www.sii.cl/estadisticas/nominas/PUB_NOM_ACTECOS.zip",
 "companies":"https://www.sii.cl/estadisticas/nominas/PUB_EMPRESAS_PJ_2020_A_2024.zip",
}

def _decode(b:bytes)->str:
    for enc in ("latin-1","cp1252","utf-8-sig","utf-8"):
        try:return b.decode(enc)
        except UnicodeDecodeError:pass
    return b.decode("latin-1",errors="replace")

def _delimiter(sample:str)->str:
    return "\t" if sample.count("\t")>=sample.count(";") else ";"

def collect_sii(registry:list[dict], enabled:bool=False):
    h=SourceHealth(source="SII",checked_at=now_iso(),url="https://www.sii.cl/sobre_el_sii/nominapersonasjuridicas.html",mode="bulk")
    if not enabled:
        h.fetch_status="skipped"; h.parse_status="scheduled_weekly"; h.message="Carga masiva deshabilitada en corrida diaria; se habilita con RADAR_SII=1."; return {},h.to_dict()
    wanted={norm_rut(x.get("rut")) for x in registry if norm_rut(x.get("rut"))}
    out={}; total_rows=0; hashes=[]
    try:
        for kind,url in SOURCES.items():
            r=requests.get(url,headers={"User-Agent":UA},timeout=120); h.http_status=r.status_code
            r.raise_for_status(); hashes.append(sha256_bytes(r.content))
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                for name in z.namelist():
                    if name.endswith("/"): continue
                    text=_decode(z.read(name)); delim=_delimiter(text[:5000]); reader=csv.reader(io.StringIO(text),delimiter=delim)
                    for row in reader:
                        total_rows+=1
                        if not row: continue
                        rut=norm_rut(row[0])
                        if rut not in wanted: continue
                        rec=out.setdefault(rut,{"rut":rut})
                        if kind=="names": rec.setdefault("sii_nombre_raw",row)
                        elif kind=="activities": rec.setdefault("sii_actividades_raw",[]).append(row)
                        elif kind=="companies": rec.setdefault("sii_empresas_raw",[]).append(row)
        h.fetch_status="ok"; h.parse_status="ok"; h.rows_seen=total_rows; h.events_emitted=len(out); h.content_sha256=sha256_bytes("|".join(hashes).encode())
    except Exception as exc:
        h.fetch_status="error"; h.parse_status="error"; h.message=f"{type(exc).__name__}: {exc}"
    return out,h.to_dict()
