import os
import requests
from bs4 import BeautifulSoup
import re
import time
import sys

import firebase_admin
from firebase_admin import credentials, firestore


# ============================================================
# CONFIGURATION
# ============================================================

SERVICE_ACCOUNT_FILE = "serviceAccountKey.json"

PARENT_COLLECTION = "NLB_Results_All"
SUBCOLLECTION = "mega-power"

BASE_URL = "https://www.nlb.lk"
LOTTERY_SLUG = "mega-power"
LOTTERY_NAME = "Mega Power"

# Delay between checking draws
REQUEST_DELAY = 1.0

# Selenium settings
USE_SELENIUM_FALLBACK = True
SELENIUM_WAIT = 5


# ============================================================
# MEGA POWER SCRAPER
# ============================================================

class MegaPowerScraper:

    def __init__(self):

        self.session = requests.Session()

        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/139.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,image/webp,"
                "image/apng,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })

        self.driver = None

    # ========================================================
    # INITIALIZE SELENIUM
    # ========================================================

    def initialize_selenium(self):

        if self.driver is not None:
            return self.driver

        print("\n🌐 Starting Selenium Chrome fallback...")

        try:

            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            options = Options()

            options.add_argument("--headless=new")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")

            options.add_argument(
                "--disable-blink-features=AutomationControlled"
            )

            options.add_experimental_option(
                "excludeSwitches",
                ["enable-automation"]
            )

            options.add_experimental_option(
                "useAutomationExtension",
                False
            )

            options.add_argument(
                "--window-size=1920,1080"
            )

            self.driver = webdriver.Chrome(
                options=options
            )

            print("✅ Selenium Chrome started.")

            return self.driver

        except Exception as e:

            print(
                f"❌ Selenium initialization failed:\n{e}"
            )

            return None

    # ========================================================
    # FETCH USING REQUESTS
    # ========================================================

    def fetch_with_requests(self, url):

        print("   → Trying requests...")

        try:

            response = self.session.get(
                url,
                timeout=30
            )

            print(
                f"   → HTTP status: {response.status_code}"
            )

            print(
                f"   → Response size: "
                f"{len(response.text):,} characters"
            )

            if response.status_code != 200:

                print(
                    "   ❌ HTTP request failed."
                )

                return None

            # A very small response usually means that
            # the actual page content was not returned.
            if len(response.text) < 1000:

                print(
                    "   ⚠️ Response is too small "
                    "to contain the result."
                )

                return None

            return response.text

        except requests.RequestException as e:

            print(
                f"   ❌ Requests error: {e}"
            )

            return None

    # ========================================================
    # FETCH USING SELENIUM
    # ========================================================

    def fetch_with_selenium(self, url):

        driver = self.initialize_selenium()

        if driver is None:
            return None

        try:

            print(
                "   → Loading page using Selenium..."
            )

            driver.get(url)

            time.sleep(
                SELENIUM_WAIT
            )

            # Get fully rendered HTML
            html = driver.page_source

            print(
                f"   → Selenium page size: "
                f"{len(html):,} characters"
            )

            if len(html) < 1000:

                print(
                    "   ❌ Selenium page is too small."
                )

                return None

            return html

        except Exception as e:

            print(
                f"   ❌ Selenium error: {e}"
            )

            return None

    # ========================================================
    # EXTRACT WINNING NUMBERS
    # ========================================================

    def extract_winning_numbers(
        self,
        text,
        draw_number
    ):

        result = {
            "symbol": None,
            "numbers": [],
            "found": False
        }

        # ----------------------------------------------------
        # Find draw number
        # ----------------------------------------------------

        draw_pattern = (
            rf'(?:Draw|Lottery)\s*'
            rf'(?:No|Number)?\.?\s*:?\s*'
            rf'{draw_number}'
        )

        draw_match = re.search(
            draw_pattern,
            text,
            re.I
        )

        if not draw_match:
            return result

        # ----------------------------------------------------
        # METHOD 1
        # Expected Mega Power format:
        #
        # V 24 03 18 29 71
        # ----------------------------------------------------

        start = draw_match.end()

        section = text[
            start:start + 300
        ]

        pattern = (
            r'\b([A-Z])\s+'
            r'(\d+)\s+'
            r'(\d+)\s+'
            r'(\d+)\s+'
            r'(\d+)\s+'
            r'(\d+)\b'
        )

        matches = re.findall(
            pattern,
            section,
            re.I
        )

        if matches:

            for match in matches:

                symbol = match[0].upper()

                numbers = list(
                    match[1:6]
                )

                numbers = [
                    n
                    for n in numbers
                    if 0 <= int(n) <= 99
                ]

                if len(numbers) == 5:

                    result["symbol"] = symbol

                    result["numbers"] = [
                        f"{int(n):02d}"
                        for n in numbers
                    ]

                    result["found"] = True

                    return result

        # ----------------------------------------------------
        # METHOD 2
        # More flexible number matching
        # ----------------------------------------------------

        pattern = (
            r'\b([A-Z])\s+'
            r'(\d+)\s+'
            r'(\d+)\s+'
            r'(\d+)\s+'
            r'(\d+)'
            r'(?:\s+(\d+))?'
            r'(?:\s+(\d+))?\b'
        )

        matches = re.findall(
            pattern,
            section,
            re.I
        )

        if matches:

            for match in matches:

                symbol = match[0].upper()

                numbers = [
                    n
                    for n in match[1:]
                    if n
                ]

                numbers = [
                    n
                    for n in numbers
                    if 0 <= int(n) <= 99
                ]

                if len(numbers) >= 4:

                    result["symbol"] = symbol

                    result["numbers"] = [
                        f"{int(n):02d}"
                        for n in numbers[:5]
                    ]

                    result["found"] = True

                    return result

        # ----------------------------------------------------
        # METHOD 3
        # Search within the draw section
        # ----------------------------------------------------

        draw_pos = draw_match.start()

        next_draw = re.search(
            r'(?:Draw|Lottery)\s*'
            r'(?:No|Number)?\.?\s*:?\s*\d+',
            text[draw_pos + 1:],
            re.I
        )

        if next_draw:

            section = text[
                draw_pos:
                draw_pos + 1 + next_draw.start()
            ]

        else:

            section = text[
                draw_pos:
                draw_pos + 500
            ]

        words_to_skip = [
            "DATE",
            "DRAW",
            "NO",
            "NUMBER",
            "PRIZE",
            "WINNER",
            "TOTAL",
            "LETTER"
        ]

        for match in re.finditer(
            r'\b([A-Z])\s+',
            section,
            re.I
        ):

            symbol = match.group(1).upper()

            if symbol in [
                "D",
                "N",
                "P",
                "T",
                "F",
                "S",
                "V"
            ]:

                start_pos = match.start()

                if start_pos > 0:

                    previous_char = section[
                        start_pos - 1
                    ]

                    if previous_char.isalpha():
                        continue

                    word_start = (
                        section.rfind(
                            " ",
                            0,
                            start_pos
                        ) + 1
                    )

                    word = section[
                        word_start:
                        start_pos + 1
                    ].upper()

                    if any(
                        w in word
                        for w in words_to_skip
                    ):
                        continue

            after_letter = section[
                match.end():
                match.end() + 100
            ]

            numbers = re.findall(
                r'\b(\d+)\b',
                after_letter
            )

            numbers = [
                n
                for n in numbers
                if 0 <= int(n) <= 99
            ]

            if len(numbers) >= 4:

                result["symbol"] = symbol

                result["numbers"] = [
                    f"{int(n):02d}"
                    for n in numbers[:5]
                ]

                result["found"] = True

                return result

        return result

    # ========================================================
    # EXTRACT DRAW DATE
    # ========================================================

    def extract_draw_date(self, text):

        date_patterns = [

            r'(?:Date|Draw Date)\s*:?\s*'
            r'([A-Za-z]+\s+\d{1,2},?\s+\d{4})',

            r'([A-Za-z]+\s+\d{1,2},?\s+\d{4})'
        ]

        for pattern in date_patterns:

            match = re.search(
                pattern,
                text,
                re.I
            )

            if match:
                return match.group(1)

        return None

    # ========================================================
    # PARSE RESULT
    # ========================================================

    def parse_result(
        self,
        html,
        draw_number
    ):

        if not html:
            return None

        soup = BeautifulSoup(
            html,
            "html.parser"
        )

        text = soup.get_text(
            separator=" ",
            strip=True
        )

        # Debug information
        print(
            f"   → Extracted text size: "
            f"{len(text):,} characters"
        )

        # Extract date
        date = self.extract_draw_date(
            text
        )

        # Extract winning numbers
        extracted = self.extract_winning_numbers(
            text,
            draw_number
        )

        if extracted["found"]:

            url = (
                f"{BASE_URL}/results/"
                f"{LOTTERY_SLUG}/"
                f"{draw_number}"
            )

            return {

                "lottery": LOTTERY_NAME,

                "draw_number": str(
                    draw_number
                ),

                "date": date,

                "symbol": extracted[
                    "symbol"
                ],

                "numbers": extracted[
                    "numbers"
                ],

                "url": url
            }

        return None

    # ========================================================
    # GET RESULT
    # ========================================================

    def get_result(self, draw_number):

        draw_number = str(
            draw_number
        )

        url = (
            f"{BASE_URL}/results/"
            f"{LOTTERY_SLUG}/"
            f"{draw_number}"
        )

        print(
            f"\n🌐 Checking NLB draw "
            f"{draw_number}..."
        )

        print(
            f"   URL: {url}"
        )

        # ----------------------------------------------------
        # FIRST: REQUESTS
        # ----------------------------------------------------

        html = self.fetch_with_requests(
            url
        )

        if html:

            result = self.parse_result(
                html,
                draw_number
            )

            if result:

                print(
                    "   ✅ Result found using requests."
                )

                return result

            print(
                "   ⚠️ Requests page loaded, "
                "but result could not be extracted."
            )

        # ----------------------------------------------------
        # SECOND: SELENIUM
        # ----------------------------------------------------

        if USE_SELENIUM_FALLBACK:

            print(
                "\n   🔄 Falling back to Selenium..."
            )

            html = self.fetch_with_selenium(
                url
            )

            if html:

                result = self.parse_result(
                    html,
                    draw_number
                )

                if result:

                    print(
                        "   ✅ Result found using Selenium!"
                    )

                    return result

                print(
                    "   ❌ Selenium loaded the page "
                    "but result could not be parsed."
                )

        return None

    # ========================================================
    # CLOSE SELENIUM
    # ========================================================

    def close(self):

        if self.driver:

            try:

                self.driver.quit()

                print(
                    "\n🌐 Selenium closed."
                )

            except Exception:
                pass

            self.driver = None


# ============================================================
# FIREBASE INITIALIZATION
# ============================================================

def initialize_firebase():

    print(
        "\n🔥 Connecting to Firebase..."
    )

    if not os.path.exists(SERVICE_ACCOUNT_FILE):

        print(
            f"❌ {SERVICE_ACCOUNT_FILE} was not found.\n"
            "   Locally: make sure the file is in this folder.\n"
            "   In GitHub Actions: check that the "
            "'Write Firebase service account key' step ran "
            "before this script, and that the "
            "FIREBASE_SERVICE_ACCOUNT_JSON secret is set."
        )

        sys.exit(1)

    try:

        if not firebase_admin._apps:

            cred = credentials.Certificate(
                SERVICE_ACCOUNT_FILE
            )

            firebase_admin.initialize_app(
                cred
            )

        db = firestore.client()

        print(
            "✅ Firebase connected."
        )

        return db

    except Exception as e:

        print(
            f"❌ Firebase initialization failed:"
            f"\n{e}"
        )

        sys.exit(1)


# ============================================================
# GET LATEST FIREBASE DRAW
# ============================================================

def get_latest_firebase_draw(db):

    print(
        "\n🔎 Checking latest draw in Firebase..."
    )

    try:

        collection_ref = (
            db.collection(
                PARENT_COLLECTION
            )
            .document(
                SUBCOLLECTION
            )
            .collection(
                SUBCOLLECTION
            )
        )

        docs = collection_ref.stream()

        latest_draw = None

        total_documents = 0

        for doc in docs:

            total_documents += 1

            data = doc.to_dict()

            draw_number = data.get(
                "draw_number"
            )

            if draw_number is None:
                continue

            try:

                draw_number_int = int(
                    draw_number
                )

                if (
                    latest_draw is None
                    or draw_number_int > latest_draw
                ):

                    latest_draw = draw_number_int

            except (
                ValueError,
                TypeError
            ):

                print(
                    f"⚠️ Invalid draw number "
                    f"in {doc.id}: "
                    f"{draw_number}"
                )

        print(
            f"📊 Firebase documents found: "
            f"{total_documents}"
        )

        if latest_draw is None:

            print(
                "❌ No valid draw found "
                "in Firebase."
            )

            return None

        print(
            f"📌 Latest Firebase draw: "
            f"{latest_draw}"
        )

        return latest_draw

    except Exception as e:

        print(
            f"❌ Firebase read error:"
            f"\n{e}"
        )

        return None


# ============================================================
# CHECK FIREBASE DOCUMENT
# ============================================================

def draw_exists_in_firebase(
    db,
    draw_number
):

    document_id = (
        f"mega-power-{draw_number}"
    )

    doc_ref = (
        db.collection(
            PARENT_COLLECTION
        )
        .document(
            SUBCOLLECTION
        )
        .collection(
            SUBCOLLECTION
        )
        .document(
            document_id
        )
    )

    try:

        return doc_ref.get().exists

    except Exception as e:

        print(
            f"⚠️ Firebase existence "
            f"check failed: {e}"
        )

        return False


# ============================================================
# UPLOAD TO FIREBASE
# ============================================================

def upload_draw(
    db,
    draw
):

    draw_number = str(
        draw["draw_number"]
    )

    document_id = (
        f"mega-power-{draw_number}"
    )

    doc_ref = (
        db.collection(
            PARENT_COLLECTION
        )
        .document(
            SUBCOLLECTION
        )
        .collection(
            SUBCOLLECTION
        )
        .document(
            document_id
        )
    )

    firestore_data = {

        "lottery": draw.get(
            "lottery"
        ),

        "draw_number": draw_number,

        "date": draw.get(
            "date"
        ),

        "symbol": draw.get(
            "symbol"
        ),

        "numbers": draw.get(
            "numbers",
            []
        ),

        "url": draw.get(
            "url"
        )
    }

    try:

        doc_ref.set(
            firestore_data
        )

        print(
            f"\n☁️ Firebase upload successful!"
        )

        print(
            f"   Document: {document_id}"
        )

        return True

    except Exception as e:

        print(
            f"❌ Firebase upload failed:"
            f"\n{e}"
        )

        return False


# ============================================================
# MAIN SYNC
# ============================================================

def sync_new_draws():

    print("\n")
    print("=" * 70)

    print(
        "🏆 MEGA POWER → FIREBASE "
        "AUTOMATIC SYNC".center(70)
    )

    print("=" * 70)

    print(
        f"\n📅 Started: "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # --------------------------------------------------------
    # Firebase
    # --------------------------------------------------------

    db = initialize_firebase()

    latest_draw = get_latest_firebase_draw(
        db
    )

    if latest_draw is None:

        print(
            "\n❌ Firebase contains no "
            "Mega Power results."
        )

        sys.exit(1)

    # --------------------------------------------------------
    # Start from next draw
    # --------------------------------------------------------

    next_draw = latest_draw + 1

    print(
        f"\n🚀 Starting from draw: "
        f"{next_draw}"
    )

    print(
        "Checking NLB for newer results..."
    )

    print("=" * 70)

    scraper = MegaPowerScraper()

    uploaded_count = 0

    checked_count = 0

    upload_failed = False

    try:

        while True:

            draw_number = next_draw

            checked_count += 1

            # ------------------------------------------------
            # Check NLB
            # ------------------------------------------------

            result = scraper.get_result(
                draw_number
            )

            # ------------------------------------------------
            # Result found
            # ------------------------------------------------

            if result:

                print(
                    "\n" + "-" * 60
                )

                print(
                    f"🎉 NEW DRAW FOUND: "
                    f"{draw_number}"
                )

                print(
                    f"📅 Date   : "
                    f"{result.get('date')}"
                )

                print(
                    f"🔤 Symbol : "
                    f"{result.get('symbol')}"
                )

                print(
                    f"🎱 Numbers: "
                    f"{', '.join(result.get('numbers', []))}"
                )

                print(
                    "-" * 60
                )

                # ------------------------------------------------
                # Check if already in Firebase
                # ------------------------------------------------

                if draw_exists_in_firebase(
                    db,
                    draw_number
                ):

                    print(
                        f"ℹ️ Draw {draw_number} "
                        f"already exists in Firebase."
                    )

                else:

                    success = upload_draw(
                        db,
                        result
                    )

                    if not success:

                        print(
                            "\n❌ Upload failed."
                        )

                        print(
                            "Stopping sync."
                        )

                        upload_failed = True

                        break

                    uploaded_count += 1

                # ------------------------------------------------
                # Check next draw
                # ------------------------------------------------

                next_draw += 1

                time.sleep(
                    REQUEST_DELAY
                )

            # ------------------------------------------------
            # Result not found
            # ------------------------------------------------

            else:

                print(
                    "\n⏹️ No new result found "
                    f"for draw {draw_number}."
                )

                print(
                    "Firebase synchronization "
                    "finished."
                )

                break

    except KeyboardInterrupt:

        print(
            "\n\n⚠️ Sync interrupted "
            "by user."
        )

    finally:

        scraper.close()

        # ----------------------------------------------------
        # SUMMARY
        # ----------------------------------------------------

        print("\n")
        print("=" * 70)

        print(
            "📊 SYNC SUMMARY".center(70)
        )

        print("=" * 70)

        print(
            f"📌 Previous Firebase draw : "
            f"{latest_draw}"
        )

        print(
            f"🔎 Draws checked          : "
            f"{checked_count}"
        )

        print(
            f"☁️ New draws uploaded     : "
            f"{uploaded_count}"
        )

        if uploaded_count > 0:

            print(
                "\n🎉 Firebase successfully "
                f"updated with {uploaded_count} "
                "new draw(s)!"
            )

        else:

            print(
                "\n✅ No new draws were uploaded."
            )

        print("=" * 70)

    if upload_failed:
        sys.exit(1)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    sync_new_draws()
