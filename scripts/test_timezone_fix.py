"""
Comprehensive multi-timezone test.
Tests that the same UTC meeting time displays correctly for organizers in different timezones.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import parse_iso_datetime, to_local_time, to_user_timezone
import pytz

print("=" * 65)
print("MULTI-TIMEZONE TEST: Same UTC meeting, different organizer TZs")
print("=" * 65)

# Meeting stored in DB as UTC: 07:20 AM UTC = 12:50 PM IST
utc_start = "2026-02-18T07:20:00+00:00"
utc_end   = "2026-02-18T07:50:00+00:00"

start_dt = parse_iso_datetime(utc_start)
end_dt   = parse_iso_datetime(utc_end)

test_cases = [
    ("Asia/Kolkata",       "12:50 PM", ["IST"]),         # India
    ("America/New_York",   "02:20 AM", ["EST"]),         # US East / Toronto (Canada)
    ("America/Chicago",    "01:20 AM", ["CST"]),         # US Central / Mexico City
    ("America/Mexico_City","01:20 AM", ["CST"]),         # Mexico City
    ("America/Los_Angeles","11:20 PM", ["PST"]),         # US West / Vancouver
    ("Europe/London",      "07:20 AM", ["GMT"]),         # UK
    ("Europe/Paris",       "08:20 AM", ["CET"]),         # Europe
    ("Asia/Singapore",     "03:20 PM", ["SGT", "+08"]),  # Asia
    ("UTC",                "07:20 AM", ["UTC"]),
]

all_pass = True
for tz_str, expected_time, expected_abbrs in test_cases:
    local_start = to_local_time(start_dt, tz_str=tz_str)
    local_end   = to_local_time(end_dt,   tz_str=tz_str)
    tz_abbr     = local_start.strftime("%Z")
    display     = (
        f"{local_start.strftime('%b %d, %I:%M %p')} - "
        f"{local_end.strftime('%I:%M %p')} {tz_abbr}"
    )
    time_part = local_start.strftime("%I:%M %p").lstrip("0")
    ok = expected_time.lstrip("0") in time_part and tz_abbr in expected_abbrs
    status = "PASS" if ok else "FAIL"
    if not ok:
        all_pass = False
    print(f"  [{status}] {tz_str:<25} -> {display}")

print()
print("=" * 65)
print("TEST: to_user_timezone fallback on invalid tz")
print("=" * 65)
result = to_local_time(start_dt, tz_str="Invalid/Timezone")
print(f"  Invalid tz -> falls back to UTC: {result.strftime('%H:%M %Z')}")
assert result.strftime("%Z") == "UTC", "FAIL: Should fall back to UTC"
print("  PASS: Invalid timezone gracefully falls back to UTC")

print()
print("=" * 65)
print("TEST: None tz_str uses APP_TIMEZONE env var")
print("=" * 65)
os.environ["APP_TIMEZONE"] = "Asia/Kolkata"
result2 = to_local_time(start_dt, tz_str=None)
print(f"  None tz_str + APP_TIMEZONE=Asia/Kolkata -> {result2.strftime('%I:%M %p %Z')}")
assert "IST" in result2.strftime("%Z"), "FAIL: Should use IST from APP_TIMEZONE"
print("  PASS: None tz_str correctly uses APP_TIMEZONE")

print()
print("=" * 65)
if all_pass:
    print("ALL TESTS PASSED - Works for all timezones worldwide!")
else:
    print("SOME TESTS FAILED - Check output above")
print("=" * 65)
