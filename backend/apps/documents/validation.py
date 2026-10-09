"""schema_json 형식과 문서 값 검증 (s2-spec 2장, 5.2 검증 규칙)."""

import re
from datetime import date, datetime

from django.utils import timezone

FIELD_TYPES = {"text", "number", "time", "date", "select", "bool", "staff"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SUBJECT_MAX = 100


def error(path, code, message):
    return {"path": path, "code": code, "message": message}


# ---------------------------------------------------------------- schema_json 형식


def check_template_schema(schema):
    """양식 등록 시 schema_json 형식 검사. 오류 문자열 목록을 돌려준다."""
    problems = []
    sections = schema.get("sections") if isinstance(schema, dict) else None
    if not isinstance(sections, list) or not sections:
        return ["sections 목록이 필요합니다."]
    section_keys = set()
    for i, section in enumerate(sections):
        where = f"sections[{i}]"
        if not isinstance(section, dict) or not isinstance(section.get("key"), str):
            problems.append(f"{where}.key가 필요합니다.")
            continue
        if section["key"] in section_keys:
            problems.append(f"{where}.key '{section['key']}'가 중복됩니다.")
        section_keys.add(section["key"])
        if not isinstance(section.get("repeat"), bool):
            problems.append(f"{where}.repeat는 true/false여야 합니다.")
        max_rows = section.get("max_rows")
        if max_rows is not None and (not isinstance(max_rows, int) or max_rows < 1):
            problems.append(f"{where}.max_rows는 1 이상의 정수여야 합니다.")
        fields = section.get("fields")
        if not isinstance(fields, list) or not fields:
            problems.append(f"{where}.fields 목록이 필요합니다.")
            continue
        field_keys = set()
        for j, field in enumerate(fields):
            fwhere = f"{where}.fields[{j}]"
            if not isinstance(field, dict) or not isinstance(field.get("key"), str):
                problems.append(f"{fwhere}.key가 필요합니다.")
                continue
            if field["key"] in field_keys:
                problems.append(f"{fwhere}.key '{field['key']}'가 중복됩니다.")
            field_keys.add(field["key"])
            if field.get("type") not in FIELD_TYPES:
                problems.append(f"{fwhere}.type이 올바르지 않습니다.")
            if field.get("type") == "select" and not field.get("options"):
                problems.append(f"{fwhere}.options가 필요합니다.")
    return problems


def sections_of(schema):
    return {section["key"]: section for section in schema["sections"]}


def section_order(schema):
    return {section["key"]: index for index, section in enumerate(schema["sections"])}


# ---------------------------------------------------------------- 기본 정보


def parse_work_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_due_at(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def check_basic(data, *, partial):
    """작성(partial=False) / 수정(partial=True)의 기본 정보 검사.

    반환: (정리된 값 dict, 오류 목록, 확인해야 할 staff id 집합)
    """
    cleaned, errors, staff_ids = {}, [], set()
    if "work_date" in data or not partial:
        parsed = parse_work_date(data.get("work_date"))
        if parsed is None:
            errors.append(error("work_date", "invalid", "작업일을 YYYY-MM-DD 형식으로 입력하세요."))
        else:
            cleaned["work_date"] = parsed
    if "subject" in data:
        subject = data["subject"]
        if subject is not None and not isinstance(subject, str):
            errors.append(error("subject", "invalid", "대상은 문자여야 합니다."))
        elif subject is not None and len(subject) > SUBJECT_MAX:
            errors.append(error("subject", "max_length", f"대상은 {SUBJECT_MAX}자 이하입니다."))
        else:
            cleaned["subject"] = subject or None
    if "due_at" in data:
        if data["due_at"] is None:
            cleaned["due_at"] = None
        else:
            parsed = parse_due_at(data["due_at"])
            if parsed is None:
                errors.append(error("due_at", "invalid", "마감은 ISO 8601 일시여야 합니다."))
            else:
                cleaned["due_at"] = parsed
    if "assignee_id" in data:
        value = data["assignee_id"]
        if value is None:
            cleaned["assignee_id"] = None
        elif isinstance(value, bool) or not isinstance(value, int):
            errors.append(error("assignee_id", "invalid", "담당자는 staff id여야 합니다."))
        else:
            cleaned["assignee_id"] = value
            staff_ids.add(value)
    return cleaned, errors, staff_ids


# ---------------------------------------------------------------- 섹션 값


def _empty(value):
    return value is None or value == ""


def check_values(schema_section, values, path):
    """한 행의 values 검사. 반환: (오류 목록, staff id 집합)."""
    errors, staff_ids = [], set()
    if not isinstance(values, dict):
        return [error(path, "invalid", "values는 객체여야 합니다.")], staff_ids
    fields = {field["key"]: field for field in schema_section["fields"]}
    for key in values:
        if key not in fields:
            errors.append(error(f"{path}.{key}", "unknown_field", "양식에 없는 항목입니다."))
    for key, field in fields.items():
        value = values.get(key)
        label = field.get("label", key)
        if _empty(value):
            if field.get("required"):
                errors.append(error(f"{path}.{key}", "required", f"{label}을(를) 입력하세요."))
            continue
        kind = field["type"]
        ok = True
        if kind == "text":
            ok = isinstance(value, str)
            if ok and field.get("max_length") and len(value) > field["max_length"]:
                errors.append(
                    error(
                        f"{path}.{key}",
                        "max_length",
                        f"{label}은(는) {field['max_length']}자 이하입니다.",
                    )
                )
        elif kind == "number":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif kind == "time":
            ok = isinstance(value, str) and bool(TIME_RE.match(value))
        elif kind == "date":
            ok = parse_work_date(value) is not None
        elif kind == "select":
            ok = value in field.get("options", [])
        elif kind == "bool":
            ok = isinstance(value, bool)
        elif kind == "staff":
            ok = isinstance(value, int) and not isinstance(value, bool)
            if ok:
                staff_ids.add(value)
        if not ok:
            errors.append(
                error(f"{path}.{key}", "invalid", f"{label} 값의 형식이 올바르지 않습니다.")
            )
    return errors, staff_ids


def staff_field_paths(schema_section, values, path):
    """staff 필드 값과 그 경로 (존재하지 않는 staff를 경로별로 알리기 위해)."""
    if not isinstance(values, dict):
        return []
    return [
        (f"{path}.{field['key']}", values.get(field["key"]))
        for field in schema_section["fields"]
        if field["type"] == "staff"
        and isinstance(values.get(field["key"]), int)
        and not isinstance(values.get(field["key"]), bool)
    ]


def max_rows_error(key, section):
    label = section.get("label", key)
    return error(
        f"sections[{key}]", "max_rows", f"'{label}' 영역은 최대 {section['max_rows']}행입니다."
    )


def duplicate_rounds(rows):
    """rows: [(path, values)] — 같은 반복 섹션의 최종 행. 재측정이 아닌 행끼리 round 중복."""
    seen, duplicates = {}, []
    for path, values in rows:
        if not isinstance(values, dict):
            continue
        round_value = values.get("round")
        if round_value is None or values.get("retake"):
            continue
        if round_value in seen:
            duplicates.append(
                error(f"{path}.round", "duplicate", f"측정시점 {round_value}이(가) 중복됩니다.")
            )
        else:
            seen[round_value] = path
    return duplicates


def merge_patch(target, patch):
    """JSON Merge Patch(RFC 7396). SQLite json_patch와 같은 결과."""
    result = dict(target)
    for key, value in patch.items():
        if value is None:
            result.pop(key, None)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_patch(result[key], value)
        else:
            result[key] = value
    return result
