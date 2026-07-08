"""Live end-to-end check of the Google Calendar service-account access.

Reads config.yaml (credentials at calendar.credentials_path — normally
~/.config/calcifer/google-service-account.json), then:
  1. health() against both configured calendars
  2. lists the next 7 days from both
  3. on the Calcifer calendar: create -> patch -> delete a test event

Run manually: python verify_calendar.py
"""

import asyncio
from datetime import timedelta

from assistant.calendar.google_calendar import GoogleCalendar
from assistant.core.config import Config
from assistant.skills.base import local_now


async def verify():
    config = Config()
    cal = config.calendar
    provider = GoogleCalendar(
        cal.credentials_path,
        timeout=cal.timeout,
        health_calendar_ids=[cal.personal_calendar_id, cal.calcifer_calendar_id],
    )
    try:
        print(f"health: {await provider.health()}")

        now = local_now()
        for label, calendar_id in (
            ("personal", cal.personal_calendar_id),
            ("calcifer", cal.calcifer_calendar_id),
        ):
            print(f"\n{label} ({calendar_id}), next 7 days:")
            events = await provider.list_events(
                calendar_id, time_min=now, time_max=now + timedelta(days=7)
            )
            if not events:
                print("  (no events)")
            for e in events:
                when = "all day" if e.all_day else e.start.strftime("%a %H:%M")
                print(f"  [{when}] {e.title} (id={e.id})")

        print("\ncreate -> patch -> delete on the calcifer calendar:")
        created = await provider.create_event(
            cal.calcifer_calendar_id,
            title="Calcifer verification event",
            start=now + timedelta(minutes=2),
            end=now + timedelta(minutes=17),
        )
        print(f"  created {created.id} at {created.start}")
        patched = await provider.update_event(
            cal.calcifer_calendar_id, created.id, title="Calcifer verification event (renamed)"
        )
        print(f"  patched title -> {patched.title}")
        await provider.delete_event(cal.calcifer_calendar_id, created.id)
        print("  deleted")
    finally:
        await provider.aclose()


if __name__ == "__main__":
    asyncio.run(verify())
