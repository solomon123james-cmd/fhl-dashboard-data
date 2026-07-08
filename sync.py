"""
sync.py — Camp Faholo Staff Dashboard
Logs into CampBrain, downloads 3 CSV reports, pushes them to GitHub.

Usage:
    python sync.py

Requirements:
    pip install selenium webdriver-manager python-dotenv requests
"""

import base64
import os
import time
import glob
import tempfile
import requests
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ── Config ────────────────────────────────────────────────────────────────────

load_dotenv(os.path.expanduser("~/camp-dashboard/.env"))

CAMPBRAIN_URL  = "https://campfaholo.campbrainoffice.com"
CB_USER        = os.environ["CAMPBRAIN_USERNAME"]
CB_PASS        = os.environ["CAMPBRAIN_PASSWORD"]
GITHUB_TOKEN   = os.environ["GITHUB_TOKEN"]
GITHUB_OWNER   = os.environ.get("GITHUB_OWNER", "solomon123james-cmd")
GITHUB_REPO    = os.environ.get("GITHUB_REPO",  "fhl-dashboard-data")

# Maps CampBrain report name → GitHub destination path
REPORTS = {
    "General_Group_Info_Report": "data/General_Group_Info_Report.csv",
    "Meal_Info_2_weeks":         "data/Meal_Info_Report.csv",
    "Resource_2_weeks_ADH_Report": "data/Resource_Report.csv",
}

GITHUB_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents"

# ── Selenium helpers ───────────────────────────────────────────────────────────

def build_driver(download_dir: str) -> webdriver.Chrome:
    """Return a Chrome driver that saves downloads to download_dir."""
    options = webdriver.ChromeOptions()
    options.add_experimental_option("prefs", {
        "download.default_directory": download_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    })
    # Remove headless=True if you want to watch the browser
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def wait_for_download(download_dir: str, timeout: int = 60) -> str:
    """Block until a completed (non-.crdownload) file appears; return its path."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        files = [
            f for f in glob.glob(os.path.join(download_dir, "*"))
            if not f.endswith(".crdownload") and os.path.isfile(f)
        ]
        if files:
            # Return the newest file
            return max(files, key=os.path.getmtime)
        time.sleep(1)
    raise TimeoutError(f"Download did not complete within {timeout}s")


def login(driver: webdriver.Chrome) -> None:
    """Log into CampBrain."""
    driver.get(CAMPBRAIN_URL)
    wait = WebDriverWait(driver, 20)

    # Fill username
    user_field = wait.until(EC.presence_of_element_located(
        (By.CSS_SELECTOR, "input[type='text'], input[name*='user'], input[id*='user']")
    ))
    user_field.clear()
    user_field.send_keys(CB_USER)

    # Fill password
    pass_field = driver.find_element(
        By.CSS_SELECTOR, "input[type='password']"
    )
    pass_field.clear()
    pass_field.send_keys(CB_PASS)

    # Submit
    pass_field.submit()

    # Wait for dashboard / post-login page
    wait.until(lambda d: d.current_url != CAMPBRAIN_URL or "login" not in d.current_url.lower())
    print("  Logged in successfully.")


def navigate_to_reports(driver: webdriver.Chrome) -> None:
    """Navigate to the Reports section of CampBrain."""
    wait = WebDriverWait(driver, 20)
    # Look for a "Reports" nav link
    reports_link = wait.until(EC.element_to_be_clickable(
        (By.XPATH, "//a[contains(translate(text(),'REPORTS','reports'),'reports')]")
    ))
    reports_link.click()
    time.sleep(2)


def download_report(driver: webdriver.Chrome, report_name: str, download_dir: str) -> str:
    """
    Find and download a specific report by name.
    Returns the local path of the downloaded file.
    """
    wait = WebDriverWait(driver, 20)

    # Clear out any old files so wait_for_download picks the right one
    for f in glob.glob(os.path.join(download_dir, "*")):
        os.remove(f)

    # Find the report row by its name and click the CSV/export button
    report_label = wait.until(EC.presence_of_element_located(
        (By.XPATH, f"//*[contains(text(), '{report_name}')]")
    ))

    # Try to find a CSV or export button near the report label
    try:
        # Sibling/nearby export button
        export_btn = report_label.find_element(
            By.XPATH, "following::*[contains(@class,'export') or contains(@class,'csv') "
                      "or contains(translate(text(),'CSV','csv'),'csv')][1]"
        )
    except Exception:
        # Fallback: click the report name itself to open it, then look for export
        report_label.click()
        time.sleep(2)
        export_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//*[contains(@class,'export') or contains(@class,'csv') "
                       "or contains(translate(text(),'CSV','csv'),'csv')]")
        ))

    export_btn.click()
    print(f"  Triggered download for: {report_name}")

    local_path = wait_for_download(download_dir)
    print(f"  Downloaded to: {local_path}")
    return local_path

# ── GitHub helpers ─────────────────────────────────────────────────────────────

def get_file_sha(dest_path: str) -> str | None:
    """Return the blob SHA of a file in GitHub (needed to update existing files)."""
    url = f"{GITHUB_API}/{dest_path}"
    r = requests.get(url, headers=_gh_headers())
    if r.status_code == 200:
        return r.json()["sha"]
    return None


def push_to_github(local_path: str, dest_path: str) -> None:
    """Base64-encode local_path and PUT it to dest_path in the GitHub repo."""
    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    sha = get_file_sha(dest_path)
    payload = {
        "message": f"sync: update {dest_path}",
        "content": content_b64,
    }
    if sha:
        payload["sha"] = sha  # required for updates

    url = f"{GITHUB_API}/{dest_path}"
    r = requests.put(url, json=payload, headers=_gh_headers())
    r.raise_for_status()
    print(f"  Pushed {dest_path} → {r.status_code}")


def _gh_headers() -> dict:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    download_dir = tempfile.mkdtemp(prefix="campbrain_")
    print(f"Download directory: {download_dir}\n")

    driver = build_driver(download_dir)
    try:
        print("Logging in to CampBrain...")
        login(driver)

        print("Navigating to Reports...")
        navigate_to_reports(driver)

        for report_name, dest_path in REPORTS.items():
            print(f"\nProcessing: {report_name}")
            local_path = download_report(driver, report_name, download_dir)
            push_to_github(local_path, dest_path)

    finally:
        driver.quit()

    print("\nAll reports synced successfully.")


if __name__ == "__main__":
    main()
