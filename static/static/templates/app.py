Last file.

Add file → Create new file
Name it app.py
Paste everything below, then Commit changes.

This version already has Rivky, $30, overtime 1.5, and week starting Sunday.
text#!/usr/bin/env python3
"""Nook — local-only hours and pay tracker. Standard library only."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "nook.db"
HOST = "127.0.0.1"
PORT = 5055

DEFAULTS = {
    "her_name": "Rivky",
    "hourly_rate": "30",
    "currency": "$",
    "overtime_after": "40",
    "overtime_multiplier": "1.5",
    "week_starts": "6",
}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".ico": "image/x-icon",
}


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clock_in TEXT NOT NULL,
                clock_out TEXT,
                note TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'now'
            );
            CREATE TABLE IF NOT EXISTS bonuses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paid_on TEXT NOT NULL,
                amount REAL NOT NULL,
                note TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                paid_on TEXT NOT NULL,
                amount REAL NOT NULL,
                note TEXT NOT NULL DEFAULT ''
            );
            """
        )
        for key, value in DEFAULTS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )


def get_settings() -> dict:
    with db() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    data = dict(DEFAULTS)
    data.update({row["key"]: row["value"] for row in rows})
    return data


def parse_dt(value: str) -> datetime:
    value = (value or "").strip()
    for fmt in (
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y %I:%M %p",
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%H:%M",
        "%I:%M %p",
        "%I:%M%p",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Could not read date/time: {value}")


def parse_time_on_date(date_s: str, time_s: str) -> datetime:
    date_s = (date_s or "").strip()
    time_s = (time_s or "").strip()
    if "T" in date_s and not time_s:
        return parse_dt(date_s)
    if not time_s:
        return parse_dt(date_s)
    for combo in (f"{date_s} {time_s}", f"{date_s}T{time_s}"):
        try:
            return parse_dt(combo)
        except ValueError:
            continue
    d = parse_dt(date_s)
    t = parse_dt(time_s)
    return datetime(d.year, d.month, d.day, t.hour, t.minute, t.second)


def hours_between(start: datetime, end: datetime) -> float:
    if end < start:
        end += timedelta(days=1)
    return round((end - start).total_seconds() / 3600.0, 4)


def week_bounds(day: datetime, week_starts: int) -> tuple[datetime, datetime]:
    weekday = day.weekday()
    delta = (weekday - week_starts) % 7
    start = datetime(day.year, day.month, day.day) - timedelta(days=delta)
    return start, start + timedelta(days=7)


def month_bounds(day: datetime) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, 1)
    if day.month == 12:
        end = datetime(day.year + 1, 1, 1)
    else:
        end = datetime(day.year, day.month + 1, 1)
    return start, end


def shift_hours(shift: sqlite3.Row, now: datetime | None = None) -> float:
    start = parse_dt(shift["clock_in"])
    end = parse_dt(shift["clock_out"]) if shift["clock_out"] else (now or datetime.now())
    return hours_between(start, end)


def load_shifts(conn: sqlite3.Connection):
    return conn.execute("SELECT * FROM shifts ORDER BY clock_in DESC, id DESC").fetchall()


def pay_for_hours(hours: float, settings: dict) -> dict:
    rate = float(settings.get("hourly_rate") or 0)
    ot_after = float(settings.get("overtime_after") or 40)
    ot_mult = float(settings.get("overtime_multiplier") or 1.5)
    regular = min(hours, ot_after)
    overtime = max(0.0, hours - ot_after)
    regular_pay = regular * rate
    overtime_pay = overtime * rate * ot_mult
    return {
        "hours": round(hours, 2),
        "regular_hours": round(regular, 2),
        "overtime_hours": round(overtime, 2),
        "regular_pay": round(regular_pay, 2),
        "overtime_pay": round(overtime_pay, 2),
        "wage_pay": round(regular_pay + overtime_pay, 2),
    }


def summarize(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    settings = get_settings()
    week_starts = int(settings.get("week_starts") or 0)
    week_start, week_end = week_bounds(now, week_starts)
    month_start, month_end = month_bounds(now)
    today_start = datetime(now.year, now.month, now.day)
    today_end = today_start + timedelta(days=1)

    with db() as conn:
        shifts = load_shifts(conn)
        bonuses = conn.execute("SELECT * FROM bonuses ORDER BY paid_on DESC, id DESC").fetchall()
        payments = conn.execute("SELECT * FROM payments ORDER BY paid_on DESC, id DESC").fetchall()
        open_shift = conn.execute(
            "SELECT * FROM shifts WHERE clock_out IS NULL ORDER BY clock_in DESC LIMIT 1"
        ).fetchone()

    def hours_in(start: datetime, end: datetime) -> float:
        total = 0.0
        for shift in shifts:
            s = parse_dt(shift["clock_in"])
            e = parse_dt(shift["clock_out"]) if shift["clock_out"] else now
            if e < s:
                e += timedelta(days=1)
            overlap_start = max(s, start)
            overlap_end = min(e, end)
            if overlap_end > overlap_start:
                total += (overlap_end - overlap_start).total_seconds() / 3600.0
        return total

    def sum_amount(rows, start=None, end=None) -> float:
        total = 0.0
        for row in rows:
            when = parse_dt(row["paid_on"])
            if start and when < start:
                continue
            if end and when >= end:
                continue
            total += float(row["amount"])
        return total

    today_h = hours_in(today_start, today_end)
    week_h = hours_in(week_start, week_end)
    month_h = hours_in(month_start, month_end)
    all_h = hours_in(datetime(2000, 1, 1), now + timedelta(days=1))
    week_pay = pay_for_hours(week_h, settings)
    month_pay = pay_for_hours(month_h, settings)
    all_pay = pay_for_hours(all_h, settings)
    bonuses_all = sum_amount(bonuses)
    bonuses_week = sum_amount(bonuses, week_start, week_end)
    bonuses_month = sum_amount(bonuses, month_start, month_end)
    paid_all = sum_amount(payments)
    paid_week = sum_amount(payments, week_start, week_end)
    paid_month = sum_amount(payments, month_start, month_end)
    earned_all = all_pay["wage_pay"] + bonuses_all
    earned_week = week_pay["wage_pay"] + bonuses_week
    earned_month = month_pay["wage_pay"] + bonuses_month

    return {
        "now": now.strftime("%Y-%m-%dT%H:%M"),
        "settings": settings,
        "open_shift": dict(open_shift) if open_shift else None,
        "today": {"hours": round(today_h, 2)},
        "week": {
            **week_pay,
            "start": week_start.strftime("%Y-%m-%d"),
            "end": (week_end - timedelta(days=1)).strftime("%Y-%m-%d"),
            "bonuses": round(bonuses_week, 2),
            "earned": round(earned_week, 2),
            "paid": round(paid_week, 2),
        },
        "month": {
            **month_pay,
            "start": month_start.strftime("%Y-%m-%d"),
            "label": month_start.strftime("%B %Y"),
            "bonuses": round(bonuses_month, 2),
            "earned": round(earned_month, 2),
            "paid": round(paid_month, 2),
        },
        "all": {
            **all_pay,
            "bonuses": round(bonuses_all, 2),
            "earned": round(earned_all, 2),
            "paid": round(paid_all, 2),
            "owed": round(earned_all - paid_all, 2),
        },
        "shifts": [dict(s) | {"hours": round(shift_hours(s, now), 2)} for s in shifts[:200]],
        "bonuses": [dict(b) for b in bonuses],
        "payments": [dict(p) for p in payments],
    }


def save_settings(payload: dict) -> dict:
    allowed = set(DEFAULTS)
    with db() as conn:
        for key, value in payload.items():
            if key in allowed:
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, str(value).strip()),
                )
    return summarize()


def punch(payload: dict) -> dict:
    mode = payload.get("mode", "now")
    note = (payload.get("note") or "").strip()
    now = datetime.now().replace(second=0, microsecond=0)
    with db() as conn:
        open_shift = conn.execute(
            "SELECT * FROM shifts WHERE clock_out IS NULL ORDER BY clock_in DESC LIMIT 1"
        ).fetchone()
        if mode == "custom":
            clock_in = parse_time_on_date(
                payload.get("date") or now.strftime("%Y-%m-%d"),
                payload.get("clock_in") or "",
            )
            out_raw = (payload.get("clock_out") or "").strip()
            clock_out = (
                parse_time_on_date(payload.get("date") or clock_in.strftime("%Y-%m-%d"), out_raw)
                if out_raw
                else None
            )
            if clock_out and clock_out <= clock_in:
                clock_out += timedelta(days=1)
            conn.execute(
                "INSERT INTO shifts(clock_in, clock_out, note, source) VALUES (?, ?, ?, ?)",
                (
                    clock_in.strftime("%Y-%m-%d %H:%M"),
                    clock_out.strftime("%Y-%m-%d %H:%M") if clock_out else None,
                    note,
                    "custom",
                ),
            )
        elif mode == "out":
            if not open_shift:
                raise ValueError("Not punched in.")
            when = now
            if payload.get("clock_out"):
                when = parse_time_on_date(
                    payload.get("date") or parse_dt(open_shift["clock_in"]).strftime("%Y-%m-%d"),
                    payload.get("clock_out"),
                )
            conn.execute(
                "UPDATE shifts SET clock_out=?, note=CASE WHEN ?!='' THEN ? ELSE note END WHERE id=?",
                (when.strftime("%Y-%m-%d %H:%M"), note, note, open_shift["id"]),
            )
        else:
            if open_shift:
                raise ValueError("Already punched in. Punch out first.")
            when = now
            if payload.get("clock_in"):
                when = parse_time_on_date(
                    payload.get("date") or now.strftime("%Y-%m-%d"),
                    payload.get("clock_in"),
                )
            conn.execute(
                "INSERT INTO shifts(clock_in, clock_out, note, source) VALUES (?, NULL, ?, ?)",
                (
                    when.strftime("%Y-%m-%d %H:%M"),
                    note,
                    "now" if not payload.get("clock_in") else "custom",
                ),
            )
    return summarize()


def add_money(table: str, payload: dict) -> dict:
    amount = float(payload.get("amount") or 0)
    if amount == 0:
        raise ValueError("Enter an amount.")
    paid_on = (payload.get("paid_on") or datetime.now().strftime("%Y-%m-%d")).strip()
    parse_dt(paid_on)
    with db() as conn:
        conn.execute(
            f"INSERT INTO {table}(paid_on, amount, note) VALUES (?, ?, ?)",
            (paid_on[:10], amount, (payload.get("note") or "").strip()),
        )
    return summarize()


def delete_row(table: str, row_id: int) -> dict:
    if table not in {"shifts", "bonuses", "payments"}:
        raise ValueError("Unknown table")
    with db() as conn:
        conn.execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
    return summarize()


def import_csv(raw: str) -> dict:
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames:
        raise ValueError("CSV needs a header row.")

    def pick(row: dict, *names: str) -> str:
        lower = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        for name in names:
            if name in lower and lower[name]:
                return lower[name]
        return ""

    added = 0
    errors = []
    with db() as conn:
        for i, row in enumerate(reader, start=2):
            date_s = pick(row, "date", "day", "worked")
            in_s = pick(row, "in", "clock in", "clock_in", "start", "time in")
            out_s = pick(row, "out", "clock out", "clock_out", "end", "time out")
            hours_s = pick(row, "hours", "hrs", "hour")
            note = pick(row, "note", "notes", "comment")
            try:
                if not date_s:
                    raise ValueError("missing date")
                if hours_s and not in_s:
                    d = parse_dt(date_s)
                    clock_in = datetime(d.year, d.month, d.day, 9, 0)
                    clock_out = clock_in + timedelta(hours=float(hours_s))
                else:
                    clock_in = parse_time_on_date(date_s, in_s or "09:00")
                    clock_out = parse_time_on_date(date_s, out_s) if out_s else None
                    if clock_out and clock_out <= clock_in:
                        clock_out += timedelta(days=1)
                conn.execute(
                    "INSERT INTO shifts(clock_in, clock_out, note, source) VALUES (?, ?, ?, ?)",
                    (
                        clock_in.strftime("%Y-%m-%d %H:%M"),
                        clock_out.strftime("%Y-%m-%d %H:%M") if clock_out else None,
                        note,
                        "import",
                    ),
                )
                added += 1
            except Exception as exc:
                errors.append(f"Row {i}: {exc}")
    state = summarize()
    state["import_result"] = {"added": added, "errors": errors[:12]}
    return state


def export_csv() -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "in", "out", "hours", "note", "source"])
    with db() as conn:
        for shift in load_shifts(conn):
            start = parse_dt(shift["clock_in"])
            end = parse_dt(shift["clock_out"]) if shift["clock_out"] else None
            writer.writerow(
                [
                    start.strftime("%Y-%m-%d"),
                    start.strftime("%H:%M"),
                    end.strftime("%H:%M") if end else "",
                    f"{shift_hours(shift):.2f}",
                    shift["note"],
                    shift["source"],
                ]
            )
    return output.getvalue().encode("utf-8")


def parse_multipart_file(headers: dict, body: bytes) -> str:
    ctype = headers.get("Content-Type", "")
    if "multipart/form-data" not in ctype:
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
            return payload.get("csv") or ""
        except Exception:
            return ""
    boundary = ""
    for part in ctype.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part.split("=", 1)[1].strip().strip('"')
    if not boundary:
        return ""
    marker = b"--" + boundary.encode()
    chunks = body.split(marker)
    for chunk in chunks:
        if b"filename=" not in chunk:
            continue
        head, _, file_body = chunk.partition(b"\r\n\r\n")
        return file_body.rstrip(b"\r\n-").decode("utf-8-sig", errors="replace")
    return ""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def send(self, code: int, body: bytes, content_type: str, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, code=200):
        raw = json.dumps(data).encode("utf-8")
        self.send(code, raw, "application/json; charset=utf-8")

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        try:
            if path == "/":
                html = (ROOT / "templates" / "index.html").read_bytes()
                return self.send(200, html, "text/html; charset=utf-8")
            if path == "/api/state":
                return self.send_json(summarize())
            if path == "/api/export":
                return self.send(
                    200,
                    export_csv(),
                    "text/csv; charset=utf-8",
                    {"Content-Disposition": "attachment; filename=nook-hours.csv"},
                )
            if path.startswith("/static/"):
                target = (ROOT / path.lstrip("/")).resolve()
                if ROOT.resolve() not in target.parents and target.parent != ROOT.resolve():
                    return self.send(403, b"forbidden", "text/plain")
                if not target.is_file():
                    return self.send(404, b"not found", "text/plain")
                return self.send(200, target.read_bytes(), MIME.get(target.suffix, "application/octet-stream"))
            self.send(404, b"not found", "text/plain")
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/settings":
                return self.send_json(save_settings(self.read_json()))
            if path == "/api/punch":
                return self.send_json(punch(self.read_json()))
            if path.startswith("/api/shift/") and path.endswith("/delete"):
                return self.send_json(delete_row("shifts", int(path.split("/")[3])))
            if path == "/api/bonus":
                return self.send_json(add_money("bonuses", self.read_json()))
            if path.startswith("/api/bonus/") and path.endswith("/delete"):
                return self.send_json(delete_row("bonuses", int(path.split("/")[3])))
            if path == "/api/payment":
                return self.send_json(add_money("payments", self.read_json()))
            if path.startswith("/api/payment/") and path.endswith("/delete"):
                return self.send_json(delete_row("payments", int(path.split("/")[3])))
            if path == "/api/import":
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                raw = parse_multipart_file(self.headers, body)
                if not raw.strip():
                    raise ValueError("No CSV data.")
                return self.send_json(import_csv(raw))
            self.send(404, b"not found", "text/plain")
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Nook is private on this computer only.")
    print(f"Open  http://{HOST}:{PORT}")
    print("Leave this window open while she uses it. Close the window to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nNook stopped.")


if __name__ == "__main__":
    main()
