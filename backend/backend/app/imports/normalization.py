import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.imports.adapters import StandardJobRow

WORK_DAYS_PER_MONTH = Decimal("21.75")
CITY_ALIASES = {
    "beijing": "北京",
    "北京": "北京",
    "changsha": "长沙",
    "长沙": "长沙",
    "chengdu": "成都",
    "成都": "成都",
    "chongqing": "重庆",
    "重庆": "重庆",
    "guangzhou": "广州",
    "广州": "广州",
    "hangzhou": "杭州",
    "杭州": "杭州",
    "nanjing": "南京",
    "南京": "南京",
    "shanghai": "上海",
    "上海": "上海",
    "shenzhen": "深圳",
    "深圳": "深圳",
    "suzhou": "苏州",
    "苏州": "苏州",
    "wuhan": "武汉",
    "武汉": "武汉",
    "xian": "西安",
    "西安": "西安",
}
CITY_CODES = {
    "北京": "CN-BJ",
    "长沙": "CN-CS",
    "成都": "CN-CD",
    "重庆": "CN-CQ",
    "广州": "CN-GZ",
    "杭州": "CN-HZ",
    "南京": "CN-NJ",
    "上海": "CN-SH",
    "深圳": "CN-SZ",
    "苏州": "CN-SZSU",
    "武汉": "CN-WH",
    "西安": "CN-XA",
}


@dataclass(frozen=True, slots=True)
class CityNormalization:
    city_name: str | None
    city_code: str | None
    work_area: str | None
    warnings: list[str]


@dataclass(frozen=True, slots=True)
class NormalizedJobRow:
    normalized_title: str
    company_name: str | None
    city_code: str | None
    city_name: str | None
    work_area: str | None
    salary_min_monthly: int | None
    salary_max_monthly: int | None
    salary_months: Decimal | None
    education_level: str
    experience_min_months: int | None
    experience_max_months: int | None
    published_at: date | None
    normalized_text: str | None
    quality_score: Decimal
    quality_flags: list[str]


def normalize_salary(
    value: str | None,
) -> tuple[int | None, int | None, Decimal | None, list[str]]:
    if not value or not value.strip():
        return None, None, None, ["salary_missing"]
    normalized = re.sub(r"\s+", "", value.lower())
    salary_months = None
    months_match = re.search(r"(?:·|\.)?(\d+(?:\.\d+)?)薪", normalized)
    if months_match:
        salary_months = Decimal(months_match.group(1))
    numbers = [Decimal(item) for item in re.findall(r"\d+(?:\.\d+)?", normalized)]
    if not numbers:
        return None, None, salary_months, ["salary_unparsed"]
    multiplier = (
        Decimal("10000")
        if "万" in normalized
        else Decimal("1000")
        if "k" in normalized
        else Decimal("1")
    )
    minimum = numbers[0] * multiplier
    maximum = numbers[1] * multiplier if len(numbers) > 1 else minimum
    warnings: list[str] = []
    if "/天" in normalized or "每天" in normalized:
        minimum *= WORK_DAYS_PER_MONTH
        maximum *= WORK_DAYS_PER_MONTH
        warnings.append("salary_period_converted")
    return (
        int(minimum.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        int(maximum.quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
        salary_months,
        warnings,
    )


def normalize_date(
    value: str | None,
    anchor: date | datetime,
) -> tuple[date | None, list[str]]:
    anchor_date = anchor.date() if isinstance(anchor, datetime) else anchor
    if not value or not value.strip():
        return None, ["issue_date_missing"]
    normalized = value.strip()
    if normalized in {"今日更新", "今天更新"}:
        return anchor_date, []
    days_match = re.fullmatch(r"(\d+)天前更新", normalized)
    if days_match:
        return anchor_date - timedelta(days=int(days_match.group(1))), []
    month_day_match = re.fullmatch(r"(\d{1,2})月(\d{1,2})日更新", normalized)
    if month_day_match:
        month = int(month_day_match.group(1))
        day = int(month_day_match.group(2))
        try:
            candidate = date(anchor_date.year, month, day)
        except ValueError:
            return None, ["issue_date_unparsed"]
        if candidate > anchor_date:
            candidate = date(anchor_date.year - 1, month, day)
        return candidate, []
    for pattern in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(normalized, pattern).date(), []
        except ValueError:
            continue
    return None, ["issue_date_unparsed"]


def normalize_experience(
    value: str | None,
) -> tuple[int | None, int | None, list[str]]:
    if not value or not value.strip():
        return None, None, ["experience_missing"]
    normalized = value.strip()
    if normalized in {"应届生", "无经验"}:
        return 0, 0, []
    if normalized in {"经验不限", "不限"}:
        return None, None, []
    range_match = re.fullmatch(r"(\d+)\s*[-至]\s*(\d+)年", normalized)
    if range_match:
        return int(range_match.group(1)) * 12, int(range_match.group(2)) * 12, []
    upper_match = re.fullmatch(r"(\d+)年以上", normalized)
    if upper_match:
        return int(upper_match.group(1)) * 12, None, []
    lower_match = re.fullmatch(r"(\d+)年以内", normalized)
    if lower_match:
        return 0, int(lower_match.group(1)) * 12, []
    return None, None, ["experience_unparsed"]


def normalize_education(value: str | None) -> str:
    if not value or not value.strip() or value.strip() in {"不限", "学历不限"}:
        return "unknown"
    normalized = value.strip()
    if "博士" in normalized:
        return "doctorate"
    if "硕士" in normalized or "研究生" in normalized:
        return "master"
    if "本科" in normalized:
        return "bachelor"
    if "大专" in normalized or "专科" in normalized:
        return "associate"
    if "高中" in normalized or "中专" in normalized:
        return "high_school"
    if "初中" in normalized or "小学" in normalized:
        return "below_high_school"
    return "unknown"


def normalize_city(
    work_area: str | None,
    city: str | None,
) -> CityNormalization:
    normalized_work_area = clean_text(work_area)
    work_city = _find_city(normalized_work_area)
    source_city = _find_city(clean_text(city))
    warnings: list[str] = []
    if work_city and source_city and work_city != source_city:
        warnings.append("city_conflict")
    city_name = work_city or source_city
    return CityNormalization(
        city_name=city_name,
        city_code=CITY_CODES.get(city_name),
        work_area=normalized_work_area,
        warnings=warnings,
    )


def normalize_row(row: StandardJobRow, anchor: date | datetime) -> NormalizedJobRow:
    salary_min, salary_max, salary_months, salary_warnings = normalize_salary(
        row.salary_text
    )
    published_at, date_warnings = normalize_date(row.issue_date_text, anchor)
    experience_min, experience_max, experience_warnings = normalize_experience(
        row.work_year_text
    )
    city = normalize_city(row.work_area_text, row.city_text)
    normalized_text = clean_text(row.raw_text)
    quality_flags = list(
        dict.fromkeys(
            [
                *row.parse_warnings,
                *salary_warnings,
                *date_warnings,
                *experience_warnings,
                *city.warnings,
            ]
        )
    )
    if detect_garbled_text(row.job_name) or detect_garbled_text(row.raw_text):
        quality_flags.append("garbled_text")
    quality_score = quality_score_for(row, quality_flags)
    return NormalizedJobRow(
        normalized_title=clean_text(row.job_name) or "",
        company_name=clean_text(row.company_name),
        city_code=city.city_code,
        city_name=city.city_name,
        work_area=city.work_area,
        salary_min_monthly=salary_min,
        salary_max_monthly=salary_max,
        salary_months=salary_months,
        education_level=normalize_education(row.education_text),
        experience_min_months=experience_min,
        experience_max_months=experience_max,
        published_at=published_at,
        normalized_text=normalized_text,
        quality_score=quality_score,
        quality_flags=list(dict.fromkeys(quality_flags)),
    )


def quality_score_for(row: StandardJobRow, quality_flags: list[str]) -> Decimal:
    if row.is_rejected:
        return Decimal("0")
    penalties = {
        "missing_company_name": 10,
        "missing_skill_requirements": 10,
        "issue_date_missing": 5,
        "salary_period_converted": 5,
        "salary_unparsed": 5,
        "experience_unparsed": 5,
        "city_conflict": 5,
        "garbled_text": 20,
    }
    score = 100 - sum(penalties.get(flag, 0) for flag in set(quality_flags))
    return Decimal(str(max(0, min(100, score))))


def detect_garbled_text(value: str | None) -> bool:
    return bool(value and ("�" in value or "\x00" in value))


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.replace("\x00", "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def _find_city(value: str | None) -> str | None:
    if not value:
        return None
    lowered = value.lower()
    for alias, city in sorted(CITY_ALIASES.items(), key=lambda item: -len(item[0])):
        if alias.lower() in lowered:
            return city
    return None
