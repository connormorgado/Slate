"""
CSLB license verification — best-effort check against the California
Contractors State License Board public lookup.

CSLB has no official public API, so this fetches the public license
detail page and parses the HTML. Two honest caveats:
  1. If CSLB changes their page layout, parsing may need updating.
  2. Some government sites block automated traffic. The function fails
     SOFT either way — it returns ok=False plus the CSLB URL so a human
     can verify manually in one click.

Use inside the app:   from cslb import check_license
Standalone:           python cslb.py 123456
"""

import re
import sys

import requests

DETAIL_URL = ("https://www.cslb.ca.gov/OnlineServices/CheckLicenseII/"
              "LicenseDetail.aspx?LicNum={num}")

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
}


def check_license(license_no, timeout=15):
    """Look up a CSLB license number.

    Returns a dict:
      ok (bool) ....... the lookup itself worked (network + page parsed)
      active (bool) ... license text reads "current and active"
      status (str) .... the raw status sentence found on the page
      expires (str) ... expiration date if found (MM/DD/YYYY)
      url (str) ....... the CSLB page, for manual verification
      error (str) ..... present when ok=False
    """
    num = re.sub(r"\D", "", str(license_no or ""))
    url = DETAIL_URL.format(num=num)
    if not num:
        return {"ok": False, "error": "no license number provided", "url": url}

    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        return {"ok": False, "error": f"lookup failed: {e}", "url": url}

    # Strip tags -> plain text for simple, layout-tolerant matching
    text = re.sub(r"<[^>]+>", " ", r.text)
    text = re.sub(r"\s+", " ", text)

    if re.search(r"could not be found|no records? found", text, re.I):
        return {"ok": True, "active": False, "status": "License not found",
                "expires": None, "url": url}

    m_status = re.search(r"This license is ([^.]+)\.", text, re.I)
    status = m_status.group(1).strip() if m_status else "status not parsed"
    active = bool(re.search(r"current\s+and\s+active", text, re.I))
    m_exp = re.search(r"Expir\w*\s*Date[:\s]*([0-9/]{8,10})", text, re.I)

    # Business name on the license — used for name-matching during
    # verification. Best effort: the name usually follows the "Business
    # Information" header and precedes the address street number.
    business = None
    for pat in (r"Business Information\s+([A-Z0-9&'.,\- ]{3,80}?)\s+\d{1,6}\s",
                r"Business Information\s+([A-Z0-9&'.,\- ]{3,80}?)\s+(?:PO BOX|P\.?O\.?)",
                r"Business Information\s+(.{3,80}?)\s{2,}"):
        m_biz = re.search(pat, text)
        if m_biz:
            business = m_biz.group(1).strip()
            break

    # License classifications (e.g. "B - GENERAL BUILDING",
    # "C10 - ELECTRICAL"). Used to sanity-check the chosen SLATE role:
    # only C-class specialties on a "GC" account suggests a sub.
    classes = []
    for m in re.finditer(r"\b([ABC])-?(\d{1,2})?\s*[-–—]\s*[A-Za-z]", text):
        c = m.group(1) + (f"-{m.group(2)}" if m.group(2) else "")
        if c not in classes:
            classes.append(c)

    return {"ok": True, "active": active, "status": status,
            "business": business, "classes": classes,
            "expires": m_exp.group(1) if m_exp else None, "url": url}


if __name__ == "__main__":
    lic = sys.argv[1] if len(sys.argv) > 1 else input("CSLB license #: ")
    result = check_license(lic)
    for k, v in result.items():
        print(f"{k}: {v}")
