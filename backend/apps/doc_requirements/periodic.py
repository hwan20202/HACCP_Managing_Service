"""주기형 작성 요구 REQ-F07~F09 (dev-notes/doc-requirements/p9-s2-spec.md 2~4장).

- 규칙 파일(설정 HACCP_PERIODIC_RULES, 기본 이 폴더의 periodic_rules.json)을 **호출마다**
  읽고 검증한다(VR-P9-01~05). 하나라도 틀리면 RulesInvalid — 아무것도 만들지 않는다.
- 주기 문서는 업무 대상 참조가 없다(refs = []). record_key = `{코드}|day:{날짜}`(daily) /
  `{코드}|week:{월요일}`(weekly). 값은 N1이 양식 규칙(P8 na_default·initial)으로 채운다.
- 트랜잭션: F07·F08은 스스로 atomic을 연다(호출자가 수불이 아니라 명령·화면).
  F07은 줄마다 세이브포인트 — 4xx 도메인 오류는 그 줄만 failed, 5xx·그 밖 예외는 전체를
  되돌린다(P7 core/batch와 같은 규칙).
- 계층(NFR-03): DOC 서비스(N1·양식 목록)와 staff 서비스만 부른다. DOC는 규칙 파일을 모른다.
"""

import datetime
import json
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.http import ApiError
from apps.core.trace import step
from apps.documents import services as doc
from apps.staff import services as staff_services

from . import errors

DEFAULT_RULES = Path(__file__).resolve().parent / "periodic_rules.json"
CADENCES = ("daily", "weekly")
RULE_KEYS = {"type_code", "cadence", "weekdays", "start_date", "enabled"}
MAX_DAYS = 31  # S1a-Q2: 보충은 양 끝 포함 31일까지
RESULTS = ("created", "existing", "skipped_rule", "failed")


def _today():
    """오늘(Asia/Seoul). 테스트는 이 함수를 바꿔 날짜를 고정한다."""
    return timezone.localdate()


def _problem(path, code, message):
    return {"path": path, "code": code, "message": message}


def _parse_day(value):
    """YYYY-MM-DD만 받는다. fromisoformat은 3.11부터 '2026-W42-1'·'20261012xx' 같은 형식도
    받으므로 다시 쓴 값이 입력과 같은지 확인한다(D-144 A3)."""
    if isinstance(value, datetime.date):
        return value
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = datetime.date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _monday(day):
    return day - datetime.timedelta(days=day.isoweekday() - 1)


def record_key(type_code, cadence, day):
    """(record_key, work_date): daily = 그날, weekly = 그 주 월요일(p9-s2-spec 3장)."""
    if cadence == "weekly":
        monday = _monday(day)
        return f"{type_code}|week:{monday.isoformat()}", monday
    return f"{type_code}|day:{day.isoformat()}", day


# ---------------------------------------------------------------- 규칙 파일 (VR-P9-01~05)


def _rules_path():
    return Path(getattr(settings, "HACCP_PERIODIC_RULES", None) or DEFAULT_RULES)


def _invalid(problems):
    raise errors.RulesInvalid(details=problems)


def load_rules():
    """규칙 파일을 읽고 검증한다.

    반환: [{type_code, cadence, weekdays, start_date(date), enabled}].
    """
    path = _rules_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _invalid([_problem("$", "missing", f"규칙 파일이 없습니다: {path.name}")])
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        _invalid([_problem("$", "invalid_json", f"JSON을 읽을 수 없습니다: {error}")])
    problems = []
    if not isinstance(data, dict):
        _invalid([_problem("$", "invalid", "JSON 객체여야 합니다.")])
    for key in sorted(set(data) - {"version", "rules"}):
        problems.append(_problem(key, "unknown_key", "허용되지 않은 키입니다."))
    if type(data.get("version")) is not int or data.get("version") != 1:  # 1.0·true 불가
        problems.append(_problem("version", "invalid", "version은 1이어야 합니다."))
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        problems.append(_problem("rules", "required", "규칙이 1개 이상 있어야 합니다."))
        raw_rules = []
    rules, seen = [], set()
    for i, raw in enumerate(raw_rules):
        where = f"rules[{i}]"
        if not isinstance(raw, dict):
            problems.append(_problem(where, "invalid", "객체여야 합니다."))
            continue
        for key in sorted(set(raw) - RULE_KEYS):
            problems.append(_problem(f"{where}.{key}", "unknown_key", "허용되지 않은 키입니다."))
        for key in sorted(RULE_KEYS - set(raw)):
            problems.append(_problem(f"{where}.{key}", "required", "필수입니다."))
        code = raw.get("type_code")
        if not isinstance(code, str) or not code:
            problems.append(_problem(f"{where}.type_code", "invalid", "양식 코드 문자열입니다."))
        elif code in seen:
            problems.append(_problem(f"{where}.type_code", "duplicate", f"{code}이(가) 겹칩니다."))
        else:
            seen.add(code)
        cadence = raw.get("cadence")
        if "cadence" in raw and cadence not in CADENCES:
            problems.append(
                _problem(f"{where}.cadence", "invalid", "daily 또는 weekly여야 합니다.")
            )
        weekdays = raw.get("weekdays")
        if "weekdays" in raw:
            ok = (
                isinstance(weekdays, list)
                and weekdays
                and all(
                    isinstance(d, int) and not isinstance(d, bool) and 1 <= d <= 7 for d in weekdays
                )
            )
            if not ok:
                problems.append(
                    _problem(f"{where}.weekdays", "invalid", "1(월)~7(일) 정수 1개 이상입니다.")
                )
            elif len(set(weekdays)) != len(weekdays):
                problems.append(_problem(f"{where}.weekdays", "duplicate", "요일이 겹칩니다."))
        start = _parse_day(raw.get("start_date")) if "start_date" in raw else None
        if "start_date" in raw and (start is None or not isinstance(raw["start_date"], str)):
            problems.append(_problem(f"{where}.start_date", "invalid", "YYYY-MM-DD 형식입니다."))
        if "enabled" in raw and not isinstance(raw.get("enabled"), bool):
            problems.append(_problem(f"{where}.enabled", "invalid", "true 또는 false입니다."))
        rules.append(
            {
                "type_code": code,
                "cadence": cadence,
                "weekdays": list(weekdays) if isinstance(weekdays, list) else [],
                "start_date": start,
                "enabled": raw.get("enabled"),
                "_path": where,
            }
        )
    if not problems:
        # VR-P9-02: DB에 그 양식 코드가 있어야 함(활성 여부는 줄마다 failed)
        known = {t["type_code"] for t in doc.list_templates(all_versions=True)}
        for rule in rules:
            if rule["type_code"] not in known:
                problems.append(
                    _problem(
                        f"{rule['_path']}.type_code",
                        "unknown_template",
                        f"양식 {rule['type_code']}이(가) 없습니다.",
                    )
                )
    if problems:
        _invalid(problems)
    for rule in rules:
        rule.pop("_path")
    return rules


# ---------------------------------------------------------------- 줄 계산 (3장)


def _reason(rule, day):
    if not rule["enabled"]:
        return "disabled"
    if day.isoweekday() not in rule["weekdays"]:
        return "weekday"
    if day < rule["start_date"]:
        return "before_start"
    return None


def plan_lines(rules, date_from, date_to):
    """대상 날짜·규칙 → 줄 목록 [{work_date(date), type_code, record_key, reason|None}].

    daily = 날마다 1줄, weekly = 대상 날짜를 그 주 월요일로 묶어 주마다 1줄 — 그 주 대상 날짜 중
    하나라도 요일·시작일을 만족하면 만든다(S2-Q1 a). 순서 = work_date → 규칙 파일 순서.
    """
    days = [date_from + datetime.timedelta(days=n) for n in range((date_to - date_from).days + 1)]
    lines = []
    for order, rule in enumerate(rules):
        if rule["cadence"] == "daily":
            for day in days:
                key, work = record_key(rule["type_code"], "daily", day)
                lines.append((work, order, rule["type_code"], key, _reason(rule, day)))
            continue
        weeks = {}
        for day in days:
            weeks.setdefault(_monday(day), []).append(day)
        for monday, in_week in weeks.items():
            key, work = record_key(rule["type_code"], "weekly", monday)
            reasons = [_reason(rule, day) for day in in_week]
            if None in reasons:
                reason = None
            elif "disabled" in reasons:
                reason = "disabled"
            elif "before_start" in reasons:
                reason = "before_start"  # 요일은 맞는데 시작일 전인 날이 있음
            else:
                reason = "weekday"
            lines.append((work, order, rule["type_code"], key, reason))
    lines.sort(key=lambda line: (line[0], line[1]))
    return [
        {"work_date": work, "type_code": code, "record_key": key, "reason": reason}
        for work, _, code, key, reason in lines
    ]


# ---------------------------------------------------------------- 입력 확인


def _check_actor(actor_id):
    if not isinstance(actor_id, int) or isinstance(actor_id, bool) or actor_id < 1:
        raise staff_services.InvalidStaff()
    if not staff_services.existing_ids([actor_id]):
        raise staff_services.InvalidStaff()


def _check_run_input(date_from, date_to, type_codes):
    """VR-P9-10 형식 부분(규칙 파일과 맞추는 부분은 규칙을 읽은 뒤). 반환 (from, to, codes|None)."""
    problems = []
    start, end = _parse_day(date_from), _parse_day(date_to)
    if start is None:
        problems.append(_problem("date_from", "invalid", "YYYY-MM-DD 형식입니다."))
    if end is None:
        problems.append(_problem("date_to", "invalid", "YYYY-MM-DD 형식입니다."))
    if start and end:
        if start > end:
            problems.append(_problem("date_from", "order", "시작일이 끝일보다 늦습니다."))
        elif (end - start).days + 1 > MAX_DAYS:
            problems.append(_problem("date_to", "max", f"기간은 {MAX_DAYS}일까지입니다."))
        if end > _today():
            problems.append(_problem("date_to", "future", "오늘 이후 날짜는 만들 수 없습니다."))
    codes = None
    if type_codes is not None:
        if not isinstance(type_codes, list) or not type_codes:
            problems.append(_problem("type_codes", "required", "양식 코드 1개 이상입니다."))
        else:
            codes, seen = [], set()
            for i, code in enumerate(type_codes):
                if not isinstance(code, str) or not code:
                    problems.append(_problem(f"type_codes[{i}]", "invalid", "양식 코드입니다."))
                elif code in seen:
                    problems.append(
                        _problem(f"type_codes[{i}]", "duplicate", f"{code}이(가) 겹칩니다.")
                    )
                else:
                    seen.add(code)
                    codes.append(code)
    if problems:
        raise errors.ValidationFailed(details=problems)
    return start, end, codes


# ---------------------------------------------------------------- F07 주기 생성


def _line_out(line, result, **extra):
    out = {
        "work_date": line["work_date"].isoformat(),
        "type_code": line["type_code"],
        "record_key": line["record_key"],
        "result": result,
    }
    out.update(extra)
    return out


def run_periodic(actor_id, date_from, date_to, type_codes=None):
    """F07: 기간의 주기 문서를 규칙대로 찾거나 만든다(REQ-PRN). 줄 실패는 그 줄만."""
    with step("REQ-PRN-02", "REQ", "입력·사용자 확인(VR-P9-10)"):
        start, end, codes = _check_run_input(date_from, date_to, type_codes)
        _check_actor(actor_id)
    with step("REQ-PRN-03", "REQ", "규칙 파일 읽기·검증(VR-P9-01~05)") as s:
        rules = load_rules()
        if codes is not None:
            known = {r["type_code"] for r in rules}
            unknown = [
                _problem(f"type_codes[{i}]", "not_periodic", f"규칙 파일에 {code}이(가) 없습니다.")
                for i, code in enumerate(codes)
                if code not in known
            ]
            if unknown:
                raise errors.ValidationFailed(details=unknown)
            rules = [r for r in rules if r["type_code"] in codes]
        s.note(",".join(r["type_code"] for r in rules))
    with step("REQ-PRN-04", "REQ", "줄 계산(daily 날마다 · weekly 주마다)") as s:
        planned = plan_lines(rules, start, end)
        s.note(f"{len(planned)}줄")
    lines = []
    with transaction.atomic():
        for line in planned:
            if line["reason"] is not None:
                lines.append(_line_out(line, "skipped_rule", reason=line["reason"]))
                continue
            with step("REQ-PRN-05", "REQ", f"{line['record_key']} 찾기/만들기(N1)") as s:
                try:
                    with transaction.atomic():  # 줄마다 세이브포인트
                        out = doc.get_or_create_document(
                            actor_id,
                            line["type_code"],
                            line["record_key"],
                            line["work_date"].isoformat(),
                            [],
                        )
                except ApiError as error:
                    if error.status >= 500:
                        raise
                    s.fail(error.code)
                    lines.append(_line_out(line, "failed", code=error.code, message=error.message))
                    continue
                document = out["document"]
                lines.append(
                    _line_out(
                        line,
                        "created" if out["created"] else "existing",
                        document_id=document["document_id"],
                        status=document["status"],
                    )
                )
    with step("REQ-PRN-06", "REQ", "결과"):
        totals = {name: 0 for name in RESULTS}
        for line in lines:
            totals[line["result"]] += 1
        return {
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "actor_id": actor_id,
            "lines": lines,
            "totals": totals,
        }


# ---------------------------------------------------------------- F08 주기 문서 하나


def open_periodic_document(actor_id, type_code, day):
    """F08: 그날(weekly는 그 주) 주기 문서를 찾거나 만든다(REQ-POD).

    미래·주말·시작일 전·꺼진 규칙도 허용(S1a-Q6, S1-Q2·Q3).
    """
    with step("REQ-POD-02", "REQ", "입력·사용자·규칙 확인(VR-P9-11)"):
        problems = []
        parsed = _parse_day(day)
        if parsed is None:
            problems.append(_problem("date", "invalid", "YYYY-MM-DD 형식입니다."))
        if not isinstance(type_code, str) or not type_code:
            problems.append(_problem("type_code", "required", "양식 코드입니다."))
        if problems:
            raise errors.ValidationFailed(details=problems)
        _check_actor(actor_id)
        rule = next((r for r in load_rules() if r["type_code"] == type_code), None)
        if rule is None:
            raise errors.NotPeriodic()
        key, work = record_key(type_code, rule["cadence"], parsed)
    with step("REQ-POD-03", "REQ", f"{key} 찾기/만들기(N1)"):
        with transaction.atomic():
            out = doc.get_or_create_document(actor_id, type_code, key, work.isoformat(), [])
    with step("REQ-POD-04", "REQ", "결과"):
        document = out["document"]
        return {
            "document_id": document["document_id"],
            "record_key": key,
            "work_date": work.isoformat(),
            "result": "created" if out["created"] else "existing",
            "status": document["status"],
            "version": document["version"],
        }


# ---------------------------------------------------------------- F09 규칙 목록


def periodic_rules():
    """F09: 규칙 목록(REQ-PRL). name = 그 양식의 최신 활성 이름(없으면 null)."""
    with step("REQ-PRL-01", "REQ", "규칙 파일 읽기·검증"):
        rules = load_rules()
    with step("REQ-PRL-02", "REQ", "양식 이름(DOC F02)"):
        names = {t["type_code"]: t["name"] for t in doc.list_templates()}
        return {
            "rules": [
                {
                    "type_code": r["type_code"],
                    "name": names.get(r["type_code"]),
                    "cadence": r["cadence"],
                    "weekdays": r["weekdays"],
                    "start_date": r["start_date"].isoformat(),
                    "enabled": r["enabled"],
                }
                for r in rules
            ]
        }
