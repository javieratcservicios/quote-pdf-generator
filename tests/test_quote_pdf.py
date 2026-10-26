import json
import sys
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import quote_pdf as q  # noqa: E402

EXAMPLE = ROOT / "examples" / "quote.example.json"


def cfg():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_example_totals_unchanged():
    lines, subtotal = q.compute_lines(cfg()["items"], 0.30)
    assert subtotal == Decimal("139000.00")
    assert lines[2]["unit"] == Decimal("72000.00")  # 50400 / 0.70


def test_half_cent_rounds_up_not_bankers():
    # 0.125 con round() de Python da 0.12 (redondeo bancario).
    lines, subtotal = q.compute_lines([{"description": "x", "price": 0.125}], 0)
    assert lines[0]["unit"] == Decimal("0.13")


def test_float_noise_does_not_leak():
    # 0.1 + 0.2 en float es 0.30000000000000004
    _, subtotal = q.compute_lines(
        [{"description": "a", "price": 0.1}, {"description": "b", "price": 0.2}], 0)
    assert subtotal == Decimal("0.30")


def test_margin_must_be_below_one():
    with pytest.raises(SystemExit):
        q.compute_lines([{"description": "x", "cost": 1}], 1.0)


def test_html_is_escaped():
    c = cfg()
    c["items"] = [{"qty": 1, "description": "Válvula <2\"> & codo", "price": 10}]
    c["client"]["name"] = "Pérez & Hijos <SA>"
    html, _ = q.build_html(c, ROOT / "examples")
    assert "Válvula &lt;2&quot;&gt; &amp; codo" in html
    assert "Pérez &amp; Hijos &lt;SA&gt;" in html
    assert "<SA>" not in html


def test_annex_html_stays_raw():
    c = cfg()
    c["annex_html"] = "<h3>Anexo</h3>"
    html, _ = q.build_html(c, ROOT / "examples")
    assert "<h3>Anexo</h3>" in html


def test_client_tax_id_and_legal_name_shown():
    html, _ = q.build_html(cfg(), ROOT / "examples")
    assert "CDE020202XYZ" in html
    assert "Cliente Demostración S. de R.L." in html


def test_labels_translatable():
    c = cfg()
    c.update({"folio_label": "No.", "tax_id_label": "Tax ID",
              "attention_label": "Attn", "date_format": "{month} {day}, {year}",
              "months": ["January", "February", "March", "April", "May", "June",
                         "July", "August", "September", "October", "November",
                         "December"]})
    html, _ = q.build_html(c, ROOT / "examples")
    assert "No.:" in html and "Tax ID:" in html and "Attn:" in html
    assert "Folio:" not in html and "RFC:" not in html


def test_tax_percentage_not_truncated():
    assert q.pct(Decimal("0.16")) == "16%"
    assert q.pct(Decimal("0.105")) == "10.5%"


def test_logo_resolved_next_to_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # lejos del repo
    html, _ = q.build_html(cfg(), ROOT / "examples")
    assert "data:image/png;base64," in html
