"""일괄 처리 공통 (P7, p7-s2-spec 2장 G1·G4·G6).

- 입력 형식: 목록 1~50개, 양의 정수, 중복 불가(P7-VR-01~03). 틀리면 400 INVALID_REQUEST.
- 실행: 호출자가 연 트랜잭션 1개 안에서 항목마다 세이브포인트. 4xx 도메인 오류(ApiError)는 그 항목만
  되돌리고 결과에 실패로 적는다. 5xx ApiError와 그 밖의 예외는 그대로 올려 전체를 되돌린다(G4).
- 결과: {action, total, succeeded, failed, results} — 결과 줄 순서 = 입력 순서(G6).

도메인 규칙은 모르고 반복·결과 모음만 한다(DOC·WF가 같이 쓴다).
"""

from django.db import transaction

from apps.core.http import ApiError
from apps.core.trace import step

MAX_ITEMS = 50


def _problem(path, code, message):
    return {"path": path, "code": code, "message": message}


def _is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _check_list(values, path):
    if not isinstance(values, list) or not values:
        raise ApiError(
            "처리할 항목이 없습니다.", [_problem(path, "required", "1개 이상 지정하세요.")]
        )
    if len(values) > MAX_ITEMS:
        raise ApiError(
            f"한 번에 최대 {MAX_ITEMS}건입니다.",
            [_problem(path, "max", f"최대 {MAX_ITEMS}건입니다.")],
        )


def id_list(values, path):
    """정수 id 목록(칸 id 등). 반환: 그대로의 목록."""
    _check_list(values, path)
    problems, seen = [], set()
    for i, value in enumerate(values):
        if not _is_positive_int(value):
            problems.append(_problem(f"{path}[{i}]", "invalid", "1 이상의 정수여야 합니다."))
        elif value in seen:
            problems.append(_problem(f"{path}[{i}]", "duplicate", f"{value}이(가) 중복됩니다."))
        else:
            seen.add(value)
    if problems:
        raise ApiError("항목 형식이 올바르지 않습니다.", problems)
    return list(values)


def version_items(items, path):
    """[{document_id, expected_version}] 목록. 반환: [(document_id, expected_version)]."""
    _check_list(items, path)
    problems, seen, cleaned = [], set(), []
    for i, item in enumerate(items):
        where = f"{path}[{i}]"
        if not isinstance(item, dict):
            problems.append(_problem(where, "invalid", "객체여야 합니다."))
            continue
        for key in sorted(set(item) - {"document_id", "expected_version"}):
            problems.append(_problem(f"{where}.{key}", "unknown_key", "허용되지 않은 키입니다."))
        document_id, version = item.get("document_id"), item.get("expected_version")
        if not _is_positive_int(document_id):
            problems.append(
                _problem(f"{where}.document_id", "invalid", "1 이상의 정수여야 합니다.")
            )
        elif document_id in seen:
            problems.append(
                _problem(f"{where}.document_id", "duplicate", f"{document_id}이(가) 중복됩니다.")
            )
        else:
            seen.add(document_id)
        if not _is_positive_int(version):
            problems.append(
                _problem(f"{where}.expected_version", "invalid", "1 이상의 정수여야 합니다.")
            )
        cleaned.append((document_id, version))
    if problems:
        raise ApiError("항목 형식이 올바르지 않습니다.", problems)
    return cleaned


def not_batchable(paths, message="일괄 처리할 수 없는 양식입니다."):
    """대상 양식 밖(P7-VR-05·06): 400 INVALID_REQUEST, details code not_batchable."""
    return ApiError(
        "일괄 처리 대상이 아닌 문서가 섞여 있습니다.",
        [_problem(path, "not_batchable", message) for path in paths],
    )


def error_body(error):
    return {"code": error.code, "message": error.message, "details": error.details}


def run_each(items, handle, *, ident, layer, item_step, ok_step=None, fail_step=None):
    """항목마다 세이브포인트로 handle(item)을 실행한다. 호출자 트랜잭션 안에서만 부른다.

    ident(item): 결과 줄 머리(예: {"document_id": 58}). ok_step·fail_step: 성공·실패 기록 단계 ID
    (흐름 도식에 있을 때만 — WF-BAP-06b·06a 등). 반환: 결과 줄 목록.
    """
    results = []
    for item in items:
        line = ident(item)
        with step(item_step, layer, "세이브포인트") as s:
            try:
                with transaction.atomic():
                    value = handle(item)
            except ApiError as error:
                if error.status >= 500:
                    raise
                s.note(f"{error.code} → 이 항목만 롤백")
                if fail_step:
                    with step(fail_step, layer, "실패 기록") as f:
                        f.fail(error.code)
                results.append({**line, "ok": False, "error": error_body(error)})
                continue
            if ok_step:
                with step(ok_step, layer, "성공 기록"):
                    pass
            results.append({**line, "ok": True, "result": value})
    return results


def summary(action, results):
    succeeded = sum(1 for r in results if r["ok"])
    return {
        "action": action,
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "results": results,
    }
