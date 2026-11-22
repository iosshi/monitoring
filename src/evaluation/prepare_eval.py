"""Convert the KT2 CSV fixtures into the frozen JSONL format used by harness.py.

The supplied CSV has each data row wrapped and quote-escaped as a single outer
field. This converter repairs that export shape, validates all 80 rows, keeps
the original HTML for baseline comparison, and wraps non-error fragments in a
neutral page shell so the production page validator sees realistic page size.
No URL is fetched.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / "tests" / "eval" / "kt2_original.csv"
DEFAULT_OUTPUT = ROOT / "tests" / "eval" / "kt2_frozen.jsonl"
HEADERS = ["pair_id", "url", "before_html", "after_html", "expected", "note"]
LABELS = {"significant": "significant", "noise": "insignificant", "error": "error"}


def read_source(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if not lines or next(csv.reader([lines[0]])) != HEADERS:
        raise ValueError("Unexpected KT2 eval CSV header")
    records = []
    for line_number, line in enumerate(lines[1:], 2):
        # The public export encloses each entire CSV row in quotes and doubles
        # the quotes inside it. Undo that outer wrapper before normal CSV parse.
        if line.startswith('"') and line.endswith('"'):
            line = line[1:-1].replace('""', '"')
        fields = next(csv.reader([line]))
        if len(fields) != len(HEADERS):
            raise ValueError(f"Malformed CSV row {line_number}: expected 6 columns, got {len(fields)}")
        records.append(dict(zip(HEADERS, fields)))
    if len(records) != 80:
        raise ValueError(f"Expected 80 KT2 examples, got {len(records)}")
    ids = [record["pair_id"] for record in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate pair_id in KT2 CSV")
    unknown = sorted({record["expected"] for record in records} - LABELS.keys())
    if unknown:
        raise ValueError(f"Unknown KT2 labels: {unknown}")
    return records


def _price_and_currency(html: str) -> tuple[int | float | None, str | None]:
    # Prefer a labeled price, and reject ranges as a single ground-truth value.
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    if re.search(r"от\s*\d[\d\s]*\s+до\s+\d", text, flags=re.I):
        return None, None
    match = re.search(
        r"цена\s*:?\s*(\d[\d\s]*(?:[.,]\d{1,2})?)\s*(руб(?:\.|лей|ля)?|₽|RUB|USD|\$)",
        text, flags=re.I,
    )
    if match:
        value = float(match.group(1).replace(" ", "").replace(",", "."))
        currency_token = match.group(2).lower()
        currency = "USD" if currency_token in {"usd", "$"} else "RUB"
        return (int(value) if value.is_integer() else value), currency
    json_price = re.search(r"['\"]price['\"]\s*:\s*['\"]?(\d+(?:[.,]\d+)?)", html, flags=re.I)
    if json_price:
        value = float(json_price.group(1).replace(",", "."))
        return (int(value) if value.is_integer() else value), None
    return None, None


def _snapshot_from_html(url: str, pair_id: str, html: str) -> dict[str, Any]:
    price, currency = _price_and_currency(html)
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()
    availability = None
    if any(term in text for term in ("нет в наличии", "не в наличии", "товар закончился")):
        availability = "out of stock"
    elif "в наличии" in text:
        availability = "in stock"
    elif "под заказ" in text:
        availability = "под заказ"
    elif "предзаказ" in text:
        availability = "предзаказ"
    snapshot: dict[str, Any] = {
        "source_url": url,
        "product_name": f"Тестовый товар {pair_id}",
        "price": price,
        "currency": currency,
        "discount": None,
        "availability": availability,
        "delivery_conditions": None,
        "payment_conditions": None,
        "warranty_conditions": None,
    }
    if "скидка" in text or "промокод" in text or "кэшбэк" in text:
        snapshot["discount"] = text
    if "достав" in text:
        snapshot["delivery_conditions"] = text
    if "оплат" in text:
        snapshot["payment_conditions"] = text
    if "гарант" in text:
        snapshot["warranty_conditions"] = text
    return snapshot


def _expected_fields(record: dict[str, str]) -> list[str]:
    note = record["note"].lower()
    fields = []
    if record["expected"] == "significant":
        if "цен" in note:
            fields.append("price")
        if "валют" in note:
            fields.append("currency")
        if "налич" in note or "остат" in note:
            fields.append("availability")
        if "достав" in note or "получен" in note:
            fields.append("delivery_conditions")
        if "возврат" in note:
            fields.append("return_conditions")
        if "гарант" in note:
            fields.append("warranty_conditions")
        if "оплат" in note:
            fields.append("payment_conditions")
        if "акци" in note or "скид" in note or "промокод" in note or "кэшбэк" in note:
            fields.append("discount")
        if "комплектац" in note:
            fields.append("configuration")
        if "статус" in note:
            fields.append("product_status")
    elif record["expected"] == "noise":
        # Noise may still contain a factual but below-threshold product-field
        # change. Keep that separate from the significance label.
        old_price, old_currency = _price_and_currency(record["before_html"])
        new_price, new_currency = _price_and_currency(record["after_html"])
        if old_price is not None and new_price is not None and old_price != new_price:
            fields.append("price")
        if (old_currency is not None and new_currency is not None
                and old_currency != new_currency):
            fields.append("currency")
    if record["expected"] == "significant" and not fields:
        fields.append("other_condition")
    return sorted(set(fields))


def _page_shell(fragment: str, pair_id: str) -> str:
    # Synthetic source rows contain snippets, not complete pages. Neutral copy
    # makes ordinary examples pass the same minimum-content validator as live
    # pages; error examples remain raw so the production validator rejects them.
    filler = ("Описание тестового товара. Проверка цены, наличия и условий продажи. " * 3)
    return (f"<!doctype html><html><head><title>Тестовый товар {pair_id}</title></head>"
            f"<body><main>{fragment}</main><section>{filler}</section></body></html>")


def convert(records: list[dict[str, str]]) -> tuple[list[dict[str, Any]], Counter]:
    output = []
    counts: Counter = Counter()
    for record in records:
        expected = LABELS[record["expected"]]
        url = record["url"].strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        current_html = record["after_html"]
        if expected != "error":
            current_html = _page_shell(current_html, record["pair_id"])
        row = {
            "id": record["pair_id"],
            "url": url,
            "product_description": f"Тестовый товар {record['pair_id']}",
            "significance_criteria": [
                "Изменение цены на 5% и более считается значимым",
                "Изменение наличия и условий продажи считается значимым",
            ],
            "previous_html": record["before_html"],
            "baseline_current_html": record["after_html"],
            "current_html": current_html,
            "previous_snapshot": _snapshot_from_html(url, record["pair_id"], record["before_html"]),
            "expected_status": expected,
            "expected_fields": _expected_fields(record),
            "source_expected": record["expected"],
            "note": record["note"],
        }
        output.append(row)
        counts[expected] += 1
    return output, counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    records = read_source(args.source)
    rows, counts = convert(records)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(rows)} rows to {args.output}")
    print("Class counts:", json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
