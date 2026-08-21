import csv
import re
from dataclasses import dataclass
from io import StringIO

OPTIONAL_WARNINGS = {
    "city": "missing_city",
    "company_name": "missing_company_name",
    "issue_date": "missing_issue_date",
    "skill_requirements": "missing_skill_requirements",
    "tech_tags": "missing_tech_tags",
}


class AdapterError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class StandardJobRow:
    row_number: int
    source_code: str
    external_id: str | None
    source_url: str | None
    job_name: str
    company_name: str | None
    salary_text: str | None
    work_area_text: str | None
    city_text: str | None
    education_text: str | None
    work_year_text: str | None
    issue_date_text: str | None
    raw_text: str | None
    source_tags: list[str]
    raw_payload: dict[str, str | None]
    parse_warnings: list[str]

    @property
    def is_rejected(self) -> bool:
        return "missing_job_name" in self.parse_warnings


class BaseAdapter:
    code = "standard_v1"
    source_codes: frozenset[str] = frozenset({"standard"})

    def iter_rows(
        self,
        text: str,
        *,
        source_code: str,
    ):
        delimiter = "\t" if text.partition("\n")[0].count("\t") else ","
        reader = csv.DictReader(StringIO(text), delimiter=delimiter)
        if not reader.fieldnames:
            raise AdapterError("IMPORT_EMPTY", "导入文件没有表头")
        normalized_headers = [_normalize_header(value) for value in reader.fieldnames]
        if "job_name" not in normalized_headers:
            raise AdapterError("IMPORT_SCHEMA_NOT_RECOGNIZED", "缺少 job_name 字段")
        for row_number, source_row in enumerate(reader, start=2):
            payload = {
                _normalize_header(key): value
                for key, value in source_row.items()
                if key is not None
            }
            yield self._to_standard_row(row_number, payload, source_code)

    def _to_standard_row(
        self,
        row_number: int,
        payload: dict[str, str | None],
        requested_source: str,
    ) -> StandardJobRow:
        job_name = _value(payload, "job_name") or ""
        row_source = (_value(payload, "source") or requested_source).lower()
        warnings = [
            warning
            for field, warning in OPTIONAL_WARNINGS.items()
            if not _value(payload, field)
        ]
        if not job_name:
            warnings.append("missing_job_name")
        if self.code != "standard_v1" and row_source not in self.source_codes:
            warnings.append("source_adapter_mismatch")
        return StandardJobRow(
            row_number=row_number,
            source_code=row_source,
            external_id=None,
            source_url=_value(payload, "job_url"),
            job_name=job_name,
            company_name=_value(payload, "company_name"),
            salary_text=_value(payload, "salary"),
            work_area_text=_value(payload, "work_area"),
            city_text=_value(payload, "city"),
            education_text=_value(payload, "education"),
            work_year_text=_value(payload, "work_year"),
            issue_date_text=_value(payload, "issue_date"),
            raw_text=_value(payload, "skill_requirements"),
            source_tags=_split_tags(_value(payload, "tech_tags")),
            raw_payload=payload,
            parse_warnings=list(dict.fromkeys(warnings)),
        )


class StandardV1Adapter(BaseAdapter):
    pass


class LiepinV1Adapter(BaseAdapter):
    code = "liepin_v1"
    source_codes = frozenset({"liepin"})


class ZhilianV1Adapter(BaseAdapter):
    code = "zhilian_v1"
    source_codes = frozenset({"zhilian", "zhilian_direct"})


ADAPTERS = {
    "standard": StandardV1Adapter(),
    "liepin": LiepinV1Adapter(),
    "zhilian": ZhilianV1Adapter(),
    "zhilian_direct": ZhilianV1Adapter(),
}


def detect_adapter(headers: list[str], source_code: str) -> BaseAdapter:
    normalized = {_normalize_header(value) for value in headers}
    if "job_name" not in normalized:
        raise AdapterError("IMPORT_SCHEMA_NOT_RECOGNIZED", "缺少 job_name 字段")
    adapter = ADAPTERS.get(source_code.strip().lower())
    if adapter is None:
        raise AdapterError("SOURCE_ADAPTER_MISMATCH", "不支持的数据来源")
    return adapter


def detect_encoding(data: bytes) -> tuple[str, str]:
    encodings = ("utf-8-sig",) if data.startswith(b"\xef\xbb\xbf") else ("utf-8",)
    for encoding in (*encodings, "gb18030"):
        try:
            return encoding, data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AdapterError("FILE_ENCODING_UNSUPPORTED", "文件编码不受支持")


def _normalize_header(value: str) -> str:
    normalized = value.lstrip("\ufeff").strip().lower().replace("-", "_")
    return re.sub(r"\s+", "_", normalized)


def _value(payload: dict[str, str | None], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _split_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return list(
        dict.fromkeys(
            item.strip() for item in re.split(r"[,，;；|]", value) if item.strip()
        )
    )
