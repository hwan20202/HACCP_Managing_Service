"""생산일지(PROD-LOG) 서비스 — p15-s2-spec.md 3.3 PLG-F01~F07·F10·F12, 흐름 p15-s2-flows.md 3.2~3.9.

- 문서 자체는 DOC 표·API를 쓴다. 이 모듈은 DOC 양식 확장(N12)으로 저장·작성완료 검사와
  작성완료·작성 재개 처리를 붙이고, 연동 조회·템플릿 불러오기/저장·CCP 값·공정 등록을 맡는다.
- 계층: DOC·REQ 공개 함수와 staff만 부른다.
  수불(apps.inventory)·REQ sources(뷰)는 import하지 않는다.
- 수량은 e6 정수(수불 계약). 단위 환산은 kg↔g만(R20·R21).
"""

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.core.trace import step
from apps.doc_requirements import errors as req_errors
from apps.doc_requirements import rules as req_rules
from apps.doc_requirements import services as req
from apps.documents import services as doc

from . import errors, services
from .models import KINDS, MODES, Process, ProcessTemplate, ProcessTemplateStep

PROD_LOG = req_rules.PROD_LOG
BUILTIN_KINDS = ("CCP-1P", "CCP-2B", "CCP-3P", "INNER", "OUTER")
CCP_KINDS = ("CCP-1P", "CCP-2B", "CCP-3P")
CCP_SECTION = {"CCP-1P": "rounds", "CCP-2B": "rounds", "CCP-3P": "checks"}
CCP_2B_LAST = "건조종료 전"  # CCP-2B v3 phase_order.last(D-238)
PRECHECKS = ("pre_label", "pre_clean", "pre_lot")
MASS = {"kg": 1000, "g": 1}
E6 = 1_000_000
CANCELLED = req_rules.CANCELLED
FREEZE_FIELDS = ("manufactured_date", "lot_numbers", "product", "report_no", "planned", "output")


# ---------------------------------------------------------------- 오류


class BatchCancelled(errors.PlgError):
    status, code, message = 409, "PLG_BATCH_CANCELLED", "취소된 배치의 생산일지는 바꿀 수 없습니다."


class LinkedUnavailable(errors.PlgError):
    status, code, message = (
        409,
        "PLG_LINKED_UNAVAILABLE",
        "수불·생산 연동 데이터를 읽지 못해 처리할 수 없습니다. 잠시 뒤 다시 시도하세요.",
    )


class NotProductionLog(errors.PlgError):
    status, code, message = 404, "PLG_NOT_PRODUCTION_LOG", "생산일지가 아닙니다."


class CcpDocMissing(errors.PlgError):
    status, code, message = 404, "PLG_CCP_DOC_MISSING", "이 배치에 그 CCP 일지가 없습니다."


def _detail(path, code, message, **extra):
    return {"path": path, "code": code, "message": message, **extra}


# ---------------------------------------------------------------- 공통


def batch_id_of(record_key):
    batch_id = req_rules.batch_of_prod_log_key(record_key)
    if batch_id is None:
        raise NotProductionLog()
    return batch_id


def _prod_log(document_id, sections=()):
    """문서 머리 + 고른 섹션(DOC N18, SQL 1~2) — 생산일지가 아니면 404."""
    document = doc.document_sections(document_id, sections)
    if document["type_code"] != PROD_LOG:
        raise NotProductionLog()
    return document, batch_id_of(document["record_key"])


def _source(batch_id):
    """REQ-F13(뷰 3개). 뷰가 없으면 None(연동 오류)."""
    try:
        return req.production_log_source(batch_id)
    except req_errors.SourceUnavailable:
        return None


def _batch_state(batch_id, with_lines=False):
    """B1(S4b r1): 쓰기 전 취소 확인 — 연동(0009 뷰)과 따로 `v_doc_batch` 상태를 읽는다. SQL 1.

    with_lines면 BOM 줄도 같은 SQL로(`lines`, 0009 뷰 없으면 None — r2 A2).
    상태를 못 읽으면 쓰기를 막는다(409 PLG_LINKED_UNAVAILABLE), 취소면 409 PLG_BATCH_CANCELLED.
    """
    try:
        state = req.production_batch_state(batch_id, with_lines=with_lines)
    except req_errors.SourceUnavailable as error:
        raise LinkedUnavailable() from error
    if state["status"] == CANCELLED:
        raise BatchCancelled()
    return state


def _rows(document, section_def):
    return document["sections"].get(section_def, [])


def _ccp_docs(batch_id, kinds=CCP_KINDS):
    """그 배치에 연결된 CCP 일지 {type_code: document_id} — 배치 참조(DOC N19, r2 B2), SQL 1."""
    return doc.documents_by_batch_ref(batch_id, kinds)


# CCP 일지 상태·값(S6 r3, D-253 — R25): 작성완료 이후 상태여야 하고 값이 같아야 생산일지 작성완료
CCP_READY = ("completed", "submitted", "approved")
CCP_STATUS_LABEL = {
    "draft": "작성중",
    "rejected": "반려",
    "correcting": "정정 중",
    "skipped": "작성 안 함",
}
CCP_FIELDS = {"CCP-1P": ("verdict",), "CCP-3P": ("verdict",), "CCP-2B": ("temp", "time_min")}


def _ccp_result(kind, rows):
    """PLG-F07: 1P·3P 판정(모두 적합 → 적합, 하나라도 부적합 → 부적합), 2B 종료전 온도·총 시간."""
    if kind == "CCP-2B":
        end = next((v for v in rows if v.get("phase") == CCP_2B_LAST), {})
        return {"temp": end.get("temp_c"), "time_min": end.get("dry_minutes")}
    verdicts = [v.get("verdict") for v in rows if v.get("verdict")]
    return {"verdict": None if not verdicts else ("부적합" if "부적합" in verdicts else "적합")}


def _ccp_state(batch_id, kinds=CCP_KINDS):
    """그 배치 CCP 일지 {kind: {document_id, status, version, ready, values}} — DOC N20, SQL 1."""
    found = doc.documents_by_batch_ref_with_sections(batch_id, {k: CCP_SECTION[k] for k in kinds})
    return {
        kind: {
            "document_id": f["document_id"],
            "status": f["status"],
            "version": f["version"],
            "ready": f["status"] in CCP_READY,
            "values": _ccp_result(kind, f["rows"]),
        }
        for kind, f in found.items()
    }


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return float(a) == float(b)
    return a == b


def ccp_problems(kind, values, state):
    """R25: 한 CCP 공정 행 ↔ 그 CCP 일지. 반환 [(필드, code, 메시지)] — 없으면 맞음."""
    if state is None:
        return [("kind", "ccp_doc_missing", f"이 배치에 {kind} 일지가 없습니다.")]
    if not state["ready"]:
        label = CCP_STATUS_LABEL.get(state["status"], state["status"])
        return [
            (
                "kind",
                "ccp_not_completed",
                f"{kind} 일지를 먼저 작성완료하세요(지금 {label}, 문서 #{state['document_id']}).",
            )
        ]
    out = []
    for key in CCP_FIELDS[kind]:
        want = state["values"].get(key)
        if want is None:
            out.append((key, "ccp_no_value", f"{kind} 일지에 이 값이 없습니다."))
        elif not _same((values or {}).get(key), want):
            out.append(
                (
                    key,
                    "ccp_mismatch",
                    f"{kind} 일지 값({want})과 다릅니다 — [CCP 일지 값 가져오기]로 다시 채우세요.",
                )
            )
    return out


def _convert(quantity_e6, unit, to):
    """e6 정수 환산(kg↔g만). 못 바꾸면 None."""
    if quantity_e6 is None:
        return None
    if unit == to:
        return quantity_e6
    if unit in MASS and to in MASS:
        return quantity_e6 * MASS[unit] // MASS[to]
    return None


def _e6(value):
    if value is None or isinstance(value, bool):
        return None
    return round(value * E6)


def _qty_text(quantity_e6, unit):
    if quantity_e6 is None:
        return None
    text = f"{quantity_e6 / E6:.6f}".rstrip("0").rstrip(".")
    return f"{text} {unit}" if unit else text


# ---------------------------------------------------------------- 원료칭량 조립 (R19~R22)


def assemble(source, used_inputs=None):
    """뷰 결과 → 기본정보·원료칭량(PLG-LNK-04). used_inputs = {bom_line_id: 직접 입력 사용량}."""
    used_inputs = used_inputs or {}
    batch = source["batch"]
    out_unit = batch["base_unit"]
    usages = source["usages"]
    by_line = {}
    for u in usages:
        by_line.setdefault(u["bom_line_id"], []).append(u)
    rows = []
    for line in source["materials"]:
        mine = by_line.get(line["bom_line_id"], [])
        quantity = _convert(line["bom_quantity_e6"], line["base_unit"], out_unit)  # R20
        base = line["bom_base_quantity_e6"]
        ratio = None if quantity is None or not base else quantity * E6 // base
        used, unconvertible = 0, 0
        for u in mine:
            value = _convert(u["net_quantity_e6"], u["base_unit"], line["base_unit"])  # R21
            if value is None:
                unconvertible += 1
            else:
                used += value
        dates = [u["input_date"] for u in mine if (u["net_quantity_e6"] or 0) > 0]
        alternatives = [u for u in mine if u["item_id"] != line["item_id"]]
        alt_names = sorted({u["item_name"] for u in alternatives if u["item_name"]})
        alt_origins = sorted({u["origin_country"] for u in alternatives if u["origin_country"]})
        origin = line["origin_country"]
        if alt_origins:
            origin = f"{origin or '—'} → {', '.join(alt_origins)}(대체)"  # D22
        stock = bool(line["is_stock_managed"])
        if stock:
            used_e6 = used if mine else None
        else:
            used_e6 = _e6(used_inputs.get(line["bom_line_id"]))  # D21 직접 입력
        rows.append(
            {
                "bom_line_id": line["bom_line_id"],
                "line_no": line["line_no"],
                "item_id": line["item_id"],
                "item_code": line["item_code"],
                "item_name": line["item_name"],
                "origin": origin,
                "unit": line["base_unit"],
                "is_stock_managed": stock,
                "ratio_e6": ratio,
                "standard_e6": line["standard_quantity_e6"],
                "used_e6": used_e6,
                "first_date": min(dates) if dates else None,
                "alternatives": alt_names,
                "unconvertible_count": unconvertible,
                "input_count": len(mine),
            }
        )
    food = batch["food_type"]
    return {
        "batch": {
            "batch_id": batch["production_batch_id"],
            "batch_number": batch["batch_number"],
            "status": batch["status"],
            "item_id": batch["item_id"],
            "item_code": batch["item_code"],
            "item_name": batch["item_name"],
            "food_type": food,
            "manufactured_date": batch["manufactured_date"],
            "lot_numbers": batch["output_lot_number"],
            "product": f"[{food}] {batch['item_name']}" if food else batch["item_name"],
            "report_no": batch["manufacturing_report_number"],
            "planned_e6": batch["planned_quantity_e6"],
            "output_e6": batch["output_quantity_e6"],
            "unit": out_unit,
            "planned": _qty_text(batch["planned_quantity_e6"], out_unit),
            "output": _qty_text(batch["output_quantity_e6"], out_unit),
        },
        "materials": rows,
        "unlinked_usage_count": sum(1 for u in usages if u["bom_line_id"] is None),  # R22
    }


def _freeze(assembled):
    """작성완료 고정 값(frozen_batch·frozen_materials, 양식 4.1 칸)."""
    batch = assembled["batch"]
    head = {k: batch[k] for k in FREEZE_FIELDS}
    rows = [
        {
            "bom_line_id": m["bom_line_id"],
            "line_no": m["line_no"],
            "item_code": m["item_code"],
            "item_name": m["item_name"],
            "origin": m["origin"],
            "ratio_e6": m["ratio_e6"],
            "standard_e6": m["standard_e6"],
            "used_e6": m["used_e6"],
            "unit": m["unit"],
            "first_date": m["first_date"],
            "alternatives": ", ".join(m["alternatives"]) or None,
        }
        for m in assembled["materials"]
    ]
    return head, rows


def _clean(values):
    return {k: v for k, v in values.items() if v is not None}


def _used_inputs(document_rows):
    out = {}
    for r in document_rows:
        values = r["values"] if "values" in r else r
        if values.get("bom_line_id") is not None and values.get("used") is not None:
            out[values["bom_line_id"]] = values["used"]
    return out


# ---------------------------------------------------------------- PLG-F01 연동 조회


def linked_data(document_id):
    """PLG-A01: 연동 값(작성완료면 고정 값) + 바뀜 + 같은 품목 최근 템플릿 + CCP 일지 번호."""
    with step("PLG-LNK-01", "PLG", "문서·배치"):
        document, batch_id = _prod_log(
            document_id, ("materials", "frozen_batch", "frozen_materials", "steps")
        )
        completed = document["status"] == "completed"
    frozen = None
    if completed:
        with step("PLG-LNK-02", "PLG", "고정 섹션"):
            head = next((r["values"] for r in _rows(document, "frozen_batch")), None)
            rows = sorted(
                (r["values"] for r in _rows(document, "frozen_materials")),
                key=lambda v: v.get("line_no") or 0,
            )
            frozen = {"batch": head, "materials": rows}
    with step("PLG-LNK-03", "PLG", "연동 데이터(REQ-F13)") as s:
        source = _source(batch_id)
        if source is None:
            s.fail("SOURCE_UNAVAILABLE")
            with step("PLG-LNK-03a", "PLG", "연동 실패 — 품목은 문서 참조에서"):
                refs = doc.document_sections(document_id, (), with_refs=True)["refs"]
    with step("PLG-LNK-04", "PLG", "원료칭량 조립(R19~R22)"):
        current = None
        if source is not None:
            current = assemble(source, _used_inputs(_rows(document, "materials")))
    changed = False
    if frozen is not None and current is not None:
        head, rows = _freeze(current)
        stored = {k: v for k, v in (frozen["batch"] or {}).items() if k != "frozen_at"}
        changed = _clean(head) != _clean(stored) or [_clean(r) for r in rows] != [
            _clean(r) for r in frozen["materials"]
        ]
    with step("PLG-LNK-05", "PLG", "같은 품목 최근 템플릿·CCP 일지"):
        if current is not None:
            item_id = current["batch"]["item_id"]
        else:
            item_id = next((r["item_id"] for r in refs if r["item_id"] is not None), None)
        last = last_template_for_item(item_id)
        states = _ccp_state(batch_id)
        ccp = {k: v["document_id"] for k, v in states.items()}
    # R25(D-253): CCP 공정 행마다 CCP 일지 상태·값 — 작성완료 뒤 바뀌면 ccp_changed
    ccp_check = {}
    for r in _rows(document, "steps"):
        v = r["values"] or {}
        kind = v.get("kind")
        if kind in CCP_KINDS:
            st = states.get(kind)
            ccp_check[kind] = {
                "status": st["status"] if st else None,
                "ready": bool(st and st["ready"]),
                "values": st["values"] if st else None,
                "problems": [c for _, c, _ in ccp_problems(kind, v, st)],
            }
    ccp_changed = completed and any(c["problems"] for c in ccp_check.values())
    return {
        "document_id": document_id,
        "batch_id": batch_id,
        "status": document["status"],
        "linked": current,
        "frozen": frozen,
        "changed": changed,
        "error": None if source is not None else "SOURCE_UNAVAILABLE",
        "last_template": last,
        "ccp_documents": ccp,
        "ccp_check": ccp_check,
        "ccp_changed": ccp_changed,
    }


def last_template_for_item(item_id):
    """PLG-F12: 같은 품목 가장 최근 생산일지에서 불러온 템플릿(사용 중인 것만). SQL 2."""
    found = doc.latest_section_value(PROD_LOG, item_id, "info", "template_id")
    if found is None:
        return None
    t = ProcessTemplate.objects.filter(pk=found["value"], is_active=True).first()
    if t is None:
        return None
    return {"process_template_id": t.pk, "name": t.name, "document_id": found["document_id"]}


# ------------------------------------------------ 필수 칸 (R07 — done·작성완료 같은 기준)


def step_missing(values):
    """공정 행에서 빠진 필수 칸 목록(S1a 3.3)."""
    v = values or {}
    need = ["name", "work_date", "worker"]
    if v.get("dur_on"):
        need += ["dur_value", "dur_unit"]
    kind, mode = v.get("kind"), v.get("mode")
    if kind in ("CCP-1P", "CCP-3P"):
        need.append("verdict")
    elif kind == "CCP-2B":
        need += ["temp", "time_min"]
    elif kind == "INNER":
        need.append("qty")
    elif kind == "OUTER":
        need += ["material", "expiry", "fg_qty"]
    elif kind == "GEN":
        need += {
            "JUDGE": ["verdict"],
            "TEMP_TIME": ["temp", "time_min"],
            "QTY": ["qty", "qty_unit"],
        }.get(mode, ["mode"])
    return [k for k in need if v.get(k) in (None, "")]


# ------------------------------------------------ PLG-F02 저장 검사 (N12 check_rows)


def _material_problems(materials, bom_lines):
    """R23 ③④ — 그 배치 BOM 줄인지, used는 재고 비관리 줄만."""
    lines = {m["bom_line_id"]: m for m in bom_lines}
    problems = []
    for path, values in materials:
        key = values.get("bom_line_id")
        if not isinstance(key, int) or isinstance(key, bool):
            continue  # ①에서 걸림
        line = lines.get(key)
        if line is None:
            problems.append(
                _detail(f"{path}.bom_line_id", "not_batch_line", "이 배치의 BOM 줄이 아닙니다.")
            )
        elif values.get("used") is not None and line["is_stock_managed"]:
            problems.append(
                _detail(
                    f"{path}.used",
                    "stock_managed",
                    "재고 관리 원료의 사용량은 수불 투입에서 옵니다(직접 입력 불가).",
                )
            )
    return problems


def check_rows(document, rows_after):
    """PLG-SAV-01~06. 반환 (문제 목록, {ref: {"done": bool}}).

    SQL(ISS-063): 배치 상태 1(바뀐 원료 행이 있으면 BOM 줄도 같은 SQL) + (바뀐 공정 행이 있으면)
    공정 1 + (바뀐 CCP 행이 있으면) CCP 일지 1 → 많아야 3. 손대지 않은 행은 공정·CCP 일지·BOM 줄을
    다시 읽지 않는다. 작성완료 때 CCP 일지(PLG-CMP-03c)·원료 ③④(PLG-CMP-03b)는 전체 행을 다시
    본다. 공정 연결(R05)·입력 방식(R06)은 행이 바뀔 때만 — 공정 기능은 바뀌지 않고 쓰인 공정은
    삭제할 수 없어 손대지 않은 행은 그대로 맞다(S4b-C12).
    """
    batch_id = batch_id_of(document.record_key)
    with_lines = any(r.get("touched", True) for r in rows_after if r["section_def"] == "materials")
    with step("PLG-SAV-01", "PLG", "배치 취소 확인(v_doc_batch — 연동과 따로, B1)"):
        state = _batch_state(batch_id, with_lines)
    steps = [
        (r["ref"], r["path"], r["values"] or {}, r.get("touched", True))
        for r in rows_after
        if r["section_def"] == "steps"
    ]
    materials = [
        (r["path"], r["values"] or {}, r.get("touched", True))
        for r in rows_after
        if r["section_def"] == "materials"
    ]
    problems = []
    with step("PLG-SAV-02", "PLG", "공정 행: 기능·입력 방식·기본 제공 1개·공정 목록(R03·R05·R06)"):
        seen = {}
        process_ids = {
            v.get("process_id")
            for _, _, v, touched in steps
            if touched and isinstance(v.get("process_id"), int)
        }
        processes = Process.objects.in_bulk(process_ids) if process_ids else {}
        for _, path, v, touched in steps:
            kind = v.get("kind")
            if kind not in KINDS:
                problems.append(_detail(f"{path}.kind", "required", "공정 기능이 필요합니다."))
                continue
            if kind in BUILTIN_KINDS:
                if kind in seen:
                    problems.append(
                        _detail(
                            f"{path}.kind", "duplicate_builtin", f"{kind}은(는) 한 번만 넣습니다."
                        )
                    )
                seen[kind] = path
            pid = v.get("process_id")
            if not touched:
                continue  # 손대지 않은 행: 기본 제공 1개 검사만
            if pid is not None:
                p = processes.get(pid) if isinstance(pid, int) else None
                if p is None or p.kind != kind:
                    problems.append(
                        _detail(
                            f"{path}.process_id", "process_mismatch", "공정 목록과 맞지 않습니다."
                        )
                    )
            elif kind != "GEN":
                problems.append(
                    _detail(
                        f"{path}.process_id",
                        "process_mismatch",
                        "기본 제공 공정은 공정 목록과 연결합니다.",
                    )
                )
            if kind == "GEN" and v.get("mode") is not None and v["mode"] not in MODES:
                problems.append(_detail(f"{path}.mode", "invalid", "입력 방식을 확인하세요."))
            if kind != "GEN" and v.get("mode") is not None:
                problems.append(
                    _detail(
                        f"{path}.mode", "not_allowed", "기본 제공은 입력 방식이 정해져 있습니다."
                    )
                )
    with step("PLG-SAV-03", "PLG", "바뀐 CCP 행 → 그 배치 CCP 일지(R04)") as s:
        wanted = {v.get("kind") for _, _, v, touched in steps if touched} & set(CCP_KINDS)
        if wanted:
            have = _ccp_docs(batch_id, sorted(wanted))
            for _, path, v, touched in steps:
                if touched and v.get("kind") in wanted and v["kind"] not in have:
                    problems.append(
                        _detail(
                            f"{path}.kind",
                            "ccp_doc_missing",
                            f"이 배치에 {v['kind']} 일지가 없습니다.",
                        )
                    )
        else:
            s.skip("CCP 행 없음")
    with step("PLG-SAV-04", "PLG", "원료 행 R23 ①② — 키·중복"):
        keys = {}
        for path, v, _ in materials:
            key = v.get("bom_line_id")
            if not isinstance(key, int) or isinstance(key, bool):
                problems.append(
                    _detail(f"{path}.bom_line_id", "required", "BOM 줄(bom_line_id)이 필요합니다.")
                )
            elif key in keys:
                problems.append(
                    _detail(
                        f"{path}.bom_line_id",
                        "duplicate",
                        f"같은 원료 줄이 이미 있습니다({keys[key]}).",
                    )
                )
            else:
                keys[key] = path
    with step("PLG-SAV-05", "PLG", "바뀐 원료 행 R23 ③④ — 배치 BOM 줄·재고 비관리") as s:
        changed = [(path, v) for path, v, touched in materials if touched]
        if not changed:
            s.skip("바뀐 원료 행 없음")
        else:
            lines = state.get("lines")
            if lines is None:
                s.skip("연동 실패 — 작성완료 때 다시(R08)")
            else:
                problems += _material_problems(changed, lines)
    with step("PLG-SAV-06", "PLG", "공정 행 done 계산"):
        computed = {ref: {"done": not step_missing(v)} for ref, _, v, _ in steps}
    return problems, computed


# ---------------------------------------------------------------- PLG-F03 작성완료 검사


def completion_problems(document, rows):
    """PLG-CMP-01~03b. rows = [(section_def, row_no, values)]. 409 예외는 그대로(롤백)."""
    batch_id = batch_id_of(document.record_key)
    with step("PLG-CMP-01", "PLG", "취소 배치(R10 — v_doc_batch, B1)"):
        state = _batch_state(batch_id, with_lines=True)
    with step("PLG-CMP-02", "PLG", "연동 읽기(R08 — BOM 줄, 01과 같은 SQL)"):
        lines = state["lines"]
        if lines is None:
            raise LinkedUnavailable()
    problems = []
    with step("PLG-CMP-03", "PLG", "필수(R07)"):
        info = next((v for k, _, v in rows if k == "info"), {}) or {}
        for key in (*PRECHECKS, "inspector"):
            if info.get(key) in (None, ""):
                problems.append(
                    _detail(f"sections[info].{key}", "required", "작업 전 점검을 채우세요.")
                )
        steps = sorted(((n, v or {}) for k, n, v in rows if k == "steps"), key=lambda x: x[0])
        if not steps:
            problems.append(_detail("sections[steps]", "min_rows", "공정을 1개 이상 넣으세요."))
        for n, v in steps:
            for key in step_missing(v):
                problems.append(_detail(f"sections[steps#{n}].{key}", "required", "필수 칸입니다."))
    with step("PLG-CMP-03b", "PLG", "원료 행 R23 ③④ 다시"):
        materials = [(f"sections[materials#{n}]", v or {}) for k, n, v in rows if k == "materials"]
        problems += _material_problems(materials, lines)
    with step("PLG-CMP-03c", "PLG", "CCP 행 ↔ CCP 일지: 있음·작성완료·같은 값(R04·R25)") as s:
        wanted = sorted({v.get("kind") for _, v in steps} & set(CCP_KINDS))
        if wanted:
            states = _ccp_state(batch_id, wanted)
            for n, v in steps:
                if v.get("kind") in wanted:
                    for key, code, message in ccp_problems(v["kind"], v, states.get(v["kind"])):
                        problems.append(_detail(f"sections[steps#{n}].{key}", code, message))
        else:
            s.skip("CCP 행 없음")
    return problems


# ---------------------------------------------------------------- PLG-F04 작성완료·작성 재개 처리


def on_transition(document_id, event, actor_id):
    """completed → 고정 섹션 쓰기(PLG-CMP-04), reopened → 취소 확인·지우기(PLG-ROP-01·02)."""
    document, batch_id = _prod_log(document_id, ("materials",))
    if event == "completed":
        with step("PLG-CMP-04", "PLG", "고정 섹션 쓰기(R09)"):
            source = _source(batch_id)
            if source is None:
                raise LinkedUnavailable()
            head, rows = _freeze(assemble(source, _used_inputs(_rows(document, "materials"))))
            head["frozen_at"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
            doc.write_system_sections(document_id, {"frozen_batch": head, "frozen_materials": rows})
    elif event == "reopened":
        with step("PLG-ROP-01", "PLG", "취소 배치 확인(v_doc_batch — 못 읽으면 막음, B1)"):
            _batch_state(batch_id)
        with step("PLG-ROP-02", "PLG", "고정 섹션 지움"):
            doc.write_system_sections(document_id, {}, clear=("frozen_batch", "frozen_materials"))


# ---------------------------------------------------------------- PLG-F05 템플릿 행 (A02)


def _require_write(actor_id, document_id):
    doc.require_write(actor_id, document_id)  # ROLE-R07(R18)


def _builtin_row_kinds(document):
    return {(r["values"] or {}).get("kind") for r in _rows(document, "steps")}


def template_rows(actor_id, document_id, template_id, mode):
    """PLG-TPL-01~06. 일지에는 쓰지 않고, 템플릿 사용 기록(used_count·last_used_at)만 올린다."""
    if mode not in ("replace", "append"):
        raise errors.ValidationFailed(details=[_detail("mode", "invalid", "replace 또는 append")])
    with step("PLG-TPL-01", "PLG", "권한·문서·배치"):
        _require_write(actor_id, document_id)
        document, batch_id = _prod_log(document_id, ("steps",))
        state = _batch_state(batch_id)  # B1: 연동과 따로, 못 읽으면 막음
        work_date = state.get("manufactured_date") or document["work_date"]
    with step("PLG-TPL-02", "PLG", "템플릿 단계(공정 기본값 + 덮어쓴 값)"):
        t = ProcessTemplate.objects.filter(pk=template_id, is_active=True).first()
        if t is None:
            raise errors.TemplateNotFound()
        steps = list(
            ProcessTemplateStep.objects.filter(template_id=t.pk)
            .select_related("process")
            .order_by("seq")
        )
    with step("PLG-TPL-03", "PLG", "CCP 일지 없는 CCP 빼기(R04)"):
        have = _ccp_docs(batch_id)
        skipped_ccp = [
            s.process.kind
            for s in steps
            if s.process.kind in CCP_KINDS and s.process.kind not in have
        ]
    with step("PLG-TPL-04", "PLG", "덧붙이기면 이미 있는 기본 제공 건너뜀") as s:
        existing = _builtin_row_kinds(document) if mode == "append" else set()
        skipped_dup = [
            st.process.kind
            for st in steps
            if st.process.kind in BUILTIN_KINDS and st.process.kind in existing
        ]
        if mode != "append":
            s.skip("바꾸기")
    with step("PLG-TPL-05", "PLG", "결과 행(복사 — R17)"):
        rows = []
        for st in steps:
            kind = st.process.kind
            if kind in skipped_ccp or kind in skipped_dup:
                continue
            r = services._resolve(st.process, st.overrides_json)
            values = {
                "kind": kind,
                "process_id": st.process_id,
                "name": r["name"],
                "work_date": work_date,
                "desc": r["desc"],
                "dur_on": r["duration"] is not None,
            }
            if kind == "GEN":
                values["mode"] = r["mode"]
            if r["duration"] is not None:
                values["dur_value"] = r["duration"]["value"]
                values["dur_unit"] = r["duration"]["unit"]
            if kind == "INNER":
                values.update({k: r[k] for k in ("spec", "qty_unit") if r[k] is not None})
            if kind == "OUTER" and r["material"] is not None:
                values["material"] = r["material"]
            rows.append({k: v for k, v in values.items() if v is not None})
        filled = (
            sum(
                1
                for r in _rows(document, "steps")
                if any(
                    (r["values"] or {}).get(k) not in (None, "")
                    for k in ("worker", "verdict", "temp", "qty", "fg_qty")
                )
            )
            if mode == "replace"
            else 0
        )
    with step("PLG-TPL-06", "PLG", "템플릿 사용 기록"):
        now = timezone.now()
        ProcessTemplate.objects.filter(pk=t.pk).update(
            used_count=F("used_count") + 1, last_used_at=now
        )
    return {
        "mode": mode,
        "rows": rows,
        "skipped_ccp": skipped_ccp,
        "skipped_dup": skipped_dup,
        "replace_filled_count": filled,
        "template": {
            "process_template_id": t.pk,
            "name": t.name,
            "at": timezone.localtime(now).strftime("%Y-%m-%dT%H:%M"),
        },
    }


# ---------------------------------------------------------------- PLG-F06 템플릿으로 저장 (A03)


def _overrides_from_row(process, values):
    """일지 행 → 공정 기본값과 다른 값만(R17 복사의 반대)."""
    out = {}
    if values.get("name") and values["name"] != process.name:
        out["name"] = values["name"]
    if (values.get("desc") or None) != (process.description or None):
        out["desc"] = values.get("desc") or ""
    if process.kind == "GEN" and values.get("mode") and values["mode"] != process.mode:
        out["mode"] = values["mode"]
    default = (
        None
        if process.std_duration_value is None
        else {"value": process.std_duration_value, "unit": process.std_duration_unit}
    )
    current = (
        {"value": values.get("dur_value"), "unit": values.get("dur_unit")}
        if values.get("dur_on") and values.get("dur_value") is not None and values.get("dur_unit")
        else None
    )
    if current != default:
        out["duration"] = current
    if process.kind == "INNER":
        out.update({k: values[k] for k in ("spec", "qty_unit") if values.get(k)})
    if process.kind == "OUTER" and values.get("material"):
        out["material"] = values["material"]
    if out.get("desc") == "":
        out.pop("desc")  # 빈 설명 덮어쓰기는 두지 않음
    return out


def save_template_from_rows(actor_id, document_id, data):
    """PLG-TSV-01~05: {name, steps, overwrite, expected_version, confirm_similar}.

    일지 한정 행(process_id 없음)은 뺀다. 덮어쓰기는 NAME_TAKEN에서 받은 version을
    expected_version으로 보낸다(A8 — 그 사이 바뀌었으면 409 VERSION_CONFLICT).
    """
    with step("PLG-TSV-01", "PLG", "권한·입력"):
        _require_write(actor_id, document_id)
        _prod_log(document_id)
        unknown = sorted(
            set(data) - {"name", "steps", "overwrite", "expected_version", "confirm_similar"}
        )
        if unknown:
            raise errors.ValidationFailed(
                details=[_detail(k, "unknown_key", "허용되지 않은 키입니다.") for k in unknown]
            )
        name = services.clean_name(data.get("name"))
        rows = data.get("steps")
        if not isinstance(rows, list):
            raise errors.ValidationFailed(details=[_detail("steps", "required", "공정 행 목록")])
        overwrite = data.get("overwrite") is True
        expected = data.get("expected_version")
    with step("PLG-TSV-02", "PLG", "이름(R13)"):
        same = next(
            (
                t
                for t in ProcessTemplate.objects.filter(is_active=True)
                if t.name_key == services.name_key(name)
            ),
            None,
        )
        if (
            same is not None
            and overwrite
            and (not isinstance(expected, int) or isinstance(expected, bool))
        ):
            raise errors.ValidationFailed(
                details=[
                    _detail("expected_version", "required", "덮어쓰기는 템플릿 버전이 필요합니다.")
                ]
            )
        if same is not None and not overwrite:
            raise errors.NameTaken(
                details=[
                    {
                        "path": "name",
                        "code": "taken",
                        "id": same.pk,
                        "name": same.name,
                        "version": same.version,
                    }
                ]
            )
    with step("PLG-TSV-03", "PLG", "행 → 단계(일지 한정 빼기, R16)"):
        linked = [r for r in rows if isinstance(r, dict) and isinstance(r.get("process_id"), int)]
        processes = Process.objects.in_bulk({r["process_id"] for r in linked})
        steps = [
            {
                "process_id": r["process_id"],
                "overrides": _overrides_from_row(processes[r["process_id"]], r)
                if r["process_id"] in processes
                else {},
            }
            for r in linked
        ]
        skipped = len(rows) - len(linked)
    with step("PLG-TSV-04", "PLG", "만들기/덮어쓰기·이력"):
        if same is None:
            out = services.create_template(
                actor_id,
                {
                    "name": name,
                    "steps": steps,
                    "confirm_similar": data.get("confirm_similar") is True,
                },
                action="create",
                document_id=document_id,
            )
        else:
            before = services._template_state(same)
            cleaned = services._clean_steps(steps, {s["process_id"] for s in before["steps"]})
            services._save_template(same, actor_id, expected)  # A8: 다르면 409
            services._write_steps(same.pk, cleaned)
            services._log(
                actor_id,
                "template",
                same.pk,
                "overwrite",
                before,
                services._template_state(same),
                document_id,
            )
            out = services.get_template(same.pk)
    with step("PLG-TSV-05", "PLG", "결과"):
        return {"template": out, "overwritten": same is not None, "skipped_rows": skipped}


# ---------------------------------------------------------------- PLG-F07 CCP 값 (A04)


def ccp_values(document_id, kind):
    """PLG-CCP-01·02·04: 1P·3P 판정(모두 적합 → 적합, 하나라도 부적합 → 부적합),
    2B 종료전 온도·총 시간 + CCP 일지 상태(S6 r3 — 작성완료 전이면 생산일지 작성완료가 막힘)."""
    if kind not in CCP_KINDS:
        raise errors.ValidationFailed(details=[_detail("kind", "invalid", "CCP-1P·CCP-2B·CCP-3P")])
    with step("PLG-CCP-01", "PLG", "문서·배치"):
        _, batch_id = _prod_log(document_id)
    with step("PLG-CCP-02", "PLG", "그 CCP 일지·상태·측정 섹션(배치 참조 N20)"):
        state = _ccp_state(batch_id, (kind,)).get(kind)
        if state is None:
            raise CcpDocMissing()
    with step("PLG-CCP-04", "PLG", "규칙(F07)"):
        return {
            "kind": kind,
            "source_document_id": state["document_id"],
            "source_version": state["version"],
            "source_status": state["status"],
            "source_ready": state["ready"],
            **state["values"],
        }


# ---------------------------------------------------------------- PLG-F10 일지에서 공정 등록 (A05)


def register_from_document(actor_id, document_id, data):
    """PLG-REG-01~04: 같은 이름 사용 중 공정이 있으면 그 공정(연결),
    없으면 만들기(이력 register)."""
    with step("PLG-REG-01", "PLG", "권한·입력"):
        _require_write(actor_id, document_id)
        _prod_log(document_id)
        unknown = sorted(set(data) - {"name", "mode", "confirm_similar"})
        if unknown:
            raise errors.ValidationFailed(
                details=[_detail(k, "unknown_key", "허용되지 않은 키입니다.") for k in unknown]
            )
        name = services.clean_name(data.get("name"))
    with step("PLG-REG-02", "PLG", "같은 이름 공정") as s:
        key = services.name_key(name)
        same = next((p for p in Process.objects.filter(is_active=True) if p.name_key == key), None)
        if same is not None:
            s.note(f"연결 {same.pk}")
            return {"process": services.get_process(same.pk), "linked_existing": True}
    with step("PLG-REG-03", "PLG", "비슷한 이름·만들기(이력 register)"):
        out = services.create_process(
            actor_id,
            {
                "name": name,
                "mode": data.get("mode"),
                "confirm_similar": data.get("confirm_similar") is True,
            },
            action="register",
            document_id=document_id,
        )
    with step("PLG-REG-04", "PLG", "결과"):
        return {"process": out, "linked_existing": False}


# ---------------------------------------------------------------- 등록 (앱 시작 때)


def register():
    doc.register_form_extension(
        PROD_LOG,
        check_rows=check_rows,
        completion_problems=completion_problems,
        on_transition=on_transition,
    )


def atomic(fn, *args):
    with transaction.atomic():
        return fn(*args)
