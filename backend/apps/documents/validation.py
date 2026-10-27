"""schema_json 형식과 문서 값 검증 (s2-spec 2장, 5.2 검증 규칙)."""

import re
from datetime import date, datetime

from django.utils import timezone

FIELD_TYPES = {"text", "number", "time", "date", "datetime", "select", "bool", "staff"}
DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d$")
CONDITION_OPS = ("min", "max", "gt", "lt", "eq", "in")
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
            if "computed" in field:
                problems += _check_condition(field["computed"], field_keys_of(section), fwhere)
            if "hint" in field and not isinstance(field["hint"], dict):
                problems.append(f"{fwhere}.hint는 객체여야 합니다.")
            problems += _check_p8_field(field, section, fwhere)
        # P4 확장 키 (p4-s2-spec 2장)
        keys = field_keys_of(section)
        for name in ("system_rows",):
            if name in section and not isinstance(section[name], bool):
                problems.append(f"{where}.{name}는 true/false여야 합니다.")
        if "min_rows" in section and (
            not isinstance(section["min_rows"], int) or section["min_rows"] < 1
        ):
            problems.append(f"{where}.min_rows는 1 이상의 정수여야 합니다.")
        if "nonconforming" in section:
            problems += _check_condition(section["nonconforming"], keys, f"{where}.nonconforming")
        order = section.get("phase_order")
        order_invalid = order is not None and (
            not isinstance(order, dict)
            or order.get("field") not in keys
            or order.get("time_field") not in keys
            or not order.get("first")
            or not order.get("last")
        )
        if order_invalid:
            problems.append(f"{where}.phase_order는 field·time_field·first·last가 필요합니다.")
        if "fixed_phase_rows" in section:
            if not isinstance(section["fixed_phase_rows"], bool) or (
                section["fixed_phase_rows"]
                and (not section.get("repeat") or not order or order_invalid)
            ):
                problems.append(f"{where}.fixed_phase_rows는 반복 영역의 phase_order가 필요합니다.")
            elif section["fixed_phase_rows"]:
                phase = next((f for f in fields if f.get("key") == order["field"]), {})
                middle = [
                    x for x in phase.get("options", []) if x not in (order["first"], order["last"])
                ]
                if len(middle) != 1:
                    problems.append(
                        f"{where}.fixed_phase_rows에는 중간 측정시점이 하나 필요합니다."
                    )
        elapsed = section.get("elapsed")
        if elapsed is not None and (
            not isinstance(elapsed, dict)
            or not section.get("fixed_phase_rows")
            or order_invalid
            or not isinstance(elapsed.get("min"), int)
            or not isinstance(elapsed.get("max"), int)
            or elapsed["min"] < 0
            or elapsed["min"] > elapsed["max"]
            or elapsed.get("value_field") not in keys
            or elapsed.get("verdict_field") not in keys
        ):
            problems.append(f"{where}.elapsed는 시작·종료 시각과 계산 필드가 필요합니다.")
    # P15(p15-s2-spec 3.1): 결재 없는 양식·화면 본문·시스템 섹션
    if "approval" in schema and not isinstance(schema["approval"], bool):
        problems.append("approval은 true/false여야 합니다.")
    if "layout" in schema and not (isinstance(schema["layout"], str) and schema["layout"]):
        problems.append("layout은 글자여야 합니다.")
    for i, section in enumerate(sections):
        if isinstance(section, dict) and "system" in section:
            if not isinstance(section["system"], bool):
                problems.append(f"sections[{i}].system은 true/false여야 합니다.")
    if "requirement_only" in schema and not isinstance(schema["requirement_only"], bool):
        problems.append("requirement_only는 true/false여야 합니다.")
    if "skippable" in schema and not isinstance(schema["skippable"], bool):
        problems.append("skippable은 true/false여야 합니다.")  # P8
    files = schema.get("files")
    if files is not None and (
        not isinstance(files, dict) or not isinstance(files.get("min", 0), int)
    ):
        problems.append("files는 {min: 정수} 형식이어야 합니다.")
    return problems


NA = "NA"  # P8: 주·월·연 항목 "해당 없음"


def _check_p8_field(field, section, where):
    """P8 필드 키(p8-s2-spec 2장): na_default·initial·date_window."""
    problems = []
    rule = field.get("na_default")
    if rule is not None:
        if (
            not isinstance(rule, dict)
            or len(rule) > 1
            or not set(rule) <= {"weekday", "first_weekday_of_month"}
            or any(
                not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 7
                for v in rule.values()
            )
        ):
            problems.append(
                f"{where}.na_default는 {{}}·{{weekday: 1~7}}·{{first_weekday_of_month: 1~7}}"
                " 중 하나여야 합니다."
            )
        elif NA not in field.get("options", []):
            problems.append(f"{where}.na_default는 선택지에 NA가 있는 select 필드에만 둡니다.")
    if "initial" in field:
        if field.get("type") != "select" or field["initial"] not in field.get("options", []):
            problems.append(f"{where}.initial은 select 필드의 선택지 값이어야 합니다.")
    window = field.get("date_window")
    if window is not None and (
        field.get("type") != "date"
        or not isinstance(window, dict)
        or set(window) != {"from", "to"}
        or any(not isinstance(v, int) or isinstance(v, bool) for v in window.values())
        or window["from"] > window["to"]
    ):
        problems.append(f"{where}.date_window는 date 필드의 {{from, to}}(정수, from ≤ to)입니다.")
    return problems


def field_keys_of(section):
    return {f.get("key") for f in section.get("fields", []) if isinstance(f, dict)}


def _check_condition(condition, keys, where):
    if not isinstance(condition, dict):
        return [f"{where}는 객체여야 합니다."]
    group = condition.get("all", condition.get("any"))
    if not isinstance(group, list) or not group:
        return [f"{where}에는 all 또는 any 목록이 필요합니다."]
    problems = []
    for i, item in enumerate(group):
        if not isinstance(item, dict) or item.get("field") not in keys:
            problems.append(f"{where}[{i}].field가 양식에 없습니다.")
        elif not any(op in item for op in CONDITION_OPS):
            problems.append(f"{where}[{i}]에 비교 조건이 없습니다.")
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


def check_values(schema_section, values, path, *, require=False):
    """한 행의 values 검사. 반환: (오류 목록, staff id 집합).

    require=True는 작성완료 검사(필수값). 저장(작성중)에서는 형식만 본다(C-2, P4 S2).
    """
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
            if require and field.get("required"):
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
        elif kind == "datetime":
            ok = parse_local_datetime(value) is not None
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


# ------------------------------------------------ P4: 시스템 값·판정·작성완료 (p4-s2-spec 2장)


def parse_local_datetime(value):
    """YYYY-MM-DDTHH:MM(현지 시각, 초 없음). DOC-VR-15."""
    if not isinstance(value, str) or not DATETIME_RE.match(value):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_system_field(field):
    """사용자가 입력할 수 없는 필드: readonly·computed, D-234 r1 file_exists hint(성적서 유무)."""
    hint = field.get("hint")
    return bool(
        field.get("readonly")
        or "computed" in field
        or (isinstance(hint, dict) and hint.get("kind") == "file_exists")
    )


def system_key_errors(schema_section, values, path):
    """사용자 요청에 시스템 필드(is_system_field) 값이 들어 있으면 오류(DOC-VR-16)."""
    if not isinstance(values, dict):
        return []
    fields = {field["key"]: field for field in schema_section["fields"]}
    return [
        error(
            f"{path}.{key}",
            "readonly",
            f"{fields[key].get('label', key)}은(는) 입력할 수 없습니다.",
        )
        for key in values
        if key in fields and is_system_field(fields[key])
    ]


def _compare(item, value):
    if value is None or value == "":
        return None
    try:
        if "eq" in item and value != item["eq"]:
            return False
        if "in" in item and value not in item["in"]:
            return False
        if "min" in item and not value >= item["min"]:
            return False
        if "max" in item and not value <= item["max"]:
            return False
        if "gt" in item and not value > item["gt"]:
            return False
        if "lt" in item and not value < item["lt"]:
            return False
    except TypeError:
        return False
    return True


def evaluate(condition, values):
    """조건 평가: True / False / None(비교할 값이 비어 있음). all·any (p4-s2-spec 2.4)."""
    values = values if isinstance(values, dict) else {}
    if "all" in condition:
        results = [_compare(item, values.get(item["field"])) for item in condition["all"]]
        if any(r is False for r in results):
            return False
        return None if any(r is None for r in results) else True
    results = [_compare(item, values.get(item["field"])) for item in condition["any"]]
    if any(r is True for r in results):
        return True
    return None if any(r is None for r in results) else False


def computed_values(schema_section, values):
    """computed 필드의 값을 계산한다. 비교할 값이 비어 있으면 None(값 지움)."""
    result = {}
    for field in schema_section["fields"]:
        rule = field.get("computed")
        if not rule:
            continue
        outcome = evaluate(rule, values)
        result[field["key"]] = None if outcome is None else rule["then" if outcome else "else"]
    return result


def with_computed(schema_section, values):
    merged = dict(values or {})
    for key, value in computed_values(schema_section, merged).items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def is_nonconforming(schema_section, values):
    rule = schema_section.get("nonconforming")
    return bool(rule) and evaluate(rule, values) is True


def fixed_phase_values(section):
    """고정 시작·종료와 사용자가 추가할 중간 구분. 다른 양식이면 None."""
    if not section.get("fixed_phase_rows"):
        return None
    order = section["phase_order"]
    field = order["field"]
    options = next(f["options"] for f in section["fields"] if f["key"] == field)
    middle = next(value for value in options if value not in (order["first"], order["last"]))
    return field, order["first"], middle, order["last"]


def elapsed_values(section, rows):
    """시작·종료 측정일시의 분 차이와 시간 판정. 미입력은 빈 값, 역순은 오류."""
    rule = section["elapsed"]
    order = section["phase_order"]
    result = {rule["value_field"]: None, rule["verdict_field"]: None}
    first = [v for v in rows if v.get(order["field"]) == order["first"]]
    last = [v for v in rows if v.get(order["field"]) == order["last"]]
    if len(first) != 1 or len(last) != 1:
        return result, None
    start = parse_local_datetime(first[0].get(order["time_field"]))
    end = parse_local_datetime(last[0].get(order["time_field"]))
    if start is None or end is None:
        return result, None
    minutes = int((end - start).total_seconds() / 60)
    if minutes <= 0:
        return result, "time_order"
    result[rule["value_field"]] = minutes
    result[rule["verdict_field"]] = "적합" if rule["min"] <= minutes <= rule["max"] else "부적합"
    return result, None


def completion_problems(schema, rows, *, deviation_count, file_count):
    """작성완료 검사 DOC-VR-19. rows: [(section_def, row_no, values)]."""
    problems = []
    sections = sections_of(schema)
    by_section = {key: [] for key in sections}
    for key, row_no, values in rows:
        if key in by_section:
            by_section[key].append((row_no, values))
    nonconforming = False
    for key, section in sections.items():
        if section.get("system"):
            continue  # P15: 시스템 섹션은 작성완료 신호 뒤 시스템이 씀(N13)
        label = section.get("label", key)
        items = sorted(by_section[key], key=lambda item: item[0])
        if not section["repeat"] and len(items) != 1:
            problems.append(
                error(f"sections[{key}]", "row_count", f"'{label}' 영역은 1행이어야 합니다.")
            )
        if section["repeat"] and len(items) < section.get("min_rows", 0):
            problems.append(
                error(
                    f"sections[{key}]",
                    "min_rows",
                    f"'{label}' 영역은 {section['min_rows']}행 이상이어야 합니다.",
                )
            )
        for row_no, values in items:
            row_errors, _ = check_values(
                section, values, f"sections[{key}#{row_no}].values", require=True
            )
            problems += [e for e in row_errors if e["code"] == "required"]
            nonconforming = nonconforming or is_nonconforming(section, values)
        order = section.get("phase_order")
        if order and section["repeat"]:
            problems += _phase_order_problems(key, label, order, [v for _, v in items])
        if section.get("elapsed"):
            calculated, issue = elapsed_values(section, [v for _, v in items])
            if issue:
                problems.append(
                    error(f"sections[{key}]", issue, "종료 전 시각은 시작 전보다 늦어야 합니다.")
                )
            elif calculated[section["elapsed"]["value_field"]] is not None:
                end = next((v for _, v in items if v.get(order["field"]) == order["last"]), None)
                if end is not None and any(end.get(k) != v for k, v in calculated.items()):
                    problems.append(
                        error(
                            f"sections[{key}]", "elapsed_mismatch", "총 건조시간을 다시 계산하세요."
                        )
                    )
    if nonconforming and deviation_count < 1:
        problems.append(
            error(
                "deviations",
                "deviation_required",
                "부적합 항목이 있어 이탈·개선조치를 1건 이상 적으세요.",
            )
        )
    file_rule = schema.get("files")
    if file_rule and file_count < file_rule.get("min", 0):
        problems.append(
            error("files", "files_required", f"증빙 파일을 {file_rule['min']}개 이상 올리세요.")
        )
    return problems


def _phase_order_problems(key, label, order, rows):
    """시작 행·종료 행이 있고, 시작이 가장 이르고 종료가 가장 늦어야 한다(같은 시각 허용). D-057."""
    field, time_field = order["field"], order["time_field"]
    first = [r for r in rows if isinstance(r, dict) and r.get(field) == order["first"]]
    last = [r for r in rows if isinstance(r, dict) and r.get(field) == order["last"]]
    path = f"sections[{key}]"
    if not first:
        return [error(path, "phase_order", f"'{label}'에 '{order['first']}' 행이 필요합니다.")]
    if not last:
        return [error(path, "phase_order", f"'{label}'에 '{order['last']}' 행이 필요합니다.")]
    times = [parse_local_datetime(r.get(time_field)) for r in rows if isinstance(r, dict)]
    if any(t is None for t in times):
        return []  # 시각이 비어 있으면 필수값 오류로 알린다
    first_min = min(parse_local_datetime(r[time_field]) for r in first)
    last_max = max(parse_local_datetime(r[time_field]) for r in last)
    if first_min > min(times) or last_max < max(times):
        return [
            error(
                path,
                "phase_order",
                f"'{order['first']}' 행이 가장 이르고 '{order['last']}' 행이 가장 늦어야 합니다.",
            )
        ]
    return []


# ---------------------------------------- P8: 미리 채움·날짜 범위 (p8-s2-spec 2장)


def na_applies(rule, day):
    """na_default 규칙이 그날 NA를 채우는가. {} = 항상, weekday = 그 요일이 아니면,
    first_weekday_of_month = 그 달 첫 번째 그 요일이 아니면."""
    if not rule:
        return True
    if "weekday" in rule:
        return day.isoweekday() != rule["weekday"]
    weekday = rule["first_weekday_of_month"]
    return not (day.isoweekday() == weekday and day.day <= 7)


def initial_values(schema_section, day):
    """N1 새 문서의 1행 섹션 초기값: initial 값, na_default가 맞는 날은 NA. 반환 {키: 값}."""
    values = {}
    for field in schema_section["fields"]:
        if "na_default" in field and na_applies(field["na_default"], day):
            values[field["key"]] = NA
        elif "initial" in field:
            values[field["key"]] = field["initial"]
    return values


def context_errors(schema_section, values, path, work_date):
    """저장 때 문서 문맥이 필요한 검사: date_window(VR-P8-02)."""
    from datetime import timedelta

    if not isinstance(values, dict):
        return []
    problems = []
    for field in schema_section["fields"]:
        key = field["key"]
        value = values.get(key)
        if _empty(value):
            continue
        label = field.get("label", key)
        window = field.get("date_window")
        if window and work_date is not None:
            day = parse_work_date(value)
            low = work_date + timedelta(days=window["from"])
            high = work_date + timedelta(days=window["to"])
            if day is not None and not low <= day <= high:
                problems.append(
                    error(
                        f"{path}.{key}",
                        "date_window",
                        f"{label}은(는) {low.isoformat()} ~ {high.isoformat()} 안이어야 합니다.",
                    )
                )
    return problems


def check_counts(schema, values_by_key):
    """점검표 결과 수(P8 DOC-F26): 1행 섹션의 O/X select 필드. 점검표가 아니면 None."""
    counts = {"O": 0, "X": 0, "NA": 0, "blank": 0}
    found = False
    for section in schema["sections"]:
        if section.get("repeat"):
            continue
        values = values_by_key.get(section["key"]) or {}
        for field in section["fields"]:
            options = field.get("options") or []
            if field.get("type") != "select" or "O" not in options or "X" not in options:
                continue
            found = True
            value = values.get(field["key"])
            counts[value if value in ("O", "X", NA) else "blank"] += 1
    return counts if found else None


def is_system_section(section):
    """P15: 양식 섹션 `system: true` — 사용자 쓰기 금지(N13으로만 씀)."""
    return bool(section and section.get("system"))
