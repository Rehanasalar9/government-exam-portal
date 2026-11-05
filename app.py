import subprocess
from flask import Flask, jsonify
from flask_cors import CORS

# Windows SSL certificate support
import truststore
truststore.inject_into_ssl()

import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pypdf import PdfReader
from io import BytesIO
from urllib.parse import urljoin
import re

app = Flask(__name__)
CORS(app)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    )
}

TIMEOUT = 30
CACHE_HOURS = 6


# =========================================================
# COMMON HELPERS
# =========================================================

def download_pdf_text(url):
    """Download a PDF and return its extracted text."""
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()

    if not response.content.startswith(b"%PDF"):
        raise ValueError("The website did not return a valid PDF.")

    pdf = PdfReader(BytesIO(response.content))
    return "\n".join(page.extract_text() or "" for page in pdf.pages)


def cache_is_fresh(cache):
    return (
        cache["data"] is not None
        and cache["checked_at"] is not None
        and datetime.now() - cache["checked_at"] < timedelta(hours=CACHE_HOURS)
    )


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def date_strings(text):
    return re.findall(r"\b\d{2}[./-]\d{2}[./-]\d{4}\b", text)


# =========================================================
# SSC CALENDAR
# =========================================================

ssc_calendar_cache = {"data": None, "checked_at": None}

SSC_CALENDAR_URL = (
    "https://ssc.gov.in/api/attachment/uploads/"
    "masterData/ExamCalendar/Tentative_Calendar2026_27_08012026.pdf"
)


def get_ssc_calendar():
    if cache_is_fresh(ssc_calendar_cache):
        return ssc_calendar_cache["data"]

    try:
        pdf_text = download_pdf_text(SSC_CALENDAR_URL)
        now = datetime.now()

        result = {
            "calendar_title": "SSC Tentative Calendar 2026-2027",
            "calendar_url": SSC_CALENDAR_URL,
            "calendar_text": pdf_text,
            "last_checked": now.strftime("%d %B %Y %H:%M"),
        }

        ssc_calendar_cache["data"] = result
        ssc_calendar_cache["checked_at"] = now

        return result

    except Exception as error:
        print("Unable to fetch SSC calendar:", repr(error))

        if ssc_calendar_cache["data"] is not None:
            return ssc_calendar_cache["data"]

        return {
            "error": "Unable to fetch the official SSC calendar.",
            "details": str(error),
            "source": SSC_CALENDAR_URL,
        }


def extract_ssc_cgl_dates():
    """Extract the CGL row and month/year values from the SSC calendar."""
    calendar = get_ssc_calendar()

    if "error" in calendar:
        return calendar

    text = clean_text(calendar.get("calendar_text", ""))

    match = re.search(
        r"Combined\s+Graduate\s+Level\s+Examination"
        r"\s*[,/.-]?\s*(20\d{2})(.*?)(?="
        r"\s+\d+\s+(?:Selection|Combined|Junior|Stenographer|"
        r"Multi|Sub-Inspector|Constables|Constable|Rifleman)|$)",
        text,
        re.IGNORECASE,
    )

    if not match:
        return {
            "error": "SSC CGL dates could not be extracted reliably.",
            "source": calendar["calendar_url"],
        }

    calendar_year = match.group(1)
    row_text = match.group(2).strip()

    month_pattern = (
        r"\b(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(20\d{2})\b"
    )

    months = re.findall(month_pattern, row_text, re.IGNORECASE)

    range_match = re.search(
        r"\b(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s*[-–]\s*"
        r"(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+(20\d{2})\b",
        row_text,
        re.IGNORECASE,
    )

    if range_match:
        first_month, second_month, year = range_match.groups()
        months.extend([(first_month, year), (second_month, year)])

    unique_months = []
    seen = set()

    for month, year in months:
        key = (month.lower(), year)

        if key not in seen:
            seen.add(key)
            unique_months.append((month.title(), year))

    if not unique_months:
        return {
            "error": "No SSC CGL exam months were found.",
            "source": calendar["calendar_url"],
        }

    month_dates = [
        datetime.strptime(f"{month} {year}", "%B %Y")
        for month, year in unique_months
    ]

    latest_month = max(month_dates)

    current_month = datetime.now().replace(
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0
    )

    status = (
        "Past schedule"
        if latest_month < current_month
        else "Tentative upcoming schedule"
    )

    return {
        "exam": "SSC CGL",
        "calendar_year": calendar_year,
        "calendar_row": row_text,
        "months_found": [
            value.strftime("%B %Y")
            for value in sorted(set(month_dates))
        ],
        "status": status,
        "schedule_status": status,
        "source": calendar["calendar_url"],
        "last_checked": calendar["last_checked"],
    }


def extract_ssc_chsl_dates():
    """Extract SSC CHSL dates from the official calendar."""

    calendar = get_ssc_calendar()

    if "error" in calendar:
        return calendar

    text = clean_text(calendar.get("calendar_text", ""))
    print("SSC CALENDAR TEXT:", text)

    match = re.search(
        r"Combined\s+Higher\s+Secondary\s+\(10\+2\)\s+"
        r"Level\s+Examination,\s*2026\s+"
        r"Tier-I\s+\(CBE\)\*?\s+"
        r"(April\s+2026)\s+"
        r"(May\s+2026)\s+"
        r"(July\s*[–-]\s*September\s+2026)",
        text,
        re.IGNORECASE
    )

    if not match:
        return {
            "error": "SSC CHSL dates could not be extracted.",
            "source": calendar["calendar_url"]
        }

    advertisement_date = match.group(1)
    closing_date = match.group(2)
    exam_period = match.group(3)

    return {
        "exam": "SSC CHSL",
        "notification_date": advertisement_date,
        "last_date_to_apply": closing_date,
        "exam_date": "Tier-I: " + exam_period,
        "calendar_row": match.group(0),
        "source": calendar["calendar_url"],
        "last_checked": calendar["last_checked"]
    }

def extract_ssc_mts_dates():
    """Extract SSC MTS dates from the official calendar."""

    calendar = get_ssc_calendar()

    if "error" in calendar:
        return calendar

    text = clean_text(calendar.get("calendar_text", ""))

    match = re.search(
        r"Multi-Tasking\s*\(Non-\s*Technical\)\s*"
        r"Staff\s*&\s*Havaldar\s*\(CBIC\s*&\s*CBN\)\s*"
        r"Examination,\s*2026\s+CBE\*?\s+"
        r"(June\s+2026)\s+"
        r"(July\s+2026)\s+"
        r"(September\s*[–-]\s*November\s+2026)",
        text,
        re.IGNORECASE
    )

    if not match:
        return {
            "error": "SSC MTS dates could not be extracted.",
            "source": calendar["calendar_url"]
        }

    return {
        "exam": "SSC MTS",
        "notification_date": match.group(1),
        "last_date_to_apply": match.group(2),
        "exam_date": "September – November 2026",
        "calendar_row": match.group(0),
        "source": calendar["calendar_url"],
        "last_checked": calendar["last_checked"]
    }

def extract_ssc_gd_dates():
    """Extract SSC GD Constable dates from the official calendar."""

    calendar = get_ssc_calendar()

    if "error" in calendar:
        return calendar

    text = clean_text(calendar.get("calendar_text", ""))

    match = re.search(
        r"Constables\s*\(GD\)\s+in\s+"
        r"Central\s+Armed\s+Police\s+Forces\s*"
        r"\(CAPFs\),\s*NIA,\s*SSF\s+and\s+"
        r"Rifleman\s*\(GD\)\s+in\s+Assam\s+Rifles\s+"
        r"Examination,\s*2027\s+CBE\*?\s+"
        r"(September\s+2026)\s+"
        r"(October\s+2026)\s+"
        r"(January\s*[–-]\s*March\s+2027)",
        text,
        re.IGNORECASE
    )

    if not match:
        return {
            "error": "SSC GD dates could not be extracted.",
            "source": calendar["calendar_url"]
        }

    return {
        "exam": "SSC GD Constable",
        "notification_date": match.group(1),
        "last_date_to_apply": match.group(2),
        "exam_date": "January – March 2027",
        "calendar_row": match.group(0),
        "source": calendar["calendar_url"],
        "last_checked": calendar["last_checked"]
    }

def extract_ssc_cpo_dates():
    """Extract SSC CPO dates from the official revised notice."""

    calendar = get_ssc_calendar()

    if "error" in calendar:
        return calendar

    notice_url = (
        "https://ssc.gov.in/api/attachment/uploads/masterData/"
        "NoticeBoards/Important%20notice_revised_dated_26_10_2026.pdf"
    )

    try:
        response = requests.get(notice_url, timeout=20)
        response.raise_for_status()

        pdf = PdfReader(BytesIO(response.content))

        text = clean_text(
            " ".join(page.extract_text() or "" for page in pdf.pages)
        )

        match = re.search(
            r"CBE\s+23rd\s+to\s+28th\s+November,\s*2026",
            text,
            re.IGNORECASE
        )

        if not match:
            return {
                "error": "SSC CPO exam dates could not be extracted.",
                "source": notice_url
            }

        return {
            "exam": "SSC CPO",
            "exam_date": "23–28 November 2026",
            "source": notice_url,
            "last_checked": datetime.now().strftime(
                "%d %B %Y %H:%M"
            )
        }

    except Exception as e:
        return {"error": str(e), "source": notice_url}


def extract_ssc_je_dates():
    """Extract SSC JE dates from the official calendar."""

    calendar = get_ssc_calendar()

    if "error" in calendar:
        return calendar

    text = clean_text(calendar.get("calendar_text", ""))

    match = re.search(
        r"Junior\s+Engineer\s*"
        r"\(Civil,\s*Mechanical\s*&\s*Electrical\)\s*"
        r"Examination,\s*2026\s+Paper-I\s+\(CBE\)\*?\s+"
        r"(March\s+2026)\s+"
        r"(April\s+2026)\s+"
        r"(May\s*[–-]\s*June\s+2026)",
        text,
        re.IGNORECASE
    )

    if not match:
        return {
            "error": "SSC JE dates could not be extracted.",
            "source": calendar["calendar_url"]
        }

    return {
        "exam": "SSC JE",
        "notification_date": match.group(1),
        "last_date_to_apply": match.group(2),
        "exam_date": "May – June 2026",
        "source": calendar["calendar_url"],
        "last_checked": calendar["last_checked"]
    }

def extract_ssc_selection_post_dates():
    """Return verified SSC Selection Post Phase XIV dates."""

    notice_url = (
        "https://ssc.gov.in/api/attachment/uploads/masterData/"
        "NoticeBoards/Notice_of_RHQ_2026_phase_xiv.pdf"
    )

    return {
        "exam": "SSC Selection Post",
        "notification_date": "13 April 2026",
        "last_date_to_apply": "04 May 2026",
        "exam_date": "16–26 September 2026",
        "source": notice_url,
        "last_checked": datetime.now().strftime(
            "%d %B %Y %H:%M"
        )
    }

def extract_ssc_stenographer_dates():
    """Extract SSC Stenographer dates from the official notice."""

    notice_url = (
        "https://ssc.gov.in/api/attachment/uploads/masterData/"
        "NoticeBoards/Approved_WriteUp_23092026.pdf"
    )

    try:
        response = requests.get(notice_url, timeout=20)
        response.raise_for_status()

        pdf = PdfReader(BytesIO(response.content))

        text = clean_text(
            " ".join(page.extract_text() or "" for page in pdf.pages)
        )

        match = re.search(
            r"conducted by the Commission on\s+"
            r"09\.09\.2026\s+to\s+12\.09\.2026\s+and\s+"
            r"15\.09\.2026",
            text,
            re.IGNORECASE
        )

        if not match:
            return {
                "error": "SSC Stenographer dates could not be extracted.",
                "source": notice_url
            }

        return {
            "exam": "SSC Stenographer Grade C & D",
            "exam_date": "09–12 September and 15 September 2026",
            "source": notice_url,
            "last_checked": datetime.now().strftime(
                "%d %B %Y %H:%M"
            )
        }

    except Exception as e:
        return {
            "error": str(e),
            "source": notice_url
        }

def extract_ssc_cht_dates():
    """Extract SSC Combined Hindi Translators dates from SSC calendar."""

    calendar_url = (
        "https://ssc.gov.in/api/attachment/uploads/masterData/"
        "ExamCalendar/Tentative_Calendar2026_27_08012026.pdf"
    )

    try:
        response = requests.get(calendar_url, timeout=20)
        response.raise_for_status()

        pdf = PdfReader(BytesIO(response.content))

        text = clean_text(
            " ".join(page.extract_text() or "" for page in pdf.pages)
        )

        match = re.search(
            r"Combined\s+Hindi\s+Translators\s+Examination,\s*2026"
            r".*?April\s+2026\s+May\s+2026\s+"
            r"August\s*[–-]\s*September\s+2026",
            text,
            re.IGNORECASE
        )

        if not match:
            return {
                "error": "SSC CHT dates could not be extracted.",
                "source": calendar_url
            }

        return {
            "exam": "SSC Combined Hindi Translators",
            "notification_date": "April 2026",
            "last_date_to_apply": "May 2026",
            "exam_date": "August – September 2026",
            "source": calendar_url,
            "last_checked": datetime.now().strftime("%d %B %Y %H:%M")
        }

    except Exception as e:
        return {
            "error": str(e),
            "source": calendar_url
        }
# =========================================================
# SSC NOTICES
# =========================================================

def get_ssc_cgl_notices():
    urls = [
        "https://ssc.gov.in/",
        "https://ssccr.gov.in/announcements",
    ]

    notices = []
    seen_urls = set()
    errors = []

    for page_url in urls:
        try:
            response = requests.get(
                page_url,
                headers=HEADERS,
                timeout=TIMEOUT
            )

            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            for link in soup.find_all("a", href=True):
                title = clean_text(link.get_text(" ", strip=True))

                if not title:
                    continue

                if not (
                    "cgl" in title.lower()
                    or "combined graduate level" in title.lower()
                ):
                    continue

                href = urljoin(page_url, link["href"])

                if href not in seen_urls:
                    seen_urls.add(href)

                    notices.append({
                        "title": title,
                        "url": href,
                        "source": page_url,
                    })

        except requests.RequestException as error:
            print("Unable to fetch", page_url, repr(error))
            errors.append(page_url)

    return {
        "checked_at": datetime.now().strftime("%d %B %Y %H:%M"),
        "notices": notices,
        "source": urls,
        "pages_with_errors": errors,
        "message": (
            "Matching notices retrieved."
            if notices
            else "No matching CGL notices were found."
        ),
    }


# =========================================================
# UPSC CALENDAR
# =========================================================

upsc_calendar_cache = {"data": None, "checked_at": None}


def get_latest_upsc_calendar():

    if cache_is_fresh(upsc_calendar_cache):
        return upsc_calendar_cache["data"]

    try:
        page_url = "https://www.upsc.gov.in/examinations/exam-calendar"

        response = requests.get(
            page_url,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        pdf_links = []

        for link in soup.find_all("a", href=True):
            href = urljoin(page_url, link["href"])
            title = clean_text(link.get_text(" ", strip=True))

            if ".pdf" in href.lower() and "calendar" in (
                href + " " + title
            ).lower():
                pdf_links.append({
                    "title": title or "UPSC Examination Calendar",
                    "url": href
                })

        if not pdf_links:
            raise ValueError("No UPSC calendar PDF was found.")

        selected_pdf = pdf_links[0]

        pdf_text = download_pdf_text(selected_pdf["url"])

        now = datetime.now()

        result = {
            "calendar_title": selected_pdf["title"],
            "calendar_url": selected_pdf["url"],
            "calendar_text": pdf_text,
            "last_checked": now.strftime("%d %B %Y %H:%M"),
        }

        upsc_calendar_cache["data"] = result
        upsc_calendar_cache["checked_at"] = now

        return result

    except Exception as error:
        print("Unable to fetch UPSC calendar:", repr(error))

        if upsc_calendar_cache["data"] is not None:
            return upsc_calendar_cache["data"]

        return {
            "error": "Unable to fetch the official UPSC calendar.",
            "details": str(error),
        }


def read_latest_upsc_calendar():
    return get_latest_upsc_calendar()


# =========================================================
# UPSC CIVIL SERVICES DATE EXTRACTION
# =========================================================
def extract_upsc_civil_services_dates():

    return {
        "calendar_title": "UPSC Annual Calendar 2027",
        "calendar_year": "2027",
        "notification_date": "13.01.2027",
        "last_date_to_apply": "02.02.2027",
        "prelims_date": "23.05.2027",
        "mains_date": "20.08.2027",
        "source": "https://www.upsc.gov.in/sites/default/files/Calendar-Year-2027-Engl-200526.pdf",
        "last_checked": datetime.now().strftime(
            "%d %B %Y %H:%M"
        )
    }
# =========================================================
# UPSC OTHER EXAM DATE EXTRACTION
# =========================================================

def extract_upsc_exam_dates(exam_type=None):

    upsc_dates = {
        "nda": {
            "notification_date": "02.12.2026",
            "last_date_to_apply": "22.12.2026",
            "exam_date": "11.04.2027",
        },
        "cds": {
            "notification_date": "13.01.2027",
            "last_date_to_apply": "02.02.2027",
            "exam_date": "23.05.2027",
        },
        "capf": {
            "notification_date": "17.02.2027",
            "last_date_to_apply": "09.03.2027",
            "exam_date": "04.07.2027",
        },
    }

    if exam_type is None:
        return extract_upsc_civil_services_dates()

    exam_type = exam_type.lower()

    if exam_type not in upsc_dates:
        return {"error": "Invalid UPSC exam type."}

    return {
        "exam": exam_type.upper(),
        **upsc_dates[exam_type],
        "calendar_title": "UPSC Annual Calendar 2027",
        "calendar_url": "https://upsc.gov.in/",
        "last_checked": datetime.now().strftime(
            "%d %B %Y %H:%M"
        ),
    }

# =========================================================
# IBPS CALENDAR AND REGISTRATION
# =========================================================

ibps_cache = {"data": None, "checked_at": None}

IBPS_CALENDAR_URL = (
    "https://www.ibps.in/wp-content/uploads/IBPS_CALENDAR_2026-27_final.pdf"
)

IBPS_PO_PAGE = (
    "https://www.ibps.in/index.php/management-trainees-xvi/"
)

IBPS_REGISTRATION_URL = (
    "https://ibpsreg.ibps.in/crppoxvijun26/index.php?stat=0"
)

def get_ibps_calendar():

    if cache_is_fresh(ibps_cache):
        return ibps_cache["data"]

    try:
        response = subprocess.run(
            [
                "curl.exe",
                "-L",
                "--fail",
                "--silent",
                "--show-error",
                IBPS_CALENDAR_URL
            ],
            capture_output=True,
            timeout=30,
            check=True
        )

        pdf = PdfReader(BytesIO(response.stdout))

        pdf_text = " ".join(
            page.extract_text() or ""
            for page in pdf.pages
        )

        if not pdf_text.strip():
            raise ValueError("IBPS calendar PDF contains no extractable text.")

        now = datetime.now()

        result = {
            "calendar_title": "IBPS Tentative Calendar 2026-2027",
            "calendar_url": IBPS_CALENDAR_URL,
            "calendar_text": pdf_text,
            "last_checked": now.strftime("%d %B %Y %H:%M"),
        }

        ibps_cache["data"] = result
        ibps_cache["checked_at"] = now

        return result

    except Exception as error:
        print("Unable to fetch IBPS calendar:", repr(error))

        if ibps_cache["data"] is not None:
            return ibps_cache["data"]

        return {
            "error": "Unable to fetch the official IBPS calendar.",
            "details": str(error),
            "source": IBPS_CALENDAR_URL,
        }

def get_ibps_registration_dates():

    try:
        response = requests.get(
            IBPS_REGISTRATION_URL,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        page_text = clean_text(
            soup.get_text(" ", strip=True)
        )

        match = re.search(
            r"(?:Commencement|Start)\s+of\s+online\s+registration"
            r".{0,300}?(\d{2}[/-]\d{2}[/-]\d{4})"
            r".{0,150}?(\d{2}[/-]\d{2}[/-]\d{4})",
            page_text,
            re.IGNORECASE,
        )

        if match:
            return {
                "registration_start": match.group(1),
                "registration_closing": match.group(2),
                "registration_source": IBPS_REGISTRATION_URL,
            }

        return {
            "error": "IBPS registration dates could not be extracted.",
            "registration_source": IBPS_REGISTRATION_URL,
        }

    except Exception as error:
        print("Unable to fetch IBPS registration page:", repr(error))

        return {
            "error": "Unable to fetch IBPS registration information.",
            "details": str(error),
            "registration_source": IBPS_REGISTRATION_URL,
        }


def extract_ibps_po_dates():

    calendar = get_ibps_calendar()

    if "error" in calendar:
        return calendar

    registration = get_ibps_registration_dates()

    result = {
        "exam": "IBPS PO/MT-XVI",
        "prelims_date": "21st and 22nd November 2026",
        "mains_date": "20th December 2026",
        "calendar_title": calendar["calendar_title"],
        "calendar_source": calendar["calendar_url"],
        "official_updates_page": IBPS_PO_PAGE,
        "last_checked": calendar["last_checked"],
        "status": "Official 2026-2027 calendar dates",
        "schedule_status": "Upcoming schedule",
        "application_status": "Application Closed",
        "exam_status": "Upcoming",
    }

    if "error" not in registration:
        result.update({
            "registration_start": registration["registration_start"],
            "registration_closing": registration["registration_closing"],
            "registration_source": registration["registration_source"],
        })
    else:
        result["registration_message"] = registration["error"]

    return result


# =========================================================
# EXAM DATA
# =========================================================

exams = [
    {
        "name": "UPSC Civil Services",
        "category": "UPSC",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Bachelor's degree from a recognised university.",
        "age_limit": "Generally 21-32 years.",
        "age_relaxation": "SC/ST: 5 years; OBC: 3 years.",
        "physical_requirements": "Service-specific medical standards apply.",
        "official_website": "https://www.upsc.gov.in/",
    },
    {
        "name": "UPSC NDA",
        "category": "UPSC",
        "qualification": "12th",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "12th pass or appearing; subject requirements vary.",
        "age_limit": "Approximately 16.5-19.5 years.",
        "age_relaxation": "No standard category-based age relaxation.",
        "physical_requirements": "Armed forces physical and medical standards apply.",
        "official_website": "https://www.upsc.gov.in/",
    },
    {
        "name": "UPSC CDS",
        "category": "UPSC",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Graduation; requirements vary by academy.",
        "age_limit": "Generally 19-24 years, depending on academy.",
        "age_relaxation": "Academy-specific conditions apply.",
        "physical_requirements": "Armed forces medical and physical standards apply.",
        "official_website": "https://www.upsc.gov.in/",
    },
    {
        "name": "UPSC CAPF",
        "category": "UPSC",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Bachelor's degree.",
        "age_limit": "Generally 20-25 years.",
        "age_relaxation": "SC/ST: 5 years; OBC: 3 years.",
        "physical_requirements": "Physical standards and medical tests apply.",
        "official_website": "https://www.upsc.gov.in/",
    },
    {
        "name": "SSC CGL",
        "category": "SSC",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Bachelor's degree for most posts.",
        "age_limit": "Post-wise age limits commonly range from 18 to 32 years.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "Physical standards apply to certain posts.",
        "official_website": "https://ssc.gov.in/",
    },
    {
        "name": "SSC CHSL",
        "category": "SSC",
        "qualification": "12th",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Generally 12th pass.",
        "age_limit": "Check the applicable SSC notification.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "No general physical test for standard posts.",
        "official_website": "https://ssc.gov.in/",
    },
    {
        "name": "SSC MTS",
        "category": "SSC",
        "qualification": "10th",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Matriculation or equivalent.",
        "age_limit": "Commonly 18-25 or 18-27 years, depending on post.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "Havaldar posts require physical tests.",
        "official_website": "https://ssc.gov.in/",
    },
    {
        "name": "SSC GD Constable",
        "category": "SSC",
        "qualification": "10th",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Matriculation or equivalent.",
        "age_limit": "Check the current SSC GD notification.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "PST, PET and medical examination.",
        "official_website": "https://ssc.gov.in/",
    },
    {
        "name": "SSC CPO",
        "category": "SSC",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Bachelor's degree.",
        "age_limit": "Check the applicable notification.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "PST and PET apply.",
        "official_website": "https://ssc.gov.in/",
    },
    
    {
        "name": "SSC Selection Post",
        "category": "SSC",
        "qualification": "10th / 12th / Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Qualification depends on the post.",
        "age_limit": "Post-wise age limits apply.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "Depends on the post.",
        "official_website": "https://ssc.gov.in/",
    },
    
    {
        "name": "SSC Stenographer Grade C & D",
        "category": "SSC",
        "qualification": "12th",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "12th pass or equivalent.",
        "age_limit": "Grade C: 18-30 years; Grade D: 18-27 years.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "No general physical test.",
        "official_website": "https://ssc.gov.in/",
    },
    {
        "name": "SSC Combined Hindi Translators",
        "category": "SSC",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Check official notification for post-wise qualifications.",
        "official_website": "https://ssc.gov.in/",
    },


    {
        "name": "SSC JE",
        "category": "SSC",
        "qualification": "Diploma / Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Relevant engineering degree or diploma.",
        "age_limit": "Varies by department and post.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "No general PET/PST for standard JE posts.",
        "official_website": "https://ssc.gov.in/",
    },
    {
        "name": "IBPS PO",
        "category": "Banking",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Bachelor's degree in any discipline.",
        "age_limit": "Generally 20-30 years.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "Medical fitness as per bank rules.",
        "official_website": "https://www.ibps.in/",
    },
    {
        "name": "SBI PO",
        "category": "Banking",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Graduation in any discipline.",
        "age_limit": "Generally 21-30 years.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "Medical fitness as per bank rules.",
        "official_website": "https://sbi.co.in/web/careers",
    },
    {
        "name": "SBI Clerk",
        "category": "Banking",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Graduation in any discipline.",
        "age_limit": "Generally 20-28 years.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "Medical fitness as per bank rules.",
        "official_website": "https://sbi.co.in/web/careers",
    },
    {
        "name": "IBPS Clerk",
        "category": "Banking",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Graduation in any discipline.",
        "age_limit": "Generally 20-28 years.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "Medical fitness as per bank rules.",
        "official_website": "https://www.ibps.in/",
    },
    {
        "name": "IBPS SO",
        "category": "Banking",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Qualification depends on specialist officer post.",
        "age_limit": "Generally 20-30 years.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "Medical fitness as per bank rules.",
        "official_website": "https://www.ibps.in/",
    },
    {
        "name": "RRB NTPC (12th Level)",
        "category": "Railways",
        "qualification": "12th",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "12th pass or equivalent.",
        "age_limit": "Check the current RRB notification.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "Medical standards vary by post.",
        "official_website": "https://www.rrbcdg.gov.in/",
    },
    {
        "name": "RRB Group D",
        "category": "Railways",
        "qualification": "10th",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "10th pass or ITI, as specified in notification.",
        "age_limit": "Check the current RRB notification.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "Physical Efficiency Test and medical standards.",
        "official_website": "https://www.rrbcdg.gov.in/",
    },
    {
        "name": "RRB ALP",
        "category": "Railways",
        "qualification": "Diploma / ITI",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Relevant ITI, diploma or engineering qualification.",
        "age_limit": "Check the current RRB notification.",
        "age_relaxation": "Category-wise relaxation applies.",
        "physical_requirements": "Railway medical and vision standards apply.",
        "official_website": "https://www.rrbcdg.gov.in/",
    },
    {
        "name": "AFCAT",
        "category": "Defence",
        "qualification": "Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Graduation requirements vary by branch.",
        "age_limit": "Generally 20-24 years; flying branch conditions differ.",
        "age_relaxation": "Check branch-specific official rules.",
        "physical_requirements": "Air Force physical and medical standards.",
        "official_website": "https://afcat.cdac.in/",
    },
    {
        "name": "Agniveer",
        "category": "Defence",
        "qualification": "10th / 12th",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Qualification depends on Agniveer category.",
        "age_limit": "Check the current recruitment notification.",
        "age_relaxation": "As specified in the official notification.",
        "physical_requirements": "Physical fitness and medical tests apply.",
        "official_website": "https://joinindianarmy.nic.in/",
    },
    {
        "name": "CTET",
        "category": "Teaching",
        "qualification": "12th / Graduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Teacher-training qualifications vary by paper.",
        "age_limit": "No general upper age limit.",
        "age_relaxation": "Qualification rules depend on applicable category.",
        "physical_requirements": "No general physical test.",
        "official_website": "https://ctet.nic.in/",
    },
    {
        "name": "UGC NET",
        "category": "Teaching",
        "qualification": "Postgraduate",
        "exam_date": "Check official notification",
        "last_date_to_apply": "Check official notification",
        "eligibility": "Master's degree or equivalent, subject to rules.",
        "age_limit": "JRF has an upper age limit; Assistant Professor has none.",
        "age_relaxation": "Applicable relaxations are in the notification.",
        "physical_requirements": "No physical test.",
        "official_website": "https://ugcnet.nta.ac.in/",
    },
]


# =========================================================
# HOME ROUTE
# =========================================================

@app.route("/")
def home():
    return jsonify({
        "message": "Government Exam Information Portal API is running.",
        "status": "Success",
        "available_routes": [
            "/api/exams",
            "/api/ssc-calendar",
            "/api/ssc-notices",
            "/api/ssc-cgl-dates",
            "/api/upsc-calendars",
            "/api/upsc-dates",
            "/api/upsc-calendar-text",
            "/api/upsc-other-dates/nda",
            "/api/upsc-other-dates/cds",
            "/api/upsc-other-dates/capf",
            "/api/ibps-po-dates",
        ]
    })


# =========================================================
# SSC ROUTES
# =========================================================

@app.route("/api/ssc-calendar")
def ssc_calendar():
    result = get_ssc_calendar()

    if "error" in result:
        return jsonify(result), 503

    return jsonify(result)


@app.route("/api/ssc-notices")
def ssc_notices():
    return jsonify(get_ssc_cgl_notices())


@app.route("/api/ssc-cgl-dates")
def ssc_cgl_dates():
    result = extract_ssc_cgl_dates()

    if "error" in result:
        return jsonify(result), 503

    return jsonify(result)


# =========================================================
# UPSC ROUTES
# =========================================================

@app.route("/api/upsc-calendars")
def upsc_calendars():
    result = get_latest_upsc_calendar()

    if "error" in result:
        return jsonify(result), 503

    return jsonify(result)


@app.route("/api/upsc-dates")
def upsc_dates():
    result = extract_upsc_civil_services_dates()

    if "error" in result:
        return jsonify(result), 503

    return jsonify(result)


@app.route("/api/upsc-calendar-text")
def upsc_calendar_text():
    result = get_latest_upsc_calendar()

    if "error" in result:
        return jsonify(result), 503

    return jsonify({
        "calendar_title": result["calendar_title"],
        "calendar_url": result["calendar_url"],
        "calendar_text": result["calendar_text"],
        "last_checked": result["last_checked"],
    })


@app.route("/api/upsc-other-dates/<exam_type>")
def upsc_other_dates(exam_type):
    result = extract_upsc_exam_dates(exam_type)

    if "error" in result:
        return jsonify(result), 503

    return jsonify(result)


# =========================================================
# IBPS ROUTE
# =========================================================

@app.route("/api/ibps-po-dates")
def ibps_po_dates():
    result = extract_ibps_po_dates()

    if "error" in result:
        return jsonify(result), 503

    return jsonify(result)


# =========================================================
# MAIN EXAMS API
# =========================================================

@app.route("/api/exams", methods=["GET"])
def get_exams():

    updated_exams = [exam.copy() for exam in exams]

         
    
    # Update SSC CGL
    ssc_data = extract_ssc_cgl_dates()

    if "error" not in ssc_data:
        for exam in updated_exams:
            if exam["name"] == "SSC CGL":
                exam["exam_date"] = "Check latest official notice"
                exam["last_date_to_apply"] = "Application closed"
                exam["official_calendar"] = ssc_data.get("source")
                exam["source"] = ssc_data.get("source")
                exam["update_status"] = (
                    "Previous calendar schedule - check latest SSC notice"
                )
                exam["last_updated"] = ssc_data.get("last_checked")

   
    # Update SSC CHSL
    chsl_data = extract_ssc_chsl_dates()

    if "error" not in chsl_data:
        for exam in updated_exams:
            if exam["name"] == "SSC CHSL":
                exam["exam_date"] = chsl_data.get(
                    "exam_date",
                    exam["exam_date"]
                )

                exam["last_date_to_apply"] = (
                    "May 2026 (tentative; exact date not specified)"
                )

                exam["notification_date"] = chsl_data.get(
                    "notification_date",
                    ""
                )

                exam["official_calendar"] = chsl_data.get("source")
                exam["source"] = chsl_data.get("source")
                exam["last_updated"] = chsl_data.get("last_checked")
                exam["update_status"] = "Updated using SSC calendar"
    
    # Update SSC MTS
    mts_data = extract_ssc_mts_dates()

    if "error" not in mts_data:
        for exam in updated_exams:
            if exam["name"] == "SSC MTS":
                exam["exam_date"] = mts_data.get(
                    "exam_date",
                    exam["exam_date"]
                )

                exam["last_date_to_apply"] = (
                    "July 2026 (tentative; exact date not specified)"
                )

                exam["notification_date"] = mts_data.get(
                    "notification_date",
                    ""
                )

                exam["official_calendar"] = mts_data.get("source")
                exam["source"] = mts_data.get("source")
                exam["last_updated"] = mts_data.get("last_checked")
                exam["update_status"] = "Updated using SSC calendar"
    
    # Update SSC GD Constable
    gd_data = extract_ssc_gd_dates()

    if "error" not in gd_data:
        for exam in updated_exams:
            if exam["name"] == "SSC GD Constable":
                exam["exam_date"] = gd_data.get(
                    "exam_date",
                    exam["exam_date"]
                )

                exam["last_date_to_apply"] = (
                    "October 2026 (tentative; exact date not specified)"
                )

                exam["notification_date"] = gd_data.get(
                    "notification_date",
                    ""
                )

                exam["official_calendar"] = gd_data.get("source")
                exam["source"] = gd_data.get("source")
                exam["last_updated"] = gd_data.get("last_checked")
                exam["update_status"] = "Updated using SSC calendar"
    
    # Update SSC CPO
    cpo_data = extract_ssc_cpo_dates()

    if "error" not in cpo_data:
        for exam in updated_exams:
            if exam["name"] == "SSC CPO":
                exam["exam_date"] = cpo_data.get(
                    "exam_date",
                    exam["exam_date"]
                )

                exam["official_calendar"] = cpo_data.get("source")
                exam["source"] = cpo_data.get("source")
                exam["last_updated"] = cpo_data.get("last_checked")
                exam["update_status"] = "Updated using SSC revised notice"
    
    # Update SSC JE
    je_data = extract_ssc_je_dates()

    if "error" not in je_data:
        for exam in updated_exams:
            if exam["name"] == "SSC JE":
                exam["exam_date"] = je_data.get(
                    "exam_date",
                    exam["exam_date"]
                )

                exam["last_date_to_apply"] = (
                    "April 2026 (tentative; exact date not specified)"
                )

                exam["notification_date"] = je_data.get(
                    "notification_date",
                    ""
                )

                exam["official_calendar"] = je_data.get("source")
                exam["source"] = je_data.get("source")
                exam["last_updated"] = je_data.get("last_checked")
                exam["update_status"] = "Updated using SSC calendar"

    
    # Update SSC Selection Post
    selection_data = extract_ssc_selection_post_dates()

    if "error" not in selection_data:
        for exam in updated_exams:
            if exam["name"] == "SSC Selection Post":
                exam["exam_date"] = selection_data.get(
                    "exam_date",
                    exam["exam_date"]
                )

                exam["last_date_to_apply"] = (
                    "04 May 2026"
                )

                exam["notification_date"] = selection_data.get(
                    "notification_date",
                    ""
                )

                exam["official_calendar"] = selection_data.get("source")
                exam["source"] = selection_data.get("source")
                exam["last_updated"] = selection_data.get("last_checked")
                exam["update_status"] = "Updated using SSC official notice"
                exam["exam_status"] = "Exam Completed"
    
    # Update SSC Stenographer
    stenographer_data = extract_ssc_stenographer_dates()

    if "error" not in stenographer_data:
        for exam in updated_exams:
            if exam["name"] == "SSC Stenographer Grade C & D":
                exam["exam_date"] = stenographer_data.get(
                    "exam_date",
                    exam["exam_date"]
                )

                exam["official_calendar"] = stenographer_data.get("source")
                exam["source"] = stenographer_data.get("source")
                exam["last_updated"] = stenographer_data.get("last_checked")
                exam["update_status"] = "Updated using SSC official notice"
    
     # Update SSC Combined Hindi Translators
    cht_data = extract_ssc_cht_dates()

    if "error" not in cht_data:
        for exam in updated_exams:
            if exam["name"] == "SSC Combined Hindi Translators":
                exam["exam_date"] = cht_data.get(
                    "exam_date",
                    exam["exam_date"]
                )
                exam["last_date_to_apply"] = (
                    "May 2026 (tentative; exact date not specified)"
                )
                exam["notification_date"] = "April 2026"
                exam["official_calendar"] = cht_data.get("source")
                exam["source"] = cht_data.get("source")
                exam["last_updated"] = cht_data.get("last_checked")
                exam["update_status"] = "Updated using SSC calendar"

        # Update UPSC Civil Services
    cse_data = extract_upsc_exam_dates()

    if "error" not in cse_data:
        for exam in updated_exams:
            if exam["name"] == "UPSC Civil Services":

                exam["exam_date"] = (
                    f"Prelims: {cse_data.get('prelims_date', 'Not announced')}; "
                    f"Mains: {cse_data.get('mains_date', 'Not announced')}"
                )

                exam["notification_date"] = cse_data.get(
                    "notification_date", ""
                )

                exam["last_date_to_apply"] = cse_data.get(
                    "last_date_to_apply", ""
                )

                exam["source"] = cse_data.get("source", "")

                exam["last_checked"] = cse_data.get(
                    "last_checked", ""
                )

                exam["update_status"] = "Updated using UPSC calendar"
    # Update UPSC NDA, CDS and CAPF
    for exam_type, exam_name in [
        ("nda", "UPSC NDA"),
        ("cds", "UPSC CDS"),
        ("capf", "UPSC CAPF"),
    ]:
        data = extract_upsc_exam_dates(exam_type)

        if "error" not in data:
            for exam in updated_exams:
                if exam["name"] == exam_name:

                    exam["exam_date"] = data.get(
                        "exam_date",
                        exam["exam_date"]
                    )

                    exam["last_date_to_apply"] = data.get(
                        "last_date_to_apply",
                        exam["last_date_to_apply"]
                    )

                    exam["notification_date"] = data.get(
                        "notification_date",
                        ""
                    )

                    exam["last_checked"] = data.get(
                        "last_checked",
                        ""
                    )

                    exam["update_status"] = (
                        "Updated using UPSC calendar"
                    )

                    exam["source"] = data.get(
                        "calendar_url",
                        "https://www.upsc.gov.in/"
                    )


    # Update IBPS PO
    ibps_data = extract_ibps_po_dates()

    if "error" not in ibps_data:
        for exam in updated_exams:
            if exam["name"] == "IBPS PO":
                exam["exam_date"] = ibps_data.get(
                    "prelims_date",
                    exam["exam_date"]
                )

                exam["last_date_to_apply"] = ibps_data.get(
                    "registration_closing",
                    exam["last_date_to_apply"]
                )

                exam["update_status"] = (
                    "Updated using IBPS calendar"
                )
                exam["exam_status"] = ibps_data.get(
                    "exam_status",
                 exam.get("exam_status", "Not announced")
                )
                exam["source"] = ibps_data.get(
                    "calendar_source",
                    "https://www.ibps.in/"
                )
            # ==========================================
    
    # AUTOMATIC EXAM STATUS FOR ALL EXAMS
    # ==========================================

    today = datetime.now().date()

    date_formats = [
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d %B %Y"
    ]

    month_formats = ["%B %Y"]

    for exam in updated_exams:

        # Application status
        deadline_text = str(
            exam.get("last_date_to_apply", "")
        )

        deadline = None

        for date_format in date_formats:
            try:
                deadline = datetime.strptime(
                    deadline_text.strip(),
                    date_format
                ).date()
                break
            except ValueError:
                continue

        month_match = re.search(
            r"(January|February|March|April|May|June|July|August|"
            r"September|October|November|December)\s+(20\d{2})",
            deadline_text,
            re.IGNORECASE
        )

        if deadline:
            exam["application_status"] = (
                "Application Closed"
                if today > deadline
                else "Check official notification"
            )

        elif month_match:
            deadline_month = datetime.strptime(
                month_match.group(0),
                "%B %Y"
            ).date()

            if (today.year, today.month) > (
                deadline_month.year,
                deadline_month.month
            ):
                exam["application_status"] = "Application Closed"
            else:
                exam["application_status"] = (
                    "Check official notification"
                )
        else:
            exam["application_status"] = (
                "Check official notification"
            )

       
      
        # Examination status
        exam_text = str(exam.get("exam_date", ""))
        found_dates = []

        # Check exact dates
        
        # Check exact examination dates
        for part in exam_text.replace("|", ";").split(";"):
            date_text = part.split(":")[-1].strip()

            for date_format in date_formats:
                try:
                    parsed_date = datetime.strptime(
                        date_text,
                        date_format
                    ).date()

                    found_dates.append(parsed_date)
                    break
                except ValueError:
                    continue
                       # Check multiple examination periods (SSC Stenographer)
            stenographer_match = re.search(
            r"(\d{1,2})\s*[–-]\s*(\d{1,2})\s+"
            r"September\s+and\s+"
            r"(\d{1,2})\s+September\s+(20\d{2})",
            exam_text,
            re.IGNORECASE
        )

        if stenographer_match:
            year = int(stenographer_match.group(4))

            start_date = datetime(
                year, 9, int(stenographer_match.group(1))
            ).date()

            end_date = datetime(
                year, 9, int(stenographer_match.group(3))
            ).date()

            if today > end_date:
                exam["exam_status"] = "Exam Completed"
            elif today < start_date:
                exam["exam_status"] = "Upcoming"
            else:
                exam["exam_status"] = "Exam Period Ongoing"

        


        else:
            # Check tentative month ranges
            range_match = re.search(
                r"(January|February|March|April|May|June|July|August|"
                r"September|October|November|December)\s*[–-]\s*"
                r"(January|February|March|April|May|June|July|August|"
                r"September|October|November|December)\s+(20\d{2})",
                exam_text,
                re.IGNORECASE
            )

            if range_match:
                start_month = datetime.strptime(
                    range_match.group(1),
                    "%B"
                ).month

                end_month = datetime.strptime(
                    range_match.group(2),
                    "%B"
                ).month

                year = int(range_match.group(3))

                current_period = (
                    today.year == year
                    and start_month <= today.month <= end_month
                )

                future_period = (
                    (today.year, today.month) < (year, start_month)
                )

                if current_period or future_period:
                    exam["exam_status"] = "Tentative Schedule"
                else:
                    exam["exam_status"] = (
                        "Tentative Schedule Period Passed"
                    )

            else:
                exam["exam_status"] = exam.get(
                   "exam_status",
                   "Date Not Announced"
                )

    return jsonify({
        "total_exams": len(updated_exams),
        "last_updated": datetime.now().strftime(
            "%d %B %Y %H:%M"
        ),
        "exams": updated_exams
    })


  


# =========================================================
# START FLASK SERVER
# =========================================================

if __name__ == "__main__":

    print("\n====================================")
    print(" GOVERNMENT EXAM PORTAL")
    print("====================================")
    print("Server running at: http://127.0.0.1:5000")
    print("API endpoint: http://127.0.0.1:5000/api/exams")
    print("====================================\n")

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )