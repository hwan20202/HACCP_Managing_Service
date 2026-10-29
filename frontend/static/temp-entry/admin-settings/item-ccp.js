// =============================================
// P16 ADM-SC-01 품목별 CCP (생산 기준정보 세 번째 탭 — p16-s1-screens.md 3장) · ADM-SC-04 이력 창(6장)
// API: ADM-A01 GET admin/item-ccp · A02 PUT admin/item-ccp/{id} · A11 GET admin/history (p16-s2-spec 4장)
// 누구나 저장(현재 사용자만 있으면 — R27). 쓰기는 X-CSRFToken(api-client가 붙임 — R71).
// 생산 기준정보(master.js)가 탭 본문(#msBody)을 넘겨 부른다: ItemCcp.render(master, body).
// =============================================
(function () {
  const T = window.TempEntry;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);

  const PROCESSES = ['1P', '2B', '3P'];
  const NAMES = { '1P': '쇳가루 제거', '2B': '건조', '3P': '금속검출' };
  const LOGS = { '1P': 'CCP-1P · 쇳가루 제거 모니터링일지', '2B': 'CCP-2B · 건조 모니터링일지', '3P': 'CCP-3P · 금속검출 모니터링일지' };
  const ACTIONS = { set: '품목 설정', default: '기본 따름으로' };
  const list = (ps) => (ps && ps.length ? ps.join('·') : '없음');
  const describe = (v) => (!v ? '—' : v.mode === 'default' ? '기본 따름' : v.processes.length ? `품목 설정 ${list(v.processes)}` : 'CCP 없음');
  const noStaff = () => !api.staffId;
  const same = (a, b) => a.mode === b.mode && a.processes.join() === b.processes.join();

  const ItemCcp = {
    filters: { q: '', only_own: false, include_inactive: false },
    seq: 0,
    open: null,   // 펼친 편집 { item, mode, processes, reason, confirm, conflict, error, saving }

    render(master, body) {
      this.master = master;
      this.body = body;
      this.open = null;
      master.dirty = () => this.isDirty();
      this.load();
    },

    isDirty() {
      const e = this.open;
      return !!e && !same(e, e.item);  // [저장] 활성 조건과 같음 — 사유만으로는 저장할 것이 없음(검토 B4)
    },

    async load() {
      const body = this.body;
      const f = this.filters;
      const q = new URLSearchParams({ q: f.q, only_own: f.only_own ? '1' : '0', include_inactive: f.include_inactive ? '1' : '0' });
      const mine = ++this.seq;
      const r = await api.get(`admin/item-ccp?${q}`);
      if (mine !== this.seq || !document.body.contains(body)) return;
      this.data = r.ok ? r.data : null;
      this.error = r.ok ? null : r;
      this.draw();
    },

    defaultLine() {
      const d = this.data ? this.data.default.MANUFACTURE : PROCESSES;
      return `<div class="te-ic-default" id="icDefault"><b>전체 품목 기본 CCP</b>
        <span>${d.length ? d.map((p) => `${p} ${esc(NAMES[p])}`).join(' · ') : '없음'}</span>
        <span class="te-hint">품목 설정이 없으면 이 구성으로 CCP 일지를 만듭니다 · 바꾸려면 개발 요청</span>
        <span class="te-pl-grow"></span><button class="btn btn-secondary btn-sm" id="icHistAll">전체 이력</button></div>`;
    },

    cell(row, p) {
      if (!row.effective.includes(p)) return '<td class="te-ic-cell"><span class="te-ic-off" title="안 만듦">—</span></td>';
      const own = row.mode === 'own';
      return `<td class="te-ic-cell"><span class="${own ? 'te-ic-own' : 'te-ic-def'}" title="${own ? '품목에 직접 정함' : '기본을 따라 만듦'}">${p}</span></td>`;
    },

    chip(row) {
      if (row.mode === 'default') return '<span class="te-pl-chip-info">기본 따름</span>';
      if (!row.processes.length) return '<span class="te-pl-chip-warn">CCP 없음</span>';
      return '<span class="te-pl-chip-link">품목 설정</span>';
    },

    draw() {
      const f = this.filters;
      const head = `${this.defaultLine()}
        <div class="te-filters">
          <div class="form-group"><label class="form-label" for="icQ">품목</label><input class="form-control" id="icQ" value="${esc(f.q)}" placeholder="품목명·코드"></div>
          <label class="te-ic-check"><input type="checkbox" id="icOwn"${f.only_own ? ' checked' : ''}> 품목 설정만</label>
          <label class="te-ic-check"><input type="checkbox" id="icInactive"${f.include_inactive ? ' checked' : ''}> 사용 중지 품목 포함</label>
          <button class="btn btn-secondary btn-sm" id="icFind">조회</button>
        </div>`;
      if (!this.data) {
        this.body.innerHTML = `${head}<div class="te-error-box" id="icError">${esc(T.errorText(this.error))}
          <div>품목 목록을 읽지 못했습니다. <button class="btn btn-secondary btn-sm" id="icRetry">다시 시도</button></div></div>`;
        this.bind();
        return;
      }
      const items = this.data.items;
      const own = items.filter((r) => r.mode === 'own').length;
      const rows = items.map((r) => `
        <tr data-item="${r.item_id}" class="${r.is_active ? '' : 'te-ic-inactive'}">
          <td class="mono">${esc(r.item_code)}</td>
          <td>${esc(r.name)}${r.is_active ? '' : ' <span class="badge badge-neutral">사용 중지</span>'}</td>
          ${PROCESSES.map((p) => this.cell(r, p)).join('')}
          <td>${this.chip(r)}</td><td class="num">${r.planned_batches}</td><td class="num">${r.running_batches}</td>
          <td class="te-ms-acts"><button class="btn btn-secondary btn-sm" data-ic-edit="${r.item_id}">${this.open && this.open.item.item_id === r.item_id ? '닫기' : '편집'}</button>
            <button class="btn btn-secondary btn-sm" data-ic-hist="${r.item_id}">이력</button></td>
        </tr>${this.open && this.open.item.item_id === r.item_id ? `<tr class="te-ic-edit-row"><td colspan="9">${this.editorHtml()}</td></tr>` : ''}`).join('');
      this.body.innerHTML = `${head}
        <div class="te-ic-title" id="icTitle">반제품 ${items.length}개 · 품목 설정 ${own}개</div>
        <div class="te-table-wrap"><table class="data-table" id="icTable"><thead><tr><th>코드</th><th>품목</th><th>1P</th><th>2B</th><th>3P</th><th>구분</th><th title="생산 시작 전 배치">시작 전</th><th title="생산 중 배치">진행 중</th><th></th></tr></thead>
          <tbody>${rows || '<tr><td colspan="9" class="te-empty">조건에 맞는 품목이 없습니다.</td></tr>'}</tbody></table></div>
        <div class="te-hint">옅은 칸 = 기본을 따라 만드는 CCP, 진한 칸 = 품목에 직접 정한 CCP, — = 만들지 않음</div>`;
      this.bind();
    },

    editorHtml() {
      const e = this.open;
      const r = e.item;
      const def = this.data.default.MANUFACTURE;
      const shown = e.mode === 'default' ? def : e.processes;
      const changed = !same(e, r);
      const after = e.mode === 'default' ? `기본 따름(${list(def)})` : (e.processes.length ? list(e.processes) : 'CCP 없음');
      const before = r.mode === 'default' ? `기본 따름(${list(def)})` : (r.processes.length ? list(r.processes) : 'CCP 없음');
      return `<div class="te-ic-editor" id="msEditor">
        <div class="te-ic-seg" role="group" aria-label="구성">
          <button type="button" class="${e.mode === 'default' ? 'on' : ''}" data-ic-mode="default">기본 따름</button>
          <button type="button" class="${e.mode === 'own' ? 'on' : ''}" data-ic-mode="own">품목 설정</button></div>
        <div class="te-ic-procs">${PROCESSES.map((p) => `<button type="button" class="te-ic-proc${shown.includes(p) ? ' on' : ''}" data-ic-proc="${p}"${e.mode === 'default' ? ' disabled' : ''}>
          <b>${esc(LOGS[p])}</b><span>${shown.includes(p) ? '만듦' : '안 만듦'}</span></button>`).join('')}</div>
        ${e.mode === 'own' && !e.processes.length ? '<div class="te-ic-warn" id="icNone">CCP 없음 — 생산을 시작해도 CCP 일지를 만들지 않고, 생산일지에도 CCP 공정을 넣을 수 없습니다.</div>' : ''}
        <div class="te-ic-info" id="icInfo"><b>다음 생산 시작부터</b> ${esc(after)} · 생산 시작 전 배치 ${r.planned_batches}건은 시작할 때 새 구성으로 · 진행 중 배치 ${r.running_batches}건은 이미 만든 CCP 일지 그대로</div>
        <div class="form-group"><label class="form-label" for="icReason">사유 (선택, 100자)</label><input class="form-control" id="icReason" maxlength="100" value="${esc(e.reason)}"></div>
        ${e.conflict ? '<div class="te-error-box" id="icConflict">다른 사람이 먼저 이 품목을 바꿨습니다. 지금 값을 다시 불러온 뒤 저장하세요. <button class="btn btn-secondary btn-sm" id="icReload">다시 불러오기</button></div>' : ''}
        ${e.error ? `<div class="te-error-box" id="icErr">${esc(e.error)}</div>` : ''}
        ${noStaff() ? '<div class="te-notice">현재 사용자를 선택하세요. 선택 전에는 저장할 수 없습니다.</div>' : ''}
        <div class="te-ic-actions">
          ${e.confirm ? `<span id="icConfirm">${esc(before)} → <b>${esc(after)}</b> 로 저장할까요?</span>
            <button class="btn btn-primary btn-sm" id="icSaveYes"${e.saving ? ' disabled' : ''}>${e.saving ? '저장 중…' : '저장'}</button><button class="btn btn-secondary btn-sm" id="icSaveNo"${e.saving ? ' disabled' : ''}>취소</button>`
            : `<button class="btn btn-primary btn-sm" id="icSave"${!changed || noStaff() ? ' disabled' : ''}>저장</button>${changed ? '' : ' <span class="te-hint">바뀐 값이 없습니다</span>'}
            <button class="btn btn-secondary btn-sm" id="icCancel">닫기</button>`}
        </div></div>`;
    },

    bind() {
      const $ = (s) => this.body.querySelector(s);
      const find = async () => {
        // 다시 그리면 펼친 편집이 닫힘 → 바뀐 값이 있으면 먼저 확인, 취소면 조회 막대를 원래 값으로(검토 B1)
        if (this.open && !(await this.master.leave())) {
          const f = this.filters;
          $('#icQ').value = f.q; $('#icOwn').checked = f.only_own; $('#icInactive').checked = f.include_inactive;
          return;
        }
        Object.assign(this.filters, { q: $('#icQ').value.trim(), only_own: $('#icOwn').checked, include_inactive: $('#icInactive').checked });
        this.open = null;
        this.load();
      };
      $('#icFind').addEventListener('click', find);
      $('#icQ').addEventListener('keydown', (ev) => { if (ev.key === 'Enter') find(); });
      ['#icOwn', '#icInactive'].forEach((s) => $(s).addEventListener('change', find));
      $('#icHistAll').addEventListener('click', () => this.history(null, '전체 품목'));
      $('#icRetry')?.addEventListener('click', () => this.load());
      if (!this.data) return;
      const byId = Object.fromEntries(this.data.items.map((r) => [r.item_id, r]));
      this.body.querySelectorAll('[data-ic-edit]').forEach((b) => b.addEventListener('click', async () => {
        const row = byId[b.dataset.icEdit];
        if (this.open && this.open.item.item_id === row.item_id) { if (await this.master.leave()) { this.open = null; this.draw(); } return; }
        if (this.open && !(await this.master.leave())) return;
        this.open = { item: row, mode: row.mode, processes: [...row.processes], reason: '', confirm: false, conflict: false, error: null, saving: false };
        this.draw();
      }));
      this.body.querySelectorAll('[data-ic-hist]').forEach((b) => b.addEventListener('click', () => {
        const row = byId[b.dataset.icHist];
        this.history(row.item_id, `${row.name}(${row.item_code})`);
      }));
      if (!this.open) return;
      const e = this.open;
      const keepReason = () => { if ($('#icReason')) e.reason = $('#icReason').value; };
      this.body.querySelectorAll('[data-ic-mode]').forEach((b) => b.addEventListener('click', () => {
        keepReason();
        e.mode = b.dataset.icMode;
        if (e.mode === 'own' && e.item.mode === 'default' && !e.processes.length) e.processes = [...this.data.default.MANUFACTURE];
        if (e.mode === 'default') e.processes = [];
        e.confirm = false;
        this.draw();
      }));
      this.body.querySelectorAll('[data-ic-proc]').forEach((b) => b.addEventListener('click', () => {
        keepReason();
        const p = b.dataset.icProc;
        e.processes = PROCESSES.filter((x) => (x === p ? !e.processes.includes(x) : e.processes.includes(x)));
        e.confirm = false;
        this.draw();
      }));
      $('#icReason').addEventListener('input', () => { e.reason = $('#icReason').value; });
      $('#icSave')?.addEventListener('click', () => { keepReason(); e.confirm = true; e.error = null; this.draw(); });
      $('#icSaveNo')?.addEventListener('click', () => { e.confirm = false; this.draw(); });
      $('#icSaveYes')?.addEventListener('click', () => this.save());
      $('#icCancel')?.addEventListener('click', async () => { if (await this.master.leave()) { this.open = null; this.draw(); } });
      $('#icReload')?.addEventListener('click', () => { this.open = null; this.load(); });
    },

    async save() {
      const e = this.open;
      if (!e || e.saving) return;  // 요청 중 다시 누름 무시(검토 B2)
      e.saving = true;
      this.draw();
      const body = { mode: e.mode, processes: e.mode === 'own' ? e.processes : [], expected_version: e.item.version };
      if (e.reason.trim()) body.reason = e.reason.trim();
      const r = await api.put(`admin/item-ccp/${e.item.item_id}`, body);
      e.saving = false;
      if (this.open !== e) return;
      if (!r.ok) {
        e.confirm = false;
        if (r.status === 409) e.conflict = true;
        else e.error = `${T.errorText(r)}${(r.data && r.data.details || []).filter((d) => d.message).map((d) => ` · ${d.path} ${d.message}`).join('')}`;
        this.draw();
        return;
      }
      const it = r.data.item;
      this.open = null;
      T.toast(`${it.name}: 저장했습니다 — 다음 생산 시작부터 ${it.effective.length ? list(it.effective) : 'CCP 없음'}`);
      this.load();
    },

    // ADM-SC-04 변경 이력(A11) — 시각·누가·대상·전 → 후·사유
    async history(itemId, name) {
      const q = new URLSearchParams({ target: 'item_ccp' });
      if (itemId) q.set('target_id', itemId);
      const r = await api.get(`admin/history?${q}`);
      if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
      const rows = r.data.items.map((x) => `<tr><td>${esc(T.fmtDateTime(x.at))}</td><td>${esc(x.actor && x.actor.name ? x.actor.name : `#${x.actor && x.actor.id}`)}</td>
        <td>${esc(x.label || `품목 #${x.target_id}(삭제됨)`)}</td><td>${esc(ACTIONS[x.action] || x.action)}</td>
        <td>${esc(describe(x.before))} → <b>${esc(describe(x.after))}</b></td><td>${esc(x.reason || '')}</td></tr>`).join('');
      const wrap = document.createElement('div');
      wrap.className = 'te-modal-wrap';
      wrap.innerHTML = `<div class="te-modal te-pl-modal-wide" role="dialog" aria-modal="true">
        <div class="modal-header"><div class="modal-title">변경 이력 — ${esc(name)}</div></div>
        <div class="te-modal-body"><div class="te-table-wrap"><table class="data-table" id="icHist"><thead><tr><th>시각</th><th>누가</th><th>품목</th><th>무엇</th><th>전 → 후</th><th>사유</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="6" class="te-empty">이력이 없습니다.</td></tr>'}</tbody></table></div>
        <div class="te-modal-footer"><button class="btn btn-secondary" data-close>닫기</button></div></div></div>`;
      document.body.appendChild(wrap);
      wrap.addEventListener('click', (ev) => { if (ev.target === wrap) wrap.remove(); });
      wrap.querySelector('[data-close]').addEventListener('click', () => wrap.remove());
    },
  };

  window.TempEntryItemCcp = ItemCcp;
})();
