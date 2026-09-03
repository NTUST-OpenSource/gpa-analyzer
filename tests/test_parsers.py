from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from GpaAnalyzer import NtustGradeScraper

FIXTURE = Path(__file__).parent / "fixtures" / "grades.html"


@pytest.fixture(scope="module")
def soup():
    return BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "html.parser")


def test_parse_student_info(soup):
    assert NtustGradeScraper._parse_student_info(soup) == {
        "student_id": "B11234567",
        "name": "王小明",
        "class_name": "資工系四A",
    }


def test_parse_courses_extracts_rows_and_strips_parentheses(soup):
    courses = NtustGradeScraper._parse_courses(soup)
    assert len(courses) == 4

    assert courses[0] == {
        "semester": "113-1",
        "course_id": "CS1001",
        "course_name": "計算機 概論",
        "credits": "3",
        "dimension": "核心",
        "grade": "A+",
    }
    assert courses[1]["grade"] == "通過"
    assert courses[3]["grade"] == "退選"


def test_parse_rankings_skips_header_row(soup):
    rankings = NtustGradeScraper._parse_rankings(soup)
    assert len(rankings) == 2
    assert rankings[0] == {
        "semester": "113-1",
        "class_rank": "3/50",
        "department_rank": "10/200",
        "average_score": "88.5",
        "cumulative_class_rank": "3/50",
        "cumulative_department_rank": "10/200",
        "cumulative_average_score": "88.5",
    }


def test_parse_credits_summary_reads_display_tags(soup):
    summary = NtustGradeScraper._parse_credits_summary(soup)
    assert summary["earned_credits"] == {"physical": "60", "online": "3", "total": "63"}
    assert summary["in_progress_credits"]["total"] == "9"
    assert summary["total_credits"]["total"] == "72"


def test_parsers_return_empty_on_unrelated_html():
    empty = BeautifulSoup("<html><body><p>nothing here</p></body></html>", "html.parser")
    assert NtustGradeScraper._parse_student_info(empty) == {}
    assert NtustGradeScraper._parse_courses(empty) == []
    assert NtustGradeScraper._parse_rankings(empty) == []
    assert NtustGradeScraper._parse_credits_summary(empty) == {}
