"""
Core meeting bot: joins a browser meeting link, captures audio + screenshots,
runs real-time transcription, and evaluates room state with LLaVA.
"""
import base64
import os
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from audio import AudioCapture
from transcriber import Transcriber
from decider import should_leave
import datetime as dt

SCREENSHOT_INTERVAL = 45            # Seconds between vision evaluations
JOIN_TIMEOUT = 25                   # Seconds to attempt auto-join
MAX_MEETING_SECONDS = 4 * 60 * 60   # 4-hour safety cap

CHROME_USER_DATA_DIR = os.environ.get(
    "CHROME_USER_DATA_DIR", str(Path.home() / ".config" / "chrome-meeting-bot")
)
CHROME_PROFILE_DIRECTORY = os.environ.get("CHROME_PROFILE_DIRECTORY", "Default")


def turn_off_mic_and_cam(page):
    """Mutes the mic and disables the camera using keyboard shortcuts and UI fallbacks."""
    # Wait briefly for Google Meet's green room controls to load
    page.wait_for_timeout(2000)

    # 1. Native Google Meet keyboard shortcuts:
    # Ctrl + d toggles microphone; Ctrl + e toggles camera
    page.keyboard.press("Control+d")
    page.wait_for_timeout(500)
    page.keyboard.press("Control+e")
    page.wait_for_timeout(500)

    # 2. Fallback: inspect aria-label toggles to confirm they are off
    # If the button still says "turn off", clicking it ensures it's disabled
    mic_off_selectors = [
        'div[role="button"][aria-label*="turn off microphone" i]',
        'button[aria-label*="turn off microphone" i]',
    ]
    cam_off_selectors = [
        'div[role="button"][aria-label*="turn off camera" i]',
        'button[aria-label*="turn off camera" i]',
    ]

    for sel in mic_off_selectors:
        try:
            elem = page.locator(sel).first
            if elem.is_visible(timeout=1000):
                elem.click()
        except Exception:
            pass

    for sel in cam_off_selectors:
        try:
            elem = page.locator(sel).first
            if elem.is_visible(timeout=1000):
                elem.click()
        except Exception:
            pass


def try_auto_join(page) -> bool:
    """Disables mic/cam and clicks join elements."""
    deadline = time.time() + JOIN_TIMEOUT

    # Turn off mic and camera first
    turn_off_mic_and_cam(page)

    # Google Meet target join buttons
    join_selectors = [
        'button:has-text("Join now")',
        'button:has-text("Ask to join")',
        'div[role="button"]:has-text("Join now")',
        'div[role="button"]:has-text("Ask to join")',
        'button:has-text("Join")',
        'button:has-text("Join meeting")'
    ]

    while time.time() < deadline:
        for sel in join_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    return True
            except Exception:
                pass
        time.sleep(1)

    return False


def run_meeting(link: str, target_end_time: dt.datetime = None) -> dict:
    """Joins link, transcribes audio, and only evaluates departure once target_end_time is reached."""
    transcript_path = Path(f"transcript_{int(time.time())}.txt")
    stop_event = threading.Event()
    reason = {"value": "ended"}

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=CHROME_USER_DATA_DIR,
            channel="chrome",
            headless=False,
            permissions=["microphone", "camera"],
            ignore_default_args=["--enable-automation"],
            args=[
                "--use-fake-ui-for-media-stream",
                f"--profile-directory={CHROME_PROFILE_DIRECTORY}",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(link, wait_until="domcontentloaded")

        joined = try_auto_join(page)
        print("Auto-join clicked." if joined else "Could not auto-join; proceed manually in the browser window.")

        audio = AudioCapture()
        audio.start()

        transcriber = Transcriber(audio.chunk_dir, transcript_path, stop_event)
        transcribe_thread = threading.Thread(target=transcriber.run, daemon=True)
        transcribe_thread.start()

        start = time.time()
        try:
            while not stop_event.is_set():
                if time.time() - start > MAX_MEETING_SECONDS:
                    reason["value"] = "timeout"
                    break

                # Ensure window hasn't crashed or closed
                try:
                    screenshot = page.screenshot()
                except Exception:
                    reason["value"] = "disconnected"
                    break

                now = dt.datetime.now()

                # ONLY evaluate leaving if we have reached or passed the expected end time
                if target_end_time and now < target_end_time:
                    remaining_mins = int((target_end_time - now).total_seconds() // 60)
                    print(f"[{now.strftime('%H:%M:%S')}] Meeting in progress (~{remaining_mins}m until scheduled end). Skipping leave evaluation.")
                else:
                    print(f"[{now.strftime('%H:%M:%S')}] Target end time reached. Checking screen and transcript for wrap-up...")
                    b64 = base64.b64encode(screenshot).decode()
                    recent_transcript = transcriber.recent_text(chars=3000)
                    decision = should_leave(b64, recent_transcript)
                    print(f"Decision: {decision}")

                    if decision.get("should_leave"):
                        reason["value"] = decision.get("reason", "ended")
                        break

                time.sleep(SCREENSHOT_INTERVAL)
        finally:
            stop_event.set()
            audio.stop()
            try:
                context.close()
            except Exception:
                pass

    print(f"Meeting ended. Transcript saved to: {transcript_path}")
    return {"reason": reason["value"], "transcript": str(transcript_path)}