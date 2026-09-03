import pytest

from GpaAnalyzer import _parse_credits, analyze_courses, grade_to_gpa, normalize_grade


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A+", "A+"),
        ("a-", "A-"),
        ("  B ", "B"),
        ("通過", "PASS"),
        ("PASS", "PASS"),
        ("退選", None),
        ("成績未到", None),
        ("W", None),
        ("nonsense", None),
        (None, None),
    ],
)
def test_normalize_grade(raw, expected):
    assert normalize_grade(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("3", 3.0), ("(4)", 4.0), (2, 2.0), ("", 0.0), (None, 0.0), ("abc", 0.0)],
)
def test_parse_credits(raw, expected):
    assert _parse_credits(raw) == expected


def test_grade_to_gpa():
    assert grade_to_gpa("A+") == 4.3
    assert grade_to_gpa("PASS") is None
    assert grade_to_gpa(None) is None


def test_analyze_courses_computes_weighted_gpa():
    courses = [
        {"semester": "113-1", "credits": "3", "grade": "A+"},
        {"semester": "113-1", "credits": "1", "grade": "B"},
    ]
    result = analyze_courses(courses)

    sem = result["per_semester"][0]
    assert sem["semester"] == "113-1"
    assert sem["gpa"] == pytest.approx((4.3 * 3 + 3.0 * 1) / 4, abs=1e-3)
    assert sem["attempted_credits"] == 4.0
    assert sem["grade_credits"]["A+"] == 3.0
    assert result["overall"]["gpa"] == sem["gpa"]


def test_pass_credits_count_toward_attempted_but_not_gpa():
    result = analyze_courses(
        [
            {"semester": "113-1", "credits": "3", "grade": "A"},
            {"semester": "113-1", "credits": "2", "grade": "通過"},
        ]
    )
    sem = result["per_semester"][0]
    assert sem["attempted_credits"] == 5.0
    assert sem["gpa"] == pytest.approx(4.0)


def test_withdrawn_courses_are_excluded_entirely():
    result = analyze_courses(
        [
            {"semester": "113-1", "credits": "3", "grade": "A"},
            {"semester": "113-1", "credits": "3", "grade": "退選"},
        ]
    )
    sem = result["per_semester"][0]
    assert sem["attempted_credits"] == 3.0
    assert sem["gpa"] == pytest.approx(4.0)


def test_semesters_are_sorted_and_overall_is_credit_weighted():
    result = analyze_courses(
        [
            {"semester": "113-2", "credits": "1", "grade": "C"},
            {"semester": "113-1", "credits": "3", "grade": "A"},
        ]
    )
    assert [s["semester"] for s in result["per_semester"]] == ["113-1", "113-2"]
    assert result["overall"]["gpa"] == pytest.approx((4.0 * 3 + 2.0 * 1) / 4, abs=1e-3)
    assert result["overall"]["earned_credits"] == 4.0


def test_analyze_courses_handles_empty_input():
    result = analyze_courses([])
    assert result["per_semester"] == []
    assert result["overall"]["gpa"] is None
    assert result["overall"]["earned_credits"] == 0.0
    assert result["grade_map"]["A+"]["percent_range"] == [90, 100]


def test_zero_credit_course_does_not_divide_by_zero():
    result = analyze_courses([{"semester": "113-1", "credits": "0", "grade": "A"}])
    assert result["per_semester"][0]["gpa"] is None
