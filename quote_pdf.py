#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quote_pdf.py — Genera cotizaciones profesionales en PDF desde Python.

Enfoque: HTML + CSS → PDF con Chrome/Edge headless.
Ventaja frente a Word/LibreOffice: el layout es código, versionable y
reproducible. Ventaja frente a ReportLab: no hay que calcular coordenadas.

La empresa, el cliente, las partidas y las condiciones vienen de un archivo
JSON. Este script no sabe nada de ningún negocio en particular.

Uso:
    python quote_pdf.py --config examples/quote.example.json
    python quote_pdf.py --config mi_cotizacion.json --out salida/
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


# ───────────────────────────── Utilidades ──────────────────────────────

def money(value: float, symbol: str = "$") -> str:
    return f"{symbol}{value:,.2f}"


def find_browser() -> str | None:
    """Localiza Chrome o Edge. Se puede forzar con la variable BROWSER_BIN."""
    override = os.environ.get("BROWSER_BIN")
    if override and Path(override).exists():
        return override
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


def logo_data_uri(path: str | None) -> str:
    """Convierte el logo a data URI para que el HTML sea autocontenido."""
    if not path:
        return ""
    p = Path(path)
    if not p.exists():
        return ""
    suffix = p.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "svg": "image/svg+xml", "webp": "image/webp"}.get(suffix, "image/png")
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"


def slugify(text: str) -> str:
    """Nombre de archivo seguro, conservando legibilidad."""
    text = re.sub(r"[^\w\s.-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def make_folio(pattern: str = "%d%m%Y-XXXX") -> str:
    """Folio con fecha y 4 caracteres aleatorios."""
    today = dt.date.today().strftime("%d%m%Y")
    return pattern.replace("%d%m%Y", today).replace("XXXX", secrets.token_hex(2).upper())


def compute_lines(items: list[dict], margin: float) -> tuple[list[dict], float]:
    """
    Calcula precio unitario e importe por partida.

    Cada partida puede traer:
      * "price":  precio de venta unitario (se usa tal cual)
      * "cost":   costo unitario; se le aplica el margen configurado

    Si viene "cost", el precio de venta es cost / (1 - margin).
    Con margin = 0.30 → precio = costo / 0.70
    """
    lines = []
    subtotal = 0.0
    divisor = 1.0 - margin
    if divisor <= 0:
        raise SystemExit("El margen debe ser menor a 1.0 (por ejemplo 0.30 = 30%).")

    for item in items:
        qty = float(item.get("qty", 1))
        desc = item["description"]
        if "price" in item:
            unit = float(item["price"])
        elif "cost" in item:
            unit = float(item["cost"]) / divisor
        else:
            raise SystemExit(f"Partida sin 'price' ni 'cost': {desc[:40]}")

        unit = round(unit, 2)
        amount = round(unit * qty, 2)
        subtotal += amount
        lines.append({"qty": qty, "description": desc, "unit": unit, "amount": amount})

    return lines, round(subtotal, 2)


# ───────────────────────────── HTML ────────────────────────────────────

CSS = """
@page { size: __PAGE_SIZE__; margin: __MARGIN__; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: __FONT__; color: #1f2430; font-size: 11.5px; }
.head { display: flex; justify-content: space-between; align-items: center;
        border-bottom: 3px solid __ACCENT__; padding-bottom: 6px; }
.head .logo img { height: __LOGO_HEIGHT__; }
.head-right { text-align: right; }
.head-right h1 { font-size: 30px; color: __ACCENT__; letter-spacing: 2px; }
.head-right .folio, .head-right .cont { font-size: 11px; color: #64748b; }
.fecha { text-align: right; margin: 8px 0 6px; font-size: 11.5px; }
.bloques { display: flex; gap: 14px; margin-bottom: 10px; }
.bloque { flex: 1; border: 1px solid #cbd5e1; border-radius: 4px; padding: 8px 12px; }
.bloque h3 { font-size: 11px; color: __ACCENT__; text-transform: uppercase;
             letter-spacing: 1px; margin-bottom: 4px; }
.bloque p { font-size: 11px; margin: 1px 0; }
.bloque .rs { font-weight: 600; }
.titulo { text-align: center; font-size: 13px; font-weight: 700;
          color: __ACCENT__; margin: 8px 0; }
table.items { width: 100%; border-collapse: collapse; }
table.items th { background: __ACCENT__; color: #fff; font-size: 10.5px;
                 padding: 6px 8px; text-align: left; }
table.items td { border-bottom: 1px solid #e2e8f0; padding: 5px 8px;
                 font-size: 10.8px; vertical-align: top; }
.c { text-align: center; }
.r { text-align: right; white-space: nowrap; }
.totales { width: 45%; margin-left: auto; margin-top: 8px; border-collapse: collapse; }
.totales td { padding: 4px 8px; font-size: 11.5px; }
.totales .label { text-align: right; }
.totales .gran { background: __ACCENT_SOFT__; font-weight: 700; font-size: 13px; }
.cond { margin-top: 12px; }
.cond h3 { color: __ACCENT__; font-size: 12px; text-transform: uppercase;
           letter-spacing: 1px; margin-bottom: 6px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1px;
        background: #cbd5e1; border: 1px solid #cbd5e1; }
.cell { background: #fff; padding: 6px 10px; font-size: 11px; }
.cell b { color: __ACCENT__; display: block; font-size: 10px; text-transform: uppercase; }
.notes { margin-top: 10px; font-size: 10.5px; color: #475569; }
.notes li { margin: 2px 0 2px 16px; }
.thanks { margin-top: 12px; font-size: 11px; color: #475569; text-align: justify; }
.sign { margin-top: 18px; }
.sign .atent { font-size: 12px; font-weight: 600; }
.sign .name { font-size: 12px; font-weight: 700; margin-top: 22px; }
.sign .role { font-size: 11px; color: #475569; }
.anexo { page-break-before: always; }
.anexo h3 { color: __ACCENT__; font-size: 12.5px; text-transform: uppercase;
            border-bottom: 2px solid __ACCENT__; padding-bottom: 4px; margin-bottom: 8px; }
.anexo h4 { color: __ACCENT__; font-size: 11.5px; margin: 10px 0 4px; }
.anexo p, .anexo li { font-size: 10.8px; line-height: 1.45; text-align: justify; }
.anexo ul, .anexo ol { margin: 4px 0 8px 18px; }
.avoid { page-break-inside: avoid; }
"""


def render_css(style: dict) -> str:
    """
    Sustituye los tokens del CSS.

    Se usa reemplazo de texto y no str.format() a propósito: el CSS está lleno
    de llaves literales y format() las interpretaría como campos, fallando con
    KeyError. Los tokens __ASI__ no colisionan con nada del CSS.
    """
    values = {
        "__PAGE_SIZE__": style.get("page_size", "Letter"),
        "__MARGIN__": style.get("page_margin", "12mm 14mm"),
        "__FONT__": style.get("font", "'Segoe UI', Arial, sans-serif"),
        "__ACCENT__": style.get("accent", "#1A237E"),
        "__ACCENT_SOFT__": style.get("accent_soft", "#e8eaf6"),
        "__LOGO_HEIGHT__": style.get("logo_height", "58px"),
    }
    css = CSS
    for token, value in values.items():
        css = css.replace(token, value)
    return css


def build_html(cfg: dict) -> tuple[str, str]:
    """Devuelve (html, folio)."""
    brand = cfg["brand"]
    client = cfg["client"]
    style = cfg.get("style", {})
    tax = cfg.get("tax", {})
    cond = cfg.get("conditions", {})

    accent = style.get("accent", "#1A237E")
    accent_soft = style.get("accent_soft", "#e8eaf6")
    margin_pct = float(cfg.get("margin", 0.30))
    tax_rate = float(tax.get("rate", 0.16))
    tax_label = tax.get("label", "IVA")

    lines, subtotal = compute_lines(cfg["items"], margin_pct)
    tax_amount = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax_amount, 2)

    folio = cfg.get("folio") or make_folio(cfg.get("folio_pattern", "%d%m%Y-XXXX"))
    today = dt.date.today()
    date_line = cfg.get("date_line") or (
        f"{brand.get('city', '')}, a {today.day} de {MESES[today.month - 1]} de {today.year}"
    ).strip(", ")

    rows = "\n".join(
        f'<tr><td class="c">{int(l["qty"]) if l["qty"] == int(l["qty"]) else l["qty"]}</td>'
        f'<td>{l["description"]}</td>'
        f'<td class="r">{money(l["unit"], brand.get("currency_symbol", "$"))}</td>'
        f'<td class="r">{money(l["amount"], brand.get("currency_symbol", "$"))}</td></tr>'
        for l in lines
    )

    client_extra = ""
    if client.get("attention"):
        client_extra += f'<p><b>Atención:</b> {client["attention"]}</p>'
    if client.get("address"):
        client_extra += f"<p>{client['address']}</p>"
    if client.get("site"):
        client_extra += f'<p><b>Ubicación del servicio:</b> {client["site"]}</p>'

    issuer_lines = ""
    for key in ("legal_name", "tax_id", "address", "phone", "email"):
        if brand.get(key):
            label = {"legal_name": "Razón Social: ", "tax_id": "RFC: "}.get(key, "")
            cls = ' class="rs"' if key == "legal_name" else ""
            issuer_lines += f"<p{cls}>{label}{brand[key]}</p>"

    notes_html = ""
    if cfg.get("notes"):
        lis = "".join(f"<li>{n}</li>" for n in cfg["notes"])
        notes_html = f'<div class="notes"><ul>{lis}</ul></div>'

    anexo_html = ""
    if cfg.get("annex_html"):
        anexo_html = f'<div class="anexo">{cfg["annex_html"]}</div>'

    logo = logo_data_uri(brand.get("logo"))

    html = f"""<!DOCTYPE html>
<html lang="{cfg.get('lang', 'es')}"><head><meta charset="utf-8">
<title>{cfg.get('title', 'Cotización')} {folio}</title>
<style>{render_css(style)}</style></head><body>

<div class="head">
  <div class="logo">{f'<img src="{logo}" alt="{brand.get("name","")}">' if logo else ''}</div>
  <div class="head-right">
    <h1>{cfg.get('doc_label', 'COTIZACIÓN')}</h1>
    <div class="folio">Folio: {folio}</div>
    <div class="cont">{brand.get('phone','')}{' | ' if brand.get('phone') and brand.get('email') else ''}{brand.get('email','')}</div>
  </div>
</div>

<div class="fecha">{date_line}</div>

<div class="bloques">
  <div class="bloque">
    <h3>{cfg.get('client_label', 'Cliente')}</h3>
    <p class="rs">{client['name']}</p>
    {client_extra}
  </div>
  <div class="bloque">
    <h3>{cfg.get('issuer_label', 'Empresa Emisora')}</h3>
    <p class="rs">{brand['name']}</p>
    {issuer_lines}
  </div>
</div>

<div class="titulo">{cfg['title']}</div>

<table class="items">
  <tr>
    <th class="c" style="width:7%">{cfg.get('qty_header', 'CANT.')}</th>
    <th>{cfg.get('desc_header', 'CONCEPTO / DESCRIPCIÓN')}</th>
    <th class="c" style="width:15%">{cfg.get('unit_header', 'P. UNITARIO')}</th>
    <th class="c" style="width:15%">{cfg.get('amount_header', 'IMPORTE')}</th>
  </tr>
  {rows}
</table>

<table class="totales">
  <tr><td class="label">{cfg.get('subtotal_label', 'Subtotal')}:</td>
      <td class="r">{money(subtotal, brand.get('currency_symbol', '$'))}</td></tr>
  <tr><td class="label">{tax_label} ({tax_rate:.0%}):</td>
      <td class="r">{money(tax_amount, brand.get('currency_symbol', '$'))}</td></tr>
  <tr class="gran"><td class="label">{cfg.get('total_label', 'Total')}:</td>
      <td class="r">{money(total, brand.get('currency_symbol', '$'))}</td></tr>
</table>

{notes_html}

<div class="cond avoid">
  <h3>{cfg.get('conditions_label', 'Condiciones Comerciales')}</h3>
  <div class="grid">
    <div class="cell"><b>{cfg.get('validity_label', 'Vigencia')}</b>{cond.get('validity', '30 días')}</div>
    <div class="cell"><b>{cfg.get('currency_label', 'Moneda')}</b>{cond.get('currency', 'MXN')}</div>
    <div class="cell"><b>{cfg.get('delivery_label', 'Tiempo de entrega')}</b>{cond.get('delivery', 'Por confirmar')}</div>
    <div class="cell"><b>{cfg.get('payment_label', 'Términos de pago')}</b>{cond.get('payment', 'Por confirmar')}</div>
  </div>
</div>

<div class="thanks">{cfg.get('thanks', '')}</div>

<div class="sign avoid">
  <div class="atent">{cfg.get('closing', 'Atentamente')}</div>
  <div class="name">{cfg.get('signer_name', brand.get('name', ''))}</div>
  <div class="role">{cfg.get('signer_role', '')}</div>
</div>

{anexo_html}

</body></html>"""
    return html, folio


# ───────────────────────────── PDF ─────────────────────────────────────

def html_to_pdf(html_path: Path, pdf_path: Path, page_size: str = "Letter") -> bool:
    """
    Renderiza con Chrome/Edge headless.

    Truco importante: el PDF se escribe primero en la carpeta temporal.
    En Windows, Chrome a veces no puede escribir dentro de ciertos directorios
    (error 0x5) y el fallo es silencioso: no hay PDF y el código de salida es 0.
    """
    browser = find_browser()
    if not browser:
        print("ERROR: no se encontró Chrome ni Edge. Define BROWSER_BIN.", file=sys.stderr)
        return False

    tmp_pdf = Path(tempfile.gettempdir()) / f"_quote_{secrets.token_hex(4)}.pdf"
    profile = Path(tempfile.gettempdir()) / "quote_pdf_profile"

    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--user-data-dir={profile}",
        f"--print-to-pdf={tmp_pdf}",
        html_path.resolve().as_uri(),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    if tmp_pdf.exists() and tmp_pdf.stat().st_size > 0:
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp_pdf), str(pdf_path))
        return True

    print("ERROR: Chrome no produjo el PDF.", file=sys.stderr)
    if result.stderr:
        print(result.stderr[-800:], file=sys.stderr)
    return False


# ───────────────────────────── CLI ─────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Genera una cotización en PDF desde un JSON.")
    ap.add_argument("--config", required=True, help="JSON con los datos de la cotización")
    ap.add_argument("--out", default=".", help="Carpeta de salida (default: actual)")
    ap.add_argument("--html-only", action="store_true", help="Solo generar el HTML, sin PDF")
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"No existe el archivo: {cfg_path}", file=sys.stderr)
        return 1

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    html, folio = build_html(cfg)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    base = cfg.get("filename") or f"Cotizacion {cfg['client']['name']} {folio}"
    base = slugify(base)
    html_path = out_dir / f"{base}.html"
    pdf_path = out_dir / f"{base}.pdf"

    html_path.write_text(html, encoding="utf-8")
    print(f"HTML: {html_path}")

    if args.html_only:
        print(f"Folio: {folio}")
        return 0

    ok = html_to_pdf(html_path, pdf_path, cfg.get("style", {}).get("page_size", "Letter"))
    if ok:
        print(f"PDF : {pdf_path} ({pdf_path.stat().st_size:,} bytes)")
        print(f"Folio: {folio}")
        return 0

    print("El HTML quedó generado; abre el archivo para imprimir a PDF a mano.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
