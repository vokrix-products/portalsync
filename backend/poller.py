"""PortalSync poller.

Polls the shared jobs table for pending portalsync process_upload jobs,
downloads the uploaded document from Supabase Storage, runs the extraction
processor, writes normalized records into the records table, and marks the
job completed. Also scans records for documents expiring soon or overdue
and creates dashboard notifications.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import requests
import processor

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
PRODUCT_ID = os.environ["PRODUCT_ID"]
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "60"))
SCAN_INTERVAL_SECONDS = int(os.environ.get("SCAN_INTERVAL_SECONDS", "600"))
EXPIRY_WINDOW_DAYS = int(os.environ.get("EXPIRY_WINDOW_DAYS", "14"))
SUPABASE_REST = f"{SUPABASE_URL}/rest/v1"


def get_headers():
    return {
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "apikey": SUPABASE_SERVICE_KEY,
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def download_file(bucket, file_path):
    if file_path.startswith(bucket + "/"):
        file_path = file_path[len(bucket) + 1:]
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{file_path}"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {SUPABASE_SERVICE_KEY}", "apikey": SUPABASE_SERVICE_KEY},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.content


def update_job(job_id, payload):
    url = f"{SUPABASE_REST}/jobs?id=eq.{job_id}"
    resp = requests.patch(url, headers=get_headers(), json=payload, timeout=30)
    resp.raise_for_status()


def insert_records(rows):
    url = f"{SUPABASE_REST}/records"
    resp = requests.post(url, headers=get_headers(), json=rows, timeout=60)
    resp.raise_for_status()


def process_job(job):
    job_id = job.get("id")
    customer_id = job.get("customer_id")
    input_path = job.get("input_file_path") or ""
    try:
        if not input_path:
            raise ValueError("No input file path on job")
        file_bytes = download_file("uploads", input_path)
        records = processor.process_file(file_bytes)
        if not records:
            raise ValueError("No records extracted")

        rows = []
        for rec in records:
            row = {
                "product_id": PRODUCT_ID,
                "customer_id": customer_id,
                "title": rec.get("title") or "Unknown",
                "status": rec.get("status") or "new",
                "details": rec.get("details") if isinstance(rec.get("details"), dict) else rec,
                "source_file_path": input_path,
            }
            if rec.get("due_date"):
                row["due_date"] = rec["due_date"]
            rows.append(row)

        insert_records(rows)
        update_job(job_id, {
            "status": "completed",
            "result_summary": f"Processed {len(rows)} records",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        print(f"completed job {job_id}: {len(rows)} records")
    except Exception as exc:
        now = datetime.now(timezone.utc).isoformat()
        try:
            update_job(job_id, {
                "status": "failed",
                "result_summary": str(exc)[:500],
                "error_message": str(exc)[:500],
                "completed_at": now,
            })
        except Exception:
            pass
        print(f"failed job {job_id}: {exc}")


def parse_dt(value):
    """Parse an ISO-8601 timestamp (possibly with Z) into a tz-aware datetime."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def notification_exists(customer_id, title, ntype, hours=24):
    """True if a notification with this title/type exists for the customer recently (dedup)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    params = {
        "select": "id",
        "product_id": f"eq.{PRODUCT_ID}",
        "customer_id": f"eq.{customer_id}",
        "title": f"eq.{title}",
        "type": f"eq.{ntype}",
        "created_at": f"gt.{since}",
        "limit": "1",
    }
    resp = requests.get(
        f"{SUPABASE_REST}/notifications",
        headers=get_headers(),
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    return len(resp.json()) > 0


def insert_notifications(rows):
    url = f"{SUPABASE_REST}/notifications"
    resp = requests.post(url, headers=get_headers(), json=rows, timeout=60)
    resp.raise_for_status()


def scan_expirations():
    """Create bell notifications for documents expiring soon or already overdue."""
    now = datetime.now(timezone.utc)
    window_end = (now + timedelta(days=EXPIRY_WINDOW_DAYS)).isoformat()
    params = {
        "select": "id,title,customer_id,due_date,status",
        "product_id": f"eq.{PRODUCT_ID}",
        "is_demo": "eq.false",
        "due_date": f"lte.{window_end}",
        "limit": "500",
    }
    resp = requests.get(
        f"{SUPABASE_REST}/records",
        headers=get_headers(),
        params=params,
        timeout=30,
    )
    resp.raise_for_status()
    records = resp.json()

    created = 0
    for rec in records:
        due = parse_dt(rec.get("due_date"))
        if due is None:
            continue
        customer_id = rec.get("customer_id")
        if not customer_id:
            continue
        title = rec.get("title") or "Unknown"
        overdue = due < now
        ntype = "error" if overdue else "warning"
        prefix = "Overdue" if overdue else "Expiring soon"
        body = f"Due {due.date().isoformat()}" if not overdue else f"Was due {due.date().isoformat()}"
        ntitle = f"{prefix}: {title}"
        try:
            if notification_exists(customer_id, ntitle, ntype):
                continue
            insert_notifications([{
                "product_id": PRODUCT_ID,
                "customer_id": customer_id,
                "title": ntitle,
                "body": body,
                "type": ntype,
            }])
            created += 1
        except Exception as exc:
            print(f"scan notification error for {title}: {exc}")
    print(f"expiration scan: {len(records)} due/overdue, {created} new notifications")


def poll():
    last_scan = 0.0
    while True:
        try:
            params = {
                "select": "*",
                "status": "eq.pending",
                "product_id": f"eq.{PRODUCT_ID}",
                "order": "created_at.asc",
            }
            resp = requests.get(
                f"{SUPABASE_REST}/jobs",
                headers=get_headers(),
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            for job in resp.json():
                process_job(job)
        except Exception:
            pass

        if time.time() - last_scan >= SCAN_INTERVAL_SECONDS:
            try:
                scan_expirations()
                last_scan = time.time()
            except Exception as exc:
                print(f"expiration scan failed: {exc}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    print(f"PortalSync poller started (product_id={PRODUCT_ID})")
    poll()
