// =============================================
// 개발 검증 › 결재 (P3 WF 사용 화면)
// 화면: WF-SC-01 문서 상세 결재 영역 · 02 상신 모달 · 03 결재함 · 04 결재 요청 상세
//       05 승인 모달 · 06 반려 모달 · 07 상신 충돌 모달
// 설계: dev-notes/document-workflow/s1-screens.md, API: s2-spec.md 2장
// P6: 유효 승인본·대체됨·정정 상신 꼬리표·⤷ 정정 줄(p6-s1-screens WF-SC-01·03·04, API p6-s2-spec A4~A6)
// 결재는 병렬이다. 칸 번호는 표시 순서일 뿐이므로 "차례" 같은 순서 표현을 쓰지 않는다.
// =============================================
(function () {
  const T = window.TempEntry;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);
  const MAX_SLOTS = 10;

  const REQUEST = {
    in_progress: { label: '결재 진행', badge: 'badge-info' },
    approved: { label: '결재 완료', badge: 'badge-success' },
    rejected: { label: '반려', badge: 'badge-danger' },
    cancelled: { label: '취소됨', badge: 'badge-neutral' },  // P10 상신 취소(ERD v7 M12)
  };
  const SLOT = {
    pending: { label: '대기', badge: 'badge-neutral' },
    approved: { label: '승인', badge: 'badge-success' },
    rejected: { label: '반려', badge: 'badge-danger' },
    skipped: { label: '미처리 종료', badge: 'badge-neutral te-skipped' },
  };
  const badge = (map, key) => {
    const m = map[key] || { label: key, badge: 'badge-neutral' };
    return `<span class="badge ${m.badge}">${m.label}</span>`;
  };

  // 방어선 오류(WF-S2-Q4): 문서 상태와 회차가 어긋난 데이터
  const MISMATCH_TEXT = '문서 상태가 결재와 맞지 않아 처리하지 못했습니다. 아무것도 바뀌지 않았습니다. 관리자에게 확인을 요청하세요.';

  function mySlot(req) {
    if (!req || req.status !== 'in_progress' || !api.staffId) return null;
    return req.slots.find((s) => String(s.approver_id) === api.staffId && s.state === 'pending') || null;
  }
  const approvedCount = (req) => req.slots.filter((s) => s.state === 'approved').length;
  const pendingCount = (req) => req.slots.filter((s) => s.state === 'pending').length;
  // P6 회차 꼬리표(계산 값 — 저장하지 않음, P6-S2-Q2)
  const effectiveChip = (req) => (req.effective ? ' <span class="badge te-chip-effective">유효 승인본</span>' : '');
  const supersededChip = (req) => (req.superseded_by ? ` <span class="badge te-chip-superseded">대체됨(${req.superseded_by}회차)</span>` : '');
  // ISS-027 ②(P10): 정정 회차 꼬리표 "정정 상신" → "정정", 버튼·창 제목·결과 문구는 "재상신"
  const correctionChip = (isCorrection) => (isCorrection ? ' <span class="badge te-chip-fix">정정</span>' : '');
  const reqChips = (req) => `${correctionChip(req.is_correction)}${effectiveChip(req)}${supersededChip(req)}`;
  // 정정 시작 기록 → 그 시점 직전 승인 회차 아래 ⤷ 줄(여러 번 정정하면 여러 줄)
  function correctionLines(items, corrections) {
    const out = {};
    (corrections || []).forEach((c) => {
      const base = items.filter((x) => x.status === 'approved' && x.closed_at && x.closed_at <= c.started_at)
        .sort((a, b) => b.attempt - a.attempt)[0];
      if (!base) return;
      const end = c.outcome === 'cancelled' ? ` · 취소됨(${T.fmtDateTime(c.closed_at)})` : (c.outcome === 'approved' ? ` · 승인으로 닫힘(${T.fmtDateTime(c.closed_at)})` : ' · 진행 중');
      (out[base.request_id] = out[base.request_id] || []).push(
        `<li class="te-fix-line" data-fix-line="${c.correction_id}">⤷ 정정 시작 ${T.fmtDateTime(c.started_at)} staff ${esc(c.started_by)} "${esc(c.reason)}"${end}</li>`);
    });
    return out;
  }
  const slotName = (s) => `${s.slot_no}번 칸${s.label ? ` · ${esc(s.label)}` : ''}`;

  function slotTable(req) {
    return `
      <div class="te-table-wrap"><table class="data-table te-slot-table">
        <thead><tr><th>칸</th><th>역할</th><th>결재자</th><th>상태</th><th>처리 일시</th><th>의견</th></tr></thead>
        <tbody>${req.slots.map((s) => `
          <tr class="${String(s.approver_id) === api.staffId ? 'te-slot-mine' : ''}" data-slot="${s.slot_no}">
            <td>${s.slot_no}</td><td>${esc(s.label || '-')}</td><td>staff ${s.approver_id}</td>
            <td>${badge(SLOT, s.state)}${req.status === 'cancelled' && s.state !== 'rejected' ? ' <span class="badge te-badge-void" title="상신 취소로 무효">무효</span>' : ''}</td><td>${T.fmtDateTime(s.decided_at)}</td>
            <td>${s.comment ? esc(s.comment) : '<span class="te-hint">-</span>'}</td>
          </tr>`).join('')}</tbody>
      </table></div>`;
  }

  function myLine(req) {
    const slot = mySlot(req);
    if (!slot) return '';
    return `
      <div class="te-my-slot" data-approval="${slot.approval_id}">
        <span>▸ <b>내 결재 대기</b> (${slotName(slot)})</span>
        <span class="te-my-actions">
          <button class="btn btn-danger btn-sm" data-decide="rejected">반려</button>
          <button class="btn btn-primary btn-sm" data-decide="approved">승인</button>
        </span>
      </div>`;
  }

  function bindMyLine(root, req, after) {
    root.querySelectorAll('[data-decide]').forEach((btn) => btn.addEventListener('click', () => {
      Approval.openDecision(mySlot(req), req, btn.dataset.decide, after);
    }));
  }

  // ---------- 폼 모달(입력 오류 때 닫지 않는 모달). 기존 te-modal 스타일 재사용 ----------
  function formModal({ title, wide }) {
    const wrap = document.createElement('div');
    wrap.className = 'te-modal-wrap';
    wrap.innerHTML = `
      <div class="te-modal ${wide ? 'te-modal-wide' : ''}" role="dialog" aria-modal="true">
        <div class="modal-header"><div class="modal-title">${esc(title)}</div></div>
        <div class="te-modal-body"></div>
        <div class="te-modal-footer"></div>
      </div>`;
    document.body.appendChild(wrap);
    return {
      wrap,
      body: wrap.querySelector('.te-modal-body'),
      footer: wrap.querySelector('.te-modal-footer'),
      close: () => wrap.remove(),
    };
  }

  async function notice(title, message) {
    await T.modal({ title, body: `<p>${esc(message)}</p>`, buttons: [{ label: '확인', value: true, cls: 'btn-primary' }] });
  }

  // ---------- 결재선 편집 표(WF-SC-02). 한 건 상신과 일괄 상신(WF-SC-12, P7)이 같이 쓴다 ----------
  function slotEditorHtml(rows, errors) {
    const chosen = rows.map((r) => r.approver_id);
    const staffOptions = (selected, others) => ['<option value="">선택</option>']
      .concat((T.staff || []).map((id) => {
        const v = String(id);
        const taken = others.includes(v);
        return `<option value="${v}" ${v === selected ? 'selected' : ''} ${taken ? 'disabled' : ''}>staff ${v}${taken ? ' (다른 칸)' : ''}</option>`;
      })).join('');
    return `
      <table class="data-table te-slot-edit">
        <thead><tr><th>칸</th><th>역할(선택)</th><th>결재자*</th><th></th></tr></thead>
        <tbody>${rows.map((r, i) => `
          <tr data-i="${i}">
            <td>${i + 1}</td>
            <td><input class="form-control ${errors[`${i}.label`] ? 'te-field-error' : ''}" data-f="label" maxlength="20" value="${esc(r.label)}" placeholder="예: 담당">
              ${errors[`${i}.label`] ? `<div class="te-error-text">${esc(errors[`${i}.label`])}</div>` : ''}</td>
            <td><select class="form-control ${errors[`${i}.approver_id`] || !r.approver_id ? 'te-field-error' : ''}" data-f="approver_id">${staffOptions(r.approver_id, chosen.filter((_, j) => j !== i))}</select>
              ${errors[`${i}.approver_id`] ? `<div class="te-error-text">${esc(errors[`${i}.approver_id`])}</div>` : (!r.approver_id ? '<div class="te-error-text">결재자를 선택하세요</div>' : '')}</td>
            <td class="te-nowrap">
              <button class="btn btn-secondary btn-sm" data-act="up" ${i === 0 ? 'disabled' : ''} title="위로">↑</button>
              <button class="btn btn-secondary btn-sm" data-act="down" ${i === rows.length - 1 ? 'disabled' : ''} title="아래로">↓</button>
              <button class="btn btn-secondary btn-sm" data-act="del" title="삭제">✕</button>
            </td>
          </tr>`).join('')}</tbody>
      </table>
      <div style="margin-top:.5rem"><button class="btn btn-secondary btn-sm" id="apAdd" ${rows.length >= MAX_SLOTS ? 'disabled' : ''}>+ 칸 추가</button> <span class="te-hint">(최대 ${MAX_SLOTS}칸)</span></div>`;
  }
  // state.errors를 고치고 다시 그린다
  function bindSlotEditor(box, rows, state, render) {
    box.querySelectorAll('tr[data-i]').forEach((tr) => {
      const i = Number(tr.dataset.i);
      tr.querySelector('[data-f="label"]').addEventListener('input', (e) => { rows[i].label = e.target.value; });
      tr.querySelector('[data-f="approver_id"]').addEventListener('change', (e) => { rows[i].approver_id = e.target.value; delete state.errors[`${i}.approver_id`]; render(); });
      tr.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', () => {
        const act = b.dataset.act;
        if (act === 'del') rows.splice(i, 1);
        if (act === 'up') [rows[i - 1], rows[i]] = [rows[i], rows[i - 1]];
        if (act === 'down') [rows[i + 1], rows[i]] = [rows[i], rows[i + 1]];
        state.errors = {};
        render();
      }));
    });
    box.querySelector('#apAdd').addEventListener('click', () => { rows.push({ label: '', approver_id: '' }); render(); });
  }
  const slotsReady = (rows) => rows.length > 0 && rows.every((r) => r.approver_id);
  function slotsPayload(rows) {
    return rows.map((r, i) => {
      const slot = { slot_no: i + 1, approver_id: Number(r.approver_id) };
      if (r.label.trim()) slot.label = r.label.trim();
      return slot;
    });
  }
  // 400 INVALID_SLOTS → 칸별 오류(state.errors) + 머리 문구
  function slotErrors(data, state) {
    state.errors = {};
    const top = [];
    (data.details || []).forEach((e) => {
      const hit = /^slots\[(\d+)\]\.(\w+)$/.exec(e.path || '');
      if (hit) state.errors[`${hit[1]}.${hit[2]}`] = e.message;
      else top.push(esc(e.message));
    });
    return `[INVALID_SLOTS] ${esc(data.message)}${top.length ? `<ul>${top.map((t) => `<li>${t}</li>`).join('')}</ul>` : ''}`;
  }

  // ================================================= P7 일괄 처리 (p7-s1-screens WF-SC-11·12·13, DOC-SC-11 결과)
  // 모달 줄(row) 모양 — 묶음 상세(DOC-SC-10)와 결재함(WF-SC-03)이 만들어 넘긴다:
  //   { document_id, lot, status, correcting, version, verdict, nonconforming, inspector_id,
  //     attempt, my_slot: {approval_id, slot_no, label} | null, progress: {approved, total, pending} | null }
  // 대상·제외는 화면 계산(S1 4장). 서버가 문서마다 다시 검사하고, 그 사이 바뀐 문서는 결과에 실패로 나온다.
  const VERDICT = { PASS: '적합', FAIL: '부적합' };
  const ACTION = { approve: '승인', submit: '상신', inspector: '점검자 지정', skip: '작성 안 함' };  // skip: P8 DOC-SC-13
  const verdictHtml = (v) => (v ? `<span class="${v === 'FAIL' ? 'te-judge-ng' : ''}">${esc(VERDICT[v] || v)}</span>` : '<span class="te-hint">–</span>');
  const staffText = (id) => (id ? `staff ${esc(id)}` : '-');
  const rowName = (r) => `#${r.document_id}${r.lot ? ` ${esc(r.lot)}` : ''}`;

  let batchConfigCache = null;
  async function batchConfig() {
    if (!batchConfigCache) {
      const r = await api.get('workflow/batch-config');
      if (r.ok) batchConfigCache = r.data;
      else return { batch_types: [], template_ids: [], max_items: 50, inspector_types: ['D03'] };
    }
    return batchConfigCache;
  }

  // 결과 실패 문구(WF-SC-13): 코드는 그대로, 화면이 code + details[0].code(상태)로 고른다(p7-s2-spec 5.3).
  // 그 밖의 코드는 한 건 처리 때와 같은 문구(P3 WF-SC-02·05).
  // ISS-022(P7 S6 D9): REQUEST_CLOSED는 "회차가 끝남"(반려 또는 결재 완료) — 반려로 단정하지 않는다(한 건·일괄 같은 문구)
  const CLOSED_TEXT = '이 회차는 이미 끝났습니다(반려 또는 결재 완료). 결재 영역에서 현재 상태를 확인하세요.';
  function failureText(action, error) {
    const code = error.code;
    // P7-S5-Q2 b: 일괄 승인에서는 다른 화면·다른 사람이 먼저 처리해 회차가 승인으로 끝난 경우에도 REQUEST_CLOSED가 온다
    if (code === 'REQUEST_CLOSED' && action === 'approve') return '이 회차는 이미 끝났습니다(반려 또는 결재 완료). 문서를 열어 확인하세요.'; // 일괄 결과(P7-S5-Q2 b) — [문서 열기]가 함께 보임
    const sub = error.details && error.details[0] && error.details[0].code;
    if (code === 'DOCUMENT_LOCKED' && action === 'submit') {
      return ['draft', 'rejected', 'correcting'].includes(sub) ? '작성완료 상태가 아닙니다. 작성완료 후 상신하세요.' : '이미 결재 진행 중이거나 승인된 문서입니다.';
    }
    if (action === 'skip') {  // P8 작성 안 함(F27): 실패 판정 순서 404 → 양식·작성 요구 → 상태 → 버전
      if (code === 'DOCUMENT_NOT_SKIPPABLE') return '주기 작성 요구 문서만 작성 안 함으로 바꿀 수 있습니다.';
      if (code === 'INVALID_TRANSITION') return '작성중 문서만 작성 안 함으로 바꿀 수 있습니다.';
    }
    if (code === 'DOCUMENT_LOCKED' && action === 'inspector') {
      return sub === 'completed' ? '작성완료된 문서입니다. 바꾸려면 작성 재개하세요.' : '결재 중이거나 승인된 문서는 바꿀 수 없습니다.';
    }
    const common = {
      VERSION_CONFLICT: '화면을 연 뒤 다른 사람이 문서를 바꿨습니다. 묶음 화면을 다시 여세요.',
      SECTION_ROW_NOT_FOUND: '문서의 기본정보 영역이 없습니다. 관리자에게 알려 주세요.',
      OPEN_REQUEST_EXISTS: '이미 결재 진행 중인 회차가 있습니다. 결재 영역을 확인하세요.',
      NOT_YOUR_SLOT: '이 칸의 결재자가 아닙니다 (현재 사용자를 확인하세요).',
      ALREADY_DECIDED: '이미 처리된 칸입니다.',
      REQUEST_CLOSED: CLOSED_TEXT,
      APPROVAL_NOT_FOUND: '결재 칸을 찾을 수 없습니다.',
      INVALID_TRANSITION: MISMATCH_TEXT,
      DOCUMENT_NOT_FOUND: action === 'approve' ? MISMATCH_TEXT : '문서를 찾을 수 없습니다 (삭제되었을 수 있습니다).',
    };
    return common[code] || error.message || '처리하지 못했습니다.';
  }
  function successText(action, result, row, extra) {
    if (action === 'approve') return result.request_status === 'approved' ? '승인 → 문서 승인됨' : `승인 (남은 대기 ${result.pending_count}칸)`;
    if (action === 'submit') return `${result.request.attempt}회차 ${result.request.attempt > 1 ? '재상신' : '상신'}${row && row.correcting ? ' (정정)' : ''}`;
    if (action === 'skip') return `작성 안 함 (v${result.version})`;
    return result.changed ? `점검자 ${staffText(extra.inspectorId)}로 지정 (v${result.version})` : `변화 없음 (이미 ${staffText(extra.inspectorId)})`;
  }

  // 모달 안 입력 오류(400·500 — 아무것도 처리 안 함). 결과 화면으로 가지 않는다(WF-SC-13 "전체 실패" 아래 줄)
  function requestErrorHtml(res) {
    const d = res.data || {};
    const details = (d.details || []).map((e) => `<li>${esc(e.path ? `${e.path}: ` : '')}${esc(e.message)}${e.code ? ` <span class="te-hint">(${esc(e.code)})</span>` : ''}</li>`).join('');
    const none = res.status >= 500 || res.status === 0 ? ' 아무것도 반영되지 않았습니다.' : ' 아무것도 처리하지 않았습니다.';
    return `<div class="te-error-box" id="bxError"><strong>${esc(T.errorText(res))}</strong>${none}${details ? `<ul>${details}</ul>` : ''}</div>`;
  }

  // WF-SC-13: 같은 모달이 결과로 바뀐다. 닫기 → 연 화면을 다시 읽음(onDone). 실패 줄 [문서 열기] → openDoc
  function showBatchResult(m, action, data, rows, { onDone, openDoc, extra = {} }) {
    const byId = Object.fromEntries(rows.map((r) => [r.document_id, r]));
    const none = data.succeeded === 0;
    m.title(`처리 결과 · ${ACTION[action]} ${data.total}건 중 ${data.succeeded}건 성공`, none ? 'te-result-fail' : (data.failed ? 'te-result-partial' : 'te-result-ok'));
    m.body.innerHTML = `
      <ul class="te-result-list" id="bxResult">${data.results.map((x) => {
        const row = byId[x.document_id] || { document_id: x.document_id ?? '?' };
        if (x.ok) return `<li class="te-result-ok-line" data-result="${x.document_id}">✅ <b>${rowName(row)}</b> <span>${esc(successText(action, x.result, row, extra))}</span></li>`;
        return `<li class="te-result-fail-line" data-result="${x.document_id ?? ''}">⚠ <b>${x.document_id ? rowName(row) : `칸 #${esc(x.approval_id)}`}</b>
          <span>[${esc(x.error.code)}] ${esc(failureText(action, x.error))}</span>
          ${x.document_id ? `<button class="btn btn-secondary btn-sm" data-open-doc="${x.document_id}">문서 열기</button>` : ''}</li>`;
      }).join('')}</ul>
      ${data.failed && data.succeeded ? '<p class="te-status-note" style="margin-top:.75rem">성공한 문서는 이미 반영되었습니다. 실패한 문서만 다시 확인하세요.</p>' : ''}
      ${none ? '<p class="te-status-note" style="margin-top:.75rem">반영된 문서가 없습니다. 실패 이유를 확인하세요.</p>' : ''}`;
    m.footer.innerHTML = '<button class="btn btn-primary" id="bxClose">닫기</button>';
    if (!data.failed) T.toast(`${ACTION[action]} ${data.succeeded}건을 모두 처리했습니다.`, 'success');
    m.footer.querySelector('#bxClose').addEventListener('click', () => { m.close(); onDone && onDone(); });
    m.body.querySelectorAll('[data-open-doc]').forEach((b) => b.addEventListener('click', () => { m.close(); openDoc(Number(b.dataset.openDoc)); }));
  }

  // P7 S5-07(ISS-023): 버튼을 빠르게 두 번 누르면 모달이 겹쳐 열려, 결과 [닫기] 뒤에도 아래 모달이 남았다.
  // 일괄 모달은 한 번에 하나 — 열려 있거나 여는 중(비동기 준비)이면 새로 열지 않는다.
  let batchBusy = false;
  const batchOpen = () => batchBusy || !!document.querySelector('.te-modal-wrap');
  async function guardOpen(prepare) {
    if (batchOpen()) return;
    batchBusy = true;
    try { await prepare(); } finally { batchBusy = false; }
  }

  // 일괄 모달 틀: formModal + 제목 바꾸기(결과로 바뀔 때)
  function batchModal(title) {
    const m = formModal({ title, wide: true });
    m.title = (text, cls) => {
      const el = m.wrap.querySelector('.modal-title');
      el.textContent = text;
      el.className = `modal-title ${cls || ''}`;
    };
    return m;
  }
  // 제외 목록(P7 S5 검토 A8): "제외 n건"을 접고, 펼치면 문서마다 한 줄
  const excludedHtml = (list) => (list.length ? `<details class="te-excluded" id="bxExcluded"><summary>제외 ${list.length}건 — 이 동작에 맞지 않아 처리하지 않음</summary>
    <ul>${list.map((x) => `<li><b>${rowName(x.row)}</b> <span class="te-hint">${esc(x.why.replace(/^\(|\)$/g, ''))}</span></li>`).join('')}</ul></details>` : '');
  const overLimit = (n, max) => (n > max ? `<div class="te-error-text">한 번에 ${max}건까지 처리할 수 있습니다(선택 ${n}건).</div>` : '');

  const Batch = {
    config: batchConfig,
    failureText,
    showResult: showBatchResult,
    modal: batchModal,
    excludedHtml,
    overLimit,
    rowName,
    verdictHtml,
    staffText,

    guardOpen,
    isOpen: batchOpen,

    // ---------- WF-SC-11 일괄 승인 ----------
    // origin: 'inbox'(결재함 대기 탭) | 'bundle'(묶음 상세). 내 칸 없음 제외는 묶음 상세에서 연 경우만 생긴다
    openApprove(rows, opts) { return guardOpen(() => this.showApprove(rows, opts)); },
    async showApprove(rows, { origin, onDone, openDoc }) {
      const cfg = await batchConfig();
      const targets = rows.filter((r) => r.my_slot);
      const excluded = rows.filter((r) => !r.my_slot).map((row) => ({ row, why: '(내 결재 대기 칸 없음)' }));
      const m = batchModal(`선택 승인 · ${targets.length}건 (${origin === 'inbox' ? '결재함' : '묶음 상세'}에서)`);
      const state = { comment: '', busy: false, error: '' };
      const ng = targets.filter((r) => r.verdict === 'FAIL').length;
      const render = () => {
        const tooLong = state.comment.length > 500;
        m.body.innerHTML = `
          <p class="te-hint">내 칸을 한 번에 승인합니다. 문서마다 따로 처리되어 일부만 실패할 수 있습니다. 반려는 결재 요청 상세에서 한 건씩 합니다.</p>
          ${state.error}
          <div class="te-table-wrap"><table class="data-table" id="bxTargets">
            <thead><tr><th>문서</th><th>LOT · 품목</th><th>판정(현재)</th><th>점검자</th><th>회차</th><th>내 칸</th><th>진행</th><th></th></tr></thead>
            <tbody>${targets.map((r) => `
              <tr data-target="${r.document_id}"><td>#${r.document_id}</td><td>${esc(r.lot || '-')}</td><td>${verdictHtml(r.verdict)}</td><td>${staffText(r.inspector_id)}</td>
                <td>${esc(r.attempt ?? '-')}${r.correcting ? ' <span class="badge te-chip-fix">정정</span>' : ''}</td>
                <td>${r.my_slot.slot_no}번${r.my_slot.label ? ` · ${esc(r.my_slot.label)}` : ''}</td>
                <td>${r.progress ? `${r.progress.approved}/${r.progress.total}` : '-'}</td>
                <td>${r.progress && r.progress.pending === 1 ? '<span class="te-last">→ 마지막 승인</span>' : ''}</td></tr>`).join('')
              || '<tr><td colspan="8" class="te-hint">승인할 내 칸이 없습니다.</td></tr>'}</tbody>
          </table></div>
          ${excludedHtml(excluded)}
          ${ng ? `<div class="te-ng-warn" id="bxNgWarn">⚠ 부적합 ${ng}건이 포함되어 있습니다.</div>` : ''}
          ${overLimit(targets.length, cfg.max_items)}
          <label class="form-label" style="margin-top:.75rem">의견 (선택, 500자) <span class="te-hint">— 모든 칸에 같게</span></label>
          <textarea class="form-control ${tooLong ? 'te-field-error' : ''}" id="bxComment" rows="2" maxlength="600">${esc(state.comment)}</textarea>
          <div class="te-counter" id="bxCount">${state.comment.length}/500</div>`;
        const can = api.staffId && targets.length && targets.length <= cfg.max_items && !tooLong && !state.busy;
        m.footer.innerHTML = `<button class="btn btn-secondary" id="bxCancel">취소</button>
          <button class="btn btn-primary" id="bxGo" ${can ? '' : 'disabled'}>${state.busy ? '처리 중…' : `${targets.length}건 승인`}</button>`;
        const box = m.body.querySelector('#bxComment');
        box.addEventListener('input', (e) => {
          state.comment = e.target.value;
          m.body.querySelector('#bxCount').textContent = `${state.comment.length}/500`;
          box.classList.toggle('te-field-error', state.comment.length > 500);
          m.footer.querySelector('#bxGo').disabled = !(api.staffId && targets.length && targets.length <= cfg.max_items && state.comment.length <= 500);
        });
        m.footer.querySelector('#bxCancel').addEventListener('click', m.close);
        m.footer.querySelector('#bxGo').addEventListener('click', go);
      };
      const go = async () => {
        state.busy = true;
        state.error = '';
        render();
        const body = { approval_ids: targets.map((r) => r.my_slot.approval_id) };
        if (state.comment.trim()) body.comment = state.comment;
        const res = await api.post('approvals/batch-decision', body);
        state.busy = false;
        if (res.ok) { showBatchResult(m, 'approve', res.data, targets, { onDone, openDoc }); return; }
        state.error = requestErrorHtml(res);
        T.toast(T.errorText(res), 'error');
        render();
      };
      render();
    },

    // ---------- WF-SC-12 일괄 상신 ----------
    openSubmit(rows, defaultSlots, opts) { return guardOpen(() => this.showSubmit(rows, defaultSlots, opts)); },
    async showSubmit(rows, defaultSlots, { onDone, openDoc }) {
      const cfg = await batchConfig();
      const targets = rows.filter((r) => r.status === 'completed');
      const excluded = rows.filter((r) => r.status !== 'completed').map((row) => ({ row, why: `(${T.STATUS[row.status]?.label || row.status} — 작성완료 아님)` }));
      const slots = (defaultSlots && defaultSlots.length ? defaultSlots : [{ label: '담당' }, { label: '검토' }, { label: '승인' }])
        .map((s) => ({ label: s.label || '', approver_id: s.approver_id ? String(s.approver_id) : '' }));
      const m = batchModal(`선택 상신 · ${targets.length}건`);
      const state = { errors: {}, top: '', busy: false };
      const render = () => {
        m.body.innerHTML = `
          <p class="te-hint">같은 결재선으로 문서마다 따로 상신합니다(문서마다 회차). 일부만 실패할 수 있습니다.</p>
          ${state.top}
          <div class="te-table-wrap"><table class="data-table" id="bxTargets">
            <thead><tr><th>문서</th><th>LOT · 품목</th><th>버전</th><th></th></tr></thead>
            <tbody>${targets.map((r) => `<tr data-target="${r.document_id}"><td>#${r.document_id}</td><td>${esc(r.lot || '-')}</td><td>v${r.version}</td>
              <td>${r.correcting ? '<span class="badge te-chip-fix">정정</span>' : ''}</td></tr>`).join('')
              || '<tr><td colspan="4" class="te-hint">작성완료 문서가 없습니다.</td></tr>'}</tbody>
          </table></div>
          ${excludedHtml(excluded)}
          ${overLimit(targets.length, cfg.max_items)}
          <div class="te-section-title" style="margin-top:1rem">결재선 <span class="te-hint">— 모든 문서에 같게 · 기본값: 이 묶음 문서 중 가장 최근 회차의 결재선${defaultSlots && defaultSlots.length ? '' : '(없어서 빈 3칸)'}</span></div>
          ${slotEditorHtml(slots, state.errors)}
          <p class="te-status-note" style="margin-top:1rem">상신하면 문서가 잠겨 결재가 끝날 때까지 수정할 수 없습니다.</p>`;
        const can = api.staffId && targets.length && targets.length <= cfg.max_items && slotsReady(slots) && !state.busy;
        m.footer.innerHTML = `<button class="btn btn-secondary" id="bxCancel">취소</button>
          <button class="btn btn-primary" id="bxGo" ${can ? '' : 'disabled'}>${state.busy ? '상신 중…' : `${targets.length}건 상신`}</button>`;
        bindSlotEditor(m.body, slots, state, render);
        m.footer.querySelector('#bxCancel').addEventListener('click', m.close);
        m.footer.querySelector('#bxGo').addEventListener('click', go);
      };
      const go = async () => {
        state.busy = true;
        state.top = '';
        render();
        const res = await api.post('documents/batch-submit', {
          items: targets.map((r) => ({ document_id: r.document_id, expected_version: r.version })),
          slots: slotsPayload(slots),
        });
        state.busy = false;
        if (res.ok) { showBatchResult(m, 'submit', res.data, targets, { onDone, openDoc }); return; }
        state.top = res.data && res.data.code === 'INVALID_SLOTS' ? `<div class="te-error-box" id="bxError">${slotErrors(res.data, state)} 아무것도 처리하지 않았습니다.</div>` : requestErrorHtml(res);
        T.toast(T.errorText(res), 'error');
        render();
      };
      render();
    },
  };

  const Approval = {
    title: '결재함',
    root: null,
    templates: {},
    inbox: { box: 'pending', from: '', to: '', template_id: '', received: '', page: 1, pendingTotal: null },
    selected: new Map(),  // P7 결재함 선택 승인: approval_id → 결재함 줄

    async templateName(id) {
      if (!this.templates[id]) {
        const r = await api.get(`templates/${id}`);
        this.templates[id] = r.ok ? r.data : { name: `양식 #${id}`, version: '', schema: { sections: [] } };
      }
      return this.templates[id];
    },

    // ================================================= WF-SC-01 문서 상세 › 결재 영역
    async mountArea(el, d, reload) {
      if (!el) return;
      el.innerHTML = '<div class="te-approval"><div class="te-section-title">결재</div><table class="data-table"><tbody><tr class="te-skeleton"><td>.</td></tr><tr class="te-skeleton"><td>.</td></tr></tbody></table></div>';
      const r = await api.get(`documents/${d.document_id}/approval-requests`);
      if (!r.ok) {
        el.innerHTML = `<div class="te-approval"><div class="te-section-title">결재</div>
          <div class="te-error-box">${esc(T.errorText(r))} <button class="btn btn-secondary btn-sm" id="apRetry">다시 시도</button></div></div>`;
        el.querySelector('#apRetry').addEventListener('click', () => this.mountArea(el, d, reload));
        return;
      }
      const items = r.data.items;
      const latest = items[0] || null;
      // P4: 상신은 작성완료(completed)에서만. 반려 뒤 수정·작성완료·작성 재개를 거치면 최신 회차는 rejected로 남는다.
      // P6: 정정 중·정정 작성완료의 최신 회차 = 유효 승인 회차 또는 반려된 정정 회차
      const fixing = !!d.correction;
      // P10: 상신 취소 뒤에는 최신 회차가 cancelled(문서 작성완료 → 작성 재개·정정 중도 가능)
      const allowed = {
        draft: [null, 'rejected', 'cancelled'], completed: fixing ? ['approved', 'rejected', 'cancelled'] : [null, 'rejected', 'cancelled'],
        submitted: ['in_progress'], approved: ['approved'], rejected: ['rejected'],
        correcting: ['approved', 'rejected', 'cancelled'],
      }[d.status] || [];
      const effective = items.find((x) => x.effective) || null;
      const lines = correctionLines(items, d.corrections);
      const linesOf = (req) => (lines[req.request_id] ? `<ul class="te-fix-lines">${lines[req.request_id].join('')}</ul>` : '');
      // 정정 진행 중의 반려 회차는 정정 회차여야 한다(일반 회차 반려 + 정정 중은 어긋남 — P6 S5 검토 B1)
      const mismatch = !allowed.includes(latest ? latest.status : null)
        || (fixing && latest && latest.status === 'rejected' && !latest.is_correction);
      const canSubmit = d.status === 'completed';
      const notReady = '<div class="te-hint">작성완료한 뒤 상신할 수 있습니다.</div>';
      let head = '';
      let body = '';
      let action = '';
      const disabled = api.staffId ? '' : 'disabled';
      if (mismatch) {
        body = `<div class="te-error-box">결재 기록이 문서 상태(${esc(T.STATUS[d.status]?.label || d.status)})와 맞지 않습니다${latest ? ` — 최신 회차 ${esc(REQUEST[latest.status]?.label || latest.status)}` : ' — 회차 없음'}. 관리자에게 확인을 요청하세요.</div>`;
        if (latest) body += slotTable(latest);
      } else if (!latest) {
        body = canSubmit
          ? '<p class="te-hint">아직 상신하지 않았습니다. 결재선을 지정해 상신하세요.</p>'
          : `<p class="te-hint">아직 상신하지 않았습니다.</p>${notReady}`;
        if (canSubmit) action = `<button class="btn btn-primary btn-sm" id="apSubmit" ${disabled}>결재 상신</button>`;
      } else {
        head = `<span class="te-hint">${latest.attempt}회차 ·</span> ${badge(REQUEST, latest.status)}${reqChips(latest)}`;
        const effLine = fixing && effective && effective.request_id !== latest.request_id
          ? `<div class="te-meta" id="teEffectiveLine">유효 승인본: <b>${effective.attempt}회차</b> (${T.fmtDateTime(effective.closed_at)} 승인) <button class="btn btn-secondary btn-sm" data-open-request="${effective.request_id}">보기</button></div>` : '';
        body = `<div class="te-meta">상신 staff ${latest.requested_by} · ${T.fmtDateTime(latest.requested_at)} · 문서 버전 v${latest.document_version}</div>${effLine}
          ${latest.is_correction && latest.correction_reason ? `<div class="te-hint">정정 사유: ${esc(latest.correction_reason)}</div>` : ''}${slotTable(latest)}`;
        if (fixing && latest.status !== 'in_progress' && d.status !== 'completed') {
          body += '<div class="te-status-note">정정 중입니다. 작성완료한 뒤 상신하세요.</div>';
        }
        if (latest.status === 'in_progress') {
          body += `<div class="te-hint te-progress">진행 ${approvedCount(latest)}/${latest.slots.length} 승인</div>${myLine(latest)}`;
          // P10 WF-SC-01: 이 회차 상신자에게만 [상신 취소](칸을 이미 받았어도 — P10-Q4 a)
          if (api.staffId && String(latest.requested_by) === api.staffId) action = '<button class="btn btn-sm te-btn-outline-danger" id="apCancelSubmit">상신 취소</button>';
        } else if (latest.status === 'cancelled') {
          body += `<div class="te-status-note" id="apCancelledNote">상신을 취소했습니다 (${T.fmtDateTime(latest.closed_at)}). 받은 승인은 무효입니다. ${canSubmit ? '작성완료된 내용으로 재상신할 수 있습니다.' : '작성완료한 뒤 재상신하세요.'}</div>`;
          if (canSubmit) action = `<button class="btn btn-primary btn-sm" id="apSubmit" ${disabled}>재상신</button>`;
        } else if (latest.status === 'approved') {
          body += `<div class="te-status-note te-ok-note">결재가 끝났습니다 (${T.fmtDateTime(latest.closed_at)})</div>${linesOf(latest)}`;
          if (fixing && canSubmit) action = `<button class="btn btn-primary btn-sm" id="apSubmit" ${disabled}>결재 상신</button>`;
        } else {
          const rej = latest.slots.find((s) => s.state === 'rejected');
          body += `<div class="te-reject-reason">${latest.is_correction && d.status === 'correcting' ? '반려 — 정정 중으로 돌아갔습니다 · ' : ''}반려 사유 — ${rej ? `${slotName(rej)} staff ${rej.approver_id}: ${esc(rej.comment)}` : '-'}</div>
            <div class="te-hint">${canSubmit ? '작성완료된 내용으로 재상신할 수 있습니다.' : '필요하면 수정하고, 작성완료한 뒤 재상신하세요.'}</div>`;
          if (canSubmit) action = `<button class="btn btn-primary btn-sm" id="apSubmit" ${disabled}>재상신</button>`;
        }
      }
      const older = items.slice(1);
      const history = older.length ? `
        <details class="te-history"><summary>이전 회차 (${older.length})</summary>
          <ul>${older.map((h) => {
            const rej = h.slots.find((s) => s.state === 'rejected');
            return `<li data-history="${h.attempt}">${h.attempt}회차 · ${badge(REQUEST, h.status)}${reqChips(h)} · ${T.fmtDateTime(h.closed_at || h.requested_at)}${rej ? ` · staff ${rej.approver_id} "${esc(rej.comment)}"` : ''}
              <button class="btn btn-secondary btn-sm" data-open-request="${h.request_id}">회차 보기</button>${linesOf(h)}</li>`;
          }).join('')}</ul></details>` : '';
      const current = latest && !mismatch ? `<button class="btn btn-secondary btn-sm" data-open-request="${latest.request_id}">회차 보기</button>` : '';
      el.innerHTML = `
        <div class="te-approval" id="teApproval">
          <div class="te-section-head"><span class="te-section-title">결재 ${head}</span><span class="page-actions">${current}${action}</span></div>
          ${body}${history}
        </div>`;
      el.querySelector('#apSubmit')?.addEventListener('click', () => this.openSubmit(d, latest, reload));
      el.querySelector('#apCancelSubmit')?.addEventListener('click', () => this.openCancel(d, latest, items, reload));
      el.querySelectorAll('[data-open-request]').forEach((b) => b.addEventListener('click', () =>
        this.showRequest(Number(b.dataset.openRequest), { from: 'doc', documentId: d.document_id })));
      if (latest && !mismatch) bindMyLine(el, latest, reload);
    },

    // ================================================= WF-SC-09 상신 취소 모달 (P10 — 사유 없음, S1a-Q9 a)
    async openCancel(d, req, items, reload) {
      const got = req.slots.filter((s) => s.state === 'approved');
      const effective = req.is_correction ? (items || []).find((x) => x.effective) : null;
      const lines = [
        '결재 요청을 취소하고 문서를 작성완료로 되돌립니다.',
        got.length ? `받은 승인 ${got.length}건(${got.map((s) => `staff ${esc(s.approver_id)}`).join(', ')})은 무효가 됩니다.` : '',
        '회차는 "취소됨"으로 남고, 다시 상신하면 새 회차가 됩니다.',
        req.is_correction ? `정정 재상신이면 정정 진행 상태${effective ? `(유효 승인본 ${effective.attempt}회차)` : ''}는 그대로입니다.` : '',
      ].filter(Boolean);
      const m = formModal({ title: `상신 취소 · 문서 #${d.document_id} ${req.attempt}회차` });
      m.wrap.querySelector('.te-modal').id = 'teCancelModal';
      m.body.innerHTML = `<div id="cxError"></div><ul class="te-cancel-lines" id="cxLines">${lines.map((x) => `<li>${x}</li>`).join('')}</ul>`;
      m.footer.innerHTML = '<button class="btn btn-secondary" id="cxClose">닫기</button><button class="btn btn-danger" id="cxGo">상신 취소</button>';
      m.footer.querySelector('#cxClose').addEventListener('click', () => m.close());
      const go = m.footer.querySelector('#cxGo');
      go.addEventListener('click', async () => {
        go.disabled = true;
        const r = await api.post(`approval-requests/${req.request_id}/cancel`, {});
        if (r.ok) {
          m.close();
          T.toast('상신을 취소했습니다. 문서는 작성완료 상태입니다.', 'success');
          reload();
          return;
        }
        const code = r.data && r.data.code;
        const text = {
          REQUEST_CLOSED: '결재가 이미 끝났습니다.',
          NOT_REQUESTER: '상신한 사람만 취소할 수 있습니다.',
          INVALID_TRANSITION: '문서 상태가 바뀌었습니다. 새로 고치세요.',
          REQUEST_NOT_FOUND: '결재 요청을 찾을 수 없습니다.',
        }[code] || T.errorText(r);
        const reopen = code === 'REQUEST_CLOSED' || code === 'INVALID_TRANSITION';
        m.body.querySelector('#cxError').innerHTML = `<div class="te-error-box">${esc(text)}${reopen ? ' <button class="btn btn-secondary btn-sm" id="cxReload">다시 열기</button>' : ''}</div>`;
        m.body.querySelector('#cxReload')?.addEventListener('click', () => { m.close(); reload(); });
        go.disabled = code === 'NOT_REQUESTER' || reopen;  // 다시 눌러도 같은 결과
      });
    },

    // ================================================= WF-SC-02 상신 모달 (결재선 지정)
    defaultSlots(d, latest) {
      if (latest) return latest.slots.map((s) => ({ label: s.label || '', approver_id: String(s.approver_id) }));
      return [
        { label: '담당', approver_id: d.assignee_id ? String(d.assignee_id) : '' },
        { label: '검토', approver_id: '' },
        { label: '승인', approver_id: '' },
      ];
    },

    openSubmit(d, latest, reload, keepRows) {
      const rows = keepRows || this.defaultSlots(d, latest);
      const m = formModal({ title: `${latest ? '재상신' : '결재 상신'} · 문서 #${d.document_id} (v${d.version})`, wide: true });
      const state = { errors: {}, top: '', busy: false };
      const render = () => {
        const ready = api.staffId && slotsReady(rows);
        m.body.innerHTML = `
          <p class="te-hint">결재선 — 칸마다 1명, 모두 승인하면 결재 완료 · 처리 순서 없음${latest ? '<br>직전 회차 결재선을 불러왔습니다.' : ''}</p>
          ${state.top ? `<div class="te-error-box">${state.top}</div>` : ''}
          ${slotEditorHtml(rows, state.errors)}
          <p class="te-status-note" style="margin-top:1rem">상신하면 문서가 잠겨 결재가 끝날 때까지 수정할 수 없습니다.</p>
          ${api.staffId ? '' : '<div class="te-notice">현재 사용자를 선택하세요.</div>'}`;
        m.footer.innerHTML = `<button class="btn btn-secondary" id="apCancel">취소</button>
          <button class="btn btn-primary" id="apGo" ${ready && !state.busy ? '' : 'disabled'}>${state.busy ? '상신 중…' : '상신'}</button>`;
        bindSlotEditor(m.body, rows, state, render);
        m.footer.querySelector('#apCancel').addEventListener('click', m.close);
        m.footer.querySelector('#apGo').addEventListener('click', go);
        m.body.querySelectorAll('[data-reload]').forEach((b) => b.addEventListener('click', () => { m.close(); reload(); }));
        m.body.querySelectorAll('[data-to-list]').forEach((b) => b.addEventListener('click', () => { m.close(); T.open('temp-doc'); }));
      };
      const go = async () => {
        state.busy = true;
        state.top = '';
        render();
        const res = await api.post(`documents/${d.document_id}/submit`, { expected_version: d.version, slots: slotsPayload(rows) });
        state.busy = false;
        if (res.ok) {
          m.close();
          T.toast(`상신했습니다 (${res.data.request.attempt}회차)`, 'success');
          reload();
          return;
        }
        const code = res.data && res.data.code;
        if (code === 'VERSION_CONFLICT') {
          m.close();
          this.showConflict(d, res.data, latest, reload, rows);
          return;
        }
        if (code === 'INVALID_SLOTS') {
          state.top = slotErrors(res.data, state);
        } else if (code === 'DOCUMENT_LOCKED') {
          state.top = '문서가 작성완료 상태가 아니거나(작성 재개됨) 이미 결재 진행 중·승인되어 상신할 수 없습니다. <button class="btn btn-secondary btn-sm" data-reload>상세 새로고침</button>';
        } else if (code === 'OPEN_REQUEST_EXISTS') {
          state.top = '이 문서에 진행 중인 결재가 이미 있습니다. <button class="btn btn-secondary btn-sm" data-reload>상세 새로고침</button>';
        } else if (res.status === 404) {
          state.top = '문서를 찾을 수 없습니다 (삭제되었을 수 있습니다). <button class="btn btn-secondary btn-sm" data-to-list>목록</button>';
        } else {
          state.top = esc(T.errorText(res));
        }
        T.toast(T.errorText(res), 'error');
        render();
      };
      render();
    },

    // ================================================= WF-SC-07 상신 충돌 모달
    async showConflict(d, data, latest, reload, rows) {
      const info = (data.details || [])[0] || {};
      const reopen = await T.modal({
        title: '문서가 바뀌었습니다',
        body: `<p>이 화면을 연 뒤에 문서가 다시 저장되었습니다.<br>
          (내가 본 버전 v${esc(info.expected ?? d.version)} → 현재 버전 v${esc(info.current ?? '?')}${info.updated_at ? `, 마지막 수정 ${esc(T.fmtDateTime(info.updated_at))}` : ''})</p>
          <p>바뀐 내용을 확인한 뒤 다시 상신하세요. 지정한 결재선은 유지됩니다.</p>`,
        buttons: [{ label: '취소', value: false }, { label: '최신 내용으로 다시 열기', value: true, cls: 'btn-primary' }],
      });
      if (!reopen) return;
      await reload();
      const fresh = await api.get(`documents/${d.document_id}`);
      if (!fresh.ok) { T.toast(T.errorText(fresh), 'error'); return; }
      this.openSubmit(fresh.data, latest, reload, rows);
    },

    // ================================================= WF-SC-05 승인 / WF-SC-06 반려
    openDecision(slot, req, result, after) {
      if (!slot) return;
      const reject = result === 'rejected';
      const last = pendingCount(req) === 1;
      const m = formModal({ title: reject ? '반려' : '승인' });
      const state = { comment: '', error: '', busy: false };
      const render = () => {
        const blank = !state.comment.trim();
        m.body.innerHTML = `
          <p class="te-hint">문서 #${req.document_id} · ${req.attempt}회차 · ${slotName(slot)}</p>
          <label class="form-label">${reject ? '반려 사유* (500자)' : '의견 (선택, 500자)'}</label>
          <textarea class="form-control ${state.error ? 'te-field-error' : ''}" id="apComment" rows="4" maxlength="600">${esc(state.comment)}</textarea>
          ${state.error ? `<div class="te-error-text">${esc(state.error)}</div>` : ''}
          ${reject ? '<p class="te-status-note" style="margin-top:.75rem">반려하면 이 회차가 바로 종료되고, 아직 처리하지 않은 칸은 미처리로 끝납니다. 문서는 반려 상태가 되어 다시 수정할 수 있습니다.</p>'
            : (last ? '<p class="te-status-note te-ok-note" style="margin-top:.75rem">승인하면 결재가 완료되고 문서가 승인 상태가 됩니다.</p>' : '')}`;
        m.footer.innerHTML = `<button class="btn btn-secondary" id="apCancel">취소</button>
          <button class="btn ${reject ? 'btn-danger' : 'btn-primary'}" id="apGo" ${state.busy || (reject && blank) ? 'disabled' : ''}>${state.busy ? '처리 중…' : (reject ? '반려' : '승인')}</button>`;
        const box = m.body.querySelector('#apComment');
        box.addEventListener('input', (e) => {
          state.comment = e.target.value;
          if (reject) m.footer.querySelector('#apGo').disabled = !state.comment.trim();
        });
        m.footer.querySelector('#apCancel').addEventListener('click', m.close);
        m.footer.querySelector('#apGo').addEventListener('click', go);
        box.focus();
      };
      const go = async () => {
        state.busy = true;
        render();
        const body = { result };
        if (state.comment.trim()) body.comment = state.comment;
        const res = await api.post(`approvals/${slot.approval_id}/decision`, body);
        state.busy = false;
        if (res.ok) {
          m.close();
          const out = res.data;
          if (out.request_status === 'approved') T.toast('결재가 완료되어 문서가 승인되었습니다.', 'success');
          else if (out.request_status === 'rejected') T.toast('반려했습니다. 문서가 반려 상태가 되었습니다.', 'success');
          else T.toast(`승인했습니다 (남은 대기 ${out.pending_count}칸)`, 'success');
          after();
          return;
        }
        const code = res.data && res.data.code;
        if (code === 'COMMENT_REQUIRED') { state.error = '반려 사유를 입력하세요'; render(); return; }
        if (code === 'INVALID_DECISION') { state.error = (res.data.details?.[0]?.message) || res.data.message; render(); return; }
        m.close();
        const messages = {
          NOT_YOUR_SLOT: '이 칸의 결재자가 아닙니다 (현재 사용자를 확인하세요).',
          ALREADY_DECIDED: '이미 처리된 칸입니다.',
          REQUEST_CLOSED: CLOSED_TEXT,
          INVALID_TRANSITION: MISMATCH_TEXT,
          DOCUMENT_NOT_FOUND: MISMATCH_TEXT,
        };
        if (code === 'APPROVAL_NOT_FOUND') {
          await notice('처리할 수 없습니다', '결재 칸을 찾을 수 없습니다.');
          T.open('temp-approval');
          return;
        }
        await notice('처리할 수 없습니다', `[${code || res.status}] ${messages[code] || res.data?.message || '요청에 실패했습니다.'}`);
        after();
      };
      render();
    },

    // ================================================= WF-SC-03 결재함
    start(root) {
      this.root = root;
      const intent = T.takeIntent();
      if (intent && intent.requestId) this.showRequest(intent.requestId, { from: 'inbox' });
      else this.showInbox();
    },

    async showInbox() {
      const f = this.inbox;
      const r = await api.get('templates');
      const templates = r.ok ? r.data.items : [];
      // P7 입고일 필터(컷 ②): 입고일 = D03 작업일. 화면이 D03 활성 양식 template_id + from=to=입고일로 조합(P7-S2-Q4, D-098)
      this.d03TemplateId = (templates.find((t) => t.type_code === 'D03') || {}).template_id || null;
      const options = ['<option value="">전체</option>'].concat(templates.map((t) =>
        `<option value="${t.template_id}" ${String(f.template_id) === String(t.template_id) ? 'selected' : ''}>${esc(t.name)} v${t.version}</option>`)).join('');
      const tab = (box, label) => `<button class="btn btn-sm ${f.box === box ? 'btn-primary' : 'btn-secondary'}" data-box="${box}">${label}</button>`;
      this.root.innerHTML = `
        <div class="fade-in" id="teInbox">
          ${T.topBar('결재함', '내 결재 대기 · 처리 완료', null, { temp: false })}
          <div class="card">
            <div class="te-tabs">${tab('pending', `대기${f.pendingTotal !== null ? ` (${f.pendingTotal})` : ''}`)} ${tab('done', '처리 완료')}
              ${f.box === 'pending' ? '<span style="flex:1"></span><button class="btn btn-secondary btn-sm" id="iBatch" disabled>선택 승인 (0)</button>' : ''}</div>
            <div class="te-filters">
              <div class="form-group"><label class="form-label">작업일 시작</label><input type="date" class="form-control" id="iFrom" value="${f.from}"></div>
              <div class="form-group"><label class="form-label">작업일 종료</label><input type="date" class="form-control" id="iTo" value="${f.to}"></div>
              <div class="form-group"><label class="form-label">양식</label><select class="form-control" id="iTemplate">${options}</select></div>
              ${this.d03TemplateId ? `<div class="form-group"><label class="form-label" title="육안검사(D03) 작업일 = 입고일">입고일 (육안검사)</label><input type="date" class="form-control" id="iRecv" value="${f.received}"></div>` : ''}
              <button class="btn btn-secondary" id="iSearch">조회</button>
            </div>
            ${f.received ? `<div class="te-hint te-filter-note" id="iRecvNote">입고일 ${esc(f.received)} 육안검사만 봅니다 — 작업일·양식 조건은 쓰지 않습니다. <a href="#" id="iRecvClear">입고일 지우기</a></div>` : ''}
            <div class="te-table-wrap" id="teInboxBody"></div>
          </div>
        </div>`;
      T.bindTopBar(this.root, () => { f.pendingTotal = null; f.page = 1; this.showInbox(); });
      const $ = (s) => this.root.querySelector(s);
      this.root.querySelectorAll('[data-box]').forEach((b) => b.addEventListener('click', () => { f.box = b.dataset.box; f.page = 1; this.showInbox(); }));
      $('#iSearch').addEventListener('click', () => {
        Object.assign(f, { from: $('#iFrom').value, to: $('#iTo').value, template_id: $('#iTemplate').value, received: $('#iRecv') ? $('#iRecv').value : '', page: 1 });
        this.showInbox();
      });
      $('#iRecvClear')?.addEventListener('click', (e) => { e.preventDefault(); f.received = ''; f.page = 1; this.showInbox(); });
      $('#iBatch')?.addEventListener('click', () => this.openInboxBatch());
      this.loadInbox();
    },

    async loadInbox() {
      const f = this.inbox;
      const body = this.root.querySelector('#teInboxBody');
      if (!api.staffId) { body.innerHTML = '<div class="te-empty">현재 사용자를 선택하세요. 결재함은 현재 사용자 기준으로 보입니다.</div>'; return; }
      body.innerHTML = `<table class="data-table"><tbody>${('<tr class="te-skeleton">' + '<td>.</td>'.repeat(8) + '</tr>').repeat(3)}</tbody></table>`;
      const q = new URLSearchParams({ box: f.box, page: f.page });
      if (f.received && this.d03TemplateId) {
        q.set('template_id', this.d03TemplateId);
        q.set('from', f.received);
        q.set('to', f.received);
      } else ['from', 'to', 'template_id'].forEach((k) => { if (f[k]) q.set(k, f[k]); });
      this.selected = new Map();
      this.refreshBatchButton();
      const r = await api.get(`approval-inbox?${q}`);
      if (!r.ok) {
        T.toast(T.errorText(r), 'error');
        body.innerHTML = `<div class="te-empty">${esc(r.data?.message || '조회에 실패했습니다.')}</div>`;
        return;
      }
      const { items, total, page, page_size: size } = r.data;
      if (f.box === 'pending' && f.pendingTotal !== total) {
        f.pendingTotal = total;
        const t = this.root.querySelector('[data-box="pending"]');
        if (t) t.textContent = `대기 (${total})`;
      }
      if (!items.length) {
        body.innerHTML = `<div class="te-empty">${f.box === 'pending' ? '결재할 문서가 없습니다.' : '처리한 결재가 없습니다.'}</div>`;
        return;
      }
      const names = {};
      for (const id of [...new Set(items.map((x) => x.request.template_id))]) {
        const t = await this.templateName(id);
        names[id] = `${t.name}${t.version !== '' ? ` v${t.version}` : ''}`;
      }
      const done = f.box === 'done';
      // P7: 일괄 대상 양식(batch-config template_ids) 줄에만 선택 칸(WF-SC-03)
      const cfg = done ? null : await Batch.config();
      const selectable = (x) => !done && cfg.template_ids.includes(x.request.template_id);
      const anySelectable = items.some(selectable);
      this.pageItems = items;
      const pages = Math.max(1, Math.ceil(total / size));
      body.innerHTML = `
        <table class="data-table">
          <thead><tr>${done ? '' : `<th class="te-check-col">${anySelectable ? '<input type="checkbox" id="iAll" title="이 페이지의 대상 줄 전체">' : ''}</th>`}<th>문서</th><th>양식</th><th>대상</th><th>작업일</th><th>회차</th><th>상신</th><th>내 칸</th>
            ${done ? '<th>내 처리</th><th>처리 일시</th><th>회차 결과</th>' : '<th>진행</th>'}</tr></thead>
          <tbody>${items.map((x) => `
            <tr class="te-row-link" data-request="${x.request.request_id}">
              ${done ? '' : `<td class="te-check-col">${selectable(x) ? `<input type="checkbox" data-pick="${x.approval_id}">` : ''}</td>`}
              <td>#${x.request.document_id}${correctionChip(x.request.is_correction)}</td><td>${esc(names[x.request.template_id])}</td>
              <td>${esc(x.request.subject || '-')}${x.request.is_correction && x.request.correction_reason ? `<div class="te-hint">정정 사유: ${esc(x.request.correction_reason)}</div>` : ''}</td>
              <td>${x.request.work_date}</td><td>${x.request.attempt}</td>
              <td>staff ${x.request.requested_by}<div class="te-hint">${T.fmtDateTime(x.request.requested_at)}</div></td>
              <td>${x.slot_no}${x.label ? ` · ${esc(x.label)}` : ''}</td>
              ${done ? `<td>${badge(SLOT, x.state)}</td><td>${T.fmtDateTime(x.decided_at)}</td><td>${badge(REQUEST, x.request.status)}${x.request.superseded ? ' <span class="badge te-chip-superseded">대체됨</span>' : ''}</td>`
                : `<td>${x.request.progress.approved}/${x.request.progress.total}</td>`}
            </tr>`).join('')}</tbody>
        </table>
        <div class="te-pager">
          <button class="btn btn-secondary btn-sm" id="iPrev" ${page <= 1 ? 'disabled' : ''}>‹</button>
          <span>${page} / ${pages}</span>
          <button class="btn btn-secondary btn-sm" id="iNext" ${page >= pages ? 'disabled' : ''}>›</button>
          <span>총 ${total}건 · ${size}건씩</span>
        </div>`;
      body.querySelectorAll('[data-request]').forEach((tr) => tr.addEventListener('click', (e) => {
        if (e.target.closest('.te-check-col')) return;
        this.showRequest(Number(tr.dataset.request), { from: 'inbox' });
      }));
      const picks = [...body.querySelectorAll('[data-pick]')];
      const sync = () => {
        this.selected = new Map(picks.filter((c) => c.checked).map((c) => [Number(c.dataset.pick), items.find((x) => x.approval_id === Number(c.dataset.pick))]));
        const all = body.querySelector('#iAll');
        if (all) all.checked = picks.length > 0 && picks.every((c) => c.checked);
        this.refreshBatchButton(cfg);
      };
      picks.forEach((c) => c.addEventListener('change', sync));
      body.querySelector('#iAll')?.addEventListener('change', (e) => { picks.forEach((c) => { c.checked = e.target.checked; }); sync(); });
      body.querySelector('#iPrev').addEventListener('click', () => { f.page -= 1; this.loadInbox(); });
      body.querySelector('#iNext').addEventListener('click', () => { f.page += 1; this.loadInbox(); });
    },

    refreshBatchButton(cfg) {
      const btn = this.root && this.root.querySelector('#iBatch');
      if (!btn) return;
      const n = this.selected.size;
      const max = cfg ? cfg.max_items : 50;
      btn.textContent = `선택 승인 (${n})`;
      btn.disabled = n === 0 || n > max;
      btn.classList.toggle('btn-primary', !btn.disabled);
      btn.classList.toggle('btn-secondary', btn.disabled);
      btn.title = n > max ? `한 번에 ${max}건까지` : '';
    },

    // WF-SC-11(결재함에서): 판정·점검자는 DOC 문서 요약 여러 건(DOC-A21)으로 읽는다(S1 검토 A4)
    openInboxBatch() { return Batch.guardOpen(() => this.prepareInboxBatch()); },
    async prepareInboxBatch() {
      const picked = [...this.selected.values()];
      if (!picked.length) return;
      const ids = [...new Set(picked.map((x) => x.request.document_id))];
      const brief = await api.get(`documents/brief?ids=${ids.join(',')}`);
      if (!brief.ok) { T.toast(T.errorText(brief), 'error'); return; }
      const docs = Object.fromEntries(brief.data.items.map((b) => [b.document_id, b]));
      const rows = picked.map((x) => {
        const b = docs[x.request.document_id] || {};
        return {
          document_id: x.request.document_id,
          lot: (b.target_summary || x.request.subject || '').replace(/^LOT /, '').split(' · ').slice(0, 2).join(' · '),
          status: b.status, correcting: x.request.is_correction, version: b.version,
          verdict: b.verdict || null, nonconforming: b.nonconforming, inspector_id: b.inspector_id,
          attempt: x.request.attempt, my_slot: { approval_id: x.approval_id, slot_no: x.slot_no, label: x.label },
          progress: x.request.progress,
        };
      });
      await Batch.showApprove(rows, {
        origin: 'inbox',
        onDone: () => { this.inbox.pendingTotal = null; this.showInbox(); },
        openDoc: (id) => T.open('temp-doc', { documentId: id }),
      });
    },

    // ================================================= WF-SC-04 결재 요청 상세
    async showRequest(requestId, origin = { from: 'inbox' }) {
      const root = T.container;
      this.root = root;
      const r = await api.get(`approval-requests/${requestId}`);
      const back = () => (origin.from === 'doc' && window.TempEntryDocument
        ? window.TempEntryDocument.showDetail(origin.documentId) : this.showInbox());
      if (!r.ok) {
        root.innerHTML = `<div class="fade-in">${T.topBar('결재 요청', '')}<div class="card te-empty">
          ${r.status === 404 ? '결재 요청을 찾을 수 없습니다.' : esc(T.errorText(r))}<br><br>
          <button class="btn btn-secondary" id="rqBack">결재함으로</button></div></div>`;
        T.bindTopBar(root, () => this.showRequest(requestId, origin));
        root.querySelector('#rqBack').addEventListener('click', () => T.open('temp-approval'));
        return;
      }
      const req = r.data;
      const snap = req.snapshot || {};
      const template = await this.templateName(req.template_id);
      const current = await api.get(`documents/${req.document_id}`);
      const changed = current.ok && current.data.version !== req.document_version;
      const sections = window.TempEntryDocument && snap.sections
        ? window.TempEntryDocument.sectionsHtml(template.schema || { sections: [] }, snap) : '';
      root.innerHTML = `
        <div class="fade-in" id="teRequest">
          ${T.topBar(`결재 요청 #${req.request_id} · 문서 #${req.document_id} · ${req.attempt}회차`, '결재 요청 상세 — 상신 당시 문서 내용(스냅샷)', req.document_id)}
          <div class="card">
            <div class="card-header">
              <div class="card-title">${badge(REQUEST, req.status)}${reqChips(req)}</div>
              <div class="page-actions">
                <button class="btn btn-secondary btn-sm" id="rqInbox">결재함으로</button>
                <button class="btn btn-secondary btn-sm" id="rqDoc">문서 열기</button>
              </div>
            </div>
            ${changed ? `<div class="te-status-note">현재 문서는 이 회차 이후 수정되었습니다 (v${req.document_version} → v${current.data.version}). <button class="btn btn-secondary btn-sm" id="rqDoc2">문서 열기</button></div>` : ''}
            ${this.requestBanner(req, current.ok ? current.data : null)}
            ${!current.ok && current.status === 404 ? '<div class="te-status-note">현재 문서를 찾을 수 없습니다(삭제되었을 수 있습니다). 아래는 상신 당시 내용입니다.</div>' : ''}
            <div class="te-meta">
              <span>${esc(template.name)} v${esc(template.version)}</span><span>대상 <b id="rqTarget">${esc(this.requestTarget(req, snap))}</b></span><span>작업일 <b>${req.work_date}</b></span>
            </div>
            <div class="te-meta" style="margin-top:.25rem">
              <span>상신 staff ${req.requested_by} · ${T.fmtDateTime(req.requested_at)}</span><span>상신 당시 문서 버전 v${req.document_version}</span>
              ${req.closed_at ? `<span>종료 ${T.fmtDateTime(req.closed_at)}</span>` : ''}
            </div>
            <div class="te-section">
              <div class="te-section-head"><span class="te-section-title">결재선</span>
                <span class="te-hint">진행 ${approvedCount(req)}/${req.slots.length} 승인</span></div>
              ${slotTable(req)}
              ${myLine(req)}
            </div>
            <div class="te-section te-snapshot">
              <div class="te-section-title">상신 당시 문서 내용 (스냅샷)</div>
              ${sections || '<p class="te-hint">표시할 내용이 없습니다.</p>'}
              ${window.TempEntryDocument && snap.sections ? window.TempEntryDocument.deviationsHtml(template.schema || { sections: [] }, snap, '상신 당시 이탈·개선조치') : ''}
            </div>
          </div>
        </div>`;
      T.bindTopBar(root, () => this.showRequest(requestId, origin));
      const openDoc = () => T.open('temp-doc', { documentId: req.document_id });
      root.querySelector('#rqInbox').addEventListener('click', () => (origin.from === 'doc' ? T.open('temp-approval') : this.showInbox()));
      root.querySelector('#rqDoc').addEventListener('click', origin.from === 'doc' ? back : openDoc);
      root.querySelector('#rqDoc2')?.addEventListener('click', origin.from === 'doc' ? back : openDoc);
      bindMyLine(root, req, () => this.showRequest(requestId, origin));
      root.querySelector('#rqEffective')?.addEventListener('click', async () => {
        const h = await api.get(`documents/${req.document_id}/approval-requests`);
        const eff = h.ok ? h.data.items.find((x) => x.effective) : null;
        if (eff) this.showRequest(eff.request_id, origin); else T.toast(h.ok ? '유효 승인본이 없습니다.' : T.errorText(h), 'error');
      });
    },

    // ISS-018: 상신 때 저장한 대상 요약. 예전 요청(저장 값 없음)은 스냅샷으로 화면에서 계산, 그것도 없으면 "-"
    requestTarget(req, snap) {
      if (req.subject) return req.subject;
      if (snap && snap.target_summary) return snap.target_summary;
      const text = snap && snap.sections && window.TempEntryDocument ? window.TempEntryDocument.targetText(snap) : '';
      return text && text !== '-' ? text : '-';
    },

    // WF-SC-04 P6 배너: 대체됨 / 유효 승인본(정정 진행 중) / 정정 상신 사유
    requestBanner(req, doc) {
      const out = [];
      if (req.superseded_by) {
        out.push(`<div class="te-status-note" id="rqSuperseded">ⓘ 이 승인본은 ${req.superseded_by}회차 승인(${T.fmtDateTime(req.superseded_at)})으로 대체되었습니다.
          <button class="btn btn-secondary btn-sm" id="rqEffective">유효 승인본 보기</button></div>`);
      } else if (req.effective && doc && doc.correction) {
        out.push(`<div class="te-fix-banner" id="rqEffectiveNote">지금 유효한 승인본입니다. 문서는 정정 중입니다(사유: ${esc(doc.correction.reason)}).</div>`);
      }
      if (req.is_correction) out.push(`<div class="te-meta" id="rqFixReason">정정 사유: ${esc(req.correction_reason || '-')}</div>`);
      return out.join('');
    },
  };

  T.register('approval-box', Approval);  // 예전 temp-approval도 이 화면(TempEntry.PAGE_ALIAS)
  Approval.batch = Batch;
  window.TempEntryApproval = Approval;
})();
