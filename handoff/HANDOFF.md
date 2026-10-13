# Faholo Staff Dashboard — Handoff Notes

Written 2026-10-13 for a new Claude session (Teams account) picking this up cold.
Owner: Solomon (GitHub: `solomon123james-cmd`). No secrets are in this file.

## What it is

A phone app (PWA) that shows Camp Faholo staff upcoming **Groups**, **Meals** (with
allergy counts) and **Resources** (buildings / activities) for the next 4 weeks,
using data exported from CampBrain.

```
CampBrain ad hoc reports (JasperServer)
  └─ sync.py on Solomon's iMac (cron, 6 AM daily)
       ├─ logs into CampBrain with headless Chrome (Selenium), gets JasperServer cookies
       ├─ downloads 3 reports as CSV
       ├─ pushes them to GitHub: data/*.csv on main
       └─ if a report changed, sends push notification via ntfy.sh
GitHub Pages (main branch) serves index.html
  └─ app fetches the CSVs from raw.githubusercontent.com on load / Refresh / every 10 min
```

## Where everything lives

| Thing | Location |
|---|---|
| Live app code | GitHub `solomon123james-cmd/fhl-dashboard-data`, branch **main** (`index.html`, `sw.js`, `manifest.json`, `icon.svg`) |
| CSV data | same repo, `data/` on main (overwritten by every sync) |
| Sync script (the one that runs) | iMac: `/Users/user/camp-dashboard/sync.py` |
| Sync script backup | this repo, branch `claude/campbrain-report-email-script-9p070r`, `sync.py` (matches the iMac copy as of 2026-10-13) |
| Secrets | iMac: `~/camp-dashboard/.env` (`CAMPBRAIN_USERNAME`, `CAMPBRAIN_PASSWORD`), `GITHUB_TOKEN` in `~/.zshrc` **and** as a line at top of `crontab -l` |
| Change-detection hashes | iMac: `~/camp-dashboard/.report_hashes.json` |
| Sync log | iMac: `/Users/user/camp-dashboard/sync.log` |
| Push notifications | ntfy.sh topic `faholo-camp-staff-2026` |

Cron entry (token line omitted here):
```
0 6 * * * cd /Users/user/camp-dashboard && /usr/bin/python3 sync.py >> /Users/user/camp-dashboard/sync.log 2>&1
```
Cron does not read `~/.zshrc`, which is why `GITHUB_TOKEN=...` must also be in the crontab.

iMac environment: `/usr/bin/python3` is Python 3.8 (LibreSSL warning on every run is harmless),
selenium 4.27.1, webdriver-manager 4.1.2, Chrome 128.

## CampBrain reports (JasperServer paths → repo files)

| JasperServer path | Repo file | Columns |
|---|---|---|
| `/Saved_Ad_Hoc_CC/General_Group_Info_Report` | `data/General_Group_Info_Report.csv` | OrgName, BookingName, ExpectedNumber, ActualNumber, ArrivalDate, ArrivalTime, DepartureDate, DepartureTime, AttendeeCategory |
| `/Saved_Ad_Hoc_CC/Meal_Info_2_Weeks_1_Report` | `data/Meal_Info_Report.csv` | OrgName, MealTypeName, MealDateTime, MealNotes, DietaryRequests, FoodAllergies, MealInstructions |
| `/Saved_Ad_Hoc_CC/Resource_2_weeks_ADH_Report` | `data/Resource_Report.csv` | BookingName, ResourceName, ResStartDateTime, ResEndDateTime, ResNotes |

Data quirks:
- Group report has one row per AttendeeCategory; ExpectedNumber/ActualNumber repeat the
  booking **total** on each row — never sum them.
- Meal CSV sometimes contains a repeated header row mid-file; the parser skips it.
- Allergy text uses mixed formats (`GF: 6`, `Gluten-free - 3`, `3 - DF`, multi-line).
  `FoodAllergies` is checked first, then `DietaryRequests`, then `MealInstructions`.
- Meals report has no BookingName/attendance; the app cross-references the group report
  by OrgName + date within arrival–departure.

## App behavior (index.html)

- Window: today → +28 days on all tabs.
- Groups stay visible until departure passes ("On site" / "Arriving today" / "Departing today" badges).
- Group card: title BookingName, sub OrgName, then `Expected: N · Actual: N` (each only if > 0).
- Meal card: meal type pill, BookingName (from group lookup), OrgName, attendees, time,
  notes, allergy bubbles (GF, DF, GF+DF, Egg, Beef, others).
- Resources split into Buildings vs Activities by the `BUILDINGS` set in index.html
  (Mezzanine, Island, Conference Room A/B, Conference Cottage, Chalet, Antioch, Tabernacle, Yurt).
- Service worker `sw.js` (cache `faholo-v5`) is network-first for HTML/CSV, so code
  changes reach phones on Refresh — no reinstall. Bump the cache name only if icons/manifest change.
- Timezone America/New_York.

## How changes have been deployed

App changes are committed straight to **main** (GitHub Pages deploys it within ~1 min);
Solomon has approved this workflow. The sync script is edited on the iMac directly
(cloud sessions cannot reach the iMac — give Solomon copy-paste Terminal commands),
then mirror the change into the backup `sync.py` in the repo.

## Troubleshooting history (what broke before and the fix)

| Symptom | Cause | Fix |
|---|---|---|
| App shows "No groups…" everywhere | Sync stopped; all data in the past | Check `sync.log`, run sync manually |
| `WebDriverException: disconnected: Unable to receive message from renderer` | Chrome/ChromeDriver mismatch after Chrome update | `pip3 install --upgrade webdriver-manager selenium`; update Chrome |
| `Download failed ... 401` | Cookies grabbed before JasperServer SSO finished | `time.sleep(10)` after the JasperServer `driver.get` + strip leading `.` from cookie domain (already applied) |
| GitHub push 401 | Expired `GITHUB_TOKEN` | New token in `~/.zshrc` and crontab; test with `curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user` |
| Allergy bubbles missing | Colon format `GF: 6` | Regex accepts `-`, `–`, `:` (done) |
| Phone shows old version | Old cache-first SW | Network-first SW `faholo-v5` (done) |

Manual sync: `cd /Users/user/camp-dashboard && /usr/bin/python3 sync.py`

## Open items / not yet confirmed

1. **CampBrain report date filters.** App now shows 4 weeks, but the Meal and Resource reports are
   named "2 weeks" and likely still filter to 14 days. Solomon needs to change them to 28 days in
   CampBrain, and make the Group report filter on *departure ≥ today* (so on-site groups stay in the data).
   If report names/paths change, update `REPORTS` in `sync.py` on the iMac (and the backup).
2. `ActualNumber` is blank for most upcoming bookings in CampBrain — expected, app hides it when empty.
3. GitHub token expiry date not recorded — when it expires, the sync fails with a 401 on push.
4. Moving to a new Mac: copy `~/camp-dashboard/` (including `.env`), re-add token to `~/.zshrc`
   and crontab, `pip3 install selenium webdriver-manager python-dotenv requests`, install Chrome.
5. Consider moving the sync to GitHub Actions so it doesn't depend on the iMac being on
   (would need CampBrain creds as repo secrets; headless Chrome works on ubuntu runners). Not started.
