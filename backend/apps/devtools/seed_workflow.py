"""P3(+P4: 상신 전 작성완료) 개발·사용 테스트용 가상 데이터 (document-workflow/s1-screens.md 7장).

결재 데이터는 WF 서비스 함수로 만든다(문서 상태와 회차 상태의 짝이 항상 맞도록).
WF-PS-05용 "어긋난 데이터" 1건만 SQL로 직접 넣는다.
"""

from datetime import timedelta

from django.db import connection
from django.utils import timezone

from apps.document_workflow import services as wf
from apps.documents import services as doc
from apps.documents.seed import ensure_staff, ensure_templates, seed_documents

SLOTS = [
    {"slot_no": 1, "label": "담당", "approver_id": 3},
    {"slot_no": 2, "label": "검토", "approver_id": 2},
    {"slot_no": 3, "label": "승인", "approver_id": 1},
]
PAGING_SLOTS = [
    {"slot_no": 1, "label": "담당", "approver_id": 4},
    {"slot_no": 2, "label": "검토", "approver_id": 5},
    {"slot_no": 3, "label": "승인", "approver_id": 1},
]


def _payload(template_id, subject, work_date, author):
    return {
        "template_id": template_id,
        "subject": subject,
        "work_date": work_date.isoformat(),
        "assignee_id": 3,
        "sections": [
            {"section_def": "info", "values": {"product": "유자차", "lot": "LOT-WF"}},
            {
                "section_def": "rounds",
                "values": {"round": "09:00", "temp": 87.0, "hold_sec": 16, "measured_by": author},
            },
            {
                "section_def": "rounds",
                "values": {"round": "10:00", "temp": 84.5, "hold_sec": 16, "measured_by": author},
            },
        ],
    }


def seed_workflow(today=None):
    today = today or timezone.localdate()
    ensure_staff()
    ccp = ensure_templates()[("CCP_MONITORING", 1)].template_id
    drafts = seed_documents(today=today, locked_states=False)
    made = {"drafts": len(drafts)}

    def new(subject, days_ago, author=3):
        data = _payload(ccp, subject, today - timedelta(days=days_ago), author)
        return doc.create_document(author, data)["document_id"]

    def submit(document_id, slots=SLOTS, actor=3):
        # P4: 상신은 작성완료(completed) 문서만 — 시드도 작성완료를 거친다(p4-s2-spec 7.1)
        version = doc.get_document(document_id)["version"]
        if doc.get_document(document_id)["status"] != "completed":
            version = doc.complete_document(actor, document_id, version)["version"]
        out = wf.submit(actor, document_id, version, [dict(s) for s in slots])
        return {s["slot_no"]: s["approval_id"] for s in out["request"]["slots"]}

    # 결재 진행 2건 (하나는 1번 칸 승인)
    submit(new("WF 결재 진행(대기 3칸)", 1))
    ids = submit(new("WF 결재 진행(1칸 승인)", 2))
    wf.decide(3, ids[1], "approved")
    # 결재 완료 1건
    ids = submit(new("WF 결재 완료", 3))
    for no, who in ((1, 3), (2, 2), (3, 1)):
        wf.decide(who, ids[no], "approved", "확인" if no == 2 else None)
    # 반려 1건 (승인 1, 반려 1, 미처리 종료 1)
    ids = submit(new("WF 반려", 4))
    wf.decide(3, ids[1], "approved")
    wf.decide(2, ids[2], "rejected", "2회차 측정 온도 84.5℃ — 한계기준 미달, 재측정 기록 필요")
    # 재상신 1건 (1회차 반려 → 수정 → 2회차 결재 진행)
    document_id = new("WF 재상신", 5)
    ids = submit(document_id)
    wf.decide(1, ids[3], "rejected", "LOT 번호 확인 필요")
    version = doc.get_document(document_id)["version"]
    doc.update_document(
        3, document_id, {"expected_version": version, "document": {"subject": "WF 재상신(수정함)"}}
    )
    submit(document_id)
    made["scenarios"] = 5
    # 결재함 페이지 확인용: staff 1 대기 21건
    for n in range(21):
        submit(
            new(f"WF 결재함 페이지 {n + 1:02d}", n % 9, author=(n % 5) + 1), PAGING_SLOTS, actor=4
        )
    made["paging"] = 21
    # WF-PS-05용 어긋난 데이터: draft 문서에 진행 중 회차(칸 없음). 결재 영역에 경고가 보여야 정상.
    broken = new("어긋난 데이터(PS-05) — 개발 콘솔 전용", 0)
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO approval_request (document_id, attempt, status, document_version,"
            " template_id, subject, work_date, snapshot_json, requested_by, requested_at)"
            " VALUES (%s, 1, 'in_progress', 1, %s, %s, %s, '{}', 3, %s)",
            [broken, ccp, "어긋난 데이터(PS-05)", today.isoformat(), timezone.now().isoformat()],
        )
    made["mismatch"] = 1
    return made
