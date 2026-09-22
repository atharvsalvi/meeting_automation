#!/usr/bin/env python3
"""
Scheduler: monitors meetings.txt and launches the meeting bot when scheduled.
Uses atomic file writes to prevent race conditions when manually editing.
"""
import datetime as dt
import os
import tempfile
import time
from pathlib import Path

from bot import run_meeting

MEETINGS_FILE = Path("meetings.txt")
POLL_SECONDS = 30


def read_entries():
    if not MEETINGS_FILE.exists():
        return []
    entries = []
    try:
        content = MEETINGS_FILE.read_text(encoding="utf-8")
    except Exception:
        return []

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        link, start_when, end_when = parts[0], parts[1], parts[2]
        status = parts[3] if len(parts) > 3 else "pending"
        entries.append({
            "link": link,
            "start_when": start_when,
            "end_when": end_when,
            "status": status
        })
    return entries


def write_entries(entries):
    lines = [f"{e['link']},{e['start_when']},{e['end_when']},{e['status']}" for e in entries]
    data = "\n".join(lines) + "\n"

    parent = MEETINGS_FILE.resolve().parent
    with tempfile.NamedTemporaryFile("w", dir=parent, delete=False, encoding="utf-8") as tf:
        tf.write(data)
        temp_path = Path(tf.name)

    os.replace(temp_path, MEETINGS_FILE)


def update_entry(link, start_when, **changes):
    entries = read_entries()
    for e in entries:
        if e["link"] == link and e["start_when"] == start_when:
            e.update(changes)
    write_entries(entries)


def main():
    print(f"Watching {MEETINGS_FILE.resolve()} every {POLL_SECONDS}s")
    while True:
        now = dt.datetime.now()
        entries = read_entries()

        for entry in entries:
            if entry["status"] != "pending":
                continue

            try:
                scheduled_start = dt.datetime.strptime(entry["start_when"], "%Y-%m-%d %H:%M")
            except ValueError:
                print(f"Skipping malformed entry: {entry}")
                continue

            if scheduled_start <= now:
                link = entry["link"]
                start_when = entry["start_when"]
                end_when = entry["end_when"]

                try:
                    scheduled_end = dt.datetime.strptime(end_when, "%Y-%m-%d %H:%M")
                except ValueError:
                    # Default to start + 1 hour if format is invalid
                    scheduled_end = scheduled_start + dt.timedelta(hours=1)

                print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Launching {link} (Expected end: {scheduled_end})...")
                update_entry(link, start_when, status="joined")

                try:
                    result = run_meeting(link, target_end_time=scheduled_end)
                except Exception as exc:
                    print(f"Meeting run error: {exc}")
                    result = {"reason": "crash"}

                if result.get("reason") == "disconnected":
                    retry_when = (dt.datetime.now() + dt.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M")
                    print(f"Disconnected — setting retry for {retry_when}")
                    update_entry(link, start_when, status="done")
                    current_entries = read_entries()
                    current_entries.append({
                        "link": link,
                        "start_when": retry_when,
                        "end_when": end_when,
                        "status": "pending"
                    })
                    write_entries(current_entries)
                else:
                    update_entry(link, start_when, status="done")
                    print(f"Left {link} ({result.get('reason')}). Returning to watch loop.")

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()