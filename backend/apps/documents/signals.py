"""DOC 생명주기 신호 (p6-s2-spec 4.7, D-079).

상태 UPDATE가 성공한 뒤 같은 트랜잭션에서 `send()`로 보낸다(받는 쪽 예외는 그대로 올라가 그 변경까지
롤백). 받는 쪽이 없으면 아무 일도 없다. DOC는 받는 쪽(EFF 등)을 모른다.

보내는 값: document_id, event, actor_id(승인·반려는 WF가 넘기지 않아 None), note(작성완료만),
at(상태 변경 시각), type_code(양식 유형 — 받는 쪽이 양식을 고르는 데 쓴다, P6 S4b G1).
"""

from django.dispatch import Signal

document_transitioned = Signal()

EVENTS = (
    "completed",
    "reopened",
    "approved",
    "rejected",
    "correction_started",
    "correction_cancelled",
)
