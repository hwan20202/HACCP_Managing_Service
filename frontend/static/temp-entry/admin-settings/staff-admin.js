// =============================================
// P16 ADM-SC-02 직원 관리 (시스템 › 설정 카드 — p16-s1-screens.md 4장) · ADM-SC-05 비활성 영향(4.5)
// API: A03 GET admin/staff · A04 next-code · A05 POST · A06 PATCH · A07 impact · A08 active · A11 history
// 시제품 app.js가 설정 화면을 그린 뒤 직원 카드 자리(#settingsStaff)에 StaffAdmin.mount(card)로 붙인다(R50).
// 현재 사용자는 카드 머리 선택 상자(T.topBar) — 바꾸면 카드를 다시 그림. 쓰기는 X-CSRFToken(R71).
// 등록·이름·비활성 뒤 화면 공통 직원·역할 캐시 다시 읽기(R52).
// =============================================
(function () {
  const T = window.TempEntry;
  const A = window.TempEntryAdmin;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);
  const NAME_MAX = 40;
  const CODE_MAX = 20;
  const STATES = { active: '활성', inactive: '비활성', all: '전체' };

  function rolesCell(p) {
    const r = p.roles || { is_leader: false, owner_of: [], writer_of: [] };
    const parts = [];
    if (r.is_leader) parts.push('<span class="te-pl-chip-link" title="HACCP팀장">HACCP팀장</span>');
    if (r.owner_of.length) parts.push(`<span class="te-pl-chip-info" title="${esc(r.owner_of.join(', '))}">담당 ${r.owner_of.length}양식</span>`);
    if (r.writer_of.length) parts.push(`<span class="te-ad-chip-line" title="${esc(r.writer_of.join(', '))}">작성 ${r.writer_of.length}양식</span>`);
    if (!parts.length) return '<span class="te-hint">역할 없음</span>';
    return `${parts.join(' ')}${p.is_active ? '' : ' <span class="te-hint">(효과 없음)</span>'}`;
  }

  const StaffAdmin = {
    card: null,
    filters: { q: '', state: 'active' },
    seq: 0,

    async mount(card) {
      this.card = card;
      this.adding = null;
      this.renaming = null;
      this.impact = null;
      this.busy = false;
      card.innerHTML = '<div class="te-empty">불러오는 중…</div>';
      // 클릭·입력은 카드에 한 번만 위임(입력 중 다시 그리지 않음 — 한글 입력 조합이 끊기지 않게)
      card.addEventListener('click', (ev) => this.onClick(ev));
      card.addEventListener('input', (ev) => this.onInput(ev));
      card.addEventListener('keydown', (ev) => this.onKey(ev));
      await T.loadStaff();
      if (this.card !== card || !document.body.contains(card)) return;
      this.load();
    },

    async load() {
      const mine = ++this.seq;
      const r = await api.get('admin/staff?state=all');
      if (mine !== this.seq || !document.body.contains(this.card)) return;
      this.items = r.ok ? r.data.items : null;
      this.error = r.ok ? null : r;
      this.draw();
    },

    shown() {
      const f = this.filters;
      const q = f.q.toLowerCase();
      return (this.items || []).filter((p) => (f.state === 'all' || (f.state === 'active') === p.is_active)
        && (!q || p.name.toLowerCase().includes(q) || p.staff_code.toLowerCase().includes(q)))
        .sort((a, b) => a.staff_code.localeCompare(b.staff_code, 'ko', { numeric: true }));  // S1 4.2 코드순(D-272 B1)
    },

    draw() {
      const card = this.card;
      const top = T.topBar('직원 관리', '등록 · 이름 수정 · 비활성 — 바꾼 것은 모두 이력으로 남습니다', null, { temp: false });
      if (!this.items) {
        card.innerHTML = `<div id="saRoot">${top}<div class="te-error-box" id="saError">${esc(T.errorText(this.error))}
          <div>직원 목록을 읽지 못했습니다. <button class="btn btn-secondary btn-sm" id="saRetry">다시 시도</button></div></div></div>`;
        T.bindTopBar(card, () => this.draw());
        return;
      }
      const all = this.items;
      const active = all.filter((p) => p.is_active).length;
      const counts = { active, inactive: all.length - active, all: all.length };
      const f = this.filters;
      const noStaff = !api.staffId;
      card.innerHTML = `<div id="saRoot">${top}
        <div class="te-ad-head">
          <b id="saCount">직원 관리 ${all.length}명</b>
          <a href="#" class="te-role-link" data-role-view id="saRolesLink">문서 권한 ↗</a>
          <span class="te-pl-grow"></span>
          <input class="form-control te-ad-search" id="saQ" value="${esc(f.q)}" placeholder="이름·코드" aria-label="직원 검색">
          <div class="te-ic-seg" role="group" aria-label="상태">${Object.keys(STATES).map((k) => `<button type="button" class="${f.state === k ? 'on' : ''}" data-sa-state="${k}">${STATES[k]} ${counts[k]}</button>`).join('')}</div>
          <button class="btn btn-primary btn-sm" id="saAdd"${noStaff || this.adding ? ' disabled' : ''}>+ 직원</button>
          <button class="btn btn-secondary btn-sm" id="saHistAll">전체 이력</button>
        </div>
        ${this.adding ? this.addHtml() : ''}
        <div class="te-table-wrap"><table class="data-table" id="saTable"><thead><tr><th>코드</th><th>이름</th><th>상태</th><th>문서 권한</th><th>등록일</th><th></th></tr></thead>
          <tbody>${this.rowsHtml()}</tbody></table></div>
      </div>`;
      T.bindTopBar(card, () => { this.renaming = null; this.impact = null; this.draw(); });
    },

    rowsHtml() {
      const noStaff = !api.staffId;
      return this.shown().map((p) => this.rowHtml(p, noStaff)).join('')
        || '<tr><td colspan="6" class="te-empty">조건에 맞는 직원이 없습니다.</td></tr>';
    },

    rowHtml(p, noStaff) {
      const editing = this.renaming && this.renaming.id === p.id;
      const open = this.impact && this.impact.id === p.id;
      const name = editing
        ? `<input class="form-control te-ad-rename" id="saRename" maxlength="${NAME_MAX}" value="${esc(this.renaming.value)}" aria-label="새 이름">
           <div id="saRenameMsg">${this.renameMsgs(p.id)}</div>`
        : esc(p.name);
      const acts = editing
        ? `<button class="btn btn-secondary btn-sm" data-sa-rename-cancel>취소</button> <button class="btn btn-primary btn-sm" data-sa-rename-save${this.busy ? ' disabled' : ''}>저장</button>`
        : `<button class="btn btn-secondary btn-sm" data-sa-rename="${p.id}"${noStaff ? ' disabled' : ''}>이름 수정</button>
           ${p.is_active
             ? `<button class="btn btn-secondary btn-sm" data-sa-off="${p.id}"${noStaff ? ' disabled' : ''}>${open ? '닫기' : '비활성'}</button>`
             : `<button class="btn btn-secondary btn-sm" data-sa-on="${p.id}"${noStaff || this.busy ? ' disabled' : ''}>다시 활성</button>`}
           <button class="btn btn-secondary btn-sm" data-sa-hist="${p.id}">이력</button>`;
      return `<tr data-staff="${p.id}" class="${p.is_active ? '' : 'te-ic-inactive'}">
          <td class="mono">${esc(p.staff_code)}</td><td>${name}</td>
          <td>${p.is_active ? '<span class="te-pl-chip-ok">활성</span>' : '<span class="badge badge-neutral">비활성</span>'}</td>
          <td>${rolesCell(p)}</td><td class="te-nowrap">${esc((p.created_at || '').slice(0, 10))}</td>
          <td class="te-ms-acts">${acts}</td></tr>
        ${open ? `<tr class="te-ic-edit-row"><td colspan="6">${this.impactHtml(p)}</td></tr>` : ''}`;
    },

    sameName(name, exceptId) {
      const v = (name || '').trim();
      if (!v) return '';
      const same = (this.items || []).filter((p) => p.name === v && p.id !== exceptId);
      return same.length ? `같은 이름의 직원이 있습니다: ${same.map((p) => `${p.name} ${p.staff_code}`).join(', ')} — 동명이인이면 그대로 저장하세요` : '';
    },

    addState() {
      const a = this.adding;
      const code = a.code.trim();
      const dup = !!code && (this.items || []).some((p) => p.staff_code.toLowerCase() === code.toLowerCase());
      return { dup, ok: !!a.name.trim() && !!code && !dup && !this.busy };
    },

    addMsgs() {
      const a = this.adding;
      const { dup } = this.addState();
      const same = this.sameName(a.name);
      return `${dup ? '<div class="te-ad-err" id="saDup">이미 쓰는 코드입니다(비활성 직원 코드 포함).</div>' : ''}
        ${same ? `<div class="te-ad-warn" id="saSame">${esc(same)}</div>` : ''}
        ${a.error ? `<div class="te-ad-err" id="saAddErr">${esc(a.error)}</div>` : ''}`;
    },

    addHtml() {
      const a = this.adding;
      const { dup, ok } = this.addState();
      return `<div class="te-ad-add" id="saAddRow">
        <div class="form-group"><label class="form-label" for="saName">이름</label><input class="form-control" id="saName" maxlength="${NAME_MAX}" value="${esc(a.name)}"></div>
        <div class="form-group"><label class="form-label" for="saCode">코드 <span class="te-hint">등록 뒤 못 바꿈</span></label><input class="form-control mono${dup ? ' te-ad-bad' : ''}" id="saCode" maxlength="${CODE_MAX}" value="${esc(a.code)}"></div>
        <button class="btn btn-primary btn-sm" id="saAddSave"${ok ? '' : ' disabled'}>${this.busy ? '등록 중…' : '등록'}</button>
        <button class="btn btn-secondary btn-sm" id="saAddCancel">취소</button>
        <div class="te-ad-msgs" id="saAddMsg">${this.addMsgs()}</div>
      </div>`;
    },

    // 입력 중에는 이 부분만 바꿈(다시 그리지 않음)
    refreshAdd() {
      const $ = (sel) => this.card.querySelector(sel);
      if (!this.adding || !$('#saAddRow')) return;
      const { dup, ok } = this.addState();
      $('#saAddSave').disabled = !ok;
      $('#saCode').classList.toggle('te-ad-bad', dup);
      $('#saAddMsg').innerHTML = this.addMsgs();
    },

    renameMsgs(id) {
      const e = this.renaming;
      const same = this.sameName(e.value, id);
      return `${same ? `<div class="te-ad-warn">${esc(same)}</div>` : ''}${e.error ? `<div class="te-ad-err">${esc(e.error)}</div>` : ''}`;
    },

    impactHtml(p) {
      const s = this.impact;
      if (s.loading) return '<div class="te-hint" id="saImpact">영향을 확인하는 중…</div>';
      if (s.error) return `<div class="te-error-box" id="saImpact">${esc(s.error)} <button class="btn btn-secondary btn-sm" data-sa-impact-retry>다시 시도</button></div>`;
      const d = s.data;
      const r = d.roles;
      const items = [];
      if (r.is_leader) items.push('HACCP팀장 — 결재 칸 후보에서 빠짐');
      if (r.owner_of.length) items.push(`담당 ${r.owner_of.length}양식(${r.owner_of.join(', ')})`);
      if (r.writer_of.length) items.push(`작성 권한 ${r.writer_of.length}양식(${r.writer_of.join(', ')})`);
      const shared = d.pending_approvals - d.sole_approvals.length;
      if (shared > 0) items.push(`결재 대기 칸 ${shared}건 — 이미 상신된 결재는 다른 후보가 처리`);
      if (d.pending_checks) items.push(`개선조치 확인 대기 ${d.pending_checks}건 — HACCP팀장이 확인 가능`);
      if (d.inspector_docs) items.push(`지정 점검자인 작성중 문서 ${d.inspector_docs}건 — 점검자 다시 지정 필요`);
      const leadersAfter = d.active_leaders - (r.is_leader && p.is_active ? 1 : 0);
      let sole = '';
      if (d.sole_approvals.length) {
        const stuck = d.sole_approvals.some((x) => !x.requester_active || x.requested_by === p.id) || leadersAfter <= 0;
        const docs = d.sole_approvals.map((x) => `문서 #${x.document_id} ${x.type_code}${x.subject ? ` ${x.subject}` : ''}(${x.slot_label || ''})`).join(', ');
        sole = `<div class="te-ad-danger" id="saSole"><b>이 사람만 처리할 수 있는 결재 ${d.sole_approvals.length}건</b> — ${esc(docs)}
          <div>상신 취소 → <a href="#" data-role-view>문서 권한 ↗</a>에 새 담당자 → 재상신</div>
          ${stuck ? `<ol class="te-ad-steps" id="saRecover"><li><a href="#" data-role-view>문서 권한 ↗</a>에서 활성 직원을 HACCP팀장으로 지정</li><li>화면 머리 "현재 사용자"에서 그 팀장 선택</li><li>문서에서 상신 취소</li><li>새 담당자 지정</li><li>재상신</li></ol>` : ''}</div>`;
      }
      const EFFECT = { submit_blocked: '상신 막힘', write_leader_only: '작성은 HACCP팀장·작성 권한자만' };
      const orphan = d.orphaned.length ? `<div class="te-ad-danger" id="saOrphan"><b>처리할 사람이 없어지는 곳</b><ul>${d.orphaned.map((o) => (o.role === 'leader'
        ? `<li>HACCP팀장 0명 → 팀장 칸이 있는 양식 상신 막힘${o.forms && o.forms.length ? ` <span class="te-hint">(${esc(o.forms.join(', '))})</span>` : ''}</li>`
        : `<li>${esc(o.type_code)} ${esc(o.name)}: 담당자 0명 → ${esc(EFFECT[o.effect] || o.effect)}</li>`)).join('')}</ul></div>` : '';
      const nothing = !items.length && !sole && !orphan ? '<div class="te-ad-ok" id="saNothing">맡은 역할·처리 대기가 없습니다.</div>' : '';
      const me = d.is_current_user ? '<div class="te-notice" id="saMe"><b>지금 현재 사용자입니다</b> — 비활성하면 현재 사용자가 비워지고 "현재 사용자를 선택하세요"가 나옵니다.</div>' : '';
      const last = d.last_active ? '<div class="te-ad-err" id="saLast">마지막 활성 직원은 비활성할 수 없습니다.</div>' : '';
      return `<div class="te-ad-impact" id="saImpact">
        <div class="te-ad-impact-title">${esc(p.name)} <span class="te-person-code">${esc(p.staff_code)}</span> 비활성 영향</div>
        ${items.length ? `<ul class="te-ad-list">${items.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
        ${sole}${orphan}${nothing}${me}
        <div class="te-hint">문서 권한은 지우지 않습니다(다시 활성하면 되살아남). 비활성 직원은 사람 선택 목록에서 빠집니다.</div>
        ${s.error2 ? `<div class="te-ad-err">${esc(s.error2)}</div>` : ''}
        ${last}
        <div class="te-ic-actions"><button class="btn btn-secondary btn-sm" data-sa-impact-cancel>취소</button>
          <button class="btn btn-danger btn-sm" id="saOffYes"${d.last_active || this.busy ? ' disabled' : ''}>${this.busy ? '처리 중…' : '비활성'}</button></div>
      </div>`;
    },

    find(id) {
      return (this.items || []).find((p) => p.id === Number(id));
    },

    onClick(ev) {
      const el = ev.target.closest('button, [data-sa-state]');
      if (!el || !this.card.contains(el) || el.disabled) return;
      const d = el.dataset;
      if (d.saState) { this.filters.state = d.saState; this.draw(); return; }
      if (el.id === 'saHistAll') { this.history(null, '전체 직원'); return; }
      if (el.id === 'saAdd') { this.startAdd(); return; }
      if (el.id === 'saAddCancel') { this.adding = null; this.draw(); return; }
      if (el.id === 'saAddSave') { this.create(); return; }
      if (el.id === 'saRetry') { this.load(); return; }
      if (el.id === 'saOffYes') { this.setActive(this.find(this.impact.id), false); return; }
      if (d.saRename) {
        const p = this.find(d.saRename);
        this.renaming = { id: p.id, value: p.name, error: null };
        this.draw();
        this.focusEnd('#saRename');
        return;
      }
      if ('saRenameCancel' in d) { this.renaming = null; this.draw(); return; }
      if ('saRenameSave' in d) { this.rename(); return; }
      if (d.saOff) {
        const id = Number(d.saOff);
        if (this.impact && this.impact.id === id) { this.impact = null; this.draw(); return; }
        this.openImpact(id);
        return;
      }
      if (d.saOn) { this.setActive(this.find(d.saOn), true); return; }
      if (d.saHist) { const p = this.find(d.saHist); this.history(p.id, `${p.name}(${p.staff_code})`); return; }
      if ('saImpactCancel' in d) { this.impact = null; this.draw(); return; }
      if ('saImpactRetry' in d) this.openImpact(this.impact.id);
    },

    onInput(ev) {
      const t = ev.target;
      if (t.id === 'saQ') {
        this.filters.q = t.value.trim();
        const body = this.card.querySelector('#saTable tbody');
        if (body) body.innerHTML = this.rowsHtml();
      } else if (t.id === 'saName' && this.adding) {
        this.adding.name = t.value; this.adding.error = null; this.refreshAdd();
      } else if (t.id === 'saCode' && this.adding) {
        this.adding.code = t.value; this.adding.error = null; this.refreshAdd();
      } else if (t.id === 'saRename' && this.renaming) {
        this.renaming.value = t.value; this.renaming.error = null;
        const msg = this.card.querySelector('#saRenameMsg');
        if (msg) msg.innerHTML = this.renameMsgs(this.renaming.id);
      }
    },

    onKey(ev) {
      if (ev.isComposing) return;  // 한글 조합 중 Enter
      const t = ev.target;
      if (t.id === 'saCode' && ev.key === 'Enter' && this.addState().ok) this.create();
      if (t.id === 'saRename' && ev.key === 'Enter') this.rename();
      if (t.id === 'saRename' && ev.key === 'Escape') { this.renaming = null; this.draw(); }
    },

    focusEnd(sel) {
      const el = this.card.querySelector(sel);
      if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
    },

    async startAdd() {
      const a = { name: '', code: '', error: null };
      this.adding = a;
      this.draw();
      this.card.querySelector('#saName')?.focus();
      const r = await api.get('admin/staff/next-code');
      if (this.adding !== a || a.code || !r.ok) return;
      a.code = r.data.code;  // 제안 값 미리 채움(S1a Q5 — 고칠 수 있음)
      const code = this.card.querySelector('#saCode');
      if (code) code.value = a.code;
      this.refreshAdd();
    },

    async openImpact(id) {
      const s = { id, loading: true };
      this.impact = s;
      this.draw();
      const r = await api.get(`admin/staff/${id}/impact`);
      if (this.impact !== s) return;
      s.loading = false;
      if (r.ok) s.data = r.data; else s.error = A.errorText(r);
      this.draw();
    },

    async create() {
      const a = this.adding;
      if (!a || this.busy) return;
      this.busy = true;
      this.draw();
      const r = await api.post('admin/staff', { name: a.name, staff_code: a.code });
      this.busy = false;
      if (this.adding !== a) return;
      if (!r.ok) { a.error = A.errorText(r); this.draw(); return; }
      this.adding = null;
      T.toast(`${r.data.staff.name}(${r.data.staff.staff_code}): 등록했습니다 — 사람 선택 목록에 바로 나옵니다`);
      await this.afterWrite();
    },

    async rename() {
      const e = this.renaming;
      if (!e || this.busy) return;
      if (!e.value.trim()) { e.error = '이름을 입력하세요.'; this.draw(); return; }
      this.busy = true;
      this.draw();
      const r = await api.patch(`admin/staff/${e.id}`, { name: e.value });
      this.busy = false;
      if (this.renaming !== e) return;
      if (!r.ok) { e.error = A.errorText(r); this.draw(); return; }
      this.renaming = null;
      T.toast(r.data.changed ? '이름을 바꿨습니다' : '바뀐 이름이 없습니다');
      await this.afterWrite();
    },

    async setActive(p, active) {
      if (!p || this.busy) return;
      this.busy = true;
      this.draw();
      const body = active ? { active: true } : { active: false, confirm_impact: true };
      const r = await api.post(`admin/staff/${p.id}/active`, body);
      this.busy = false;
      if (!r.ok) {
        if (!active && this.impact && this.impact.id === p.id) { this.impact.error2 = A.errorText(r); this.draw(); } else { T.toast(A.errorText(r), 'error'); this.draw(); }
        return;
      }
      this.impact = null;
      T.toast(active ? `${p.name}: 다시 활성 — 남아 있던 역할이 다시 적용됩니다` : `${p.name}: 비활성했습니다`);
      await this.afterWrite();
    },

    async afterWrite() {
      await A.refreshPeople();  // 현재 사용자가 비활성이 되면 core.loadStaff가 비움(R52)
      await this.load();
    },

    async history(staffId, name) {
      const q = new URLSearchParams({ target: 'staff' });
      if (staffId) q.set('target_id', staffId);
      const r = await api.get(`admin/history?${q}`);
      if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
      const show = (v) => {
        if (!v) return '—';
        if ('is_active' in v) return v.is_active ? '활성' : '비활성';
        if ('staff_code' in v) return `${v.name} ${v.staff_code}`;
        return v.name || '—';
      };
      const rows = r.data.items.map((x) => `<tr><td>${esc(T.fmtDateTime(x.at))}</td><td>${esc(A.actorName(x))}</td>
        <td>${esc(x.label || `직원 #${x.target_id}`)}</td><td>${esc(A.STAFF_ACTIONS[x.action] || x.action)}</td>
        <td>${esc(show(x.before))} → <b>${esc(show(x.after))}</b></td></tr>`).join('');
      A.historyModal(name, ['시각', '누가', '직원', '무엇', '전 → 후'], rows);
    },
  };

  window.TempEntryStaffAdmin = StaffAdmin;
})();
