// =============================================
// 개발 검증 › 문서 작성 (P1 DOC 사용 화면 + P4 확장)
// 화면: DOC-SC-01 목록 · 02 양식 선택 · 03 작성/수정 폼 · 04 상세(+ P3 결재 영역) · 05 삭제 확인
//       P4: 09 작성완료 확인·검사 결과, 이탈·개선조치 영역, 작성 요구 문서 표시
//       P6: 정정 시작(WF-SC-08)·정정 배너·정정 취소(WF-SC-10), D03 작성완료의 판정 전달(DOC-SC-09)
// 설계: dev-notes/document/s1-screens.md, p4-s1-screens.md, document-workflow/p6-s1-screens.md(+ p6a 3.2)
//       API: s2-spec.md 4장, p4-s2-spec.md, p6-s2-spec.md
// 파일 영역(SC-07·08)은 스프린트 3(D-058)
// =============================================
(function () {
  const T = window.TempEntry;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);
  const EDITABLE = ['draft', 'rejected', 'correcting'];  // P6: 정정 중도 수정·작성완료
  const COMPLETABLE = ['draft', 'rejected', 'correcting'];
  const REASON_MAX = 200;
  const REQUIREMENT = { lot: '⚙ 입고', batch: '⚙ 생산' };

  function today(offset = 0) {
    const d = new Date();
    d.setDate(d.getDate() + offset);
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  // ---------------------------------------------------------------- 판정 계산 (서버 validation.evaluate와 같은 규칙)
  // 비교할 값이 비어 있으면 null. 화면 표시용이며 저장 값은 서버가 계산한다(P4-S2-Q5).
  function compare(item, value) {
    if (value === undefined || value === null || value === '') return null;
    if ('eq' in item && value !== item.eq) return false;
    if ('in' in item && !item.in.includes(value)) return false;
    const numeric = ['min', 'max', 'gt', 'lt'].some((k) => k in item);
    if (numeric && typeof value !== 'number') return false;
    if ('min' in item && !(value >= item.min)) return false;
    if ('max' in item && !(value <= item.max)) return false;
    if ('gt' in item && !(value > item.gt)) return false;
    if ('lt' in item && !(value < item.lt)) return false;
    return true;
  }
  function evaluate(cond, values) {
    const v = values || {};
    if (cond.all) {
      const r = cond.all.map((i) => compare(i, v[i.field]));
      if (r.includes(false)) return false;
      return r.includes(null) ? null : true;
    }
    const r = (cond.any || []).map((i) => compare(i, v[i.field]));
    if (r.includes(true)) return true;
    return r.includes(null) ? null : false;
  }
  function withComputed(section, values) {
    const out = { ...(values || {}) };
    section.fields.filter((fd) => fd.computed).forEach((fd) => {
      const r = evaluate(fd.computed, out);
      if (r === null) delete out[fd.key]; else out[fd.key] = r ? fd.computed.then : fd.computed.else;
    });
    return out;
  }
  const isNonconforming = (section, values) => !!section.nonconforming && evaluate(section.nonconforming, withComputed(section, values)) === true;
  const isSystem = (fd) => fd.readonly || !!fd.computed;
  const hasComputed = (section) => section.fields.some((fd) => fd.computed);
  const optionLabel = (fd, v) => (fd.option_labels && fd.option_labels[v]) || v;
  const fmtMinutes = (m) => `${Math.floor(m / 60)}시간 ${m % 60}분`;

  // 문서 단위 LOT 문서(D01·D02·D03)의 머리 정보: 품명·매입처(P6a-S1 DOC-SC-04). info 값이 없으면 빈 배열
  function lotInfo(d) {
    const info = (d.sections || []).find((x) => x.section_def === 'info');
    const v = (info && info.values) || {};
    return [v.item_name, v.supplier_name].filter(Boolean);
  }
  // 업무 대상 표시 (DOC-SC-01·03·04)
  function targetText(d) {
    const refs = d.refs || [];
    if (!d.record_key || !refs.length) return d.subject || '-';
    const docLevel = refs.filter((r) => r.section_id === null);
    const parts = docLevel.map((r) => {
      if (r.production_batch_id !== null) return `배치 ${r.label || r.production_batch_id}${r.process_code ? ` · ${r.process_code}` : ''}`;
      if (r.lot_id !== null) return [`LOT ${r.label || r.lot_id}`, ...lotInfo(d)].join(' · ');
      return r.label || r.process_code || '-';
    });
    const rowLots = refs.filter((r) => r.section_id !== null && r.lot_id !== null);
    if (rowLots.length) parts.push(`LOT ${rowLots.length}건 (${rowLots.map((r) => r.label || r.lot_id).join(', ')})`);
    else if (!docLevel.length) parts.push('LOT 0건');
    return parts.join(' / ');
  }
  // 문서 상세용: 같은 문구에 LOT마다 "LOT별 연결 문서"(REQ-SC-05) 링크(REQ-S1-Q4)
  function targetHtml(d) {
    const refs = d.refs || [];
    if (!d.record_key || !refs.length) return esc(d.subject || '-');
    const lotLink = (r) => `<a href="#" class="te-lot-link" data-lot="${r.lot_id}" title="이 LOT의 연결 문서">${esc(r.label || r.lot_id)}</a>`;
    const docLevel = refs.filter((r) => r.section_id === null);
    const parts = docLevel.map((r) => {
      if (r.production_batch_id !== null) return esc(`배치 ${r.label || r.production_batch_id}${r.process_code ? ` · ${r.process_code}` : ''}`);
      if (r.lot_id !== null) return [`LOT ${lotLink(r)}`, ...lotInfo(d).map(esc)].join(' · ');
      return esc(r.label || r.process_code || '-');
    });
    const rowLots = refs.filter((r) => r.section_id !== null && r.lot_id !== null);
    if (rowLots.length) parts.push(`LOT ${rowLots.length}건 (${rowLots.map(lotLink).join(', ')})`);
    else if (!docLevel.length) parts.push('LOT 0건');
    return parts.join(' / ');
  }
  // 측정일시(datetime) 행이 있는 양식의 기간: 작업일 ~ 마지막 측정일(D-051 F11, 저장 컬럼 없음)
  function periodText(schema, d) {
    const dates = [];
    schema.sections.filter((s) => s.repeat).forEach((s) => s.fields.filter((fd) => fd.type === 'datetime').forEach((fd) => {
      d.sections.filter((x) => x.section_def === s.key && x.values[fd.key]).forEach((x) => dates.push(String(x.values[fd.key]).slice(0, 10)));
    }));
    if (!schema.sections.some((s) => s.repeat && s.fields.some((fd) => fd.type === 'datetime'))) return '';
    const last = dates.length ? dates.sort()[dates.length - 1] : null;
    const label = d.template && d.template.type_code === 'CCP-2B' ? '건조 기간' : '측정 기간';
    return `<span id="tePeriod">${label} <b>${esc(d.work_date)} ~ ${esc(last && last > d.work_date ? last : d.work_date)}</b> <span class="te-hint">(마지막 측정일 기준)</span></span>`;
  }
  // 정정 진행 중이면 배지 옆 `정정` 꼬리표(정정 중 상태는 배지 자체가 "정정 중", DOC-SC-01·04)
  const correctionTag = (status, correcting) => (correcting && status !== 'correcting' ? ' <span class="badge te-chip-fix">정정</span>' : '');
  const statusCell = (status, correcting) => `${T.statusBadge(status)}${correctionTag(status, correcting)}`;
  // P7 S4: 목록 묶음 줄(DOC-F04 변경, D03 작업일마다 1줄)이 화면을 깨지 않게 하는 최소 표시.
  // 묶음 줄 화면(DOC-SC-01·10)은 P7 S5에서 만든다.
  const bundleRow = (b) => `
            <tr class="te-row-bundle">
              <td>묶음</td>
              <td>${esc(b.template_name)}</td>
              <td>입고 ${b.count}건${b.count !== b.total ? ` (전체 ${b.total})` : ''}</td>
              <td>${b.work_date}</td>
              <td>-</td>
              <td>${Object.entries(b.status_counts).map(([k, n]) => `${T.statusBadge(k)} ${n}`).join(' ')}${b.correcting_count ? ` (정정 ${b.correcting_count})` : ''}</td>
              <td><span class="te-req">${REQUIREMENT[b.requirement]}</span></td>
              <td>-</td>
            </tr>`;
  const requirementChip = (d) => (d.requirement ? `<span class="badge te-chip-req">${REQUIREMENT[d.requirement]} 작성 요구</span>` : '');

  const Doc = {
    title: '문서 작성',
    root: null,
    templates: null,
    filters: { from: today(-6), to: today(0), template_id: '', status: '', target: '', mine: false, assigned: false, correcting: false, page: 1 },
    form: null,
    devDrafts: [],

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
      const statusOptions = ['', 'draft', 'completed', 'submitted', 'approved', 'rejected', 'correcting']
        .map((s) => `<option value="${s}" ${f.status === s ? 'selected' : ''}>${s ? T.STATUS[s].label : '전체'}</option>`).join('');
      const templateOptions = ['<option value="">전체</option>']
        .concat(templates.map((t) => `<option value="${t.template_id}" ${String(f.template_id) === String(t.template_id) ? 'selected' : ''}>${esc(t.name)} v${t.version}</option>`))
        .join('');
      // 육안검사 오늘 빠른 필터(P6a-S1-Q6): 그날 육안검사 묶음 화면(P7) 전까지 목록으로 본다. D03 중 최신 버전
      const d03 = templates.filter((t) => t.type_code === 'D03').sort((a, b) => b.version - a.version)[0];
      this.root.innerHTML = `
        <div class="fade-in" id="teDocList">
          ${T.topBar('문서 작성', '문서 도메인 사용 화면 — 작성·조회·수정·삭제, 작성완료(P4)')}
          <div class="card">
            <div class="te-filters">
              <div class="form-group"><label class="form-label">작업일 시작</label><input type="date" class="form-control" id="fFrom" value="${f.from}"></div>
              <div class="form-group"><label class="form-label">작업일 종료</label><input type="date" class="form-control" id="fTo" value="${f.to}"></div>
              <div class="form-group"><label class="form-label">양식</label><select class="form-control" id="fTemplate">${templateOptions}</select></div>
              <div class="form-group"><label class="form-label">상태</label><select class="form-control" id="fStatus">${statusOptions}</select></div>
              <div class="form-group"><label class="form-label">대상</label><input class="form-control" id="fTarget" maxlength="50" placeholder="LOT·배치 번호" value="${esc(f.target)}"></div>
              <label class="te-check"><input type="checkbox" id="fMine" ${f.mine ? 'checked' : ''}> 내가 작성</label>
              <label class="te-check"><input type="checkbox" id="fAssigned" ${f.assigned ? 'checked' : ''}> 내 담당</label>
              <label class="te-check" title="정정 중 + 정정 꼬리표가 붙은 작성완료·결재중"><input type="checkbox" id="fCorrecting" ${f.correcting ? 'checked' : ''}> 정정 진행 중 전체</label>
              <button class="btn btn-secondary" id="fSearch">조회</button>
              ${d03 ? '<button class="btn btn-secondary" id="fD03Today" title="작업일 = 오늘 · 양식 = 육안검사(D03)">육안검사 오늘</button>' : ''}
              <span style="flex:1"></span>
              <button class="btn btn-primary" id="btnNew">+ 새 문서</button>
            </div>
            <div class="te-table-wrap" id="teListBody">${this.skeleton()}</div>
          </div>
        </div>`;
      this.rerenderTopBar(() => this.showList());
      const $ = (id) => this.root.querySelector(id);
      const search = () => {
        Object.assign(f, {
          from: $('#fFrom').value, to: $('#fTo').value, template_id: $('#fTemplate').value,
          status: $('#fStatus').value, target: $('#fTarget').value.trim(),
          mine: $('#fMine').checked, assigned: $('#fAssigned').checked, correcting: $('#fCorrecting').checked, page: 1,
        });
        this.loadList();
      };
      $('#fSearch').addEventListener('click', search);
      if (d03) {
        $('#fD03Today').addEventListener('click', () => {
          Object.assign(f, { from: today(0), to: today(0), template_id: String(d03.template_id), status: '', target: '', mine: false, assigned: false, correcting: false, page: 1 });
          this.showList();
        });
      }
      $('#fTarget').addEventListener('keydown', (e) => { if (e.key === 'Enter') search(); });
      $('#btnNew').addEventListener('click', () => this.showPicker());
      this.loadList();
    },

    skeleton() {
      const row = '<tr class="te-skeleton">' + '<td>.</td>'.repeat(8) + '</tr>';
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
      if (f.target) q.set('target', f.target);
      if (f.mine) q.set('author_id', api.staffId);
      if (f.assigned) q.set('assignee_id', api.staffId);
      if (f.correcting) q.set('correcting', 'true');
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
          <thead><tr><th>번호</th><th>양식(버전)</th><th>대상</th><th>작업일</th><th>작성/담당</th><th>상태</th><th>작성 요구</th><th>작성일</th></tr></thead>
          <tbody>${items.map((d) => d.kind === 'bundle' ? bundleRow(d) : `
            <tr class="te-row-link" data-id="${d.document_id}">
              <td>${d.document_id}</td>
              <td>${esc(d.template.name)} v${d.template.version}</td>
              <td>${esc(d.target_summary || d.subject || '-')}</td>
              <td>${d.work_date}</td>
              <td>staff ${d.created_by} / ${d.assignee_id ? `staff ${d.assignee_id}` : '-'}</td>
              <td>${statusCell(d.status, d.correcting)}</td>
              <td>${d.requirement ? `<span class="te-req">${REQUIREMENT[d.requirement]}</span>` : '<span class="te-hint">–</span>'}</td>
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
      // 작성 요구 양식은 작성 요구로만 생긴다(P4-S1-Q1)
      const templates = (await this.loadTemplates()).filter((t) => !t.requirement_only);
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
          <p class="te-hint" id="teReqNote" style="margin-top:1rem">시험성적서·원산지·육안검사·CCP 일지는 입고·생산 시작 때 자동으로 만들어집니다.</p>
          <div class="te-actions"><button class="btn btn-secondary" id="btnCancel">취소</button></div>
        </div>`;
      this.rerenderTopBar(() => this.showPicker());
      this.root.querySelector('#btnCancel').addEventListener('click', () => this.showList());
      this.root.querySelectorAll('button[data-template]').forEach((b) =>
        b.addEventListener('click', () => this.openForm({ templateId: Number(b.dataset.template) })));
    },

    // ================================================= DOC-SC-03 작성/수정 폼
    async openForm({ templateId, document, pending, problems }) {
      const tid = document ? document.template.template_id : templateId;
      const r = await api.get(`templates/${tid}`);
      if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
      const schema = r.data.schema;
      let uid = 0;
      const rows = [];
      const sectionByKey = Object.fromEntries(schema.sections.map((s) => [s.key, s]));
      const hinted = [];
      if (document) {
        document.sections.forEach((s) => {
          const row = {
            uid: ++uid, key: s.section_def, sectionId: s.section_id, rowNo: s.row_no,
            values: { ...s.values }, original: { ...s.values }, deleted: false, hints: s.hints || {},
          };
          // hint(FR-28): 빈 칸을 계산 값으로 채운다. 저장 전까지는 "변경"으로 표시된다.
          Object.entries(row.hints).forEach(([k, v]) => {
            if (row.values[k] === undefined || row.values[k] === null || row.values[k] === '') { row.values[k] = v; hinted.push(`${row.uid}.${k}`); }
          });
          rows.push(row);
        });
      } else {
        schema.sections.forEach((s) => {
          if (!s.repeat) rows.push({ uid: ++uid, key: s.key, sectionId: null, values: {}, original: null, deleted: false, hints: {} });
        });
      }
      const basic = document
        ? { subject: document.subject || '', work_date: document.work_date, assignee_id: document.assignee_id ? String(document.assignee_id) : '', due_at: document.due_at ? document.due_at.slice(0, 16) : '' }
        : { subject: '', work_date: today(0), assignee_id: '', due_at: '' };
      this.form = {
        mode: document ? 'edit' : 'create', template: r.data, schema, sectionByKey, document,
        requirement: !!(document && document.record_key),
        rows, basic, originalBasic: { ...basic }, nextUid: uid, errors: {}, errorList: [],
        pending: pending || [], hinted: new Set(hinted),
      };
      if (!document) schema.sections.filter((s) => s.repeat && !s.system_rows).forEach((s) => this.addRow(s.key, false));
      if (problems) this.applyErrors({ code: 'COMPLETION_INCOMPLETE', message: '작성완료할 수 없습니다. 빠진 항목을 채우세요.', details: problems }, {}, true);
      else this.renderForm();
    },

    addRow(key, redraw = true) {
      const f = this.form;
      const values = {};
      // CCP-3P 제품 통과 요약: 품명 기본값 = 기본정보의 품명(배치 품목, D-060 Q2)
      const section = f.sectionByKey[key];
      const info = f.rows.find((r) => r.key === 'info');
      if (section.fields.some((fd) => fd.key === 'item_name' && !fd.readonly) && info && info.values.item_name) values.item_name = info.values.item_name;
      f.rows.push({ uid: ++f.nextUid, key, sectionId: null, values, original: null, deleted: false, hints: {} });
      if (redraw) this.renderForm();
    },

    fieldInput(field, value, row) {
      const name = `data-row="${row.uid}" data-field="${field.key}"`;
      const v = value === undefined || value === null ? '' : value;
      if (field.readonly) return `<span class="te-ro" title="자동 입력(수정 불가)">${this.display(field, value)}</span>`;
      if (field.computed) {
        const section = this.form.sectionByKey[row.key];
        return `<span data-computed="${row.uid}.${field.key}">${this.display(field, withComputed(section, row.values)[field.key])}</span>`;
      }
      const staffOptions = ['<option value="">-</option>']
        .concat((T.staff || []).map((id) => `<option value="${id}" ${String(v) === String(id) ? 'selected' : ''}>staff ${id}</option>`)).join('');
      const hintMark = this.form.hinted.has(`${row.uid}.${field.key}`) ? '<div class="te-hint">자동 제안(같은 LOT 성적서)</div>' : '';
      switch (field.type) {
        case 'number':
          if (field.display === 'hm') {
            const h = v === '' ? '' : Math.floor(v / 60);
            const m = v === '' ? '' : v % 60;
            return `<span class="te-hm"><input type="number" min="0" class="form-control" ${name} data-part="h" value="${h}">시간<input type="number" min="0" max="59" class="form-control" ${name} data-part="m" value="${m}">분</span>`;
          }
          return `<input type="number" step="any" class="form-control" ${name} value="${esc(v)}">`;
        case 'time': return `<input type="time" class="form-control" ${name} value="${esc(v)}">`;
        case 'date': return `<input type="date" class="form-control" ${name} value="${esc(v)}">`;
        case 'datetime': {
          // 날짜 기본값 = 작업일(D-051 F11). 시각을 넣어야 값이 생긴다.
          const date = v ? v.slice(0, 10) : this.form.basic.work_date;
          const time = v ? v.slice(11, 16) : '';
          return `<span class="te-dt"><input type="date" class="form-control" ${name} data-part="date" value="${esc(date)}"><input type="time" class="form-control" ${name} data-part="time" value="${esc(time)}"></span>`;
        }
        case 'bool': return `<input type="checkbox" ${name} ${v === true ? 'checked' : ''}>`;
        case 'staff': return `<select class="form-control" ${name}>${staffOptions}</select>`;
        case 'select': return `<select class="form-control" ${name}><option value="">-</option>${field.options.map((o) => `<option value="${esc(o)}" ${o === v ? 'selected' : ''}>${esc(optionLabel(field, o))}</option>`).join('')}</select>${hintMark}`;
        default: return `<input type="text" class="form-control" ${name} value="${esc(v)}" ${field.max_length ? `maxlength="${field.max_length}"` : ''}>`;
      }
    },

    readInput(el, field) {
      if (field.type === 'bool') return el.checked ? true : undefined;
      const scope = el.closest('td, .form-group') || el.parentElement;
      const part = (p) => scope.querySelector(`[data-field="${field.key}"][data-part="${p}"]`);
      if (field.type === 'datetime') {
        const date = part('date').value;
        const time = part('time').value;
        return date && time ? `${date}T${time}` : undefined;
      }
      if (field.display === 'hm') {
        const h = part('h').value;
        const m = part('m').value;
        if (h === '' && m === '') return undefined;
        return Number(h || 0) * 60 + Number(m || 0);
      }
      const raw = el.value;
      if (raw === '') return undefined;
      if (field.type === 'number') { const n = Number(raw); return Number.isNaN(n) ? raw : n; }
      if (field.type === 'staff') return Number(raw);
      return raw;
    },

    // P1 양식(한계기준 limit만 있는 섹션)의 화면 판정. P4 양식은 computed 필드가 판정이다.
    judge(section, values) {
      if (hasComputed(section)) return isNonconforming(section, values) ? 'ng' : null;
      const limited = section.fields.filter((fd) => fd.limit);
      if (!limited.length) return isNonconforming(section, values) ? 'ng' : null;
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
    legacyJudge: (s) => !hasComputed(s) && s.fields.some((fd) => fd.limit),

    rowState(row) {
      if (row.deleted) return 'deleted';
      if (!row.sectionId) return 'new';
      return Object.keys(this.rowPatch(row)).length ? 'changed' : '';
    },

    rowPatch(row) {
      const patch = {};
      const section = this.form.sectionByKey[row.key];
      const system = new Set(section.fields.filter(isSystem).map((fd) => fd.key));
      const keys = new Set([...Object.keys(row.original || {}), ...Object.keys(row.values)]);
      keys.forEach((k) => {
        if (system.has(k)) return; // 자동 값·판정은 보내지 않는다(VR-16)
        const a = (row.original || {})[k];
        const b = row.values[k];
        if (JSON.stringify(a) !== JSON.stringify(b)) patch[k] = b === undefined ? null : b;
      });
      return patch;
    },

    userValues(row) {
      const section = this.form.sectionByKey[row.key];
      const system = new Set(section.fields.filter(isSystem).map((fd) => fd.key));
      return Object.fromEntries(Object.entries(row.values).filter(([k]) => !system.has(k)));
    },

    basicChanges() {
      const f = this.form;
      const out = {};
      Object.keys(f.basic).forEach((k) => {
        if (f.requirement && (k === 'work_date' || k === 'subject')) return;
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

    guideHtml(schema) {
      if (!schema.guide || !schema.guide.length) return '';
      return `<details class="te-guide" id="teGuide"><summary>고정 안내 (관리기준) 펼치기</summary>
        ${schema.guide.map((g) => `<div class="te-section-title">${esc(g.title)}</div>
          <table class="data-table"><tbody>${g.rows.map(([k, v]) => `<tr><th class="te-nowrap">${esc(k)}</th><td>${esc(v)}</td></tr>`).join('')}</tbody></table>`).join('')}
      </details>`;
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
        const sectionErr = f.errors[`section.${s.key}`] ? `<div class="te-error-text" data-error-section="${s.key}">${esc(f.errors[`section.${s.key}`])}</div>` : '';
        if (!s.repeat) {
          const row = rows[0];
          const ng = row && isNonconforming(s, row.values) ? ' te-section-ng' : '';
          return `<div class="te-section${ng}" ${s.nonconforming && row ? `data-ng-section="${row.uid}"` : ''}><div class="te-section-head"><span class="te-section-title">${esc(s.label)}</span><span class="te-hint">행 1개</span></div>${sectionErr}
            <div class="te-grid">${s.fields.map((fd) => `
              <div class="form-group"><label class="form-label">${esc(fd.label)}${fd.required ? ' *' : ''}${fd.unit ? ` (${esc(fd.unit)})` : ''}</label>
                ${this.fieldInput(fd, row.values[fd.key], row)}${this.errorFor(row.uid, fd.key)}</div>`).join('')}</div></div>`;
        }
        const legacy = this.legacyJudge(s);
        const limits = s.fields.filter((fd) => fd.limit).map((fd) => `${fd.label} ${fd.limit.min !== undefined ? `${fd.limit.min}${fd.unit || ''} 이상` : ''}${fd.limit.max !== undefined ? ` ${fd.limit.max}${fd.unit || ''} 이하` : ''}`).join(', ');
        const canAdd = !s.system_rows;
        // 측정자 = 행 기록자(recorded_by). 설계 순서(판정 → 측정자 → 비고)대로 판정 열 바로 뒤에 둔다
        const recorder = hasComputed(s);
        const recorderCell = (row) => `<td class="te-hint">${row.sectionId ? `staff ${(d.sections.find((x) => x.section_id === row.sectionId) || {}).recorded_by ?? '-'}` : (api.staffId ? `staff ${api.staffId}` : '-')}</td>`;
        const afterField = (fd, html) => (recorder && fd.computed ? html : '');
        return `<div class="te-section">
          <div class="te-section-head"><span class="te-section-title">${esc(s.label)} <span class="te-hint">반복${s.max_rows ? ` · 최대 ${s.max_rows}행` : ''}${s.min_rows ? ` · 최소 ${s.min_rows}행(작성완료 때)` : ''}${limits ? ` · 한계기준: ${esc(limits)}` : ''}${s.system_rows ? ' · 행은 입고 때 자동으로 추가됩니다' : ''}</span></span>
            ${canAdd ? `<button class="btn btn-secondary btn-sm" data-add="${s.key}">+ 행 추가</button>` : ''}</div>${sectionErr}
          <div class="te-table-wrap"><table class="data-table te-rows">
            <thead><tr><th>#</th>${s.fields.map((fd) => `<th class="${fd.readonly ? 'te-ro-head' : ''}">${esc(fd.label)}${fd.required ? ' *' : ''}${fd.unit ? ` (${esc(fd.unit)})` : ''}</th>${afterField(fd, '<th>측정자</th>')}`).join('')}${legacy ? '<th>판정</th>' : ''}${canAdd ? '<th></th>' : ''}</tr></thead>
            <tbody>${rows.length ? rows.map((row, i) => `
              <tr class="te-row-${this.rowState(row) || 'same'}${isNonconforming(s, row.values) ? ' te-row-ng' : ''}" data-tr="${row.uid}">
                <td>${i + 1}</td>
                ${s.fields.map((fd) => `<td class="${fd.readonly ? 'te-ro-cell' : ''}">${this.fieldInput(fd, row.values[fd.key], row)}${this.errorFor(row.uid, fd.key)}</td>${afterField(fd, recorderCell(row))}`).join('')}
                ${legacy ? `<td data-judge="${row.uid}">${this.judgeCell(s, row.values)}</td>` : ''}
                ${canAdd ? `<td><button class="btn btn-secondary btn-sm" data-del="${row.uid}" title="${row.deleted ? '삭제 취소' : '행 삭제'}">${row.deleted ? '↺' : '✕'}</button></td>` : ''}
              </tr>`).join('') : `<tr><td colspan="${s.fields.length + 3}" class="te-empty">${s.system_rows ? '아직 입고된 LOT가 없습니다' : '행이 없습니다.'}</td></tr>`}</tbody>
          </table></div></div>`;
      }).join('');

      const basicFields = f.requirement
        ? `<div class="form-group"><label class="form-label">대상</label><div class="te-ro te-ro-block">${esc(targetText(d))}</div></div>
           <div class="form-group"><label class="form-label">작업일</label><div class="te-ro te-ro-block">${esc(d.work_date)} <span class="te-hint">(고정)</span></div></div>`
        : `<div class="form-group"><label class="form-label">대상</label><input class="form-control ${cls('subject')}" data-basic="subject" maxlength="100" value="${esc(f.basic.subject)}">${basicErr('subject')}</div>
           <div class="form-group"><label class="form-label">작업일 *</label><input type="date" class="form-control ${cls('work_date')}" data-basic="work_date" value="${esc(f.basic.work_date)}">${basicErr('work_date')}${future}</div>`;

      this.root.innerHTML = `
        <div class="fade-in">
          ${T.topBar(title, f.mode === 'edit' ? '바뀐 부분만 저장됩니다. 노란색=변경, 초록색=추가, 취소선=삭제 예정 · 저장은 필수값을 검사하지 않습니다(작성완료 때 검사)' : '기본 정보와 영역 값을 입력하세요. 필수값(*)은 작성완료 때 검사합니다.', d && d.document_id)}
          ${f.pending.length ? `<div class="te-notice"><strong>다른 사용자가 먼저 수정해서 최신 내용으로 다시 열었습니다.</strong> 아래 변경을 다시 입력하세요.<ul class="te-pending">${f.pending.map((p) => `<li>${esc(p)}</li>`).join('')}</ul></div>` : ''}
          ${f.errorList.length ? `<div class="te-error-box" id="teErrorBox"><strong>${esc(f.errorTitle || '입력값을 확인하세요.')}</strong><ul>${f.errorList.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></div>` : ''}
          <div class="card">
            <div class="card-header"><div class="card-title">문서 정보 ${d ? requirementChip(d) : ''}</div><div class="te-hint">작성자: ${esc(author)}</div></div>
            <div class="te-grid">
              ${basicFields}
              <div class="form-group"><label class="form-label">담당자</label><select class="form-control ${cls('assignee_id')}" data-basic="assignee_id">${staffOptions(f.basic.assignee_id)}</select>${basicErr('assignee_id')}</div>
              <div class="form-group"><label class="form-label">마감</label><input type="datetime-local" class="form-control ${cls('due_at')}" data-basic="due_at" value="${esc(f.basic.due_at)}">${basicErr('due_at')}</div>
            </div>
            ${d ? `<div class="te-meta">${periodText(f.schema, d)}</div>` : ''}
            ${this.guideHtml(f.schema)}
            ${sectionsHtml}
            ${f.mode === 'edit' ? '<div class="te-hint" style="margin-top:1rem">이탈·개선조치는 문서 상세 화면에서 따로 저장합니다(문서 상태와 상관없이 언제든).</div>' : ''}
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
          const section = f.sectionByKey[row.key];
          const field = section.fields.find((fd) => fd.key === el.dataset.field);
          const value = this.readInput(el, field);
          if (value === undefined) delete row.values[field.key]; else row.values[field.key] = value;
          f.hinted.delete(`${row.uid}.${field.key}`);
          const tr = root.querySelector(`tr[data-tr="${row.uid}"]`);
          if (tr) tr.className = `te-row-${this.rowState(row) || 'same'}${isNonconforming(section, row.values) ? ' te-row-ng' : ''}`;
          root.querySelector(`[data-ng-section="${row.uid}"]`)?.classList.toggle('te-section-ng', isNonconforming(section, row.values));
          const judge = root.querySelector(`[data-judge="${row.uid}"]`);
          if (judge) judge.innerHTML = this.judgeCell(section, row.values);
          const computed = withComputed(section, row.values);
          section.fields.filter((fd) => fd.computed).forEach((fd) => {
            const cell = root.querySelector(`[data-computed="${row.uid}.${fd.key}"]`);
            if (cell) cell.innerHTML = this.display(fd, computed[fd.key]);
          });
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
      const firstError = root.querySelector('.te-error-text');
      if (firstError && f.focusError) {
        f.focusError = false;
        firstError.scrollIntoView({ block: 'center' });
        const input = firstError.parentElement.querySelector('input, select');
        if (input) input.focus({ preventScroll: true });
      }
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
          sections.push({ section_def: r.key, values: this.userValues(r) });
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
          else if (state === 'new') { pathMap[`sections.add[${add.length}]`] = r.uid; add.push({ section_def: r.key, values: this.userValues(r) }); }
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
          else if (state === 'new') out.push(`${s.label} 행 추가: ${fmt(this.userValues(r))}`);
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

    applyErrors(data, pathMap, completion = false) {
      const f = this.form;
      f.errors = {};
      f.errorList = [];
      f.errorTitle = completion ? '작성완료할 수 없습니다. 아래 항목을 채운 뒤 저장하고 다시 작성완료하세요.' : null;
      (data.details || []).forEach((e) => {
        const path = e.path || '';
        const basic = /^(?:document\.)?(subject|work_date|assignee_id|due_at)$/.exec(path);
        const row = /^(sections(?:\.(?:update|add|delete))?\[[^\]#]+\])(?:\.values\.(\w+)|\.round)?$/.exec(path);
        const numbered = /^sections\[(\w+)#(\d+)\]\.values\.(\w+)$/.exec(path); // 작성완료 검사(VR-19)
        const section = /^sections\[(\w+)\]$/.exec(path);
        if (basic) f.errors[`basic.${basic[1]}`] = e.message;
        else if (numbered) {
          const target = f.rows.find((r) => r.key === numbered[1] && r.rowNo === Number(numbered[2]));
          if (target) f.errors[`${target.uid}.${numbered[3]}`] = e.message;
        } else if (row && pathMap[row[1]] !== undefined) f.errors[`${pathMap[row[1]]}.${row[2] || 'round'}`] = e.message;
        else if (section && f.sectionByKey[section[1]]) f.errors[`section.${section[1]}`] = e.message;
        f.errorList.push(e.path === 'deviations' ? `${e.message} — 이탈·개선조치는 저장 후 문서 상세 화면에서 입력합니다.` : this.problemText(e));
      });
      if (!f.errorList.length) f.errorList.push(data.message || '저장에 실패했습니다.');
      if (!completion) T.toast(`[${data.code}] ${data.message}`, 'error');
      f.focusError = true;
      this.renderForm();
    },

    // 작성완료 검사 결과 한 줄 (DOC-SC-09). 행 오류는 "영역 · 행 이름: 메시지"
    problemText(e, schema, sections) {
      const sch = schema || (this.form && this.form.schema);
      const rows = sections || (this.form && this.form.document && this.form.document.sections) || [];
      const m = /^sections\[(\w+)#(\d+)\]\.values\.(\w+)$/.exec(e.path || '');
      if (!m || !sch) return e.message;
      const s = sch.sections.find((x) => x.key === m[1]);
      if (!s) return e.message;
      if (!s.repeat) return `${s.label}: ${e.message}`;
      const row = rows.find((x) => x.section_def === m[1] && x.row_no === Number(m[2]));
      const name = row && row.values && row.values.lot_number ? row.values.lot_number : `${m[2]}행`;
      return `${s.label} ${name}: ${e.message}`;
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
      if (this.devDocument !== d.document_id) { this.devDrafts = []; this.devDocument = d.document_id; }
      const canEdit = EDITABLE.includes(d.status);
      const canComplete = COMPLETABLE.includes(d.status);
      const canReopen = d.status === 'completed';
      const fixing = d.correction || null; // 정정 진행 중(정정 중·작성완료·결재중)
      const canCorrect = d.status === 'approved' && !fixing;
      const canDelete = d.status === 'draft' && !d.submitted_at && !d.record_key && !fixing; // 정정 중 숨김
      // 유효 승인본(가장 큰 attempt의 승인 회차, APR A5 effective) — 정정 배너용
      let effective = null;
      if (fixing) {
        const h = await api.get(`documents/${d.document_id}/approval-requests`);
        effective = h.ok ? h.data.items.find((x) => x.effective) || null : null;
      }
      const notes = {
        completed: '작성완료된 문서입니다. 수정하려면 [작성 재개]를 누르세요. 상신은 아래 결재 영역에서 합니다.',
        submitted: '결재 진행 중인 문서는 수정할 수 없습니다.',
        approved: '승인된 문서는 수정할 수 없습니다.',
        rejected: '반려된 문서입니다. 수정한 뒤 작성완료하면 재상신할 수 있습니다(삭제는 불가 — 상신 이력 보존).',
        correcting: '정정 중입니다. 수정한 뒤 작성완료하고 다시 상신하세요.',
      };
      if (fixing && d.status === 'completed') notes.completed = '정정 내용을 작성완료했습니다. 아래 결재 영역에서 상신하세요. 고치려면 [작성 재개](정정 중으로 돌아감).';
      if (d.status === 'approved') notes.approved = '승인된 문서는 수정할 수 없습니다. 고쳐야 하면 [정정 시작]을 누르세요.';
      if (d.status === 'draft' && d.submitted_at) notes.draft = '상신 이력이 있어 삭제할 수 없습니다.';
      if (d.status === 'draft' && d.record_key) notes.draft = '작성 요구로 만들어진 문서입니다. 삭제할 수 없습니다.';
      const info = d.sections.find((s) => s.section_def === 'info');
      const inspector = info && info.values.inspector ? `<span>점검자 <b>staff ${esc(info.values.inspector)}</b></span>` : '';
      const sections = this.sectionsHtml(schema, d, { detail: true });
      this.root.innerHTML = `
        <div class="fade-in">
          ${T.topBar(`문서 #${d.document_id} · ${d.template.name} v${d.template.version}`, '문서 상세', d.document_id)}
          <div class="card">
            <div class="card-header">
              <div class="card-title">${statusCell(d.status, !!fixing)} ${requirementChip(d)}</div>
              <div class="page-actions">
                <button class="btn btn-secondary btn-sm" id="btnList">목록</button>
                ${canEdit ? `<button class="btn btn-primary btn-sm" id="btnEdit" ${api.staffId ? '' : 'disabled'}>수정</button>` : ''}
                ${canComplete ? `<button class="btn btn-primary te-btn-complete btn-sm" id="btnComplete" ${api.staffId ? '' : 'disabled'}>작성완료</button>` : ''}
                ${canReopen ? `<button class="btn btn-secondary btn-sm" id="btnReopen" ${api.staffId ? '' : 'disabled'}>작성 재개</button>` : ''}
                ${canCorrect ? `<button class="btn btn-warning btn-sm" id="btnCorrect" ${api.staffId ? '' : 'disabled title="현재 사용자를 선택하세요"'}>정정 시작</button>` : ''}
                ${canDelete ? `<button class="btn btn-danger btn-sm" id="btnDelete" ${api.staffId ? '' : 'disabled'}>삭제</button>` : ''}
              </div>
            </div>
            ${fixing ? this.correctionBanner(d, fixing, effective) : ''}
            ${notes[d.status] ? `<div class="te-status-note">${notes[d.status]}</div>` : ''}
            <div class="te-meta">
              <span>대상 <b id="teTarget">${targetHtml(d)}</b></span><span>작업일 <b>${d.work_date}</b></span>
              <span>작성자 <b>staff ${d.created_by}</b></span><span>담당자 <b>${d.assignee_id ? `staff ${d.assignee_id}` : '-'}</b></span>${inspector}
              <span>마감 <b>${T.fmtDateTime(d.due_at)}</b></span>${periodText(schema, d)}
            </div>
            <div class="te-meta" style="margin-top:.25rem">
              <span>작성 ${T.fmtDateTime(d.created_at)}</span><span>최종 수정 ${T.fmtDateTime(d.updated_at)}</span>
              ${d.completed_at ? `<span id="teCompleted">작성완료 ${T.fmtDateTime(d.completed_at)} (staff ${d.completed_by})</span>` : ''}
              ${d.submitted_at ? `<span>상신 ${T.fmtDateTime(d.submitted_at)}</span>` : ''}<span class="te-hint">v${d.version}</span>
            </div>
            ${this.guideHtml(schema)}
            ${sections}
            ${schema.files ? `<div class="te-placeholder" id="teFiles">증빙 파일 ${d.files.length}개${d.files.length ? `: ${d.files.map((x) => esc(x.original_name)).join(', ')}` : ''} — 파일 올리기·불러오기 화면은 스프린트 3(D-058). 작성완료에는 파일이 ${schema.files.min}개 이상 필요합니다.</div>` : ''}
            <div id="teDeviationArea"></div>
            <div id="teApprovalArea"></div>
          </div>
        </div>`;
      this.rerenderTopBar(() => this.showDetail(id));
      const $ = (sel) => this.root.querySelector(sel);
      $('#btnList').addEventListener('click', () => this.showList());
      $('#btnEdit')?.addEventListener('click', () => this.openForm({ document: d }));
      $('#btnDelete')?.addEventListener('click', () => this.confirmDelete(d));
      $('#btnComplete')?.addEventListener('click', () => this.confirmComplete(d, schema));
      $('#btnReopen')?.addEventListener('click', () => this.reopen(d));
      $('#btnCorrect')?.addEventListener('click', () => this.openCorrection(d, effective));
      $('#btnFixCancel')?.addEventListener('click', () => this.cancelCorrection(d, effective));
      $('#btnEffective')?.addEventListener('click', () => {
        if (window.TempEntryApproval) window.TempEntryApproval.showRequest(Number($('#btnEffective').dataset.request), { from: 'doc', documentId: d.document_id });
      });
      this.root.querySelectorAll('#teTarget [data-lot]').forEach((a) => a.addEventListener('click', (e) => {
        e.preventDefault();
        T.open('temp-lot-docs', { lotId: Number(a.dataset.lot), back: { page: 'temp-doc', documentId: d.document_id } });
      }));
      this.root.querySelectorAll('[data-dev-for]').forEach((b) => b.addEventListener('click', () => {
        this.devDrafts.push({ section_id: b.dataset.devFor ? Number(b.dataset.devFor) : null, description: b.dataset.devText });
        this.renderDeviations(d, schema);
        this.root.querySelector('#teDeviationArea').scrollIntoView({ block: 'center' });
      }));
      this.renderDeviations(d, schema);
      // P3 결재 영역 (WF-SC-01) — temp-entry/approval/approval.js
      const area = $('#teApprovalArea');
      if (window.TempEntryApproval) window.TempEntryApproval.mountArea(area, d, () => this.showDetail(id));
    },

    // 문서 내용(섹션) 읽기 전용 표시. 결재 요청 상세(WF-SC-04)도 스냅샷을 이 함수로 그린다.
    sectionsHtml(schema, d, { detail = false } = {}) {
      return schema.sections.map((s) => {
        const rows = d.sections.filter((x) => x.section_def === s.key);
        if (!s.repeat) {
          const v = rows[0] ? rows[0].values : {};
          const ng = !!rows[0] && isNonconforming(s, v);
          const add = ng && detail && api.staffId ? ` <button class="btn btn-secondary btn-sm te-dev-add" data-dev-for="" data-dev-text="${esc(`${s.label} 부적합`)}">개선조치 추가</button>` : '';
          return `<div class="te-section${ng ? ' te-section-ng' : ''}"><div class="te-section-title">${esc(s.label)}${ng ? ' <span class="te-judge-ng">⚠ 부적합</span>' : ''}${add}</div>
            <dl class="te-kv">${s.fields.map((fd) => `<div><dt>${esc(fd.label)}</dt><dd>${this.display(fd, withComputed(s, v)[fd.key])}</dd></div>`).join('')}</dl></div>`;
        }
        const legacy = this.legacyJudge(s);
        const canDev = detail && api.staffId && !!s.nonconforming;
        const body = rows.map((x, i) => {
          const values = withComputed(s, x.values);
          const ng = this.judge(s, x.values) === 'ng';
          const rowName = x.values.lot_number || `${i + 1}행`;
          return `<tr class="${ng ? 'te-row-ng' : ''}" data-section-row="${x.section_id}">
            <td>${i + 1}</td>${s.fields.map((fd) => `<td>${this.display(fd, values[fd.key], x.hints && x.hints[fd.key])}</td>`).join('')}
            ${legacy ? `<td>${this.judgeCell(s, x.values)}</td>` : ''}
            <td class="te-hint">${ng && !legacy && !hasComputed(s) ? '<span class="te-judge-ng">⚠ 부적합</span><br>' : ''}${T.fmtDateTime(x.recorded_at)} · staff ${x.recorded_by ?? '-'}${ng && canDev ? `<br><button class="btn btn-secondary btn-sm te-dev-add" data-dev-for="${x.section_id}" data-dev-text="${esc(`${s.label} ${rowName} 부적합`)}">개선조치 추가</button>` : ''}</td></tr>`;
        }).join('')
          || `<tr><td colspan="${s.fields.length + 3}" class="te-empty">${s.system_rows ? '아직 입고된 LOT가 없습니다' : '행이 없습니다.'}</td></tr>`;
        return `<div class="te-section"><div class="te-section-title">${esc(s.label)} <span class="te-hint">${rows.length}행</span></div>
          <div class="te-table-wrap"><table class="data-table"><thead><tr><th>#</th>${s.fields.map((fd) => `<th>${esc(fd.label)}${fd.unit ? ` (${esc(fd.unit)})` : ''}</th>`).join('')}${legacy ? '<th>판정</th>' : ''}<th>기록</th></tr></thead>
          <tbody>${body}</tbody></table></div></div>`;
      }).join('');
    },

    // 상신 당시 이탈·개선조치(스냅샷, FR-27). 결재 요청 상세(WF-SC-04)에서 쓴다.
    deviationsHtml(schema, d, title = '이탈·개선조치') {
      const list = d.deviations || [];
      const rowName = (sid) => {
        for (const s of schema.sections.filter((x) => x.repeat)) {
          const rows = d.sections.filter((x) => x.section_def === s.key);
          const i = rows.findIndex((x) => x.section_id === sid);
          if (i >= 0) return `${s.label} ${rows[i].values.lot_number || `${i + 1}행`}`;
        }
        return sid ? `행 #${sid}` : '–';
      };
      const hasRows = schema.sections.some((x) => x.repeat) || list.some((x) => x.section_id);
      return `<div class="te-section" id="teSnapDeviation"><div class="te-section-title">${esc(title)} <span class="te-hint">${list.length}건</span></div>
        ${list.length ? `<div class="te-table-wrap"><table class="data-table"><thead><tr>${hasRows ? '<th>관련 행</th>' : ''}<th>한계기준 이탈내용</th><th>조치자</th><th>개선조치 및 결과</th><th>확인자</th></tr></thead>
        <tbody>${list.map((x) => `<tr>${hasRows ? `<td>${esc(rowName(x.section_id))}</td>` : ''}<td>${esc(x.description)}</td><td>${x.actor_id ? `staff ${x.actor_id}` : '-'}</td>
          <td>${esc(x.action_result || '-')}</td><td>${(x.checker_ids || []).map((c) => `staff ${c}`).join(', ') || '-'}</td></tr>`).join('')}</tbody></table></div>`
        : '<p class="te-hint">기록된 개선조치가 없습니다.</p>'}</div>`;
    },

    display(field, value, hint) {
      if (value === undefined || value === null || value === '') {
        if (hint !== undefined) return `<span class="te-hint" title="저장된 값 없음 — 같은 LOT 성적서 기준 자동 제안">${esc(hint)} (자동)</span>`;
        return '<span class="te-hint">-</span>';
      }
      if (field.type === 'bool') return value ? '예' : '아니오';
      if (field.type === 'staff') return `staff ${esc(value)}`;
      if (field.type === 'datetime') return esc(String(value).replace('T', ' '));
      if (field.display === 'hm' && typeof value === 'number') return esc(fmtMinutes(value));
      if (field.computed) {
        const bad = value === field.computed.else;
        return `<span class="${bad ? 'te-judge-ng' : 'te-judge-ok'}">${bad ? '⚠ ' : ''}${esc(value)}</span>`;
      }
      return esc(optionLabel(field, value));
    },

    // ================================================= 이탈·개선조치 영역 (P4-S1 (5), F19~F21)
    // 문서 상태와 상관없이 언제든 저장한다. 문서 버전과 무관하게 개선조치 자기 version으로 충돌을 감지한다.
    renderDeviations(d, schema) {
      const el = this.root.querySelector('#teDeviationArea');
      if (!el) return;
      const rowOptions = [];
      schema.sections.filter((s) => s.repeat).forEach((s) => d.sections.filter((x) => x.section_def === s.key).forEach((x, i) => {
        rowOptions.push({ id: x.section_id, label: `${s.label} ${x.values.lot_number || `${i + 1}행`}` });
      }));
      const staffOpts = (sel) => ['<option value="">-</option>'].concat((T.staff || []).map((sid) => `<option value="${sid}" ${String(sel) === String(sid) ? 'selected' : ''}>staff ${sid}</option>`)).join('');
      const rowSelect = (sel) => ['<option value="">– 없음</option>'].concat(rowOptions.map((o) => `<option value="${o.id}" ${String(sel) === String(o.id) ? 'selected' : ''}>${esc(o.label)}</option>`)).join('');
      // 확인 슬롯 1개에 여러 명(D-054). 1명이 확인하면 끝(확인 기능은 ISS-008)
      const checkerSelect = (ids) => `<span class="te-checkers">${(T.staff || []).map((sid) => `<label class="te-check"><input type="checkbox" data-checker value="${sid}" ${ids.includes(sid) ? 'checked' : ''}>${sid}</label>`).join('')}</span>`;
      const line = (x, key) => `
        <tr data-dev="${key}">
          ${hasRows ? `<td><select class="form-control" data-k="section_id">${rowSelect(x.section_id)}</select></td>` : ''}
          <td><input class="form-control" data-k="description" maxlength="500" value="${esc(x.description || '')}" placeholder="이탈내용(필수)"></td>
          <td><select class="form-control" data-k="actor_id">${staffOpts(x.actor_id)}</select></td>
          <td><input class="form-control" data-k="action_result" maxlength="1000" value="${esc(x.action_result || '')}"></td>
          <td>${checkerSelect(x.checker_ids || [])}</td>
          <td class="te-nowrap">${x.deviation_id ? ((x.checker_ids || []).length ? (x.checked_at ? '확인' : '대기') : '–') : '<span class="te-hint">새 행</span>'}</td>
          <td class="te-nowrap"><button class="btn btn-primary btn-sm" data-dev-save="${key}" ${api.staffId ? '' : 'disabled'}>저장</button>
            <button class="btn btn-secondary btn-sm" data-dev-del="${key}" ${api.staffId ? '' : 'disabled'}>${x.deviation_id ? '삭제' : '취소'}</button></td>
        </tr>`;
      const saved = d.deviations || [];
      const nonconforming = schema.sections.some((s) => d.sections.some((x) => x.section_def === s.key && isNonconforming(s, x.values)));
      // 반복 섹션이 없는 양식(D03 v2 등)은 "관련 행" 열을 숨긴다(P6a-S1 DOC-SC-04). 행이 아직 없는 CCP 문서는 열 유지
      const hasRows = schema.sections.some((s) => s.repeat);
      el.innerHTML = `
        <div class="te-section te-deviation" id="teDeviation">
          <div class="te-section-head"><span class="te-section-title">한계기준 이탈·개선조치 <span class="te-hint">문서 상태와 상관없이 언제든 수정할 수 있습니다 · 확인 기능은 다음 스프린트</span></span>
            <button class="btn btn-secondary btn-sm" id="devAdd" ${api.staffId ? '' : 'disabled'}>+ 추가</button></div>
          ${nonconforming && !saved.length ? '<div class="te-error-text">부적합 항목이 있어 작성완료하려면 이탈·개선조치를 1건 이상 적어야 합니다.</div>' : ''}
          <div class="te-table-wrap"><table class="data-table te-rows">
            <thead><tr>${hasRows ? '<th>관련 행</th>' : ''}<th>한계기준 이탈내용 *</th><th>조치자</th><th>개선조치 및 결과</th><th>확인자 <span class="te-hint">(staff, 여러 명)</span></th><th>확인</th><th></th></tr></thead>
            <tbody>${saved.map((x) => line(x, `s${x.deviation_id}`)).join('')}${this.devDrafts.map((x, i) => line(x, `n${i}`)).join('')
              || (saved.length ? '' : `<tr><td colspan="${hasRows ? 7 : 6}" class="te-empty">기록된 개선조치가 없습니다.</td></tr>`)}</tbody>
          </table></div>
        </div>`;
      const read = (tr) => {
        const v = (k) => tr.querySelector(`[data-k="${k}"]`);
        const num = (x) => (x === '' ? null : Number(x));
        return {
          section_id: v('section_id') ? num(v('section_id').value) : null, description: v('description').value.trim(),
          actor_id: num(v('actor_id').value), action_result: v('action_result').value.trim() || null,
          checker_ids: [...tr.querySelectorAll('[data-checker]:checked')].map((o) => Number(o.value)),
        };
      };
      const reload = () => this.showDetail(d.document_id);
      el.querySelector('#devAdd').addEventListener('click', () => { this.devDrafts.push({}); this.renderDeviations(d, schema); });
      el.querySelectorAll('[data-dev-save]').forEach((b) => b.addEventListener('click', async () => {
        const key = b.dataset.devSave;
        const tr = el.querySelector(`tr[data-dev="${key}"]`);
        const body = read(tr);
        let res;
        if (key.startsWith('n')) {
          res = await api.post(`documents/${d.document_id}/deviations`, body);
          if (res.ok) this.devDrafts.splice(Number(key.slice(1)), 1);
        } else {
          const cur = saved.find((x) => `s${x.deviation_id}` === key);
          const patch = {};
          Object.entries(body).forEach(([k, val]) => { if (JSON.stringify(val) !== JSON.stringify(cur[k] ?? (k === 'checker_ids' ? [] : null))) patch[k] = val; });
          if (!Object.keys(patch).length) { T.toast('바뀐 내용이 없습니다.', 'info'); return; }
          res = await api.patch(`deviations/${cur.deviation_id}`, { expected_version: cur.version, ...patch });
        }
        if (res.ok) { T.toast('개선조치를 저장했습니다.', 'success'); reload(); return; }
        if (res.data && res.data.code === 'VERSION_CONFLICT') { T.toast('다른 사용자가 먼저 이 개선조치를 수정했습니다. 최신 내용으로 다시 불러옵니다.', 'error'); reload(); return; }
        const details = (res.data && res.data.details) || [];
        T.toast(`${T.errorText(res)}${details.length ? ` — ${details.map((x) => x.message).join(' / ')}` : ''}`, 'error');
      }));
      el.querySelectorAll('[data-dev-del]').forEach((b) => b.addEventListener('click', async () => {
        const key = b.dataset.devDel;
        if (key.startsWith('n')) { this.devDrafts.splice(Number(key.slice(1)), 1); this.renderDeviations(d, schema); return; }
        const cur = saved.find((x) => `s${x.deviation_id}` === key);
        if (!(await T.confirm('개선조치 삭제', '이 개선조치를 삭제합니다. 기록은 삭제자·시각과 함께 보존됩니다.', '삭제', 'btn-danger'))) return;
        const res = await api.del(`deviations/${cur.deviation_id}?expected_version=${cur.version}`);
        if (res.ok) { T.toast('삭제했습니다.', 'success'); reload(); return; }
        T.toast(T.errorText(res), 'error');
        reload();
      }));
    },

    // ================================================= DOC-SC-09 작성완료 확인·검사 결과
    async confirmComplete(d, schema) {
      let r;
      if (d.template.type_code === 'D03') {
        r = await this.completeD03(d, schema);
        if (!r) return; // 취소
      } else {
        const ok = await T.confirm('작성완료', `문서 #${d.document_id}을(를) 작성완료합니다.<br>작성완료 후에는 [작성 재개]를 눌러야 수정할 수 있습니다.`, '작성완료', 'btn-primary te-btn-complete');
        if (!ok) return;
        r = await api.post(`documents/${d.document_id}/complete`, { expected_version: d.version });
      }
      if (r.ok) { T.toast(d.template.type_code === 'D03' ? '작성완료 · 판정 전달' : '작성완료했습니다.', 'success'); this.showDetail(d.document_id); return; }
      const data = r.data || {};
      if (data.code === 'COMPLETION_INCOMPLETE') {
        const details = data.details || [];
        const items = details.map((e) => `<li>${esc(this.problemText(e, schema, d.sections))}</li>`).join('');
        // 이동할 곳: 폼 항목(값·행) → 작성 폼, 개선조치만 → 상세의 개선조치 영역, 파일만 → 이동 없음(스프린트 3)
        const formProblems = details.filter((e) => e.path !== 'deviations' && e.path !== 'files');
        const devProblem = details.some((e) => e.path === 'deviations');
        const buttons = [{ label: '닫기', value: false }];
        if (formProblems.length && EDITABLE.includes(d.status)) buttons.push({ label: '수정하러 가기', value: 'form', cls: 'btn-primary' });
        else if (devProblem) buttons.push({ label: '개선조치 입력하러 가기', value: 'deviation', cls: 'btn-primary' });
        const go = await T.modal({
          title: '작성완료할 수 없습니다',
          body: `<p>아래 항목을 먼저 채워 주세요.</p><ul class="te-pending" id="teCompleteProblems">${items}</ul>
            ${details.some((e) => e.path === 'files') ? '<p class="te-hint">파일 올리기 화면은 스프린트 3에서 제공됩니다.</p>' : ''}`,
          buttons,
        });
        if (go === 'form') this.openForm({ document: d, problems: details });
        else if (go === 'deviation') this.goToDeviation(d, schema);
        return;
      }
      if (data.code === 'VERSION_CONFLICT') {
        await T.modal({ title: '다른 사용자가 먼저 수정했습니다', body: '<p>최신 내용을 다시 불러옵니다. 확인한 뒤 다시 작성완료하세요.</p>', buttons: [{ label: '확인', value: true, cls: 'btn-primary' }] });
        this.showDetail(d.document_id);
        return;
      }
      T.toast(T.errorText(r), 'error');
      this.showDetail(d.document_id);
    },

    // DOC-SC-09 (D03, P6 + P6a 3.2): LOT 1건의 판정 + 판정 변경 사유(note, 저장하지 않음 — 수불에 전달만).
    // 수불 거부(409 INVENTORY_REJECTED)·연동 없음(503)은 모달을 닫지 않고 위에 빨간 영역. 그 밖의 응답은 호출자로 넘긴다.
    completeD03(d, schema) {
      const section = schema.sections.find((x) => x.key === 'inspection');
      const field = section && section.fields.find((fd) => fd.key === 'verdict');
      const row = d.sections.find((x) => x.section_def === 'inspection');
      const verdict = row && row.values.verdict;
      const lot = (d.refs || []).find((x) => x.lot_id !== null);
      const lotName = lot ? (lot.label || lot.lot_id) : '-';
      const verdictText = verdict ? `${field ? optionLabel(field, verdict) : verdict}(${verdict})` : '(판정 없음)';
      const prefill = d.correction ? d.correction.reason : '';
      return new Promise((resolve) => {
        const wrap = document.createElement('div');
        wrap.className = 'te-modal-wrap';
        wrap.innerHTML = `
          <div class="te-modal" role="dialog" aria-modal="true" id="teD03Complete">
            <div class="modal-header"><div class="modal-title">작성완료 — ${esc(d.template.name)} #${d.document_id} · LOT ${esc(lotName)}</div></div>
            <div class="te-modal-body">
              <div id="d03Reject"></div>
              <p>작성완료하면 판정 <b class="${verdict === 'FAIL' ? 'te-judge-ng' : 'te-judge-ok'}">${esc(verdictText)}</b>이 수불에 전달됩니다.</p>
              <label class="form-label" for="d03Note" style="margin-top:.6rem">판정 변경 사유 (선택, ${REASON_MAX}자)</label>
              <input class="form-control" id="d03Note" maxlength="${REASON_MAX}" value="${esc(prefill)}">
              <div class="te-counter" id="d03Count">${prefill.length}/${REASON_MAX}</div>
              <p class="te-hint">ⓘ 이미 판정된 LOT의 판정을 바꾸면 사유가 필요합니다.${d.correction ? ' 정정 사유를 미리 채웠습니다(지우면 정정 사유가 그대로 쓰입니다).' : ''}</p>
            </div>
            <div class="te-modal-footer">
              <button class="btn btn-secondary" id="d03Close">취소</button>
              <button class="btn btn-primary te-btn-complete" id="d03Go">작성완료</button>
            </div>
          </div>`;
        document.body.appendChild(wrap);
        const $ = (sel) => wrap.querySelector(sel);
        const done = (value) => { wrap.remove(); resolve(value); };
        const note = $('#d03Note');
        note.addEventListener('input', () => { $('#d03Count').textContent = `${note.value.trim().length}/${REASON_MAX}`; });
        $('#d03Close').addEventListener('click', () => done(null));
        $('#d03Go').addEventListener('click', async () => {
          $('#d03Go').disabled = true;
          $('#d03Go').textContent = '처리 중…';
          const body = { expected_version: d.version };
          if (note.value.trim()) body.note = note.value.trim();
          const r = await api.post(`documents/${d.document_id}/complete`, body);
          const code = r.data && r.data.code;
          if (code === 'INVENTORY_REJECTED' || code === 'INVENTORY_NOT_CONFIGURED') {
            const items = (r.data.details || []).map((x) => `<li><b>${esc(x.lot_number || x.lot_id || '')}</b> ${esc(x.message)}</li>`).join('');
            $('#d03Reject').innerHTML = `<div class="te-inv-reject" id="teInvReject">
              <b>⚠ ${code === 'INVENTORY_REJECTED' ? '수불이 판정을 받지 않았습니다' : esc(r.data.message)} — 작성완료하지 않았습니다</b>
              ${items ? `<ul>${items}</ul>` : ''}
              <div class="te-hint">${code === 'INVENTORY_REJECTED' ? '메시지는 수불이 보낸 문구입니다. 사유를 적거나 수불 담당자와 확인하세요.' : '서버 설정(HACCP_INVENTORY_JUDGMENT)을 확인하세요.'}</div></div>`;
            $('#d03Go').disabled = false;
            $('#d03Go').textContent = '작성완료';
            note.focus();
            return;
          }
          done(r);
        });
        note.focus();
      });
    },

    // 개선조치 입력 위치로 이동: 첫 부적합 행을 관련 행으로 한 새 입력 행을 연다
    goToDeviation(d, schema) {
      if (!this.devDrafts.length) {
        let related = null;
        schema.sections.filter((s) => s.repeat).forEach((s) => d.sections.filter((x) => x.section_def === s.key).forEach((x) => {
          if (related === null && isNonconforming(s, x.values)) related = x.section_id;
        }));
        this.devDrafts.push(related ? { section_id: related } : {});
      }
      this.renderDeviations(d, schema);
      const area = this.root.querySelector('#teDeviation');
      area.scrollIntoView({ block: 'center' });
      area.querySelector("tr[data-dev^='n'] [data-k=description]")?.focus({ preventScroll: true });
    },

    async reopen(d) {
      // 확인 없이 작성중으로 돌아간다(P4-S1-Q4)
      const r = await api.post(`documents/${d.document_id}/reopen`, { expected_version: d.version });
      if (r.ok) T.toast(r.data.status === 'correcting' ? '작성을 재개했습니다. 정정 중으로 돌아갔습니다.' : '작성을 재개했습니다. 이제 수정할 수 있습니다.', 'success');
      else T.toast(T.errorText(r), 'error');
      this.showDetail(d.document_id);
    },

    // ================================================= P6 정정 배너 (DOC-SC-04)
    correctionBanner(d, c, effective) {
      const eff = effective
        ? `새로 승인될 때까지 유효한 승인본은 <b>${effective.attempt}회차</b>(${T.fmtDateTime(effective.closed_at)} 승인)입니다.
           <button class="btn btn-secondary btn-sm" id="btnEffective" data-request="${effective.request_id}">유효 승인본 보기</button>`
        : '<span class="te-hint">유효 승인본을 읽지 못했습니다.</span>';
      const cancel = d.status === 'correcting'
        ? `<button class="btn btn-secondary btn-sm" id="btnFixCancel" ${api.staffId && c.cancellable ? '' : 'disabled'}
             title="${c.cancellable ? (api.staffId ? '정정을 취소하고 승인 상태로 되돌립니다' : '현재 사용자를 선택하세요') : '수정한 내용이 있어 취소할 수 없습니다. 작성완료 후 재상신하세요'}">정정 취소</button>`
        : '';
      return `<div class="te-fix-banner" id="teFixBanner">
        <div class="te-fix-head">⚠ 정정 중입니다</div>
        <div>${T.fmtDateTime(c.started_at)} staff ${esc(c.started_by)} · 사유: ${esc(c.reason)}</div>
        <div>${eff}</div>
        ${cancel ? `<div class="te-fix-actions">${c.cancellable ? '' : '<span class="te-hint">수정한 내용이 있어 취소할 수 없습니다 — 작성완료 후 재상신하세요</span>'}${cancel}</div>` : ''}
      </div>`;
    },

    // 정정 시작·취소 오류 공통: 다시 열기 안내(DOC-SC-06과 같은 방식)
    async reopenAfter(title, message, d) {
      const again = await T.modal({ title, body: `<p>${message}</p>`, buttons: [{ label: '닫기', value: false }, { label: '최신 내용으로 다시 열기', value: true, cls: 'btn-primary' }] });
      if (again) this.showDetail(d.document_id);
    },

    // ================================================= WF-SC-08 정정 시작 모달
    openCorrection(d, effective) {
      const wrap = document.createElement('div');
      wrap.className = 'te-modal-wrap';
      wrap.innerHTML = `
        <div class="te-modal" role="dialog" aria-modal="true" id="teFixModal">
          <div class="modal-header"><div class="modal-title">정정 시작 · 문서 #${d.document_id} (v${d.version})</div></div>
          <div class="te-modal-body">
            <p>승인된 문서를 다시 열어 고칩니다.</p>
            <ul class="te-pending">
              <li>새로 승인될 때까지 지금 승인본${effective ? `(${effective.attempt}회차)` : ''}이 유효합니다.</li>
              <li>고친 뒤 작성완료 → 결재 상신을 다시 해야 합니다.</li>
            </ul>
            <div id="fixTop"></div>
            <label class="form-label" for="fixReason" style="margin-top:.6rem">정정 사유 *</label>
            <input class="form-control" id="fixReason" maxlength="${REASON_MAX + 50}" placeholder="예: 외포장 판정 오기(부적합 → 적합)">
            <div class="te-counter" id="fixCount">0/${REASON_MAX}</div>
            <div class="te-error-text" id="fixError"></div>
          </div>
          <div class="te-modal-footer">
            <button class="btn btn-secondary" id="fixClose">취소</button>
            <button class="btn btn-warning" id="fixGo" disabled>정정 시작</button>
          </div>
        </div>`;
      document.body.appendChild(wrap);
      const $ = (sel) => wrap.querySelector(sel);
      const close = () => wrap.remove();
      const input = $('#fixReason');
      const check = () => {
        const n = input.value.trim().length;
        $('#fixCount').textContent = `${n}/${REASON_MAX}`;
        $('#fixCount').classList.toggle('te-error-text', n > REASON_MAX);
        $('#fixError').textContent = n === 0 ? '정정 사유를 입력하세요' : (n > REASON_MAX ? `${REASON_MAX}자 이하로 입력하세요` : '');
        $('#fixGo').disabled = !api.staffId || n === 0 || n > REASON_MAX;
      };
      input.addEventListener('input', check);
      $('#fixClose').addEventListener('click', close);
      $('#fixGo').addEventListener('click', async () => {
        $('#fixGo').disabled = true;
        $('#fixGo').textContent = '처리 중…';
        const r = await api.post(`documents/${d.document_id}/correction`, { expected_version: d.version, reason: input.value.trim() });
        if (r.ok) { close(); T.toast('정정을 시작했습니다. 이제 수정할 수 있습니다.', 'success'); this.showDetail(d.document_id); return; }
        $('#fixGo').textContent = '정정 시작';
        const data = r.data || {};
        if (data.code === 'VALIDATION_ERROR') {
          $('#fixError').textContent = (data.details || [])[0]?.message || data.message;
          check();
          $('#fixGo').disabled = false;
          return;
        }
        // 409(다른 사람이 먼저 정정 시작·승인 아님·버전) → 모달 안 [코드] 메시지 + [다시 열기]
        $('#fixTop').innerHTML = `<div class="te-error-box">${esc(T.errorText(r))} <button class="btn btn-secondary btn-sm" id="fixReload">다시 열기</button></div>`;
        $('#fixReload').addEventListener('click', () => { close(); this.showDetail(d.document_id); });
      });
      input.focus();
    },

    // ================================================= WF-SC-10 정정 취소 확인 (D-075)
    async cancelCorrection(d, effective) {
      const ok = await T.modal({
        title: `정정 취소 · 문서 #${d.document_id} (v${d.version})`,
        body: `<p>정정을 취소하고 승인 상태로 되돌립니다.</p>
          <ul class="te-pending"><li>정정 시작 뒤 고친 내용이 없어 지금 승인본${effective ? `(${effective.attempt}회차)` : ''}이 그대로 유효합니다.</li>
          <li>정정 기록은 "취소됨"으로 남습니다(사유 이력 보존).</li></ul>`,
        buttons: [{ label: '닫기', value: false }, { label: '정정 취소', value: true, cls: 'btn-danger' }],
      });
      if (!ok) return;
      const r = await api.post(`documents/${d.document_id}/correction/cancel`, { expected_version: d.version });
      if (r.ok) { T.toast('정정을 취소했습니다. 승인 상태로 돌아갔습니다.', 'success'); this.showDetail(d.document_id); return; }
      const code = r.data && r.data.code;
      const message = code === 'CORRECTION_HAS_CHANGES'
        ? '수정한 내용이 있어 취소할 수 없습니다. 작성완료 후 재상신하세요.'
        : esc(T.errorText(r));
      await this.reopenAfter('정정을 취소할 수 없습니다', `${code === 'CORRECTION_HAS_CHANGES' ? `[${code}] ` : ''}${message}`, d);
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
