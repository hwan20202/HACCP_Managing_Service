// =============================================
// 개발 검증 › 문서 작성 (P1 DOC 사용 화면)
// 화면: DOC-SC-01 목록 · 02 양식 선택 · 03 작성/수정 폼 · 04 상세(+ P3 결재 영역) · 05 삭제 확인
// 설계: dev-notes/document/s1-screens.md, API: s2-spec.md 4장
// =============================================
(function () {
  const T = window.TempEntry;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);
  const EDITABLE = ['draft', 'rejected'];

  function today(offset = 0) {
    const d = new Date();
    d.setDate(d.getDate() + offset);
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  const Doc = {
    title: '문서 작성',
    root: null,
    templates: null,
    filters: { from: today(-6), to: today(0), template_id: '', status: '', mine: false, assigned: false, page: 1 },
    form: null,

    start(root) {
      this.root = root;
      const intent = T.takeIntent();
      if (intent && intent.documentId) this.showDetail(intent.documentId);
      else this.showList();
    },

    async loadTemplates() {
      if (!this.templates) {
        const r = await api.get('templates');
        this.templates = r.ok ? r.data.items : [];
      }
      return this.templates;
    },

    rerenderTopBar(redraw) {
      T.bindTopBar(this.root, redraw);
    },

    // ================================================= DOC-SC-01 목록
    async showList() {
      const f = this.filters;
      const templates = await this.loadTemplates();
      const statusOptions = ['', 'draft', 'submitted', 'approved', 'rejected']
        .map((s) => `<option value="${s}" ${f.status === s ? 'selected' : ''}>${s ? T.STATUS[s].label : '전체'}</option>`).join('');
      const templateOptions = ['<option value="">전체</option>']
        .concat(templates.map((t) => `<option value="${t.template_id}" ${String(f.template_id) === String(t.template_id) ? 'selected' : ''}>${esc(t.name)} v${t.version}</option>`))
        .join('');
      this.root.innerHTML = `
        <div class="fade-in" id="teDocList">
          ${T.topBar('문서 작성', '문서 도메인(P1) 사용 화면 — 작성·조회·수정·삭제')}
          <div class="card">
            <div class="te-filters">
              <div class="form-group"><label class="form-label">작업일 시작</label><input type="date" class="form-control" id="fFrom" value="${f.from}"></div>
              <div class="form-group"><label class="form-label">작업일 종료</label><input type="date" class="form-control" id="fTo" value="${f.to}"></div>
              <div class="form-group"><label class="form-label">양식</label><select class="form-control" id="fTemplate">${templateOptions}</select></div>
              <div class="form-group"><label class="form-label">상태</label><select class="form-control" id="fStatus">${statusOptions}</select></div>
              <label class="te-check"><input type="checkbox" id="fMine" ${f.mine ? 'checked' : ''}> 내가 작성</label>
              <label class="te-check"><input type="checkbox" id="fAssigned" ${f.assigned ? 'checked' : ''}> 내 담당</label>
              <button class="btn btn-secondary" id="fSearch">조회</button>
              <span style="flex:1"></span>
              <button class="btn btn-primary" id="btnNew">+ 새 문서</button>
            </div>
            <div class="te-table-wrap" id="teListBody">${this.skeleton()}</div>
          </div>
        </div>`;
      this.rerenderTopBar(() => this.showList());
      const $ = (id) => this.root.querySelector(id);
      $('#fSearch').addEventListener('click', () => {
        Object.assign(f, {
          from: $('#fFrom').value, to: $('#fTo').value, template_id: $('#fTemplate').value,
          status: $('#fStatus').value, mine: $('#fMine').checked, assigned: $('#fAssigned').checked, page: 1,
        });
        this.loadList();
      });
      $('#btnNew').addEventListener('click', () => this.showPicker());
      this.loadList();
    },

    skeleton() {
      const row = '<tr class="te-skeleton">' + '<td>.</td>'.repeat(7) + '</tr>';
      return `<table class="data-table"><tbody>${row.repeat(3)}</tbody></table>`;
    },

    async loadList() {
      const f = this.filters;
      const body = this.root.querySelector('#teListBody');
      body.innerHTML = this.skeleton();
      if ((f.mine || f.assigned) && !api.staffId) {
        body.innerHTML = '<div class="te-empty">"내가 작성/내 담당"은 현재 사용자를 먼저 선택하세요.</div>';
        return;
      }
      const q = new URLSearchParams();
      if (f.from) q.set('from', f.from);
      if (f.to) q.set('to', f.to);
      if (f.template_id) q.set('template_id', f.template_id);
      if (f.status) q.set('status', f.status);
      if (f.mine) q.set('author_id', api.staffId);
      if (f.assigned) q.set('assignee_id', api.staffId);
      q.set('page', f.page);
      const r = await api.get(`documents?${q}`);
      if (!r.ok) {
        T.toast(T.errorText(r), 'error');
        body.innerHTML = `<div class="te-empty">${esc(r.data?.message || '조회에 실패했습니다.')}</div>`;
        return;
      }
      const { items, total, page, page_size: size } = r.data;
      if (!items.length) {
        body.innerHTML = '<div class="te-empty">조건에 맞는 문서가 없습니다.<br><br><button class="btn btn-primary btn-sm" id="btnNew2">+ 새 문서</button></div>';
        body.querySelector('#btnNew2').addEventListener('click', () => this.showPicker());
        return;
      }
      const pages = Math.max(1, Math.ceil(total / size));
      body.innerHTML = `
        <table class="data-table">
          <thead><tr><th>번호</th><th>양식(버전)</th><th>대상</th><th>작업일</th><th>작성/담당</th><th>상태</th><th>작성일</th></tr></thead>
          <tbody>${items.map((d) => `
            <tr class="te-row-link" data-id="${d.document_id}">
              <td>${d.document_id}</td>
              <td>${esc(d.template.name)} v${d.template.version}</td>
              <td>${esc(d.subject || '-')}</td>
              <td>${d.work_date}</td>
              <td>staff ${d.created_by} / ${d.assignee_id ? `staff ${d.assignee_id}` : '-'}</td>
              <td>${T.statusBadge(d.status)}</td>
              <td>${T.fmtDateTime(d.created_at)}</td>
            </tr>`).join('')}</tbody>
        </table>
        <div class="te-pager">
          <button class="btn btn-secondary btn-sm" data-page="${page - 1}" ${page <= 1 ? 'disabled' : ''}>‹</button>
          <span>${page} / ${pages} · 총 ${total}건 · ${size}건씩</span>
          <button class="btn btn-secondary btn-sm" data-page="${page + 1}" ${page >= pages ? 'disabled' : ''}>›</button>
        </div>`;
      body.querySelectorAll('tr[data-id]').forEach((tr) =>
        tr.addEventListener('click', () => this.showDetail(Number(tr.dataset.id))));
      body.querySelectorAll('button[data-page]').forEach((b) =>
        b.addEventListener('click', () => { f.page = Number(b.dataset.page); this.loadList(); }));
    },

    // ================================================= DOC-SC-02 양식 선택
    async showPicker() {
      const templates = await this.loadTemplates();
      this.root.innerHTML = `
        <div class="fade-in">
          ${T.topBar('새 문서 › 양식 선택', '활성 양식 중 유형별 최신 버전만 표시됩니다.')}
          ${templates.length ? `<div class="te-cards">${templates.map((t) => `
            <div class="card">
              <div class="card-title">${esc(t.name)}</div>
              <div class="te-card-meta">${esc(t.type_code)} · v${t.version}</div>
              <div class="te-hint">${t.sections.map((s) => `${esc(s.label)}${s.repeat ? '(반복)' : ''}`).join(' · ')}</div>
              <div class="te-actions"><button class="btn btn-primary btn-sm" data-template="${t.template_id}">선택</button></div>
            </div>`).join('')}</div>`
          : '<div class="te-empty">사용 가능한 양식이 없습니다 (개발용 시드 데이터를 넣으세요).</div>'}
          <div class="te-actions"><button class="btn btn-secondary" id="btnCancel">취소</button></div>
        </div>`;
      this.rerenderTopBar(() => this.showPicker());
      this.root.querySelector('#btnCancel').addEventListener('click', () => this.showList());
      this.root.querySelectorAll('button[data-template]').forEach((b) =>
        b.addEventListener('click', () => this.openForm({ templateId: Number(b.dataset.template) })));
    },

    // ================================================= DOC-SC-03 작성/수정 폼
    async openForm({ templateId, document, pending }) {
      const tid = document ? document.template.template_id : templateId;
      const r = await api.get(`templates/${tid}`);
      if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
      const schema = r.data.schema;
      let uid = 0;
      const rows = [];
      const sectionByKey = Object.fromEntries(schema.sections.map((s) => [s.key, s]));
      if (document) {
        document.sections.forEach((s) => rows.push({
          uid: ++uid, key: s.section_def, sectionId: s.section_id,
          values: { ...s.values }, original: { ...s.values }, deleted: false,
        }));
      } else {
        schema.sections.forEach((s) => {
          if (!s.repeat) rows.push({ uid: ++uid, key: s.key, sectionId: null, values: {}, original: null, deleted: false });
        });
      }
      const basic = document
        ? { subject: document.subject || '', work_date: document.work_date, assignee_id: document.assignee_id ? String(document.assignee_id) : '', due_at: document.due_at ? document.due_at.slice(0, 16) : '' }
        : { subject: '', work_date: today(0), assignee_id: '', due_at: '' };
      this.form = {
        mode: document ? 'edit' : 'create', template: r.data, schema, sectionByKey, document,
        rows, basic, originalBasic: { ...basic }, nextUid: uid, errors: {}, errorList: [],
        pending: pending || [],
      };
      if (!document) schema.sections.filter((s) => s.repeat).forEach((s) => this.addRow(s.key, false));
      this.renderForm();
    },

    addRow(key, redraw = true) {
      const f = this.form;
      f.rows.push({ uid: ++f.nextUid, key, sectionId: null, values: {}, original: null, deleted: false });
      if (redraw) this.renderForm();
    },

    fieldInput(field, value, rowUid) {
      const name = `data-row="${rowUid}" data-field="${field.key}"`;
      const v = value === undefined || value === null ? '' : value;
      const staffOptions = ['<option value="">-</option>']
        .concat((T.staff || []).map((id) => `<option value="${id}" ${String(v) === String(id) ? 'selected' : ''}>staff ${id}</option>`)).join('');
      switch (field.type) {
        case 'number': return `<input type="number" step="any" class="form-control" ${name} value="${esc(v)}">`;
        case 'time': return `<input type="time" class="form-control" ${name} value="${esc(v)}">`;
        case 'date': return `<input type="date" class="form-control" ${name} value="${esc(v)}">`;
        case 'bool': return `<input type="checkbox" ${name} ${v === true ? 'checked' : ''}>`;
        case 'staff': return `<select class="form-control" ${name}>${staffOptions}</select>`;
        case 'select': return `<select class="form-control" ${name}><option value="">-</option>${field.options.map((o) => `<option ${o === v ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
        default: return `<input type="text" class="form-control" ${name} value="${esc(v)}" ${field.max_length ? `maxlength="${field.max_length}"` : ''}>`;
      }
    },

    readInput(el, field) {
      if (field.type === 'bool') return el.checked ? true : undefined;
      const raw = el.value;
      if (raw === '') return undefined;
      if (field.type === 'number') { const n = Number(raw); return Number.isNaN(n) ? raw : n; }
      if (field.type === 'staff') return Number(raw);
      return raw;
    },

    judge(section, values) {
      const limited = section.fields.filter((fd) => fd.limit);
      if (!limited.length) return null;
      let missing = false;
      for (const fd of limited) {
        const v = values[fd.key];
        if (typeof v !== 'number') { missing = true; continue; }
        if ((fd.limit.min !== undefined && v < fd.limit.min) || (fd.limit.max !== undefined && v > fd.limit.max)) return 'ng';
      }
      return missing ? null : 'ok';
    },

    judgeCell(section, values) {
      const j = this.judge(section, values);
      if (j === 'ok') return '<span class="te-judge-ok">적합</span>';
      if (j === 'ng') return '<span class="te-judge-ng">⚠ 부적합</span>';
      return '<span class="te-hint">-</span>';
    },

    rowState(row) {
      if (row.deleted) return 'deleted';
      if (!row.sectionId) return 'new';
      return Object.keys(this.rowPatch(row)).length ? 'changed' : '';
    },

    rowPatch(row) {
      const patch = {};
      const keys = new Set([...Object.keys(row.original || {}), ...Object.keys(row.values)]);
      keys.forEach((k) => {
        const a = (row.original || {})[k];
        const b = row.values[k];
        if (JSON.stringify(a) !== JSON.stringify(b)) patch[k] = b === undefined ? null : b;
      });
      return patch;
    },

    basicChanges() {
      const f = this.form;
      const out = {};
      Object.keys(f.basic).forEach((k) => {
        if (f.basic[k] !== f.originalBasic[k]) out[k] = f.basic[k];
      });
      return out;
    },

    isDirty() {
      const f = this.form;
      if (f.mode === 'create') return true;
      return Object.keys(this.basicChanges()).length > 0 || f.rows.some((r) => this.rowState(r));
    },

    errorFor(rowUid, key) {
      const msg = this.form.errors[`${rowUid}.${key}`];
      return msg ? `<div class="te-error-text">${esc(msg)}</div>` : '';
    },

    renderForm() {
      const f = this.form;
      const d = f.document;
      const title = f.mode === 'create' ? `새 문서 › ${f.template.name} v${f.template.version}` : `문서 #${d.document_id} 수정 › ${f.template.name} v${f.template.version}`;
      const staffOptions = (sel) => ['<option value="">-</option>']
        .concat((T.staff || []).map((id) => `<option value="${id}" ${String(sel) === String(id) ? 'selected' : ''}>staff ${id}</option>`)).join('');
      const changed = this.basicChanges();
      const cls = (k) => (f.mode === 'edit' && k in changed ? 'te-field-changed' : '') + (f.errors[`basic.${k}`] ? ' te-field-error' : '');
      const basicErr = (k) => (f.errors[`basic.${k}`] ? `<div class="te-error-text">${esc(f.errors[`basic.${k}`])}</div>` : '');
      const future = f.basic.work_date > today(0) ? '<div class="te-hint">미래 날짜입니다(작성 지시용).</div>' : '';
      const author = f.mode === 'create' ? (api.staffId ? `staff ${api.staffId} (자동)` : '현재 사용자 미선택') : `staff ${d.created_by}`;

      const sectionsHtml = f.schema.sections.map((s) => {
        const rows = f.rows.filter((r) => r.key === s.key);
        const sectionErr = f.errors[`section.${s.key}`] ? `<div class="te-error-text">${esc(f.errors[`section.${s.key}`])}</div>` : '';
        if (!s.repeat) {
          const row = rows[0];
          return `<div class="te-section"><div class="te-section-head"><span class="te-section-title">${esc(s.label)}</span><span class="te-hint">행 1개</span></div>${sectionErr}
            <div class="te-grid">${s.fields.map((fd) => `
              <div class="form-group"><label class="form-label">${esc(fd.label)}${fd.required ? ' *' : ''}${fd.unit ? ` (${esc(fd.unit)})` : ''}</label>
                ${this.fieldInput(fd, row.values[fd.key], row.uid)}${this.errorFor(row.uid, fd.key)}</div>`).join('')}</div></div>`;
        }
        const hasJudge = s.fields.some((fd) => fd.limit);
        const limits = s.fields.filter((fd) => fd.limit).map((fd) => `${fd.label} ${fd.limit.min !== undefined ? `${fd.limit.min}${fd.unit || ''} 이상` : ''}${fd.limit.max !== undefined ? ` ${fd.limit.max}${fd.unit || ''} 이하` : ''}`).join(', ');
        return `<div class="te-section">
          <div class="te-section-head"><span class="te-section-title">${esc(s.label)} <span class="te-hint">반복${s.max_rows ? ` · 최대 ${s.max_rows}행` : ''}${limits ? ` · 한계기준: ${esc(limits)} (판정은 화면 표시용)` : ''}</span></span>
            <button class="btn btn-secondary btn-sm" data-add="${s.key}">+ 행 추가</button></div>${sectionErr}
          <div class="te-table-wrap"><table class="data-table te-rows">
            <thead><tr><th>#</th>${s.fields.map((fd) => `<th>${esc(fd.label)}${fd.required ? ' *' : ''}${fd.unit ? ` (${esc(fd.unit)})` : ''}</th>`).join('')}${hasJudge ? '<th>판정</th>' : ''}<th></th></tr></thead>
            <tbody>${rows.length ? rows.map((row, i) => `
              <tr class="te-row-${this.rowState(row) || 'same'}" data-tr="${row.uid}">
                <td>${i + 1}</td>
                ${s.fields.map((fd) => `<td>${this.fieldInput(fd, row.values[fd.key], row.uid)}${this.errorFor(row.uid, fd.key)}</td>`).join('')}
                ${hasJudge ? `<td data-judge="${row.uid}">${this.judgeCell(s, row.values)}</td>` : ''}
                <td><button class="btn btn-secondary btn-sm" data-del="${row.uid}" title="${row.deleted ? '삭제 취소' : '행 삭제'}">${row.deleted ? '↺' : '✕'}</button></td>
              </tr>`).join('') : `<tr><td colspan="${s.fields.length + 3}" class="te-empty">행이 없습니다.</td></tr>`}</tbody>
          </table></div></div>`;
      }).join('');

      this.root.innerHTML = `
        <div class="fade-in">
          ${T.topBar(title, f.mode === 'edit' ? '바뀐 부분만 저장됩니다. 노란색=변경, 초록색=추가, 취소선=삭제 예정' : '기본 정보와 영역 값을 입력하세요.', d && d.document_id)}
          ${f.pending.length ? `<div class="te-notice"><strong>다른 사용자가 먼저 수정해서 최신 내용으로 다시 열었습니다.</strong> 아래 변경을 다시 입력하세요.<ul class="te-pending">${f.pending.map((p) => `<li>${esc(p)}</li>`).join('')}</ul></div>` : ''}
          ${f.errorList.length ? `<div class="te-error-box"><strong>입력값을 확인하세요.</strong><ul>${f.errorList.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></div>` : ''}
          <div class="card">
            <div class="card-header"><div class="card-title">문서 정보</div><div class="te-hint">작성자: ${esc(author)}</div></div>
            <div class="te-grid">
              <div class="form-group"><label class="form-label">대상</label><input class="form-control ${cls('subject')}" data-basic="subject" maxlength="100" value="${esc(f.basic.subject)}">${basicErr('subject')}</div>
              <div class="form-group"><label class="form-label">작업일 *</label><input type="date" class="form-control ${cls('work_date')}" data-basic="work_date" value="${esc(f.basic.work_date)}">${basicErr('work_date')}${future}</div>
              <div class="form-group"><label class="form-label">담당자</label><select class="form-control ${cls('assignee_id')}" data-basic="assignee_id">${staffOptions(f.basic.assignee_id)}</select>${basicErr('assignee_id')}</div>
              <div class="form-group"><label class="form-label">마감</label><input type="datetime-local" class="form-control ${cls('due_at')}" data-basic="due_at" value="${esc(f.basic.due_at)}">${basicErr('due_at')}</div>
            </div>
            ${sectionsHtml}
            <div class="te-actions">
              <button class="btn btn-secondary" id="btnCancel">취소</button>
              <button class="btn btn-primary" id="btnSave" ${!api.staffId || !this.isDirty() ? 'disabled' : ''}>저장</button>
            </div>
          </div>
        </div>`;
      this.bindForm();
    },

    bindForm() {
      const f = this.form;
      const root = this.root;
      this.rerenderTopBar(() => this.renderForm());
      root.querySelectorAll('[data-basic]').forEach((el) => el.addEventListener('input', () => {
        f.basic[el.dataset.basic] = el.value;
        if (f.mode === 'edit') el.classList.toggle('te-field-changed', f.basic[el.dataset.basic] !== f.originalBasic[el.dataset.basic]);
        this.refreshSave();
      }));
      root.querySelectorAll('[data-row][data-field]').forEach((el) => {
        const handler = () => {
          const row = f.rows.find((r) => r.uid === Number(el.dataset.row));
          const field = f.sectionByKey[row.key].fields.find((fd) => fd.key === el.dataset.field);
          const value = this.readInput(el, field);
          if (value === undefined) delete row.values[field.key]; else row.values[field.key] = value;
          const tr = root.querySelector(`tr[data-tr="${row.uid}"]`);
          if (tr) tr.className = `te-row-${this.rowState(row) || 'same'}`;
          const judge = root.querySelector(`[data-judge="${row.uid}"]`);
          if (judge) judge.innerHTML = this.judgeCell(f.sectionByKey[row.key], row.values);
          this.refreshSave();
        };
        el.addEventListener('input', handler);
        el.addEventListener('change', handler);
      });
      root.querySelectorAll('[data-add]').forEach((b) => b.addEventListener('click', () => this.addRow(b.dataset.add)));
      root.querySelectorAll('[data-del]').forEach((b) => b.addEventListener('click', () => {
        const row = f.rows.find((r) => r.uid === Number(b.dataset.del));
        if (row.sectionId) row.deleted = !row.deleted; else f.rows.splice(f.rows.indexOf(row), 1);
        this.renderForm();
      }));
      root.querySelector('#btnCancel').addEventListener('click', async () => {
        if (f.mode === 'edit' && this.isDirty() && !(await T.confirm('변경 취소', '변경 내용을 버릴까요?', '버리기', 'btn-danger'))) return;
        if (f.mode === 'edit') this.showDetail(f.document.document_id); else this.showList();
      });
      root.querySelector('#btnSave').addEventListener('click', () => this.save());
    },

    refreshSave() {
      const btn = this.root.querySelector('#btnSave');
      if (btn) btn.disabled = !api.staffId || !this.isDirty();
    },

    basicPayload(source) {
      const out = {};
      Object.entries(source).forEach(([k, v]) => {
        if (k === 'assignee_id') out[k] = v === '' ? null : Number(v);
        else if (k === 'subject' || k === 'due_at') out[k] = v === '' ? null : v;
        else out[k] = v;
      });
      return out;
    },

    async save() {
      const f = this.form;
      const pathMap = {};
      let result;
      if (f.mode === 'create') {
        const sections = [];
        f.schema.sections.forEach((s) => f.rows.filter((r) => r.key === s.key && !r.deleted).forEach((r) => {
          pathMap[`sections[${sections.length}]`] = r.uid;
          sections.push({ section_def: r.key, values: r.values });
        }));
        result = await api.post('documents', { template_id: f.template.template_id, ...this.basicPayload(f.basic), sections });
      } else {
        const body = { expected_version: f.document.version };
        const docChanges = this.basicPayload(this.basicChanges());
        if (Object.keys(docChanges).length) body.document = docChanges;
        const add = []; const update = []; const del = [];
        f.rows.forEach((r) => {
          const state = this.rowState(r);
          if (state === 'deleted') { pathMap[`sections.delete[${r.sectionId}]`] = r.uid; del.push(r.sectionId); }
          else if (state === 'new') { pathMap[`sections.add[${add.length}]`] = r.uid; add.push({ section_def: r.key, values: r.values }); }
          else if (state === 'changed') { pathMap[`sections.update[${update.length}]`] = r.uid; update.push({ section_id: r.sectionId, values: this.rowPatch(r) }); }
        });
        const sections = {};
        if (add.length) sections.add = add;
        if (update.length) sections.update = update;
        if (del.length) sections.delete = del;
        if (Object.keys(sections).length) body.sections = sections;
        result = await api.patch(`documents/${f.document.document_id}`, body);
      }
      if (result.ok) {
        T.toast('저장했습니다.', 'success');
        this.showDetail(result.data.document_id);
        return;
      }
      const data = result.data || {};
      if (data.code === 'VERSION_CONFLICT') {
        await this.handleConflict(data);
        return;
      }
      if (data.code === 'DOCUMENT_LOCKED' || data.code === 'DOCUMENT_NOT_FOUND') {
        await T.modal({ title: '저장할 수 없습니다', body: `<p>${esc(data.message)}</p>`, buttons: [{ label: data.code === 'DOCUMENT_LOCKED' ? '상세로' : '목록으로', value: true, cls: 'btn-primary' }] });
        if (data.code === 'DOCUMENT_LOCKED') this.showDetail(f.document.document_id); else this.showList();
        return;
      }
      this.applyErrors(data, pathMap);
    },

    // ================================================= DOC-SC-06 수정 충돌 (ISS-001)
    changeSummary() {
      const f = this.form;
      const labels = { subject: '대상', work_date: '작업일', assignee_id: '담당자', due_at: '마감' };
      const out = Object.entries(this.basicChanges()).map(([k, v]) => `${labels[k]}: ${v === '' ? '(비움)' : (k === 'assignee_id' ? `staff ${v}` : v)}`);
      f.schema.sections.forEach((s) => {
        const fieldLabel = (key) => (s.fields.find((fd) => fd.key === key) || { label: key }).label;
        const fmt = (values) => Object.entries(values).map(([k, v]) => `${fieldLabel(k)} ${v === null ? '(비움)' : v}`).join(', ');
        f.rows.filter((r) => r.key === s.key).forEach((r, i) => {
          const state = this.rowState(r);
          const where = s.repeat ? `${s.label} ${i + 1}행` : s.label;
          if (state === 'changed') out.push(`${where}: ${fmt(this.rowPatch(r))}`);
          else if (state === 'deleted') out.push(`${where} 삭제`);
          else if (state === 'new') out.push(`${s.label} 행 추가: ${fmt(r.values)}`);
        });
      });
      return out;
    },

    async handleConflict(data) {
      const f = this.form;
      const info = (data.details || [])[0] || {};
      const pending = this.changeSummary();
      const reopen = await T.modal({
        title: '다른 사용자가 먼저 수정했습니다',
        body: `<p>이 문서는 내가 연 뒤에 다시 저장되었습니다.<br>
          <span class="te-hint">내가 연 버전 ${esc(info.expected ?? f.document.version)} → 현재 버전 ${esc(info.current ?? '?')}${info.updated_at ? `, 마지막 수정 ${esc(T.fmtDateTime(info.updated_at))}` : ''}</span></p>
          ${pending.length ? `<p style="margin-top:.6rem"><b>내가 바꾼 내용</b> (다시 입력해야 함)</p><ul class="te-pending">${pending.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : ''}`,
        buttons: [{ label: '이 화면에 머물기', value: false }, { label: '최신 내용으로 다시 열기', value: true, cls: 'btn-primary' }],
      });
      if (!reopen) return;
      const latest = await api.get(`documents/${f.document.document_id}`);
      if (!latest.ok) { T.toast(T.errorText(latest), 'error'); this.showList(); return; }
      this.openForm({ document: latest.data, pending });
    },

    applyErrors(data, pathMap) {
      const f = this.form;
      f.errors = {};
      f.errorList = [];
      (data.details || []).forEach((e) => {
        const path = e.path || '';
        const basic = /^(?:document\.)?(subject|work_date|assignee_id|due_at)$/.exec(path);
        const row = /^(sections(?:\.(?:update|add|delete))?\[[^\]]+\])(?:\.values\.(\w+)|\.round)?$/.exec(path);
        const section = /^sections\[(\w+)\]$/.exec(path);
        if (basic) f.errors[`basic.${basic[1]}`] = e.message;
        else if (row && pathMap[row[1]] !== undefined) f.errors[`${pathMap[row[1]]}.${row[2] || 'round'}`] = e.message;
        else if (section && f.sectionByKey[section[1]]) f.errors[`section.${section[1]}`] = e.message;
        f.errorList.push(e.message);
      });
      if (!f.errorList.length) f.errorList.push(data.message || '저장에 실패했습니다.');
      T.toast(`[${data.code}] ${data.message}`, 'error');
      this.renderForm();
    },

    // ================================================= DOC-SC-04 상세
    async showDetail(id) {
      const r = await api.get(`documents/${id}`);
      if (!r.ok) {
        this.root.innerHTML = `<div class="fade-in">${T.topBar('문서 상세', '')}<div class="card te-empty">${r.status === 404 ? '문서를 찾을 수 없습니다 (삭제되었을 수 있습니다).' : esc(T.errorText(r))}<br><br><button class="btn btn-secondary" id="btnBack">목록</button></div></div>`;
        this.rerenderTopBar(() => this.showDetail(id));
        this.root.querySelector('#btnBack').addEventListener('click', () => this.showList());
        return;
      }
      const d = r.data;
      const t = await api.get(`templates/${d.template.template_id}`);
      const schema = t.ok ? t.data.schema : { sections: [] };
      const canEdit = EDITABLE.includes(d.status);
      const canDelete = d.status === 'draft' && !d.submitted_at;
      const notes = {
        submitted: '결재 진행 중인 문서는 수정할 수 없습니다.',
        approved: '승인된 문서는 수정할 수 없습니다.',
        rejected: '반려된 문서입니다. 수정할 수 있습니다(삭제는 불가 — 상신 이력 보존).',
      };
      if (d.status === 'draft' && d.submitted_at) notes.draft = '상신 이력이 있어 삭제할 수 없습니다.';
      const sections = this.sectionsHtml(schema, d);
      this.root.innerHTML = `
        <div class="fade-in">
          ${T.topBar(`문서 #${d.document_id} · ${d.template.name} v${d.template.version}`, '문서 상세', d.document_id)}
          <div class="card">
            <div class="card-header">
              <div class="card-title">${T.statusBadge(d.status)}</div>
              <div class="page-actions">
                <button class="btn btn-secondary btn-sm" id="btnList">목록</button>
                ${canEdit ? `<button class="btn btn-primary btn-sm" id="btnEdit" ${api.staffId ? '' : 'disabled'}>수정</button>` : ''}
                ${canDelete ? `<button class="btn btn-danger btn-sm" id="btnDelete" ${api.staffId ? '' : 'disabled'}>삭제</button>` : ''}
              </div>
            </div>
            ${notes[d.status] ? `<div class="te-status-note">${notes[d.status]}</div>` : ''}
            <div class="te-meta">
              <span>대상 <b>${esc(d.subject || '-')}</b></span><span>작업일 <b>${d.work_date}</b></span>
              <span>작성자 <b>staff ${d.created_by}</b></span><span>담당자 <b>${d.assignee_id ? `staff ${d.assignee_id}` : '-'}</b></span>
              <span>마감 <b>${T.fmtDateTime(d.due_at)}</b></span>
            </div>
            <div class="te-meta" style="margin-top:.25rem">
              <span>작성 ${T.fmtDateTime(d.created_at)}</span><span>최종 수정 ${T.fmtDateTime(d.updated_at)}</span>${d.submitted_at ? `<span>상신 ${T.fmtDateTime(d.submitted_at)}</span>` : ''}
            </div>
            ${sections}
            <div id="teApprovalArea"></div>
          </div>
        </div>`;
      this.rerenderTopBar(() => this.showDetail(id));
      this.root.querySelector('#btnList').addEventListener('click', () => this.showList());
      this.root.querySelector('#btnEdit')?.addEventListener('click', () => this.openForm({ document: d }));
      this.root.querySelector('#btnDelete')?.addEventListener('click', () => this.confirmDelete(d));
      // P3 결재 영역 (WF-SC-01) — temp-entry/approval/approval.js
      const area = this.root.querySelector('#teApprovalArea');
      if (window.TempEntryApproval) window.TempEntryApproval.mountArea(area, d, () => this.showDetail(id));
    },

    // 문서 내용(섹션) 읽기 전용 표시. 결재 요청 상세(WF-SC-04)도 스냅샷을 이 함수로 그린다.
    sectionsHtml(schema, d) {
      return schema.sections.map((s) => {
        const rows = d.sections.filter((x) => x.section_def === s.key);
        if (!s.repeat) {
          const v = rows[0] ? rows[0].values : {};
          return `<div class="te-section"><div class="te-section-title">${esc(s.label)}</div>
            <dl class="te-kv">${s.fields.map((fd) => `<div><dt>${esc(fd.label)}</dt><dd>${this.display(fd, v[fd.key])}</dd></div>`).join('')}</dl></div>`;
        }
        const hasJudge = s.fields.some((fd) => fd.limit);
        const body = rows.map((x, i) => `<tr class="${this.judge(s, x.values) === 'ng' ? 'te-row-ng' : ''}">
            <td>${i + 1}</td>${s.fields.map((fd) => `<td>${this.display(fd, x.values[fd.key])}</td>`).join('')}
            ${hasJudge ? `<td>${this.judgeCell(s, x.values)}</td>` : ''}
            <td class="te-hint">${T.fmtDateTime(x.recorded_at)} · staff ${x.recorded_by ?? '-'}</td></tr>`).join('')
          || `<tr><td colspan="${s.fields.length + 3}" class="te-empty">행이 없습니다.</td></tr>`;
        return `<div class="te-section"><div class="te-section-title">${esc(s.label)} <span class="te-hint">${rows.length}행</span></div>
          <div class="te-table-wrap"><table class="data-table"><thead><tr><th>#</th>${s.fields.map((fd) => `<th>${esc(fd.label)}${fd.unit ? ` (${esc(fd.unit)})` : ''}</th>`).join('')}${hasJudge ? '<th>판정</th>' : ''}<th>기록</th></tr></thead>
          <tbody>${body}</tbody></table></div></div>`;
      }).join('');
    },

    display(field, value) {
      if (value === undefined || value === null || value === '') return '<span class="te-hint">-</span>';
      if (field.type === 'bool') return value ? '예' : '아니오';
      if (field.type === 'staff') return `staff ${esc(value)}`;
      return esc(value);
    },

    // ================================================= DOC-SC-05 삭제 확인
    async confirmDelete(d) {
      const ok = await T.confirm('문서 삭제',
        `문서 #${d.document_id} (${esc(d.template.name)}, ${d.work_date})를 삭제합니다.<br>목록에서 사라지지만 기록은 삭제자·삭제 시각과 함께 보존됩니다.`,
        '삭제', 'btn-danger');
      if (!ok) return;
      const r = await api.del(`documents/${d.document_id}`);
      if (r.ok) { T.toast('삭제했습니다.', 'success'); this.showList(); return; }
      await T.modal({ title: '삭제할 수 없습니다', body: `<p>${esc(r.data?.message || T.errorText(r))}</p>`, buttons: [{ label: '확인', value: true, cls: 'btn-primary' }] });
      this.showDetail(d.document_id);
    },
  };

  T.register('temp-doc', Doc);
  window.TempEntryDocument = Doc;
})();
