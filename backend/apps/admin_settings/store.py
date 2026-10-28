"""ADM 저장소 — 다른 단위(REQ)가 부르는 읽기·기록 함수(p16-s2-spec 3.1).

다른 단위를 import하지 않는다.
- ADM-F01 `ccp_for_batch`: 배치 CCP 적용 기록(A28). 기록이 있으면 그대로
  (R06 — 설정을 다시 읽지 않음), 없으면 품목 설정(own) → 공정 구분 기본(A26)으로 정해
  **기록하고** 돌려준다(R05). 호출자 트랜잭션 안.
- ADM-F03 `batch_ccp`: 여러 배치의 적용 기록(R08). 기록 없음 = None(생산 시작 전).
"""

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from .models import PROCESSES, BatchCcpApplied

CCP_TYPES = tuple(f"CCP-{p}" for p in PROCESSES)  # ADM-R09: 고정 3종, 1P→2B→3P

_DECIDE_SQL = (
    "SELECT d.ccp_1p, d.ccp_2b, d.ccp_3p, i.mode, i.ccp_1p, i.ccp_2b, i.ccp_3p"
    " FROM ccp_default d LEFT JOIN item_ccp i ON i.item_id = %s"
    " WHERE d.process_type = %s"
)


def _on(flags):
    return [p for p, on in zip(PROCESSES, flags, strict=True) if on]


def _decide(item_id, process_type):
    """R05: 품목 own이면 그 집합, 아니면 공정 구분 기본(기본 행이 없으면 없음). SQL 1."""
    with connection.cursor() as cursor:
        cursor.execute(_DECIDE_SQL, [item_id, process_type])
        row = cursor.fetchone()
    if row is None:
        return []
    if row[3] == "own":
        return _on(row[4:7])
    return _on(row[0:3])


def ccp_for_batch(batch_id, item_id, process_type):
    """F01: 기록 있으면 그것(SQL 1), 없으면 결정 + 기록(SQL 2). 반환 = 1P→2B→3P 목록."""
    row = BatchCcpApplied.objects.filter(batch_id=batch_id).first()
    if row is not None:
        return row.processes
    processes = _decide(item_id, process_type)
    try:
        with transaction.atomic():  # 저장점 — 동시 처음 시작이면 먼저 기록한 쪽을 따름
            BatchCcpApplied.objects.create(
                batch_id=batch_id, decided_at=timezone.now(), **BatchCcpApplied.flags(processes)
            )
    except IntegrityError:
        return BatchCcpApplied.objects.get(batch_id=batch_id).processes
    return processes


def batch_ccp(batch_ids):
    """F03: {batch_id: [..] | [] | None}. 빈 목록이면 SQL 없음, 아니면 1."""
    ids = sorted({int(i) for i in batch_ids})
    if not ids:
        return {}
    found = {r.batch_id: r.processes for r in BatchCcpApplied.objects.filter(batch_id__in=ids)}
    return {i: found.get(i) for i in ids}
