// =============================================
// P16 ADM-SC-03 문서 권한 (p16-s1-screens.md 5장 — P14 ROLE-SC-01 역할 보기 자리, 페이지 키 role-view 그대로)
// API: ADM-A09 GET admin/roles · A10 PUT admin/roles · A11 GET admin/history?target=roles (p16-s2-spec 4장)
// - 저장 = 화면 전체 한 번(팀장 + 바꾼 양식들의 담당자·작성 권한자), 전체 버전 조건부(R32) — 충돌이면 합치지 않고 다시 읽음
// - 결재 칸 구성(slots·labels)은 보기만(R31). 새로 넣는 사람은 활성 직원만(R33), 이미 있던 비활성 직원은 그대로 둘 수 있음
// - 저장 즉시 다음 작성·상신·결재부터(R36). 저장 뒤 화면 공통 역할 캐시 다시 읽기(R52)
// - 저장 안 한 변경 + 이탈(사이드바·머리 현재 사용자·새로고침)이면 확인 창(S1 Q4 a)
// =============================================
(function () {
  const T = window.TempEntry;
  const A = window.TempEntryAdmin;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);
  const SLOTS = { owner: ['owner'], owner_leader: ['owner', 'leader'], leader: ['leader'], none: [] };
  const SLOT_TEXT = { owner: '담당자만', owner_leader: '담당자 + HACCP팀장', leader: 'HACCP팀장만', none: '결재 없음' };
  const ROLE_TEXT = { owner: '담당자', writer: '작성 권한자', leader: 'HACCP팀장' };
  const sameSet = (a, b) => a.length === b.length && a.every((x) => b.includes(x));

  const Roles = {
    title: '문서 권한',
    root: null,

    start(root) {
      this.root = root;
      this.guard();
      this.load();
    },

    // ---------- 저장 안 한 변경 확인(master.js guard와 같은 방식) ----------
    dirty() {
      return !!(this.data && this.root && document.body.contains(this.root) && document.querySelector('#roEditor') && this.changes().length);
    },

    async leave() {
      if (!this.dirty()) return true;
      return T.confirm('저장 안 된 변경', '저장하지 않은 문서 권한 변경이 있습니다. 나갈까요?', '나가기', 'btn-danger');
    },

    guard() {
      const RO = this;
      if (typeof App !== 'undefined' && !App._roGuard) {  // eslint-disable-line no-undef — 시제품 app.js의 const App
        const original = App.navigate;
        App._roGuard = true;
        let seq = 0;
        App.navigate = async function (page, updateNav = true, fromHistory = false) {
          const mine = ++seq;
          if (!fromHistory && RO.dirty()) {
            const ok = await RO.leave();
            if (mine !== seq || !ok) return undefined;
            RO.data = null;  // 나가기로 함 — 다시 묻지 않음
          }
          return original.call(this, page, updateNav, fromHistory);
        };
      }
      if (!this._unload) {
        this._unload = (e) => { if (this.dirty()) { e.preventDefault(); e.returnValue = ''; } };
        window.addEventListener('beforeunload', this._unload);
      }
    },

    // ---------- 읽기 ----------
    async load() {
      this.data = null;
      this.confirming = false;
      this.conflict = null;
      this.error = null;
      this.root.innerHTML = `
        <div class="fade-in" id="teRoles">
          ${this.top()}
          <div class="card" id="roBody"><table class="data-table"><tbody>${'<tr class="te-skeleton"><td>.</td><td>.</td><td>.</td><td>.</td></tr>'.repeat(4)}</tbody></table></div>
        </div>`;
      this.bindTop();
      const body = this.root.querySelector('#roBody');
      const r = await api.get('admin/roles');
      if (!this.root.contains(body)) return;
      if (!r.ok) {
        body.innerHTML = `<div class="te-error-box">${esc(T.errorText(r))} <button class="btn btn-secondary btn-sm" id="roRetry">다시 시도</button></div>`;
        body.querySelector('#roRetry').addEventListener('click', () => this.load());
        return;
      }
      this.data = r.data;
      this.people = {};
      const keep = (p) => { this.people[p.id] = p; };
      Object.values(T.people || {}).forEach(keep);
      r.data.leaders.forEach(keep);
      r.data.forms.forEach((f) => { f.owners.forEach(keep); f.writers.forEach(keep); });
      this.edit = {
        leaders: r.data.leaders.map((p) => p.id),
        forms: Object.fromEntries(r.data.forms.map((f) => [f.type_code, { owner: f.owners.map((p) => p.id), writer: f.writers.map((p) => p.id) }])),
      };
      this.draw();
    },

    top() {
      return T.topBar('문서 권한', 'HACCP팀장 · 양식별 담당자·작성 권한자 — 저장하면 다음 작성·상신·결재부터 적용', null, { temp: false });
    },

    bindTop() {
      // 머리 현재 사용자를 바꾸면 다시 그림 — 저장 안 한 변경은 그대로 둔다(편집은 사용자와 무관)
      T.bindTopBar(this.root, () => { if (this.data) this.draw(); else this.load(); });
    },

    // ---------- 바뀐 곳 ----------
    original() {
      const d = this.data;
      return {
        leaders: d.leaders.map((p) => p.id),
        forms: Object.fromEntries(d.forms.map((f) => [f.type_code, { owner: f.owners.map((p) => p.id), writer: f.writers.map((p) => p.id) }])),
      };
    },

    changes() {
      if (!this.data) return [];
      const o = this.original();
      const out = [];
      const diff = (key, label, before, after) => {
        const added = after.filter((x) => !before.includes(x));
        const removed = before.filter((x) => !after.includes(x));
        if (added.length || removed.length) out.push({ key, label, added, removed });
      };
      diff('leaders', 'HACCP팀장', o.leaders, this.edit.leaders);
      this.data.forms.forEach((f) => {
        ['owner', 'writer'].forEach((role) => diff(`${f.type_code}.${role}`, `${f.type_code} ${ROLE_TEXT[role]}`, o.forms[f.type_code][role], this.edit.forms[f.type_code][role]));
      });
      return out;
    },

    isActive(id) {
      const p = this.people[id];
      return !!p && p.is_active !== false;
    },

    // 화면 경고(저장은 됨 — R35): 활성 보유자 0명인 칸
    formWarnings(f) {
      const slots = SLOTS[f.slots] || [];
      const out = [];
      const owners = this.edit.forms[f.type_code].owner.filter((id) => this.isActive(id));
      const leaders = this.edit.leaders.filter((id) => this.isActive(id));
      if (slots.includes('owner') && !owners.length) out.push('담당자 0명 → 상신 막힘');
      if (slots.includes('leader') && !leaders.length) out.push('HACCP팀장 0명 → 상신 막힘');
      if (!slots.length && f.slots === 'none' && !owners.length) out.push('담당자 0명 → 작성은 HACCP팀장·작성 권한자만');
      return out;
    },

    // ---------- 그리기 ----------
    chips(ids, key, before) {
      const list = ids.map((id) => A.chip(this.people[id] || { id, name: `#${id}`, staff_code: '', is_active: false }, { removable: true, added: !before.includes(id) })).join(' ');
      const choices = (T.staff || []).filter((p) => !ids.includes(p.id));
      const add = choices.length
        ? `<select class="form-control te-ad-pick" data-add="${esc(key)}" aria-label="추가"><option value="">+ 추가</option>${choices.map((p) => `<option value="${p.id}">${esc(`${p.name} ${p.staff_code}`)}</option>`).join('')}</select>`
        : '';
      return `<div class="te-ad-chips" data-chips="${esc(key)}">${list || '<span class="te-hint">없음</span>'} ${add}</div>`;
    },

    draw() {
      const d = this.data;
      const o = this.original();
      const changes = this.changes();
      const setup = d.setup || { blocked_forms: [] };
      const blocked = d.forms.filter((f) => this.formWarnings(f).some((w) => w.includes('상신 막힘')));
      const empty = !this.edit.leaders.length && Object.values(this.edit.forms).every((f) => !f.owner.length && !f.writer.length);
      // R38: 빈 권한 경고 — 화면 위(편집 중 값 기준)
      const setupWarn = blocked.length || empty
        ? `<div class="te-notice" id="roSetup"><strong>문서 권한에 비어 있는 곳이 있습니다 — 상신할 수 없는 양식 ${blocked.length}개</strong>${blocked.length ? `<div class="te-hint">${blocked.map((f) => esc(f.type_code)).join(', ')}</div>` : ''}${empty ? '<div class="te-hint">담당자·HACCP팀장이 한 명도 지정되지 않았습니다.</div>' : ''}</div>`
        : '';
      const activeLeaders = this.edit.leaders.filter((id) => this.isActive(id)).length;
      const rows = d.forms.map((f) => {
        const warn = this.formWarnings(f);
        const changed = changes.some((c) => c.key.startsWith(`${f.type_code}.`));
        const renamed = f.labels && f.labels.owner && f.labels.owner !== '담당자' ? `<div class="te-hint">칸 이름: 담당자 → ${esc(f.labels.owner)}</div>` : '';
        const renamedL = f.labels && f.labels.leader && f.labels.leader !== 'HACCP팀장' ? `<div class="te-hint">칸 이름: HACCP팀장 → ${esc(f.labels.leader)}</div>` : '';
        return `<tr data-form="${esc(f.type_code)}" class="${changed ? 'te-ad-changed' : ''}">
          <td><b>${esc(f.type_code)}</b> ${esc(f.name)}</td>
          <td><span class="te-ad-chip-line" title="바꾸려면 개발 요청">${esc(SLOT_TEXT[f.slots] || '설정 없음')}</span>${renamed}${renamedL}</td>
          <td>${this.chips(this.edit.forms[f.type_code].owner, `${f.type_code}.owner`, o.forms[f.type_code].owner)}</td>
          <td>${this.chips(this.edit.forms[f.type_code].writer, `${f.type_code}.writer`, o.forms[f.type_code].writer)}</td>
          <td class="te-nowrap">${warn.length ? warn.map((w) => `<div class="te-pl-chip-warn">${esc(w)}</div>`).join('') : '<span class="te-pl-chip-ok">정상</span>'}</td>
        </tr>`;
      }).join('');
      const leadersChanged = changes.some((c) => c.key === 'leaders');
      this.root.querySelector('#teRoles').innerHTML = `
        ${this.top()}
        <div id="roEditor">
          <div class="te-ad-head"><b>버전 ${d.version}</b>
            <span class="te-hint">직원 등록·이름 수정·비활성은 시스템 › 설정의 직원 관리에서 합니다</span>
            <a href="#" class="te-role-link" id="roStaffLink">직원 관리 ↗</a>
            <span class="te-pl-grow"></span><button class="btn btn-secondary btn-sm" id="roHist">이력</button></div>
          ${this.conflict ? `<div class="te-ad-danger" id="roConflict">다른 사람이 먼저 문서 권한을 바꿨습니다${this.conflict.version ? `(버전 ${this.conflict.version})` : ''}. <button class="btn btn-secondary btn-sm" id="roReload">새 값 보기</button> <span class="te-hint">내 변경은 버리고 다시 읽습니다</span></div>` : ''}
          ${this.confirming ? this.confirmHtml(changes) : ''}
          ${setupWarn}
          <div class="card${leadersChanged ? ' te-ad-changed-card' : ''}" id="roLeaderCard">
            <div class="card-title">HACCP팀장</div>
            ${this.chips(this.edit.leaders, 'leaders', o.leaders)}
            ${activeLeaders ? '' : '<div class="te-ad-err" id="roNoLeader">활성 HACCP팀장이 없습니다 — 팀장 칸이 있는 양식은 상신할 수 없습니다.</div>'}
          </div>
          <div class="card">
            <div class="te-table-wrap"><table class="data-table" id="roForms">
              <thead><tr><th>양식</th><th>결재 칸 구성</th><th>담당자</th><th title="작성·상신 — 결재 칸 후보 아님">작성 권한자</th><th>상태</th></tr></thead>
              <tbody>${rows || '<tr><td colspan="5" class="te-hint">활성 양식이 없습니다.</td></tr>'}</tbody>
            </table></div>
            <div class="te-hint">점선·취소선 = 비활성 직원(효과 없음 — 남아 있음) · 초록 테두리 = 이번에 넣은 사람 · 왼쪽 노란 줄 = 바뀐 줄. 담당자와 작성 권한자는 겹쳐도 됩니다.</div>
          </div>
          ${changes.length ? `<div class="te-ad-bar" id="roBar"><span>바뀐 곳 <b>${changes.length}</b>개 · 저장하기 전에는 적용되지 않습니다</span>
            <span class="te-pl-grow"></span><button class="btn btn-secondary btn-sm" id="roUndo">되돌리기</button>
            <button class="btn btn-primary btn-sm" id="roSave"${!api.staffId || this.confirming ? ' disabled' : ''} title="${api.staffId ? '' : '현재 사용자를 선택하세요'}">저장…</button></div>` : ''}
          ${this.error ? `<div class="te-error-box" id="roError">${esc(this.error)}</div>` : ''}
        </div>`;
      this.bindTop();
      this.bind();
    },

    confirmHtml(changes) {
      const name = (id) => (this.people[id] ? this.people[id].name : `#${id}`);
      const lines = changes.map((c) => `<li>${esc(c.label)} ${c.added.map((id) => `<span class="te-ad-plus">+ ${esc(name(id))}</span>`).join(' ')} ${c.removed.map((id) => `<span class="te-ad-minus">− ${esc(name(id))}</span>`).join(' ')}</li>`).join('');
      const warns = this.data.forms.flatMap((f) => this.formWarnings(f).map((w) => `${f.type_code}: ${w}`));
      return `<div class="te-ad-confirm" id="roConfirm"><b>이대로 저장할까요?</b>
        <ul>${lines}</ul>
        ${warns.length ? `<div class="te-ad-warn">경고(저장은 됩니다)<ul>${warns.map((w) => `<li>${esc(w)}</li>`).join('')}</ul></div>` : ''}
        <div class="te-hint">이미 상신된 결재 요청은 상신 때 정한 결재 후보 그대로입니다.</div>
        <div class="te-ic-actions"><button class="btn btn-primary btn-sm" id="roSaveYes"${this.saving || !api.staffId ? ' disabled' : ''}>${this.saving ? '저장 중…' : '저장'}</button>
          <button class="btn btn-secondary btn-sm" id="roSaveNo"${this.saving ? ' disabled' : ''}>다시 고치기</button>
          ${api.staffId ? '' : '<span class="te-ad-err" id="roNoUser">현재 사용자를 선택하세요 — 선택 전에는 저장할 수 없습니다.</span>'}</div></div>`;
    },

    list(key) {
      if (key === 'leaders') return this.edit.leaders;
      const [type, role] = key.split('.');
      return this.edit.forms[type][role];
    },

    bind() {
      const $ = (s) => this.root.querySelector(s);
      this.root.querySelectorAll('[data-add]').forEach((sel) => sel.addEventListener('change', () => {
        const id = Number(sel.value);
        if (!id) return;
        this.list(sel.dataset.add).push(id);
        this.confirming = false;
        this.error = null;
        this.draw();
      }));
      this.root.querySelectorAll('[data-chips]').forEach((box) => box.addEventListener('click', (ev) => {
        const x = ev.target.closest('[data-remove]');
        if (!x) return;
        const list = this.list(box.dataset.chips);
        list.splice(list.indexOf(Number(x.dataset.remove)), 1);
        this.confirming = false;
        this.error = null;
        this.draw();
      }));
      $('#roStaffLink').addEventListener('click', (ev) => { ev.preventDefault(); App.navigate('settings'); });  // eslint-disable-line no-undef
      $('#roHist').addEventListener('click', () => this.history());
      $('#roReload')?.addEventListener('click', () => this.load());
      $('#roUndo')?.addEventListener('click', () => { this.edit = this.original(); this.confirming = false; this.error = null; this.draw(); });
      $('#roSave')?.addEventListener('click', () => { this.confirming = true; this.error = null; this.draw(); $('#roConfirm')?.scrollIntoView({ block: 'nearest' }); });
      $('#roSaveNo')?.addEventListener('click', () => { this.confirming = false; this.draw(); });
      $('#roSaveYes')?.addEventListener('click', () => this.save());
    },

    async save() {
      if (this.saving || !api.staffId) return;  // 확인 상자를 연 뒤 현재 사용자를 비운 경우(D-272 B2)
      const changes = this.changes();
      const forms = {};
      changes.filter((c) => c.key !== 'leaders').forEach((c) => {
        const type = c.key.split('.')[0];
        forms[type] = { owners: this.edit.forms[type].owner, writers: this.edit.forms[type].writer };
      });
      const body = { expected_version: this.data.version, leaders: this.edit.leaders, forms };
      this.saving = true;
      this.draw();
      const r = await api.put('admin/roles', body);
      this.saving = false;
      if (!document.body.contains(this.root)) return;
      if (!r.ok) {
        this.confirming = false;
        if (r.status === 409) {
          const now = await api.get('admin/roles');
          this.conflict = { version: now.ok ? now.data.version : null };
        } else {
          this.error = A.errorText(r);
        }
        this.draw();
        return;
      }
      const warn = (r.data.warnings || []).filter((w) => w.code === 'R-W5').length;
      T.toast(`저장했습니다(버전 ${r.data.version}) — 다음 작성·상신·결재부터 적용${warn ? ` · 상신할 수 없는 양식 경고 ${warn}건` : ''}`);
      await A.refreshPeople();
      this.load();
    },

    async history() {
      const r = await api.get('admin/history?target=roles');
      if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
      const names = (ids) => (ids && ids.length ? ids.map((id) => T.person(id)).join(', ') : '(없음)');
      const rows = r.data.items.map((x) => {
        let what;
        let change;
        if (x.action === 'import') {
          const a = x.after || {};
          what = '가져오기';
          change = `roles.json → DB(양식 ${(a.forms || []).length}개, 팀장 ${a.leaders || 0}명${a.replace ? ', 바꾸기' : ''})`;
        } else {
          what = x.target === 'role_leader' ? 'HACCP팀장' : ROLE_TEXT[(x.after || {}).role] || '';
          change = `${names((x.before || {}).staff_ids)} → ${names((x.after || {}).staff_ids)}`;
        }
        return `<tr><td>${esc(T.fmtDateTime(x.at))}</td><td>${esc(A.actorName(x))}</td><td>${esc(x.label || '')}</td><td>${esc(what)}</td><td>${esc(change)}</td></tr>`;
      }).join('');
      A.historyModal('문서 권한', ['시각', '누가', '대상', '역할', '전 → 후'], rows);
    },
  };

  T.register('role-view', Roles);
  window.TempEntryRoles = Roles;
})();
