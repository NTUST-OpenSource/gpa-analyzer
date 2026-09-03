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


TBODY_LESS = """
<div class="box">
  <h2>歷年學業成績列表</h2>
  <table class="table table-striped">
    <tr><td>1</td><td>113-1</td><td>CS1</td><td>演算法</td><td>(3)</td><td>A+</td><td></td><td>核心</td></tr>
    <tr><td>2</td><td>113-1</td><td>CS2</td><td>作業系統</td><td>4</td><td>C-</td><td></td><td>核心</td></tr>
  </table>
</div>
"""


def test_courses_parse_without_a_tbody_element():
    """Regression: html.parser does not synthesize <tbody>, so rows were dropped."""
    courses = NtustGradeScraper._parse_courses(BeautifulSoup(TBODY_LESS, "html.parser"))
    assert [c["course_id"] for c in courses] == ["CS1", "CS2"]
    assert courses[0]["credits"] == "3"
    assert courses[1]["grade"] == "C-"


def test_decorative_span_does_not_swallow_the_grade():
    html = """
    <div class="box"><h2>歷年學業成績列表</h2><table class="table-striped"><tbody>
      <tr><td>1</td><td>113-1</td><td>CS1</td><td>演算法</td><td>3</td>
          <td><span class="icon"></span><span class="text-success">B+</span></td>
          <td></td><td>核心</td></tr>
    </tbody></table></div>
    """
    courses = NtustGradeScraper._parse_courses(BeautifulSoup(html, "html.parser"))
    assert courses[0]["grade"] == "B+"


def test_rankings_tolerate_an_extra_column():
    html = """
    <div class="box"><h2>排名資料</h2><table class="table-striped"><tbody>
      <tr><td>113-1</td><td>3/50</td><td>10/200</td><td>88.5</td>
          <td>3/50</td><td>10/200</td><td>88.5</td><td>extra</td></tr>
    </tbody></table></div>
    """
    rankings = NtustGradeScraper._parse_rankings(BeautifulSoup(html, "html.parser"))
    assert len(rankings) == 1
    assert rankings[0]["semester"] == "113-1"


def test_credits_summary_anchors_on_a_th_label():
    html = """
    <table><tbody>
      <tr><th>已實得學分數</th><td>60</td><td>3</td><td>63</td></tr>
    </tbody></table>
    """
    summary = NtustGradeScraper._parse_credits_summary(BeautifulSoup(html, "html.parser"))
    assert summary["earned_credits"]["total"] == "63"


def test_student_info_skips_a_td_based_header_row():
    html = """
    <div class="box"><h2>基本資料</h2><table class="table">
      <tr><td>學號</td><td>姓名</td><td>班級</td></tr>
      <tr><td>B11234567</td><td>王小明</td><td>資工四A</td></tr>
    </table></div>
    """
    info = NtustGradeScraper._parse_student_info(BeautifulSoup(html, "html.parser"))
    assert info == {"student_id": "B11234567", "name": "王小明", "class_name": "資工四A"}


def test_parse_credits_never_returns_a_negative():
    from GpaAnalyzer import _parse_credits

    assert _parse_credits("-2") == 2.0
    assert _parse_credits("(3)") == 3.0
