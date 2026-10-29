// =============================================
// P15 생산 기준정보 (PLG-SC-04 공정 목록 · PLG-SC-05 공정 템플릿 — p15-s1-screens.md 6·7장)
// P16 세 번째 탭 품목별 CCP(ADM-SC-01) — admin-settings/item-ccp.js(TempEntryItemCcp)
// API: PLG-A06 processes · A07 process-templates · A08 master-history (명세 p15-s2-spec.md 5장)
// 공정·템플릿 관리는 누구나(현재 사용자만 있으면 — PLG-R12), 모든 변경은 이력 1행.
// =============================================
(function () {
  const T = window.TempEntry;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);

  const KIND_LABEL = { 'CCP-1P': 'CCP-1P 쇳가루', 'CCP-2B': 'CCP-2B 건조', 'CCP-3P': 'CCP-3P 금속검출', INNER: '내포장', OUTER: '외포장', GEN: '일반' };
  const MODES = { JUDGE: '적합/부적합', TEMP_TIME: '온도·시간', QTY: '수량' };
  const UNITS = ['분', '시간', '일'];
  const ACTIONS = { create: '추가', update: '수정', deactivate: '사용 중지', reactivate: '다시 사용', delete: '삭제', copy: '복제', register: '일지에서 등록', overwrite: '일지에서 덮어쓰기' };
  const OVERRIDE = { common: ['name', 'desc', 'duration'], GEN: ['mode'], INNER: ['spec', 'qty_unit'], OUTER: ['material'] };
  const OV_LABEL = { name: '표시명', desc: '설명', duration: '소요기간', mode: '입력 방식', spec: '포장 규격', qty_unit: '수량 단위', material: '포장재질' };
  const blank = (v) => v === undefined || v === null || v === '';
  const dur = (d) => (d ? `${d.value}${d.unit}` : '—');
  const day = (iso) => (iso ? T.fmtDateTime(iso).slice(0, 10) : '—');
  const noStaff = () => !api.staffId;
  const MAX_STEPS = 30;  // 명세 PLG-R16 — 템플릿 단계 1~30개

  function modal(title, body, wide = false) {
    const wrap = document.createElement('div');
    wrap.className = 'te-modal-wrap';
    wrap.innerHTML = `<div class="te-modal${wide ? ' te-pl-modal-wide' : ''}" role="dialog" aria-modal="true">
      <div class="modal-header"><div class="modal-title">${esc(title)}</div></div><div class="te-modal-body">${body}</div></div>`;
    document.body.appendChild(wrap);
    wrap.addEventListener('click', (e) => { if (e.target === wrap) wrap.remove(); });
    return wrap;
  }
  const errorBox = (r) => `<div class="te-error-box" data-err>${esc(T.errorText(r))}${(r.data && r.data.details || []).filter((x) => x.message).map((x) => `<div>· ${esc(x.path || '')} ${esc(x.message)}</div>`).join('')}</div>`;

  const Master = {
    title: '생산 기준정보',
    root: null,
    tab: 'process',
    pf: { q: '', kind: 'all', status: 'active' },
    tf: { q: '', status: 'active' },
    seq: 0,            // r1 B2: 요청 순번 — 늦게 온 이전 응답은 그리지 않음
    dirty: () => false, // r1 B1: 템플릿 편집에 저장 안 한 변경이 있는지(편집 화면이 바꿔 끼움)

    start(root) {
      this.root = root;
      const intent = T.takeIntent();
      if (intent && intent.tab) this.tab = intent.tab;
      this.editing = null;
      this.dirty = () => false;
      this.guard();
      this.show();
    },

    // r1 B1: 편집 화면을 떠나는 모든 길([← 목록]·탭·새로고침·사이드바·브라우저)에서 확인
    async leave() {
      if (!this.dirty() || !document.querySelector('#msEditor')) return true;
      return T.confirm('저장 안 된 변경', '저장하지 않은 변경이 있습니다. 나갈까요?', '나가기', 'btn-danger');  // 다시 그릴 때 편집 상태가 초기화됨
    },

    guard() {
      const MS = this;
      if (typeof App !== 'undefined' && !App._msGuard) {  // eslint-disable-line no-undef — 시제품 app.js의 const App
        const original = App.navigate;
        App._msGuard = true;
        let seq = 0;
        let pending = null;
        App.navigate = async function (page, updateNav = true, fromHistory = false) {
          const mine = ++seq;
          if (pending) { pending.remove(); pending = null; }
          if (!fromHistory && MS.dirty() && document.querySelector('#msEditor')) {
            const asked = T.confirm('저장 안 된 변경', '저장하지 않은 변경이 있습니다. 이 화면을 나갈까요?', '나가기', 'btn-danger');
            pending = [...document.querySelectorAll('.te-modal-wrap')].pop() || null;
            const ok = await asked;
            if (mine !== seq) return undefined;
            pending = null;
            if (!ok) return undefined;
          }
          MS.dirty = () => false;
          return original.call(this, page, updateNav, fromHistory);
        };
      }
      if (!this._unload) {
        this._unload = (e) => { if (this.dirty() && document.querySelector('#msEditor')) { e.preventDefault(); e.returnValue = ''; } };
        window.addEventListener('beforeunload', this._unload);
      }
    },

    show() {
      this.root.innerHTML = `
        <div class="fade-in" id="teMaster">
          ${T.topBar('생산 기준정보', '공정 · 공정 템플릿 · 품목별 CCP — 누구나 관리, 모든 변경은 이력으로 남습니다', null, { temp: false })}
          <div class="te-ms-tabs" role="tablist"><button type="button" class="te-ms-tab${this.tab === 'process' ? ' on' : ''}" data-tab="process" id="msTabProc">공정</button><button type="button" class="te-ms-tab${this.tab === 'template' ? ' on' : ''}" data-tab="template" id="msTabTpl">공정 템플릿</button><button type="button" class="te-ms-tab${this.tab === 'item-ccp' ? ' on' : ''}" data-tab="item-ccp" id="msTabCcp">품목별 CCP</button></div>
          <div class="card" id="msBody"><div class="te-empty">불러오는 중…</div></div>
        </div>`;
      T.bindTopBar(this.root, async () => { if (await this.leave()) this.show(); });
      this.root.querySelectorAll('[data-tab]').forEach((b) => b.addEventListener('click', async () => {
        if (!(await this.leave())) return;
        this.tab = b.dataset.tab; this.editing = null; this.dirty = () => false; this.show();
      }));
      if (this.tab === 'item-ccp' && window.TempEntryItemCcp) window.TempEntryItemCcp.render(this, this.body());
      else if (this.tab === 'process') this.showProcesses(); else if (this.editing) this.showEditor(this.editing); else this.showTemplates();
    },

    body() { return this.root.querySelector('#msBody'); },

    // ================================================ PLG-SC-04 공정 목록
    async showProcesses() {
      const body = this.body();
      const f = this.pf;
      const q = new URLSearchParams({ q: f.q, kind: f.kind, status: f.status });
      const mine = ++this.seq;
      const r = await api.get(`processes?${q}`);
      if (mine !== this.seq || !this.root.contains(body)) return;
      if (!r.ok) { body.innerHTML = errorBox(r); return; }
      const items = r.data.items;
      const sel = (id, value, opts) => `<select class="form-control" id="${id}">${opts.map(([v, l]) => `<option value="${v}"${value === v ? ' selected' : ''}>${l}</option>`).join('')}</select>`;
      body.innerHTML = `
        <div class="te-filters">
          <div class="form-group"><label class="form-label" for="msQ">이름</label><input class="form-control" id="msQ" value="${esc(f.q)}" placeholder="이름 검색"></div>
          <div class="form-group"><label class="form-label" for="msKind">기능</label>${sel('msKind', f.kind, [['all', '전체'], ['builtin', '기본 제공'], ['general', '일반']])}</div>
          <div class="form-group"><label class="form-label" for="msStatus">상태</label>${sel('msStatus', f.status, [['active', '사용'], ['inactive', '중지'], ['all', '전체']])}</div>
          <button class="btn btn-secondary btn-sm" id="msFind">조회</button><span class="te-pl-grow"></span>
          <button class="btn btn-primary btn-sm" id="msNew" ${noStaff() ? 'disabled title="현재 사용자를 선택하세요"' : ''}>+ 공정 추가</button>
        </div>
        <div class="te-table-wrap"><table class="data-table" id="msProcTable"><thead><tr><th>공정</th><th>기능</th><th>기본 입력</th><th>표준 소요기간</th><th>쓰는 템플릿</th><th>최근 사용</th><th>상태</th><th></th></tr></thead>
          <tbody>${items.map((p) => `<tr data-proc="${p.process_id}"><td><b>${esc(p.name)}</b>${p.is_builtin ? ' <span title="기본 제공 — 기능·입력 방식 고정, 중지·삭제 불가">🔒</span>' : ''}${p.description ? `<div class="te-hint">${esc(p.description)}</div>` : ''}</td>
            <td>${esc(KIND_LABEL[p.kind] || p.kind)}</td><td>${p.is_builtin ? '<span class="te-hint">고정</span>' : esc(MODES[p.mode] || '-')}</td><td>${esc(dur(p.std_duration))}</td>
            <td>${p.template_count}</td><td>${esc(day(p.last_used_at))}</td><td>${p.is_active ? '<span class="te-pl-chip-ok">사용</span>' : '<span class="badge badge-neutral">중지</span>'}</td>
            <td class="te-ms-acts"><button class="btn btn-secondary btn-sm" data-edit="${p.process_id}"${noStaff() ? ' disabled' : ''}>수정</button>
              ${p.is_builtin ? '' : `<button class="btn btn-secondary btn-sm" data-active="${p.process_id}"${noStaff() ? ' disabled' : ''}>${p.is_active ? '사용 중지' : '다시 사용'}</button>
              <button class="btn btn-secondary btn-sm" data-del="${p.process_id}"${noStaff() || p.template_count ? ` disabled title="${p.template_count ? `템플릿 ${p.template_count}개에서 씁니다 — 삭제 대신 사용 중지` : '현재 사용자를 선택하세요'}"` : ''}>삭제</button>`}
              <button class="btn btn-secondary btn-sm" data-hist="${p.process_id}">이력</button></td></tr>`).join('') || '<tr><td colspan="8" class="te-empty">조건에 맞는 공정이 없습니다.</td></tr>'}</tbody></table></div>
        <div class="te-hint">기본 제공 공정은 표시명·설명·표준 소요기간만 고칠 수 있습니다. 템플릿·생산일지에 한 번이라도 쓴 공정은 삭제 대신 사용 중지합니다.</div>`;
      const $ = (s) => body.querySelector(s);
      const find = () => { Object.assign(this.pf, { q: $('#msQ').value.trim(), kind: $('#msKind').value, status: $('#msStatus').value }); this.showProcesses(); };
      $('#msFind').addEventListener('click', find);
      $('#msQ').addEventListener('keydown', (e) => { if (e.key === 'Enter') find(); });
      ['#msKind', '#msStatus'].forEach((s) => $(s).addEventListener('change', find));
      $('#msNew').addEventListener('click', () => this.editProcess(null));
      const byId = Object.fromEntries(items.map((p) => [p.process_id, p]));
      body.querySelectorAll('[data-edit]').forEach((b) => b.addEventListener('click', () => this.editProcess(byId[b.dataset.edit])));
      body.querySelectorAll('[data-active]').forEach((b) => b.addEventListener('click', () => this.toggleProcess(byId[b.dataset.active])));
      body.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', () => this.deleteProcess(byId[b.dataset.del])));
      body.querySelectorAll('[data-hist]').forEach((b) => b.addEventListener('click', () => this.history('process', Number(b.dataset.hist), byId[b.dataset.hist].name)));
    },

    editProcess(p) {
      const builtin = p && p.is_builtin;
      const st = { similar: null, confirmMode: null, error: '' };
      const wrap = modal(p ? `공정 수정 — ${p.name}` : '공정 추가', '<div id="msEdit"></div>');
      const v = { name: p ? p.name : '', mode: p ? p.mode : 'JUDGE', description: p ? p.description || '' : '', durOn: !!(p && p.std_duration), durValue: p && p.std_duration ? p.std_duration.value : '', durUnit: p && p.std_duration ? p.std_duration.unit : '분' };
      const draw = () => {
        wrap.querySelector('#msEdit').innerHTML = `
          ${st.error}
          <div class="form-group"><label class="form-label" for="msName">이름 *</label><input class="form-control" id="msName" maxlength="40" value="${esc(v.name)}"></div>
          ${builtin ? `<div class="te-hint">기본 제공(${esc(KIND_LABEL[p.kind])}) — 기능·입력 방식은 바꿀 수 없습니다.</div>` : `<div class="form-group"><label class="form-label" for="msMode">입력 방식 *</label><select class="form-control" id="msMode">${Object.entries(MODES).map(([k, l]) => `<option value="${k}"${v.mode === k ? ' selected' : ''}>${l}</option>`).join('')}</select></div>`}
          <div class="form-group"><label class="form-label" for="msDesc">설명</label><textarea class="form-control" id="msDesc" rows="2" maxlength="300">${esc(v.description)}</textarea></div>
          <div class="form-group"><label class="te-check"><input type="checkbox" id="msDurOn"${v.durOn ? ' checked' : ''}> 표준 소요기간 (켜면 일지에 불러올 때 소요기간 기록이 켜짐)</label>
            <div class="te-pl-inline"><input type="number" class="form-control" id="msDurValue" min="0" step="0.5" value="${esc(v.durValue)}"${v.durOn ? '' : ' disabled'}><select class="form-control te-pl-unit" id="msDurUnit"${v.durOn ? '' : ' disabled'}>${UNITS.map((u) => `<option${v.durUnit === u ? ' selected' : ''}>${u}</option>`).join('')}</select></div></div>
          ${p && p.template_count ? `<div class="te-pl-warn" id="msImpact">덮어쓰지 않은 템플릿 ${p.template_count}개에 반영됩니다(이미 만든 생산일지는 바뀌지 않음).</div>` : ''}
          ${st.similar ? `<div class="te-pl-warn" id="msSimilar">비슷한 이름이 있습니다: <b>${esc(st.similar)}</b> <button class="btn btn-secondary btn-sm" id="msSimilarOk">그래도 저장</button></div>` : ''}
          ${st.confirmMode !== null ? `<div class="te-pl-warn" id="msModeConfirm">입력 방식을 바꾸면 이 공정을 쓰는 템플릿 ${st.confirmMode}개에 반영됩니다. <button class="btn btn-warning btn-sm" id="msModeOk">바꾸기</button></div>` : ''}
          <div class="te-modal-footer"><button class="btn btn-secondary" data-close>취소</button><button class="btn btn-primary" id="msSave">저장</button></div>`;
        const $ = (s) => wrap.querySelector(s);
        const read = () => Object.assign(v, { name: $('#msName').value, mode: $('#msMode') ? $('#msMode').value : v.mode, description: $('#msDesc').value, durOn: $('#msDurOn').checked, durValue: $('#msDurValue').value, durUnit: $('#msDurUnit').value });
        $('#msDurOn').addEventListener('change', () => { read(); draw(); });
        $('[data-close]').addEventListener('click', () => wrap.remove());
        $('#msSave').addEventListener('click', () => { read(); save({}); });
        $('#msSimilarOk')?.addEventListener('click', () => { read(); save({ confirm_similar: true }); });
        $('#msModeOk')?.addEventListener('click', () => { read(); save({ confirm_mode: true, confirm_similar: !!st.similar }); });
      };
      const save = async (flags) => {
        const data = { name: v.name.trim(), description: v.description.trim() || null, std_duration: v.durOn ? { value: Number(v.durValue), unit: v.durUnit } : null, ...flags };
        if (!builtin) data.mode = v.mode;
        let r;
        if (p) {
          const patch = {};
          if (data.name !== p.name) patch.name = data.name;
          if ((data.description || null) !== (p.description || null)) patch.description = data.description;
          if (JSON.stringify(data.std_duration) !== JSON.stringify(p.std_duration || null)) patch.std_duration = data.std_duration;
          if (!builtin && data.mode !== p.mode) patch.mode = data.mode;
          r = await api.patch(`processes/${p.process_id}`, { expected_version: p.version, ...patch, ...flags });
        } else r = await api.post('processes', data);
        if (!r.ok) {
          const code = r.data && r.data.code;
          if (code === 'PLG_SIMILAR_NAME') { st.similar = (r.data.details || []).map((x) => x.name).filter(Boolean).join(', ') || '있음'; st.error = ''; draw(); return; }
          if (code === 'PLG_CONFIRM_REQUIRED') { st.confirmMode = ((r.data.details || [])[0] || {}).template_count || 0; st.error = ''; draw(); return; }
          st.error = errorBox(r);
          draw();
          return;
        }
        wrap.remove();
        T.toast(p ? `"${r.data.name}"을(를) 고쳤습니다.` : `공정 "${r.data.name}"을(를) 추가했습니다.`);
        this.showProcesses();
      };
      draw();
    },

    async toggleProcess(p) {
      const off = p.is_active;
      if (off && !(await T.confirm('사용 중지', `"${esc(p.name)}"을(를) 사용 중지할까요? 공정 추가 메뉴·새 템플릿에서 빠집니다. 이미 넣은 템플릿·생산일지는 그대로입니다.`, '사용 중지', 'btn-warning'))) return;
      const r = await api.post(`processes/${p.process_id}/active`, { expected_version: p.version, active: !off });
      if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
      T.toast(off ? `"${p.name}" 사용 중지` : `"${p.name}" 다시 사용`);
      this.showProcesses();
    },

    async deleteProcess(p) {
      if (!(await T.confirm('공정 삭제', `"${esc(p.name)}"을(를) 삭제할까요? 되돌릴 수 없습니다(이력은 남음).`, '삭제', 'btn-danger'))) return;
      const r = await api.del(`processes/${p.process_id}?expected_version=${p.version}`);
      if (!r.ok) { T.toast(r.data && r.data.code === 'PLG_IN_USE' ? '템플릿이나 생산일지에 쓴 적이 있어 삭제할 수 없습니다. 사용 중지하세요.' : T.errorText(r), 'error'); return; }
      T.toast(`"${p.name}"을(를) 삭제했습니다.`);
      this.showProcesses();
    },

    // 변경 이력(A08) — 누가·언제·무엇을(전 → 후), 생산일지에서 바뀌었으면 문서 번호
    async history(target, id, name) {
      const r = await api.get(`master-history?target=${target}&id=${id}`);
      if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
      const diff = (before, after) => {
        if (!before || !after) return '';
        const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].filter((k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]));
        const show = (x) => (x === null || x === undefined ? '없음' : (typeof x === 'object' ? (Array.isArray(x) ? `${x.length}개` : (x.value !== undefined ? `${x.value}${x.unit}` : JSON.stringify(x))) : String(x)));
        return keys.map((k) => `${k}: ${show(before[k])} → ${show(after[k])}`).join(' · ');
      };
      const rows = r.data.items.map((x) => `<tr><td>${esc(T.fmtDateTime(x.at))}</td><td>${esc(x.actor && x.actor.name ? x.actor.name : (x.actor && x.actor.id ? `#${x.actor.id}` : '시스템'))}</td><td>${esc(ACTIONS[x.action] || x.action)}</td>
        <td class="te-hint">${esc(diff(x.before, x.after))}</td><td>${x.document_id ? `<a href="#" data-doc="${x.document_id}">문서 #${x.document_id}</a>` : ''}</td></tr>`).join('');
      const wrap = modal(`변경 이력 — ${name}`, `<div class="te-table-wrap"><table class="data-table" id="msHist"><thead><tr><th>시각</th><th>누가</th><th>무엇</th><th>바뀐 값</th><th>생산일지</th></tr></thead><tbody>${rows || '<tr><td colspan="5" class="te-empty">이력이 없습니다.</td></tr>'}</tbody></table></div>
        <div class="te-modal-footer"><button class="btn btn-secondary" data-close>닫기</button></div>`, true);
      wrap.querySelector('[data-close]').addEventListener('click', () => wrap.remove());
      wrap.querySelectorAll('[data-doc]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); wrap.remove(); T.open('doc-box', { documentId: Number(a.dataset.doc), back: { page: 'prod-master', intent: { tab: this.tab } } }); }));
    },

    // ================================================ PLG-SC-05 공정 템플릿
    async showTemplates() {
      const body = this.body();
      const f = this.tf;
      const mine = ++this.seq;
      this.dirty = () => false;
      const r = await api.get(`process-templates?${new URLSearchParams({ q: f.q, status: f.status })}`);
      if (mine !== this.seq || !this.root.contains(body)) return;
      if (!r.ok) { body.innerHTML = errorBox(r); return; }
      const items = r.data.items;
      body.innerHTML = `
        <div class="te-filters">
          <div class="form-group"><label class="form-label" for="msTq">이름</label><input class="form-control" id="msTq" value="${esc(f.q)}" placeholder="이름 검색"></div>
          <div class="form-group"><label class="form-label" for="msTs">상태</label><select class="form-control" id="msTs">${[['active', '사용'], ['inactive', '중지'], ['all', '전체']].map(([k, l]) => `<option value="${k}"${f.status === k ? ' selected' : ''}>${l}</option>`).join('')}</select></div>
          <button class="btn btn-secondary btn-sm" id="msTfind">조회</button><span class="te-pl-grow"></span>
          <button class="btn btn-primary btn-sm" id="msTnew" ${noStaff() ? 'disabled title="현재 사용자를 선택하세요"' : ''}>+ 템플릿 만들기</button>
        </div>
        <div class="te-table-wrap"><table class="data-table" id="msTplTable"><thead><tr><th>이름</th><th>공정</th><th>CCP</th><th>만든 사람</th><th>최근 사용</th><th>상태</th><th></th></tr></thead>
          <tbody>${items.map((t) => `<tr data-tpl="${t.process_template_id}"><td><b>${esc(t.name)}</b></td><td>${t.step_count}개</td><td>${(t.ccp_kinds || []).map((k) => `<span class="te-pl-chip-ccp">${esc(k)}</span>`).join(' ') || '<span class="te-hint">없음</span>'}</td>
            <td>${esc(t.created_by && t.created_by.name ? t.created_by.name : '-')}</td><td>${esc(day(t.last_used_at))}${t.used_count ? ` <span class="te-hint">(${t.used_count}회)</span>` : ''}</td>
            <td>${t.is_active ? '<span class="te-pl-chip-ok">사용</span>' : '<span class="badge badge-neutral">중지</span>'}</td>
            <td class="te-ms-acts"><button class="btn btn-secondary btn-sm" data-tedit="${t.process_template_id}">편집</button><button class="btn btn-secondary btn-sm" data-copy="${t.process_template_id}"${noStaff() ? ' disabled' : ''}>복제</button></td></tr>`).join('') || '<tr><td colspan="7" class="te-empty">조건에 맞는 템플릿이 없습니다.</td></tr>'}</tbody></table></div>`;
      const $ = (s) => body.querySelector(s);
      const find = () => { Object.assign(this.tf, { q: $('#msTq').value.trim(), status: $('#msTs').value }); this.showTemplates(); };
      $('#msTfind').addEventListener('click', find);
      $('#msTq').addEventListener('keydown', (e) => { if (e.key === 'Enter') find(); });
      $('#msTs').addEventListener('change', find);
      $('#msTnew').addEventListener('click', () => { this.editing = 'new'; this.showEditor('new'); });
      body.querySelectorAll('[data-tedit]').forEach((b) => b.addEventListener('click', () => { this.editing = Number(b.dataset.tedit); this.showEditor(this.editing); }));
      body.querySelectorAll('[data-copy]').forEach((b) => b.addEventListener('click', async () => {
        const c = await api.post(`process-templates/${b.dataset.copy}/copy`, {});
        if (!c.ok) { T.toast(T.errorText(c), 'error'); return; }
        T.toast(`"${c.data.name}"(으)로 복제했습니다.`);
        this.editing = c.data.process_template_id;
        this.showEditor(this.editing);
      }));
    },

    async showEditor(id) {
      const body = this.body();
      const mine = ++this.seq;
      this.dirty = () => false;
      const [procs, tpl] = await Promise.all([api.get('processes?status=all'), id === 'new' ? null : api.get(`process-templates/${id}`)]);
      if (mine !== this.seq || !this.root.contains(body)) return;
      if (!procs.ok || (tpl && !tpl.ok)) { body.innerHTML = errorBox(!procs.ok ? procs : tpl); return; }
      const all = procs.data.items;
      const byId = Object.fromEntries(all.map((p) => [p.process_id, p]));
      const t = tpl ? tpl.data : null;
      const st = {
        name: t ? t.name : '',
        steps: t ? t.steps.map((s) => ({ process_id: s.process_id, overrides: { ...s.overrides }, open: false })) : [],
        error: '', similar: null,
      };
      const snap = () => JSON.stringify({ name: st.name.trim(), steps: st.steps.map((s) => [s.process_id, s.overrides]) });
      const saved = snap();
      this.dirty = () => snap() !== saved;
      const allowed = (kind) => [...OVERRIDE.common, ...(OVERRIDE[kind] || [])];
      const draw = () => {
        const have = new Set(st.steps.map((s) => s.process_id));
        const builtinKinds = new Set(st.steps.map((s) => byId[s.process_id] && byId[s.process_id].is_builtin && byId[s.process_id].kind).filter(Boolean));
        const options = all.filter((p) => p.is_active && !have.has(p.process_id) && !(p.is_builtin && builtinKinds.has(p.kind)));
        const full = st.steps.length >= MAX_STEPS;  // r1 C1
        const ovEditor = (s, i) => {
          const p = byId[s.process_id];
          return `<div class="te-ms-ov" data-ov="${i}">${allowed(p.kind).map((k) => {
            const val = s.overrides[k];
            if (k === 'duration') {
              const modeVal = !('duration' in s.overrides) ? 'default' : (val ? 'on' : 'off');
              return `<div class="form-group"><label class="form-label">${OV_LABEL[k]} <span class="te-hint">기본 ${esc(dur(p.std_duration))}</span></label><div class="te-pl-inline">
                <select class="form-control" data-ovk="duration-mode"><option value="default"${modeVal === 'default' ? ' selected' : ''}>기본값</option><option value="on"${modeVal === 'on' ? ' selected' : ''}>직접</option><option value="off"${modeVal === 'off' ? ' selected' : ''}>기록 안 함</option></select>
                ${modeVal === 'on' ? `<input type="number" class="form-control" data-ovk="duration-value" min="0" step="0.5" value="${esc(val.value)}"><select class="form-control te-pl-unit" data-ovk="duration-unit">${UNITS.map((u) => `<option${val.unit === u ? ' selected' : ''}>${u}</option>`).join('')}</select>` : ''}</div></div>`;
            }
            if (k === 'mode') return `<div class="form-group"><label class="form-label">${OV_LABEL[k]} <span class="te-hint">기본 ${esc(MODES[p.mode] || '-')}</span></label><select class="form-control" data-ovk="mode"><option value="">기본값</option>${Object.entries(MODES).map(([m, l]) => `<option value="${m}"${val === m ? ' selected' : ''}>${l}</option>`).join('')}</select></div>`;
            const base = k === 'name' ? p.name : (k === 'desc' ? p.description || '' : '');
            return `<div class="form-group"><label class="form-label">${OV_LABEL[k]}</label><input class="form-control" data-ovk="${k}" value="${esc(blank(val) ? '' : val)}" placeholder="${esc(base || '기본값')}"></div>`;
          }).join('')}</div>`;
        };
        body.innerHTML = `
          <div class="te-ms-editor" id="msEditor">
            <div class="te-pl-sec-head"><button class="btn btn-secondary btn-sm" id="msBack">← 목록</button><span class="te-section-title">${t ? `템플릿 편집 — ${esc(t.name)}` : '새 템플릿'}</span>
              ${t ? `${t.is_active ? '<span class="te-pl-chip-ok">사용</span>' : '<span class="badge badge-neutral">중지</span>'} <span class="te-hint">불러온 횟수 ${t.used_count} · v${t.version}</span>` : ''}</div>
            ${st.error}
            <div class="form-group" style="max-width:24rem"><label class="form-label" for="msTname">이름 *</label><input class="form-control" id="msTname" maxlength="40" value="${esc(st.name)}"></div>
            <div class="te-table-wrap"><table class="data-table" id="msSteps"><thead><tr><th>#</th><th>공정</th><th>기능</th><th>덮어쓸 값</th><th></th></tr></thead><tbody>
              ${st.steps.map((s, i) => {
                const p = byId[s.process_id] || { name: `#${s.process_id}`, kind: 'GEN' };
                const n = Object.keys(s.overrides).length;
                return `<tr data-step="${i}"><td>${i + 2}</td><td><b>${esc(s.overrides.name || p.name)}</b>${s.overrides.name ? ` <span class="te-hint">(${esc(p.name)})</span>` : ''}${p.is_active === false ? ' <span class="te-pl-chip-warn">중지됨</span>' : ''}</td><td>${esc(KIND_LABEL[p.kind] || p.kind)}</td>
                  <td><button class="btn btn-secondary btn-sm" data-open="${i}">${s.open ? '접기' : `펼치기${n ? ` · ${n}개` : ''}`}</button></td>
                  <td class="te-ms-acts"><button class="btn btn-secondary btn-sm" data-up="${i}"${i === 0 ? ' disabled' : ''} aria-label="위로">↑</button><button class="btn btn-secondary btn-sm" data-down="${i}"${i === st.steps.length - 1 ? ' disabled' : ''} aria-label="아래로">↓</button><button class="btn btn-secondary btn-sm" data-remove="${i}">빼기</button></td></tr>
                  ${s.open ? `<tr class="te-ms-ovrow"><td></td><td colspan="4">${ovEditor(s, i)}</td></tr>` : ''}`;
              }).join('') || '<tr><td colspan="5" class="te-empty">공정을 넣으세요(1개 이상).</td></tr>'}</tbody></table></div>
            <div class="te-pl-inline te-ms-add"><select class="form-control" id="msAddProc"${full ? ' disabled' : ''}><option value="">공정 목록에서 넣기…</option>${options.map((p) => `<option value="${p.process_id}">${esc(p.name)} · ${esc(KIND_LABEL[p.kind])}</option>`).join('')}</select><button class="btn btn-secondary btn-sm" id="msAddGo"${full ? ' disabled' : ''}>넣기</button>
              <span class="te-hint" id="msAddHint">${full ? `공정은 ${MAX_STEPS}개까지 넣을 수 있습니다.` : `기본 제공 기능은 템플릿당 1개 · 같은 공정 두 번 불가 · 최대 ${MAX_STEPS}개`}</span></div>
            ${st.similar ? `<div class="te-pl-warn" id="msTsimilar">비슷한 이름이 있습니다: <b>${esc(st.similar)}</b> <button class="btn btn-secondary btn-sm" id="msTsimilarOk">그래도 저장</button></div>` : ''}
            <div class="te-actions">
              ${t ? `<button class="btn btn-secondary btn-sm" id="msThist">변경 이력</button>
                <button class="btn btn-secondary btn-sm" id="msTactive"${noStaff() ? ' disabled' : ''}>${t.is_active ? '사용 중지' : '다시 사용'}</button>
                <button class="btn btn-danger btn-sm" id="msTdel"${noStaff() || t.used_count ? ` disabled title="${t.used_count ? `생산일지에서 ${t.used_count}번 불러온 템플릿 — 삭제 대신 사용 중지` : '현재 사용자를 선택하세요'}"` : ''}>삭제</button>` : ''}
              <button class="btn btn-primary btn-sm" id="msTsave"${noStaff() ? ' disabled title="현재 사용자를 선택하세요"' : ''}>저장</button></div>
          </div>`;
        const $ = (s) => body.querySelector(s);
        $('#msBack').addEventListener('click', async () => { if (!(await this.leave())) return; this.editing = null; this.showTemplates(); });
        $('#msTname').addEventListener('input', (e) => { st.name = e.target.value; });
        body.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', () => { st.steps[b.dataset.open].open = !st.steps[b.dataset.open].open; draw(); }));
        body.querySelectorAll('[data-up],[data-down]').forEach((b) => b.addEventListener('click', () => {
          const i = Number(b.dataset.up ?? b.dataset.down);
          const j = b.dataset.up !== undefined ? i - 1 : i + 1;
          [st.steps[i], st.steps[j]] = [st.steps[j], st.steps[i]];
          draw();
        }));
        body.querySelectorAll('[data-remove]').forEach((b) => b.addEventListener('click', () => { st.steps.splice(Number(b.dataset.remove), 1); draw(); }));
        $('#msAddGo').addEventListener('click', () => {
          const pid = Number($('#msAddProc').value);
          if (!pid || st.steps.length >= MAX_STEPS) return;
          st.steps.push({ process_id: pid, overrides: {}, open: false });
          draw();
        });
        body.querySelectorAll('[data-ov]').forEach((box) => {
          const s = st.steps[Number(box.dataset.ov)];
          box.querySelectorAll('[data-ovk]').forEach((el) => el.addEventListener('change', () => {
            const k = el.dataset.ovk;
            if (k === 'duration-mode') {
              if (el.value === 'default') delete s.overrides.duration;
              else if (el.value === 'off') s.overrides.duration = null;
              else s.overrides.duration = { value: 1, unit: '시간' };
              draw();
              return;
            }
            if (k === 'duration-value') s.overrides.duration = { ...s.overrides.duration, value: Number(el.value) };
            else if (k === 'duration-unit') s.overrides.duration = { ...s.overrides.duration, unit: el.value };
            else if (blank(el.value.trim())) delete s.overrides[k];
            else s.overrides[k] = el.value.trim();
          }));
        });
        $('#msTsave').addEventListener('click', () => save({}));
        $('#msTsimilarOk')?.addEventListener('click', () => save({ confirm_similar: true }));
        $('#msThist')?.addEventListener('click', () => this.history('template', t.process_template_id, t.name));
        $('#msTactive')?.addEventListener('click', async () => {
          if (!(await this.leave())) return;  // 다시 그리면 저장 안 한 편집이 사라짐
          if (t.is_active && !(await T.confirm('사용 중지', `"${esc(t.name)}"을(를) 사용 중지할까요? 생산일지 불러오기 목록에서 빠집니다.`, '사용 중지', 'btn-warning'))) return;
          const r = await api.post(`process-templates/${t.process_template_id}/active`, { expected_version: t.version, active: !t.is_active });
          if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
          T.toast(t.is_active ? '사용 중지했습니다.' : '다시 사용합니다.');
          this.showEditor(t.process_template_id);
        });
        $('#msTdel')?.addEventListener('click', async () => {
          if (!(await T.confirm('템플릿 삭제', `"${esc(t.name)}"을(를) 삭제할까요? 되돌릴 수 없습니다(이력은 남음).`, '삭제', 'btn-danger'))) return;
          const r = await api.del(`process-templates/${t.process_template_id}?expected_version=${t.version}`);
          if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
          T.toast(`"${t.name}"을(를) 삭제했습니다.`);
          this.editing = null;
          this.showTemplates();
        });
      };
      const save = async (flags) => {
        const mine = this.seq;
        const steps = st.steps.map((s) => ({ process_id: s.process_id, overrides: s.overrides }));
        const r = t
          ? await api.patch(`process-templates/${t.process_template_id}`, { expected_version: t.version, name: st.name.trim(), steps, ...flags })
          : await api.post('process-templates', { name: st.name.trim(), steps, ...flags });
        if (mine !== this.seq || !this.root.contains(body)) {  // 응답 전에 다른 화면으로 감 — 결과만 알림
          if (r.ok) T.toast(`"${r.data.name}"을(를) 저장했습니다.`); else T.toast(T.errorText(r), 'error');
          return;
        }
        if (!r.ok) {
          if (r.data && r.data.code === 'PLG_SIMILAR_NAME') { st.similar = (r.data.details || []).map((x) => x.name).filter(Boolean).join(', ') || '있음'; st.error = ''; draw(); return; }
          st.error = errorBox(r);
          draw();
          return;
        }
        T.toast(t ? `"${r.data.name}"을(를) 저장했습니다.` : `템플릿 "${r.data.name}"을(를) 만들었습니다.`);
        this.dirty = () => false;
        this.editing = r.data.process_template_id;
        this.showEditor(this.editing);
      };
      draw();
    },
  };

  T.register('prod-master', Master);
  window.TempEntryMaster = Master;
})();
