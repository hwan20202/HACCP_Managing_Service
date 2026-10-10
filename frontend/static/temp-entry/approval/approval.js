// =============================================
// 개발 검증 › 결재 (P3 WF 사용 화면)
// 화면: WF-SC-01 문서 상세 결재 영역 · 02 상신 모달 · 03 결재함 · 04 결재 요청 상세
//       05 승인 모달 · 06 반려 모달 · 07 상신 충돌 모달
// 설계: dev-notes/document-workflow/s1-screens.md, API: s2-spec.md 2장
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
  const slotName = (s) => `${s.slot_no}번 칸${s.label ? ` · ${esc(s.label)}` : ''}`;

  function slotTable(req) {
    return `
      <div class="te-table-wrap"><table class="data-table te-slot-table">
        <thead><tr><th>칸</th><th>역할</th><th>결재자</th><th>상태</th><th>처리 일시</th><th>의견</th></tr></thead>
        <tbody>${req.slots.map((s) => `
          <tr class="${String(s.approver_id) === api.staffId ? 'te-slot-mine' : ''}" data-slot="${s.slot_no}">
            <td>${s.slot_no}</td><td>${esc(s.label || '-')}</td><td>staff ${s.approver_id}</td>
            <td>${badge(SLOT, s.state)}</td><td>${T.fmtDateTime(s.decided_at)}</td>
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

  const Approval = {
    title: '결재함',
    root: null,
    templates: {},
    inbox: { box: 'pending', from: '', to: '', template_id: '', page: 1, pendingTotal: null },

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
      const expected = { draft: null, submitted: 'in_progress', approved: 'approved', rejected: 'rejected' }[d.status];
      const mismatch = (latest ? latest.status : null) !== expected;
      let head = '';
      let body = '';
      let action = '';
      const disabled = api.staffId ? '' : 'disabled';
      if (mismatch) {
        body = `<div class="te-error-box">결재 기록이 문서 상태(${esc(T.STATUS[d.status]?.label || d.status)})와 맞지 않습니다${latest ? ` — 최신 회차 ${esc(REQUEST[latest.status]?.label || latest.status)}` : ' — 회차 없음'}. 관리자에게 확인을 요청하세요.</div>`;
        if (latest) body += slotTable(latest);
      } else if (!latest) {
        body = '<p class="te-hint">아직 상신하지 않았습니다. 결재선을 지정해 상신하세요.</p>';
        action = `<button class="btn btn-primary btn-sm" id="apSubmit" ${disabled}>결재 상신</button>`;
      } else {
        head = `<span class="te-hint">${latest.attempt}회차 ·</span> ${badge(REQUEST, latest.status)}`;
        body = `<div class="te-meta">상신 staff ${latest.requested_by} · ${T.fmtDateTime(latest.requested_at)} · 문서 버전 v${latest.document_version}</div>${slotTable(latest)}`;
        if (latest.status === 'in_progress') {
          body += `<div class="te-hint te-progress">진행 ${approvedCount(latest)}/${latest.slots.length} 승인</div>${myLine(latest)}`;
        } else if (latest.status === 'approved') {
          body += `<div class="te-status-note te-ok-note">결재가 끝났습니다 (${T.fmtDateTime(latest.closed_at)})</div>`;
        } else {
          const rej = latest.slots.find((s) => s.state === 'rejected');
          body += `<div class="te-reject-reason">반려 사유 — ${rej ? `${slotName(rej)} staff ${rej.approver_id}: ${esc(rej.comment)}` : '-'}</div>
            <div class="te-hint">수정한 뒤 재상신하세요. 수정 없이 재상신할 수도 있습니다.</div>`;
          action = `<button class="btn btn-primary btn-sm" id="apSubmit" ${disabled}>재상신</button>`;
        }
      }
      const older = items.slice(1);
      const history = older.length ? `
        <details class="te-history"><summary>이전 회차 (${older.length})</summary>
          <ul>${older.map((h) => {
            const rej = h.slots.find((s) => s.state === 'rejected');
            return `<li>${h.attempt}회차 · ${badge(REQUEST, h.status)} · ${T.fmtDateTime(h.closed_at || h.requested_at)}${rej ? ` · staff ${rej.approver_id} "${esc(rej.comment)}"` : ''}
              <button class="btn btn-secondary btn-sm" data-open-request="${h.request_id}">회차 보기</button></li>`;
          }).join('')}</ul></details>` : '';
      const current = latest && !mismatch ? `<button class="btn btn-secondary btn-sm" data-open-request="${latest.request_id}">회차 보기</button>` : '';
      el.innerHTML = `
        <div class="te-approval" id="teApproval">
          <div class="te-section-head"><span class="te-section-title">결재 ${head}</span><span class="page-actions">${current}${action}</span></div>
          ${body}${history}
        </div>`;
      el.querySelector('#apSubmit')?.addEventListener('click', () => this.openSubmit(d, latest, reload));
      el.querySelectorAll('[data-open-request]').forEach((b) => b.addEventListener('click', () =>
        this.showRequest(Number(b.dataset.openRequest), { from: 'doc', documentId: d.document_id })));
      if (latest && !mismatch) bindMyLine(el, latest, reload);
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
      const staffOptions = (selected, others) => ['<option value="">선택</option>']
        .concat((T.staff || []).map((id) => {
          const v = String(id);
          const taken = others.includes(v);
          return `<option value="${v}" ${v === selected ? 'selected' : ''} ${taken ? 'disabled' : ''}>staff ${v}${taken ? ' (다른 칸)' : ''}</option>`;
        })).join('');
      const render = () => {
        const chosen = rows.map((r) => r.approver_id);
        const ready = api.staffId && rows.length > 0 && rows.every((r) => r.approver_id);
        m.body.innerHTML = `
          <p class="te-hint">결재선 — 칸마다 1명, 모두 승인하면 결재 완료 · 처리 순서 없음${latest ? '<br>직전 회차 결재선을 불러왔습니다.' : ''}</p>
          ${state.top ? `<div class="te-error-box">${state.top}</div>` : ''}
          <table class="data-table te-slot-edit">
            <thead><tr><th>칸</th><th>역할(선택)</th><th>결재자*</th><th></th></tr></thead>
            <tbody>${rows.map((r, i) => `
              <tr data-i="${i}">
                <td>${i + 1}</td>
                <td><input class="form-control ${state.errors[`${i}.label`] ? 'te-field-error' : ''}" data-f="label" maxlength="20" value="${esc(r.label)}" placeholder="예: 담당">
                  ${state.errors[`${i}.label`] ? `<div class="te-error-text">${esc(state.errors[`${i}.label`])}</div>` : ''}</td>
                <td><select class="form-control ${state.errors[`${i}.approver_id`] || !r.approver_id ? 'te-field-error' : ''}" data-f="approver_id">${staffOptions(r.approver_id, chosen.filter((_, j) => j !== i))}</select>
                  ${state.errors[`${i}.approver_id`] ? `<div class="te-error-text">${esc(state.errors[`${i}.approver_id`])}</div>` : (!r.approver_id ? '<div class="te-error-text">결재자를 선택하세요</div>' : '')}</td>
                <td class="te-nowrap">
                  <button class="btn btn-secondary btn-sm" data-act="up" ${i === 0 ? 'disabled' : ''} title="위로">↑</button>
                  <button class="btn btn-secondary btn-sm" data-act="down" ${i === rows.length - 1 ? 'disabled' : ''} title="아래로">↓</button>
                  <button class="btn btn-secondary btn-sm" data-act="del" title="삭제">✕</button>
                </td>
              </tr>`).join('')}</tbody>
          </table>
          <div style="margin-top:.5rem"><button class="btn btn-secondary btn-sm" id="apAdd" ${rows.length >= MAX_SLOTS ? 'disabled' : ''}>+ 칸 추가</button> <span class="te-hint">(최대 ${MAX_SLOTS}칸)</span></div>
          <p class="te-status-note" style="margin-top:1rem">상신하면 문서가 잠겨 결재가 끝날 때까지 수정할 수 없습니다.</p>
          ${api.staffId ? '' : '<div class="te-notice">현재 사용자를 선택하세요.</div>'}`;
        m.footer.innerHTML = `<button class="btn btn-secondary" id="apCancel">취소</button>
          <button class="btn btn-primary" id="apGo" ${ready && !state.busy ? '' : 'disabled'}>${state.busy ? '상신 중…' : '상신'}</button>`;
        m.body.querySelectorAll('tr[data-i]').forEach((tr) => {
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
        m.body.querySelector('#apAdd').addEventListener('click', () => { rows.push({ label: '', approver_id: '' }); render(); });
        m.footer.querySelector('#apCancel').addEventListener('click', m.close);
        m.footer.querySelector('#apGo').addEventListener('click', go);
        m.body.querySelectorAll('[data-reload]').forEach((b) => b.addEventListener('click', () => { m.close(); reload(); }));
        m.body.querySelectorAll('[data-to-list]').forEach((b) => b.addEventListener('click', () => { m.close(); T.open('temp-doc'); }));
      };
      const go = async () => {
        state.busy = true;
        state.top = '';
        render();
        const slots = rows.map((r, i) => {
          const slot = { slot_no: i + 1, approver_id: Number(r.approver_id) };
          if (r.label.trim()) slot.label = r.label.trim();
          return slot;
        });
        const res = await api.post(`documents/${d.document_id}/submit`, { expected_version: d.version, slots });
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
          state.errors = {};
          const top = [];
          (res.data.details || []).forEach((e) => {
            const hit = /^slots\[(\d+)\]\.(\w+)$/.exec(e.path || '');
            if (hit) state.errors[`${hit[1]}.${hit[2]}`] = e.message;
            else top.push(esc(e.message));
          });
          state.top = `[INVALID_SLOTS] ${esc(res.data.message)}${top.length ? `<ul>${top.map((t) => `<li>${t}</li>`).join('')}</ul>` : ''}`;
        } else if (code === 'DOCUMENT_LOCKED') {
          state.top = '문서가 이미 결재 진행 중이거나 승인되어 상신할 수 없습니다. <button class="btn btn-secondary btn-sm" data-reload>상세 새로고침</button>';
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
          REQUEST_CLOSED: '다른 결재자가 반려해 이 회차가 종료되었습니다.',
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
      const options = ['<option value="">전체</option>'].concat(templates.map((t) =>
        `<option value="${t.template_id}" ${String(f.template_id) === String(t.template_id) ? 'selected' : ''}>${esc(t.name)} v${t.version}</option>`)).join('');
      const tab = (box, label) => `<button class="btn btn-sm ${f.box === box ? 'btn-primary' : 'btn-secondary'}" data-box="${box}">${label}</button>`;
      this.root.innerHTML = `
        <div class="fade-in" id="teInbox">
          ${T.topBar('결재함', '결재 워크플로우(P3) 사용 화면 — 내 결재 대기·처리 완료')}
          <div class="card">
            <div class="te-tabs">${tab('pending', `대기${f.pendingTotal !== null ? ` (${f.pendingTotal})` : ''}`)} ${tab('done', '처리 완료')}</div>
            <div class="te-filters">
              <div class="form-group"><label class="form-label">작업일 시작</label><input type="date" class="form-control" id="iFrom" value="${f.from}"></div>
              <div class="form-group"><label class="form-label">작업일 종료</label><input type="date" class="form-control" id="iTo" value="${f.to}"></div>
              <div class="form-group"><label class="form-label">양식</label><select class="form-control" id="iTemplate">${options}</select></div>
              <button class="btn btn-secondary" id="iSearch">조회</button>
            </div>
            <div class="te-table-wrap" id="teInboxBody"></div>
          </div>
        </div>`;
      T.bindTopBar(this.root, () => { f.pendingTotal = null; f.page = 1; this.showInbox(); });
      const $ = (s) => this.root.querySelector(s);
      this.root.querySelectorAll('[data-box]').forEach((b) => b.addEventListener('click', () => { f.box = b.dataset.box; f.page = 1; this.showInbox(); }));
      $('#iSearch').addEventListener('click', () => {
        Object.assign(f, { from: $('#iFrom').value, to: $('#iTo').value, template_id: $('#iTemplate').value, page: 1 });
        this.loadInbox();
      });
      this.loadInbox();
    },

    async loadInbox() {
      const f = this.inbox;
      const body = this.root.querySelector('#teInboxBody');
      if (!api.staffId) { body.innerHTML = '<div class="te-empty">현재 사용자를 선택하세요. 결재함은 현재 사용자 기준으로 보입니다.</div>'; return; }
      body.innerHTML = `<table class="data-table"><tbody>${('<tr class="te-skeleton">' + '<td>.</td>'.repeat(8) + '</tr>').repeat(3)}</tbody></table>`;
      const q = new URLSearchParams({ box: f.box, page: f.page });
      ['from', 'to', 'template_id'].forEach((k) => { if (f[k]) q.set(k, f[k]); });
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
      const pages = Math.max(1, Math.ceil(total / size));
      body.innerHTML = `
        <table class="data-table">
          <thead><tr><th>문서</th><th>양식</th><th>대상</th><th>작업일</th><th>회차</th><th>상신</th><th>내 칸</th>
            ${done ? '<th>내 처리</th><th>처리 일시</th><th>회차 결과</th>' : '<th>진행</th>'}</tr></thead>
          <tbody>${items.map((x) => `
            <tr class="te-row-link" data-request="${x.request.request_id}">
              <td>#${x.request.document_id}</td><td>${esc(names[x.request.template_id])}</td><td>${esc(x.request.subject || '-')}</td>
              <td>${x.request.work_date}</td><td>${x.request.attempt}</td>
              <td>staff ${x.request.requested_by}<div class="te-hint">${T.fmtDateTime(x.request.requested_at)}</div></td>
              <td>${x.slot_no}${x.label ? ` · ${esc(x.label)}` : ''}</td>
              ${done ? `<td>${badge(SLOT, x.state)}</td><td>${T.fmtDateTime(x.decided_at)}</td><td>${badge(REQUEST, x.request.status)}</td>`
                : `<td>${x.request.progress.approved}/${x.request.progress.total}</td>`}
            </tr>`).join('')}</tbody>
        </table>
        <div class="te-pager">
          <button class="btn btn-secondary btn-sm" id="iPrev" ${page <= 1 ? 'disabled' : ''}>‹</button>
          <span>${page} / ${pages}</span>
          <button class="btn btn-secondary btn-sm" id="iNext" ${page >= pages ? 'disabled' : ''}>›</button>
          <span>총 ${total}건 · ${size}건씩</span>
        </div>`;
      body.querySelectorAll('[data-request]').forEach((tr) => tr.addEventListener('click', () => this.showRequest(Number(tr.dataset.request), { from: 'inbox' })));
      body.querySelector('#iPrev').addEventListener('click', () => { f.page -= 1; this.loadInbox(); });
      body.querySelector('#iNext').addEventListener('click', () => { f.page += 1; this.loadInbox(); });
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
              <div class="card-title">${badge(REQUEST, req.status)}</div>
              <div class="page-actions">
                <button class="btn btn-secondary btn-sm" id="rqInbox">결재함으로</button>
                <button class="btn btn-secondary btn-sm" id="rqDoc">문서 열기</button>
              </div>
            </div>
            ${changed ? `<div class="te-status-note">현재 문서는 이 회차 이후 수정되었습니다 (v${req.document_version} → v${current.data.version}). <button class="btn btn-secondary btn-sm" id="rqDoc2">문서 열기</button></div>` : ''}
            ${!current.ok && current.status === 404 ? '<div class="te-status-note">현재 문서를 찾을 수 없습니다(삭제되었을 수 있습니다). 아래는 상신 당시 내용입니다.</div>' : ''}
            <div class="te-meta">
              <span>${esc(template.name)} v${esc(template.version)}</span><span>대상 <b>${esc(req.subject || '-')}</b></span><span>작업일 <b>${req.work_date}</b></span>
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
            </div>
          </div>
        </div>`;
      T.bindTopBar(root, () => this.showRequest(requestId, origin));
      const openDoc = () => T.open('temp-doc', { documentId: req.document_id });
      root.querySelector('#rqInbox').addEventListener('click', () => (origin.from === 'doc' ? T.open('temp-approval') : this.showInbox()));
      root.querySelector('#rqDoc').addEventListener('click', origin.from === 'doc' ? back : openDoc);
      root.querySelector('#rqDoc2')?.addEventListener('click', origin.from === 'doc' ? back : openDoc);
      bindMyLine(root, req, () => this.showRequest(requestId, origin));
    },
  };

  T.register('temp-approval', Approval);
  window.TempEntryApproval = Approval;
})();
