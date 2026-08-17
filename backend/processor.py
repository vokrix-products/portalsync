import csv
import datetime
import io
import json
import os
from typing import Any, Dict, List, Optional

TITLE_KEYS = [
    "insured_name",
    "policyholder_name",
    "insured",
    "policyholder",
    "name",
    "customer",
    "client",
    "supplier",
    "vendor",
    "employee_name",
    "employee",
    "company",
    "carrier_name",
    "policy_number",
]

ALLOWED_STATUSES = {
    "valid",
    "expiring",
    "expired",
    "missing",
    "flagged",
    "new",
    "duplicate",
    "login_required",
    "sync_error",
    "portal_change_required",
}

EXTRACTION_PROMPT = (
    "You are an extraction engine for insurance documents. "
    "Extract these fields from the document text: carrier name, document type, policy number, "
    "insured/policyholder name, effective date, expiration date, premium amount, commission rate, "
    "commission amount, transaction type, document date, statement period, source portal. "
    "Return ONLY valid JSON with keys: carrier_name, document_type, policy_number, insured_name, "
    "effective_date, expiration_date, premium_amount, commission_rate, commission_amount, transaction_type, "
    "document_date, statement_period, source_portal. "
    "Dates must be ISO-8601 strings. "
    "The title field MUST be the primary entity the buyer tracks (employee name, vendor name, contract party, "
    "patient name etc) — NEVER the document type or category. For these documents, the title is insured_name "
    "if present, otherwise policy_number. Do not output markdown."
)


def first_nonempty(mapping: Dict[str, Any], keys: List[str]) -> Optional[str]:
    for key in keys:
        val = mapping.get(key)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return None


def parse_date(value: Any) -> Optional[datetime.date]:
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    if not text:
        return None

    formats = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%m-%d-%Y",
        "%d/%m/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d %H:%M:%S",
    )
    for fmt in formats:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "")).date()
    except Exception:
        return None


def parse_date_from_row(row: Dict[str, Any]) -> Optional[str]:
    for key in (
        "expiration_date",
        "expiration",
        "end_date",
        "effective_date",
        "start_date",
        "due_date",
        "document_date",
        "date",
    ):
        val = row.get(key)
        if val is None:
            val = row.get(key.replace("_", " ").title())
        parsed = parse_date(val)
        if parsed:
            return parsed.isoformat()
    return None


def determine_status_from_row(row: Dict[str, Any]) -> str:
    exp = parse_date(
        row.get("expiration_date")
        or row.get("expiration")
        or row.get("end_date")
    )
    if exp:
        today = datetime.date.today()
        if exp < today:
            return "expired"
        if (exp - today).days <= 90:
            return "expiring"
        return "valid"
    return "new"


def extract_text_from_bytes(file_bytes: bytes) -> str:
    # Try PDF first.
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            page_texts = []
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text:
                    page_texts.append(page_text)

            if page_texts:
                return "\n".join(page_texts).strip()

            table_rows = []
            for page in pdf.pages:
                tables = page.extract_tables() or []
                for table in tables:
                    for row in table:
                        table_rows.append("\t".join(str(cell or "") for cell in row))

            if table_rows:
                return "\n".join(table_rows)
    except Exception:
        pass

    # Try Excel.
    try:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
        sheet_texts = []
        for ws in wb.worksheets:
            rows = []
            for row in ws.iter_rows(values_only=True):
                rows.append("\t".join("" if cell is None else str(cell) for cell in row))
            sheet_texts.append("\n".join(rows))
        wb.close()

        if sheet_texts and any(sheet.strip() for sheet in sheet_texts):
            return "\n".join(sheet_texts)
    except Exception:
        pass

    # Fallback: UTF-8 text/CSV.
    try:
        return file_bytes.decode("utf-8", errors="ignore").strip()
    except Exception:
        return ""


def parse_csv_records(text: str) -> List[Dict[str, Any]]:
    for delimiter in (",", "\t"):
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            rows = [row for row in reader]
            if not rows:
                continue

            # Accept the parsed header only if it contains a known entity field.
            if not any(key in TITLE_KEYS for key in rows[0].keys()):
                continue

            records = []
            useful = False
            for row in rows:
                if not any(v not in (None, "", [], {}) for v in row.values()):
                    continue

                useful = True
                title = first_nonempty(row, TITLE_KEYS)
                status = determine_status_from_row(row)
                details = {key: value for key, value in row.items() if value not in (None, "")}
                due_date = parse_date_from_row(row)

                records.append({
                    "title": title or "Untitled",
                    "status": status,
                    "details": details,
                    "due_date": due_date,
                })

            if useful:
                return records
        except Exception:
            continue

    return []


def strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.lstrip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip("`").strip()
    return text


def deepseek_extract(text: str) -> Optional[Dict[str, Any]]:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        response = client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": EXTRACTION_PROMPT},
                {"role": "user", "content": text[:12000]},
            ],
        )
        content = response.choices[0].message.content
        data = json.loads(strip_code_fence(content))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def derive_title_from_text(text: str) -> Optional[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines:
        return lines[0][:120]
    return None


def classify_status_from_data(data: Dict[str, Any]) -> str:
    exp = parse_date(data.get("expiration_date"))
    if exp:
        today = datetime.date.today()
        if exp < today:
            return "expired"
        if (exp - today).days <= 90:
            return "expiring"
        return "valid"
    return "new"


def build_record_from_structured(structured: Dict[str, Any]) -> Dict[str, Any]:
    title = first_nonempty(
        structured,
        [
            "insured_name",
            "policyholder_name",
            "insured",
            "policyholder",
            "name",
            "policy_number",
            "carrier_name",
        ],
    )
    due_date = (
        parse_date(structured.get("expiration_date"))
        or parse_date(structured.get("effective_date"))
        or parse_date(structured.get("document_date"))
    )
    status = classify_status_from_data(structured)
    details = {key: value for key, value in structured.items() if value not in (None, "")}

    return {
        "title": title or "Untitled",
        "status": status,
        "details": details,
        "due_date": due_date.isoformat() if due_date else None,
    }


def process_file(file_bytes: bytes) -> List[Dict[str, Any]]:
    text = extract_text_from_bytes(file_bytes)
    if not text:
        return []

    records = parse_csv_records(text)
    if records:
        return records

    structured = deepseek_extract(text)
    if structured:
        return [build_record_from_structured(structured)]

    fallback_title = derive_title_from_text(text)
    return [{
        "title": fallback_title or "Untitled",
        "status": "new",
        "details": {"raw_text": text[:2000]},
        "due_date": None,
    }]
