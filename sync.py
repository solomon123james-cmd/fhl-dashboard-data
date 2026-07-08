"""
sync.py — Camp Faholo Staff Dashboard
Logs into CampBrain (via Selenium SSO), downloads 3 CSV reports via JasperServer
REST API, pushes them to GitHub, and sends ntfy.sh push notifications on changes.

Usage:
    python sync.py

Requirements:
    pip install selenium webdriver-manager python-dotenv requests
"""

import base64
import hashlib
import json
import os
import time
import requests
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(os.path.expanduser("~/camp-dashboard/.env"))

CAMPBRAIN_URL = "https://campfaholo.campbrainoffice.com"
JASPER_BASE   = "https://reports.campbrainoffice.com:447/jasperserver-pro"
CB_USER       = os.environ["CAMPBRAIN_USERNAME"]
CB_PASS       = os.environ["CAMPBRAIN_PASSWORD"]
GITHUB_TOKEN  = os.environ["GITHUB_TOKEN"]
GITHUB_OWNER  = os.environ.get("GITHUB_OWNER", "solomon123james-cmd")
GITHUB_REPO   = os.environ.get("GITHUB_REPO",  "fhl-dashboard-data")
NTFY_TOPIC    = os.environ.get("NTFY_TOPIC", "faholo-camp-staff-2026")

# Maps JasperServer resource path → GitHub destination path
REPORTS = [
    ("/Saved_Ad_Hoc_CC/General_Group_Info_Report",    "data/General_Group_Info_Report.csv"),
    ("/Saved_Ad_Hoc_CC/Meal_Info_2_weeks",            "data/Meal_Info_Report.csv"),
    ("/Saved_Ad_Hoc_CC/Resource_2_weeks_ADH_Report",  "data/Resource_Report.csv"),
]

GITHUB_API   = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents"
HASH_FILE    = os.path.expanduser("~/camp-dashboard/.report_hashes.json")

# ── Selenium: establish JasperServer session via CampBrain SSO ─────────────────

def get_jasper_session() -> requests.Session:
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=options
    )
    try:
        # 1. Load CampBrain login page
        driver.get(CAMPBRAIN_URL)
        time.sleep(3)

        # 2. Fill username
        for sel in ["input[type='email']", "input[name='username']", "input[type='text']"]:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                if el.is_displayed() and el.is_enabled():
                    driver.execute_script("arguments[0].value = '';", el)
                    el.send_keys(CB_USER)
                    break
            else:
                continue
            break

        # 3. Fill password and submit
        pf = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
        driver.execute_script("arguments[0].value = '';", pf)
        pf.send_keys(CB_PASS)
        pf.submit()
        time.sleep(3)

        # 4. Navigate to Conference Center and trigger SSO into JasperServer
        driver.get("https://campfaholo.campbrainoffice.com/ConferenceCenter")
        time.sleep(3)
        driver.execute_script("""
            var links = document.querySelectorAll('ul.occadhoc a, ul.submenu.occadhoc a');
            for (var l of links) {
                if (l.textContent.toLowerCase().includes('ad hoc')) { l.click(); return; }
            }
        """)
        time.sleep(5)

        # 5. Switch to the new tab opened by JasperServer SSO
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])

        # 6. Navigate to JasperServer library to confirm session
        driver.get(f"{JASPER_BASE}/flow.html?_flowId=searchFlow&mode=library")
        time.sleep(3)

        # 7. Transfer cookies to a requests.Session
        session = requests.Session()
        for cookie in driver.get_cookies():
            session.cookies.set(
                cookie["name"], cookie["value"], domain=cookie.get("domain", "")
            )
        return session
    finally:
        driver.quit()


# ── JasperServer REST API download ────────────────────────────────────────────

def download_csv(session: requests.Session, resource_path: str) -> bytes:
    url = f"{JASPER_BASE}/rest_v2/reports{resource_path}.csv"
    r = session.get(url)
    if r.status_code == 200 and len(r.content) > 0:
        return r.content
    raise RuntimeError(f"Download failed for {resource_path}: {r.status_code}\n{r.text[:300]}")


# ── GitHub helpers ─────────────────────────────────────────────────────────────

def _gh_headers() -> dict:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def get_file_sha(dest_path: str):
    r = requests.get(f"{GITHUB_API}/{dest_path}", headers=_gh_headers())
    return r.json()["sha"] if r.status_code == 200 else None


def push_to_github(content_bytes: bytes, dest_path: str) -> None:
    content_b64 = base64.b64encode(content_bytes).decode()
    sha = get_file_sha(dest_path)
    payload = {"message": f"sync: update {dest_path}", "content": content_b64}
    if sha:
        payload["sha"] = sha
    r = requests.put(f"{GITHUB_API}/{dest_path}", json=payload, headers=_gh_headers())
    r.raise_for_status()
    print(f"  Pushed {dest_path} → {r.status_code}")


# ── Change detection + ntfy notifications ────────────────────────────────────

def load_hashes() -> dict:
    if os.path.exists(HASH_FILE):
        with open(HASH_FILE) as f:
            return json.load(f)
    return {}


def save_hashes(hashes: dict) -> None:
    with open(HASH_FILE, "w") as f:
        json.dump(hashes, f)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def notify(report_name: str) -> None:
    try:
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=f"Faholo {report_name} report updated — open the dashboard to review changes.",
            headers={
                "Title": f"Faholo {report_name} Updated",
                "Priority": "default",
                "Tags": "campfire",
            },
            timeout=10,
        )
        print(f"  Sent ntfy notification for {report_name}")
    except Exception as e:
        print(f"  ntfy notification failed: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Establishing JasperServer session via CampBrain SSO...")
    session = get_jasper_session()
    print("  Session established.\n")

    hashes = load_hashes()

    for resource_path, dest_path in REPORTS:
        report_name = dest_path.split("/")[-1].replace(".csv", "")
        print(f"Processing: {report_name}")

        csv_bytes = download_csv(session, resource_path)
        print(f"  Downloaded {len(csv_bytes):,} bytes")

        new_hash = sha256(csv_bytes)
        old_hash = hashes.get(dest_path)

        if old_hash and old_hash != new_hash:
            print(f"  Change detected — sending notification")
            notify(report_name)
        elif not old_hash:
            print(f"  First sync — no notification sent")
        else:
            print(f"  No changes")

        hashes[dest_path] = new_hash
        push_to_github(csv_bytes, dest_path)

    save_hashes(hashes)
    print("\nAll reports synced successfully.")


if __name__ == "__main__":
    main()
