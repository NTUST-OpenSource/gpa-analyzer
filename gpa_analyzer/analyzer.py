import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import ssl
import threading
import time
from contextlib import contextmanager
from functools import cache
from pathlib import Path
from typing import Any, ClassVar

import certifi
import httpx
from bs4 import BeautifulSoup

try:
    import fcntl
except ImportError:
    fcntl = None

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

COOKIE_CACHE_TTL = 30 * 60
STUDENT_INFO_TTL = 7 * 24 * 60 * 60

_cache_lock = threading.Lock()
_fallback_secret = secrets.token_bytes(32)


@contextmanager
def _locked_cache(path: Path):
    """Serialises the read-modify-write across threads and across processes."""
    with _cache_lock:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_file = path.with_name(f"{path.name}.lock")
        fd = os.open(lock_file, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            if fcntl is not None:
                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)


def cache_path(name: str) -> Path:
    """Resolved per call so CACHE_DIR stays configurable regardless of import order."""
    return Path(os.getenv("CACHE_DIR") or (ROOT / ".cache")) / name


@cache
def ssl_context() -> ssl.SSLContext:
    """
    Full chain, expiry and hostname verification against the certifi trust store.

    Only Python 3.13+'s strict RFC 5280 extension checks are relaxed: an
    intermediate in the NTUST chain omits the Subject Key Identifier, which
    would otherwise abort the handshake.
    """
    ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    return ctx


def _cache_secret() -> bytes:
    """Key for deriving cache lookup keys; falls back to a per-process secret."""
    configured = os.getenv("SECRET_KEY")
    return configured.encode("utf-8") if configured else _fallback_secret


def _prune_expired(cache: dict, ttl: int) -> dict:
    now = time.time()
    return {
        k: v for k, v in cache.items() if isinstance(v, dict) and now - v.get("timestamp", 0) < ttl
    }


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        logger.error("Failed to write %s: %s", path.name, e)
        tmp.unlink(missing_ok=True)


def _read_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as e:
        logger.error("Failed to read %s: %s", path.name, e)
        return {}


class NtustGradeScraper:
    COOKIE_CACHE_NAME: ClassVar[str] = "cookie_cache.json"
    STUDENT_INFO_NAME: ClassVar[str] = "student_info_cache.json"

    REQUIRED_COOKIES: ClassVar[tuple[str, ...]] = (
        "StuScoreQueryServ",
        "StuScoreQueryServC1",
        "StuScoreQueryServC2",
    )

    SSO_HOST: ClassVar[str] = "ssoam2.ntust.edu.tw"
    PORTAL_HOST: ClassVar[str] = "stuinfosys.ntust.edu.tw"
    URLS: ClassVar[dict[str, str]] = {
        "entry": "https://stuinfosys.ntust.edu.tw/StuScoreQueryServ/StuScoreQuery",
        "sso_root": "https://ssoam2.ntust.edu.tw/",
        "grades_display": "https://stuinfosys.ntust.edu.tw/StuScoreQueryServ/StuScoreQuery/DisplayAll",
        "student_info_index": "https://stuinfosys.ntust.edu.tw/StuScoreQueryServ/",
    }

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/141.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "zh-TW,zh;q=0.9",
                "Upgrade-Insecure-Requests": "1",
            },
            verify=ssl_context(),
            http2=True,
            follow_redirects=True,
            timeout=30.0,
        )

    @property
    def _cookie_cache_file(self) -> Path:
        return cache_path(self.COOKIE_CACHE_NAME)

    @property
    def _student_info_file(self) -> Path:
        return cache_path(self.STUDENT_INFO_NAME)

    def _hmac_key(self, domain: str, *parts: str) -> str:
        material = domain.encode() + b"\x00"
        for part in parts:
            material += f"{len(part)}:{part}".encode() + b"\x00"
        return hmac.new(_cache_secret(), material, hashlib.sha256).hexdigest()

    @property
    def _cache_key(self) -> str:
        """Binds cached cookies to the exact credential pair, not just the username."""
        return self._hmac_key("gpa-analyzer/cookie-cache", self.username, self.password)

    @property
    def _info_key(self) -> str:
        return self._hmac_key("gpa-analyzer/student-info", self.username)

    def _load_cached_cookies(self) -> bool:
        key = self._cache_key
        path = self._cookie_cache_file
        with _locked_cache(path):
            entry = _read_json(path).get(key)
        if not isinstance(entry, dict):
            return False
        if time.time() - entry.get("timestamp", 0) >= COOKIE_CACHE_TTL:
            return False
        cookies = entry.get("cookies")
        if not isinstance(cookies, dict) or not cookies:
            return False
        for name, value in cookies.items():
            self.client.cookies.set(name, value, domain=self.PORTAL_HOST, path="/")
        return True

    def _store_cookies(self) -> None:
        cookies = {
            name: value
            for name in self.REQUIRED_COOKIES
            if (value := self.client.cookies.get(name))
        }
        if not cookies:
            return
        path = self._cookie_cache_file
        with _locked_cache(path):
            cache = _prune_expired(_read_json(path), COOKIE_CACHE_TTL)
            cache[self._cache_key] = {"timestamp": time.time(), "cookies": cookies}
            _write_json_atomic(path, cache)

    def _drop_cached_cookies(self) -> None:
        path = self._cookie_cache_file
        with _locked_cache(path):
            cache = _read_json(path)
            if cache.pop(self._cache_key, None) is not None:
                _write_json_atomic(path, _prune_expired(cache, COOKIE_CACHE_TTL))

    def login(self) -> bool:
        if self._load_cached_cookies():
            return True

        self.client.cookies.clear()

        try:
            r_init = self.client.get(self.URLS["entry"])

            # Cookies were just cleared, so anything but an SSO challenge means the
            # portal never verified this password. A session cookie alone is not proof.
            if r_init.url.host != self.SSO_HOST:
                logger.warning("Entry point did not redirect to SSO; refusing to authenticate")
                return False

            form = BeautifulSoup(r_init.text, "html.parser").find("form", id="loginForm")
            if not form:
                return False

            payload = {
                name: tag.get("value", "")
                for tag in form.find_all("input")
                if (name := tag.get("name"))
            }
            payload["Username"] = self.username
            payload["Password"] = self.password
            payload.setdefault("captcha", "")

            r_login = self.client.post(self.URLS["sso_root"], data=payload)

            oidc_form = BeautifulSoup(r_login.text, "html.parser").find("form")
            if not oidc_form or not (action := oidc_form.get("action")):
                return False
            if oidc_form.get("id") == "loginForm":
                return False

            oidc_data = {
                name: tag.get("value", "")
                for tag in oidc_form.find_all("input")
                if (name := tag.get("name"))
            }
            r_done = self.client.post(r_login.url.join(action), data=oidc_data)

            # Authentication is proven by landing back on the portal holding a
            # session cookie the portal only issues after SSO succeeds.
            if r_done.url.host != self.PORTAL_HOST:
                return False
            if "StuScoreQueryServ" not in self.client.cookies:
                return False
            self._store_cookies()
            return True

        except (httpx.HTTPError, httpx.CookieConflict, ValueError) as e:
            logger.warning("Login transport error: %s", type(e).__name__)
            return False

    def _get_student_info(self) -> dict:
        now = time.time()
        path = self._student_info_file
        with _locked_cache(path):
            cache = _read_json(path)
        entry = cache.get(self._info_key)
        if isinstance(entry, dict) and now - entry.get("timestamp", 0) < STUDENT_INFO_TTL:
            return entry.get("data", {})

        try:
            r = self.client.get(self.URLS["student_info_index"])
            if r.url.host == self.SSO_HOST:
                self._drop_cached_cookies()
                if not self.login():
                    return {}
                r = self.client.get(self.URLS["student_info_index"])

            r.raise_for_status()
            info = self._parse_student_info(BeautifulSoup(r.text, "html.parser"))
        except (httpx.HTTPError, httpx.CookieConflict) as e:
            logger.warning("Student info fetch failed: %s", type(e).__name__)
            return {}

        if info:
            with _locked_cache(path):
                cache = _prune_expired(_read_json(path), STUDENT_INFO_TTL)
                cache[self._info_key] = {"timestamp": now, "data": info}
                _write_json_atomic(path, cache)
        return info

    def fetch_grades(self) -> dict:
        empty = {"courses": [], "rankings": [], "credits_summary": {}, "student_info": {}}
        try:
            r = self.client.get(self.URLS["grades_display"])

            if r.url.host == self.SSO_HOST:
                self._drop_cached_cookies()
                if not self.login():
                    return {**empty, "error": "session_expired"}
                r = self.client.get(self.URLS["grades_display"])

            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

            student_info = self._get_student_info()
            courses = self._parse_courses(soup)

            if not courses and "歷年學業成績列表" not in r.text:
                return {**empty, "student_info": student_info, "error": "grade_page_unavailable"}

            return {
                "courses": courses,
                "rankings": self._parse_rankings(soup),
                "credits_summary": self._parse_credits_summary(soup),
                "student_info": student_info,
            }
        except (httpx.HTTPError, httpx.CookieConflict) as e:
            logger.warning("Grade fetch failed: %s", type(e).__name__)
            return {**empty, "error": "upstream_unavailable"}

    @staticmethod
    def _parse_student_info(soup: BeautifulSoup) -> dict:
        header = soup.find(lambda tag: tag.name == "h2" and "基本資料" in tag.get_text())
        if not header or not (box := header.find_parent("div", class_="box")):
            return {}
        if not (table := box.find("table", class_="table")):
            return {}

        for row in (table.find("tbody") or table).find_all("tr"):
            cols = [c.get_text(strip=True) for c in row.find_all("td")]
            if len(cols) < 3 or cols[0] in ("學號", "姓名"):
                continue
            return {"student_id": cols[0], "name": cols[1], "class_name": cols[2]}
        return {}

    @staticmethod
    def _parse_courses(soup: BeautifulSoup) -> list:
        grade_table = None
        header = soup.find(lambda tag: tag.name == "h2" and "歷年學業成績列表" in tag.get_text())
        if header and (box := header.find_parent("div", class_="box")):
            grade_table = box.find("table", class_="table-striped")

        if not grade_table:
            for table in soup.find_all("table"):
                if "課程名稱" in table.get_text():
                    grade_table = table
                    break

        if not grade_table:
            return []

        courses = []
        for row in (grade_table.find("tbody") or grade_table).find_all("tr"):
            cols = row.find_all("td")
            if len(cols) < 8:
                continue

            grade_cell = cols[5]
            spans = [t for span in grade_cell.find_all("span") if (t := span.get_text(strip=True))]
            grade_text = spans[0] if spans else grade_cell.get_text(strip=True)
            cleaned = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cols]

            courses.append(
                {
                    "semester": cleaned[1],
                    "course_id": cleaned[2],
                    "course_name": cleaned[3],
                    "credits": cleaned[4].strip("()"),
                    "dimension": cleaned[7],
                    "grade": grade_text.strip("()"),
                }
            )
        return courses

    @staticmethod
    def _parse_rankings(soup: BeautifulSoup) -> list:
        rank_header = next((h2 for h2 in soup.find_all("h2") if "排名資料" in h2.get_text()), None)
        if not rank_header or not (box := rank_header.find_parent("div", class_="box")):
            return []
        if not (table := box.find("table", class_="table-striped")):
            return []

        rows = (table.find("tbody") or table).find_all("tr")
        rankings = []
        for row in rows:
            cols = [col.get_text(strip=True) for col in row.find_all("td")]
            if len(cols) < 7 or "學年期" in cols:
                continue
            rankings.append(
                {
                    "semester": cols[0],
                    "class_rank": cols[1],
                    "department_rank": cols[2],
                    "average_score": cols[3],
                    "cumulative_class_rank": cols[4],
                    "cumulative_department_rank": cols[5],
                    "cumulative_average_score": cols[6],
                }
            )
        return rankings

    @staticmethod
    def _parse_credits_summary(soup: BeautifulSoup) -> dict:
        anchor = soup.find(
            lambda tag: tag.name in ("td", "th") and "已實得學分數" in tag.get_text()
        )
        if not anchor or not (table := anchor.find_parent("table")):
            return {}

        def cell_text(cell) -> str:
            display = cell.find("display")
            return (display or cell).get_text(strip=True)

        keys = {
            "已實得學分數": "earned_credits",
            "修習中學分數": "in_progress_credits",
            "合計": "total_credits",
        }

        summary = {}
        for row in (table.find("tbody") or table).find_all("tr"):
            cols = row.find_all(["td", "th"])
            if len(cols) < 4:
                continue
            title = cols[0].get_text(strip=True)
            for marker, key in keys.items():
                if marker in title:
                    summary[key] = {
                        "physical": cell_text(cols[1]),
                        "online": cell_text(cols[2]),
                        "total": cell_text(cols[3]),
                    }
                    break
        return summary

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


GRADE_TO_GPA: dict[str, float] = {
    "A+": 4.3, "A": 4.0, "A-": 3.7,
    "B+": 3.3, "B": 3.0, "B-": 2.7,
    "C+": 2.3, "C": 2.0, "C-": 1.7,
    "D": 1.0, "E": 0.0, "X": 0.0,
}  # fmt: skip

GRADE_PERCENT_RANGE: dict[str, tuple[int, int]] = {
    "A+": (90, 100), "A": (85, 89), "A-": (80, 84),
    "B+": (77, 79), "B": (73, 76), "B-": (70, 72),
    "C+": (67, 69), "C": (63, 66), "C-": (60, 62),
    "D": (50, 59), "E": (1, 49), "X": (0, 0),
}  # fmt: skip

NON_GRADED = {
    "成績未到", "二次退選", "退選", "休學", "抵免", "免修", "缺考", "不通過",
    "W", "WITHDRAW",
}  # fmt: skip

PASSING = {"通過", "P", "PASS"}


def semester_sort_key(semester: str) -> tuple[int, ...] | tuple[()]:
    """Numeric ordering: ROC year 99 must sort before 100, which strings get wrong."""
    parts = re.findall(r"\d+", str(semester))
    return tuple(int(p) for p in parts) if parts else ()


def _parse_credits(value: Any) -> float:
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else 0.0


def normalize_grade(grade: Any) -> str | None:
    if grade is None:
        return None
    g = str(grade).strip().upper()
    if g in NON_GRADED:
        return None
    if g in PASSING:
        return "PASS"
    return g if g in GRADE_TO_GPA else None


def grade_to_gpa(letter: str | None) -> float | None:
    return None if letter is None else GRADE_TO_GPA.get(letter)


def analyze_courses(courses: list[dict]) -> dict:
    by_semester: dict[str, list[dict]] = {}
    for c in courses or []:
        by_semester.setdefault(str(c.get("semester", "")).strip(), []).append(c)

    per_semester = []
    overall_qp = 0.0
    overall_credits_for_gpa = 0.0
    overall_total_credits = 0.0
    overall_earned_credits = 0.0

    ordered = sorted(by_semester.items(), key=lambda kv: (semester_sort_key(kv[0]), kv[0]))
    for semester, items in ordered:
        total_credits = 0.0
        qp = 0.0
        credits_for_gpa = 0.0
        grade_credits: dict[str, float] = dict.fromkeys(GRADE_TO_GPA, 0.0)

        for item in items:
            cr = _parse_credits(item.get("credits", 0))
            letter = normalize_grade(item.get("grade"))
            if letter is None:
                continue

            total_credits += cr
            gpa_val = grade_to_gpa(letter)
            if letter == "PASS" or (gpa_val is not None and gpa_val > 0):
                overall_earned_credits += cr
            if letter != "PASS" and cr > 0 and gpa_val is not None:
                qp += gpa_val * cr
                credits_for_gpa += cr
                grade_credits[letter] += cr

        sem_gpa = (qp / credits_for_gpa) if credits_for_gpa > 0 else None
        per_semester.append(
            {
                "semester": semester,
                "gpa": round(sem_gpa, 3) if sem_gpa is not None else None,
                "attempted_credits": total_credits,
                "grade_credits": grade_credits,
            }
        )
        overall_qp += qp
        overall_credits_for_gpa += credits_for_gpa
        overall_total_credits += total_credits

    overall_gpa = (overall_qp / overall_credits_for_gpa) if overall_credits_for_gpa > 0 else None

    return {
        "per_semester": per_semester,
        "overall": {
            "gpa": round(overall_gpa, 3) if overall_gpa is not None else None,
            "attempted_credits": overall_total_credits,
            "earned_credits": overall_earned_credits,
        },
        "grade_map": {
            k: {"gpa": v, "percent_range": list(GRADE_PERCENT_RANGE.get(k, (None, None)))}
            for k, v in GRADE_TO_GPA.items()
        },
    }


def _main() -> int:
    import sys

    from dotenv import load_dotenv

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if len(sys.argv) >= 3:
        username, password = sys.argv[1:3]
    else:
        load_dotenv()
        username = os.getenv("NTUST_USERNAME")
        password = os.getenv("NTUST_PASSWORD")

    if not username or not password:
        print(json.dumps({"error": "Missing NTUST_USERNAME or NTUST_PASSWORD."}))
        return 1

    with NtustGradeScraper(username, password) as scraper:
        if not scraper.login():
            print(json.dumps({"error": "Login failed."}))
            return 1

        grade_data = scraper.fetch_grades()
        if grade_data.get("error"):
            print(json.dumps({"error": grade_data["error"]}))
            return 1

        print(
            json.dumps(
                {**grade_data, "analysis": analyze_courses(grade_data["courses"])},
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
