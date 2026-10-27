// =============================================
// P15 생산일지 화면 (PLG-SC-01~03, p15-s1-screens.md 3~5장 · 명세 p15-s2-spec.md r5)
// - 문서 상세(doc-box)가 양식 layout "prodlog"이면 이 본문으로 그린다(S1 Q1 a — 머리·저장·상태 틀은 문서 상세와 같게).
// - 저장은 DOC PATCH 하나(S1 Q4 a — [저장] 버튼). 공정 순서를 바꾸거나 중간에 넣으면 공정 행을 지우고 다시 넣는다
//   (행 순서 = row_no, DOC에 순서 바꾸기 API 없음 — S5a-C1).
// - 연동 값은 PLG-A01, 템플릿 행 A02, 템플릿으로 저장 A03, CCP 값 A04, 공정 등록 A05.
// =============================================
(function () {
  const T = window.TempEntry;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);

  const KIND = {
    'CCP-1P': { tag: 'CCP-1P', ccp: true, doc: 'CCP-1P 일지' },
    'CCP-2B': { tag: 'CCP-2B', ccp: true, doc: 'CCP-2B 일지' },
    'CCP-3P': { tag: 'CCP-3P', ccp: true, doc: 'CCP-3P 일지' },
    INNER: { tag: '내포장' },
    OUTER: { tag: '외포장' },
    GEN: { tag: '일반' },
  };
  const MODES = { JUDGE: '적합/부적합', TEMP_TIME: '온도·시간', QTY: '수량' };
  const PRECHECKS = [
    ['pre_label', '원료 적합라벨 확인'],
    ['pre_clean', '검교정 상태 후 칭량도구 청결'],
    ['pre_lot', '작업 로트·제품명 재확인'],
  ];
  const QTY_UNITS = ['EA', '환', 'box', 'kg', 'g'];
  const FIELD_LABEL = {
    name: '표시명', work_date: '작업일', worker: '작업자', dur_value: '소요기간', dur_unit: '소요기간 단위',
    verdict: '결과', temp: '온도', time_min: '시간', qty: '수량', qty_unit: '수량 단위', material: '포장재질',
    expiry: '소비기한', fg_qty: '완제품수량', mode: '입력 방식', kind: '기능', process_id: '공정',
    pre_label: PRECHECKS[0][1], pre_clean: PRECHECKS[1][1], pre_lot: PRECHECKS[2][1], inspector: '점검자',
    bom_line_id: 'BOM 줄', used: '사용량',
  };

  const blank = (v) => v === undefined || v === null || v === '';
  const nowText = () => {
    const d = new Date();
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
  };
  // e6 정수 → 글자(끝 0 지움)
  const q6 = (e6) => {
    if (e6 === null || e6 === undefined) return '';
    return (e6 / 1e6).toFixed(6).replace(/0+$/, '').replace(/\.$/, '');
  };
  const pct = (e6) => (e6 === null || e6 === undefined ? null : `${(e6 / 1e4).toFixed(2)}%`);  // 명세 R20 소수 둘째 자리
  const num = (v) => (blank(v) ? null : Number(v));

  // 서버 logbook.step_missing과 같은 기준(R07)
  function stepMissing(v) {
    const need = ['name', 'work_date', 'worker'];
    if (v.dur_on) need.push('dur_value', 'dur_unit');
    const k = v.kind;
    if (k === 'CCP-1P' || k === 'CCP-3P') need.push('verdict');
    else if (k === 'CCP-2B') need.push('temp', 'time_min');
    else if (k === 'INNER') need.push('qty');
    else if (k === 'OUTER') need.push('material', 'expiry', 'fg_qty');
    else if (k === 'GEN') need.push(...({ JUDGE: ['verdict'], TEMP_TIME: ['temp', 'time_min'], QTY: ['qty', 'qty_unit'] }[v.mode] || ['mode']));
    return need.filter((key) => blank(v[key]));
  }
  // 목차 점: 결과·작업자 아무것도 없음 = 미입력, 빠진 것 있음 = 입력 중, 다 참 = 완료
  function stepState(v) {
    const missing = stepMissing(v);
    if (!missing.length) return 'ok';
    const touched = ['worker', 'verdict', 'temp', 'time_min', 'qty', 'material', 'expiry', 'fg_qty'].some((k) => !blank(v[k]));
    return touched ? 'doing' : 'idle';
  }
  const STATE_LABEL = { ok: '완료', doing: '입력 중', idle: '미입력' };

  function modal({ title, body, wide = false }) {
    const wrap = document.createElement('div');
    wrap.className = 'te-modal-wrap';
    wrap.innerHTML = `<div class="te-modal${wide ? ' te-pl-modal-wide' : ''}" role="dialog" aria-modal="true">
      <div class="modal-header"><div class="modal-title">${esc(title)}</div></div>
      <div class="te-modal-body">${body}</div></div>`;
    document.body.appendChild(wrap);
    wrap.addEventListener('click', (e) => { if (e.target === wrap) wrap.remove(); });
    return wrap;
  }

  const PL = {
    // ------------------------------------------------------------ 열기
    async show(host, d, schema, current = () => true) {
      const [linked, procs] = await Promise.all([
        api.get(`production-logs/${d.document_id}/linked`),
        api.get('processes?status=active'),
      ]);
      if (!current() || !host.root.isConnected) return;  // r2(재검토 B2): 그사이 다른 문서·화면을 열었음
      this.host = host;
      this.root = host.root;
      this.d = d;
      this.schema = schema;
      this.linked = linked.ok ? linked.data : null;
      this.linkedError = linked.ok ? null : T.errorText(linked);
      this.procs = procs.ok ? procs.data.items : [];
      this.load();
      this.render();
    },

    load() {
      const d = this.d;
      const rows = (key) => d.sections.filter((s) => s.section_def === key).sort((a, b) => a.row_no - b.row_no);
      const info = rows('info')[0];
      this.infoSid = info ? info.section_id : null;
      this.info = { ...(info ? info.values : {}) };
      this.infoOrig = { ...this.info };
      this.mats = {};
      rows('materials').forEach((r) => { if (r.values.bom_line_id) this.mats[r.values.bom_line_id] = { sid: r.section_id, values: { ...r.values }, orig: { ...r.values } }; });
      this.steps = rows('steps').map((r) => ({ sid: r.section_id, rowNo: r.row_no, values: { ...r.values }, orig: { ...r.values } }));
      this.origSids = this.steps.map((s) => s.sid);
      this.dirty = false;
      this.check = null;
      this.menu = false;
      this.seq = 0;
    },

    get id() { return this.d.document_id; },
    get completed() { return this.d.status === 'completed'; },
    get batch() { return (this.linked && this.linked.linked && this.linked.linked.batch) || null; },
    get cancelled() { return !!this.batch && this.batch.status === 'CANCELLED'; },
    get mayWrite() { return !!api.staffId && !!(this.d.permissions && this.d.permissions.write); },
    get ro() { return this.d.status !== 'draft' || this.cancelled || !this.mayWrite; },
    get ccpDocs() { return (this.linked && this.linked.ccp_documents) || {}; },
    // B1(S5a r1): 작성완료면 고정 원료(0줄이어도 고정 결과)
    get frozenMaterials() {
      const f = this.completed && this.linked && this.linked.frozen;
      return f && Array.isArray(f.materials) && f.batch ? f.materials : null;
    },
    get workDate() { return (this.batch && this.batch.manufactured_date) || this.d.work_date; },

    markDirty() {
      this.dirty = true;
      const el = this.root.querySelector('#plSaved');
      if (el) el.textContent = '저장 안 된 변경 있음';
    },

    // ------------------------------------------------------------ 그리기
    render() {
      const d = this.d;
      const keep = window.scrollY;
      const ro = this.ro;
      const writeOff = !api.staffId ? 'disabled title="현재 사용자를 선택하세요"' : (this.mayWrite ? '' : `disabled title="${esc(T.WRITE_WHY)}"`);
      const buttons = this.cancelled ? '' : (d.status === 'draft'
        ? `<button class="btn btn-secondary btn-sm" id="plSave" ${writeOff}>저장</button><button class="btn btn-primary te-btn-complete btn-sm" id="plComplete" ${writeOff}>작성완료</button>`
        : (this.completed ? `<button class="btn btn-secondary btn-sm" id="plReopen" ${writeOff}>작성 재개</button>` : ''));
      const savedText = d.status === 'draft' ? (this.dirty ? '저장 안 된 변경 있음' : `저장됨 ${T.fmtDateTime(d.updated_at)}`)
        : (this.completed ? `작성완료 ${T.fmtDateTime(d.completed_at)} (${T.person(d.completed_by)})` : '');
      const notes = [];
      if (this.cancelled) notes.push('<div class="te-pl-cancel" id="plCancelled">취소된 배치입니다 — 읽기 전용</div>');
      if (this.completed && this.linked && this.linked.changed) notes.push('<div class="te-pl-warn" id="plChanged">연동 값이 바뀌었습니다 — 반영하려면 [작성 재개]</div>');
      if (this.completed) notes.push(`<div class="te-status-note" id="teStatusNote">작성완료된 생산일지입니다. 연동 값(기본정보·원료칭량)은 작성완료 시점 값으로 고정해 보여 줍니다. 고치려면 [작성 재개].</div>`);
      if (api.staffId && !this.mayWrite && !this.cancelled) notes.push(`<div class="te-perm-note" id="teWriteWhy">${esc(T.WRITE_WHY)} ${T.roleLink()}</div>`);
      const target = (d.refs || []).find((r) => r.section_id === null && r.production_batch_id !== null);
      this.root.innerHTML = `
        <div class="fade-in te-pl">
          ${T.topBar(`문서 #${d.document_id} · ${d.template.name} v${d.template.version}`, '생산일지', d.document_id)}
          <div class="card">
            <div class="card-header">
              <div class="card-title">${T.statusBadge(d.status)} <span class="te-req">⚙ 생산 작성 요구</span> <span class="badge badge-neutral" id="plNoApproval">결재 없음</span></div>
              <div class="page-actions">
                <span class="te-hint" id="plSaved">${esc(savedText)}</span>
                <button class="btn btn-secondary btn-sm" id="plList">${this.host.detailBack ? '뒤로' : '목록'}</button>
                ${buttons}
              </div>
            </div>
            ${notes.join('')}
            <div class="te-meta">
              <span>대상 <b id="teTarget">${target ? `배치 ${esc(target.label || target.production_batch_id)}` : esc(d.subject || '-')}</b></span>
              <span>제조일 <b>${esc(this.workDate || '미정')}</b></span>
              <span id="teAuthor">작성자 <b>${T.authorHtml(d)}</b></span>
              <span class="te-hint">v${d.version}</span>
            </div>
            ${this.checkHtml()}
            <div class="te-pl-layout">
              <nav class="te-pl-toc" aria-label="일지 목차">${this.tocHtml()}</nav>
              <div class="te-pl-main">
                ${this.infoHtml()}
                ${this.precheckHtml(ro)}
                ${this.materialsHtml(ro)}
                ${this.processHeadHtml(ro)}
                ${this.steps.map((s, i) => this.stepHtml(s, i, ro)).join('')}
                ${ro ? '' : `<div class="te-pl-addbar"><div class="te-pl-adder"><button class="btn btn-primary btn-sm" id="plAdd" aria-expanded="${this.menu}">+ 공정 추가</button>${this.menu ? this.menuHtml() : ''}</div><span class="te-hint">기본 제공 5종 · 공정 목록의 일반 공정 · 직접 입력</span></div>`}
              </div>
            </div>
          </div>
        </div>`;
      this.host.rerenderTopBar(() => this.host.showDetail(this.id));
      this.bind();
      window.scrollTo({ top: keep });
    },

    checkHtml() {
      if (!this.check) return '';
      const list = this.check;
      return `<div class="te-error-box" id="plCheck" role="alert"><b>${esc(list.title)}</b>
        ${list.items.length ? `<ul>${list.items.map((x) => `<li><a href="#" data-goto="${esc(x.target || '')}">${esc(x.text)}</a></li>`).join('')}</ul>` : ''}</div>`;
    },

    tocHtml() {
      const L = this.linked;
      const err = !L || !L.linked;
      const preOk = PRECHECKS.every(([k]) => !blank(this.info[k])) && !blank(this.info.inspector);
      const mats = this.matRows();
      const stock = mats.filter((m) => m.is_stock_managed);
      const left = stock.filter((m) => !m.input_count).length;
      const item = (target, no, dot, label) => `<a href="#" data-goto="${target}"><span class="te-pl-tn">${no}</span><span class="te-pl-dot te-pl-dot-${dot}"></span><span>${esc(label)}</span></a>`;
      return [
        item('plInfo', '', err && !this.completed ? 'bad' : 'link', '기본정보'),
        item('plPre', '', preOk ? 'ok' : 'idle', '작업 전 점검'),
        item('plMat', '1', err && !this.completed ? 'bad' : (left ? 'warn' : 'link'), '원료칭량'),
        item('plProc', '', this.steps.length ? 'link' : 'idle', `공정${this.info.template_name ? ` · ${this.info.template_name}` : ''}`),
        ...this.steps.map((s, i) => item(`plStep${i}`, i + 2, stepState(s.values), s.values.name || '공정명 없음')),
      ].join('');
    },

    errorBox() {
      return `<div class="te-pl-linkerr" data-linkerr>불러오지 못했습니다 — 나머지는 계속 쓸 수 있습니다 <button class="btn btn-secondary btn-sm" data-reload>다시 불러오기</button></div>`;
    },

    infoHtml() {
      const frozen = this.completed && this.linked && this.linked.frozen && this.linked.frozen.batch;
      const b = this.batch;
      const kv = (label, value) => `<div><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
      const empty = (text, why, warn) => `<span class="${warn ? 'te-pl-miss' : 'te-hint'}"${why ? ` title="${esc(why)}"` : ''}>${esc(text)}</span>`;
      let body;
      if (frozen) {
        const f = this.linked.frozen.batch;
        body = `<dl class="te-kv">${kv('제조일', esc(f.manufactured_date || '미정'))}${kv('LOT NO', f.lot_numbers ? esc(f.lot_numbers) : empty('산출 전'))}
          ${kv('유형 및 제품명', esc(f.product || '-'))}${kv('품목제조보고번호', f.report_no ? esc(f.report_no) : empty('—', '', true))}
          ${kv('생산지시량', f.planned ? esc(f.planned) : empty('미정'))}${kv('실생산량', f.output ? esc(f.output) : empty('산출 전'))}</dl>
          <div class="te-hint">고정 ${esc(T.fmtDateTime(f.frozen_at))}</div>`;
      } else if (!b) {
        body = this.errorBox();
      } else {
        body = `<dl class="te-kv">
          ${kv('제조일', b.manufactured_date ? esc(b.manufactured_date) : empty('미정'))}
          ${kv('LOT NO', b.lot_numbers ? esc(b.lot_numbers) : empty('산출 전'))}
          ${kv('유형 및 제품명', b.food_type ? esc(b.product) : `[ — ] ${esc(b.item_name)} ${empty('수불 품목 정보에 없음', '', true)}`)}
          ${kv('품목제조보고번호', b.report_no ? esc(b.report_no) : `— ${empty('수불 품목 정보에 없음', '', true)}`)}
          ${kv('생산지시량', b.planned ? esc(b.planned) : empty('미정'))}
          ${kv('실생산량', b.output_e6 ? esc(b.output) : empty(`산출 전 · 0 ${b.unit || ''}`))}</dl>`;
      }
      return `<section class="te-pl-sec" id="plInfo"><div class="te-pl-sec-head"><span class="te-section-title">기본정보</span><span class="te-pl-chip-link">${frozen ? '작성완료 때 고정' : '수불에서 연동'}</span>${!frozen && !b ? '<span class="te-pl-chip-bad">연동 오류</span>' : ''}</div>${body}</section>`;
    },

    precheckHtml(ro) {
      const dis = ro ? ' disabled' : '';
      const bad = (k) => (this.check && blank(this.info[k]) ? ' te-field-error' : '');
      return `<section class="te-pl-sec" id="plPre"><div class="te-pl-sec-head"><span class="te-section-title">작업 전 점검</span><span class="te-hint">모두 필수</span></div>
        ${PRECHECKS.map(([k, label], i) => `<div class="te-pl-pc"><span>${i + 1}. ${esc(label)}</span>${this.seg(`info:${k}`, this.info[k], ro, bad(k))}</div>`).join('')}
        <div class="form-group te-pl-inspector"><label class="form-label" for="plInspector">점검자 *</label>
          <select class="form-control${bad('inspector')}" id="plInspector" data-info="inspector"${dis}>${T.staffOptions(this.info.inspector)}</select></div></section>`;
    },

    seg(key, value, ro, extra = '') {
      const dis = ro ? ' disabled' : '';
      return `<span class="te-pl-seg${extra}" role="group" data-seg="${esc(key)}">${['적합', '부적합'].map((v) => `<button type="button" class="te-pl-seg-${v === '적합' ? 'ok' : 'ng'}" data-v="${v}" aria-pressed="${value === v}"${dis}>${v}</button>`).join('')}</span>`;
    },

    // 원료칭량 표 행: 작성완료면 고정 값, 아니면 연동 값
    matRows() {
      if (this.frozenMaterials) {
        return this.linked.frozen.materials.map((m) => ({ ...m, frozen: true, alternatives: m.alternatives ? m.alternatives.split(', ') : [], is_stock_managed: m.used_e6 === null ? true : null, input_count: m.used_e6 === null ? 0 : 1 }));
      }
      return (this.linked && this.linked.linked && this.linked.linked.materials) || [];
    },

    materialsHtml(ro) {
      const L = this.linked;
      const frozen = !!this.frozenMaterials;
      if (!frozen && (!L || !L.linked)) {
        return `<section class="te-pl-sec" id="plMat"><div class="te-pl-sec-head"><span class="te-pl-no">1</span><span class="te-section-title">원료칭량</span><span class="te-pl-chip-bad">연동 오류</span></div>${this.errorBox()}</section>`;
      }
      const rows = this.matRows();
      if (!rows.length) {
        return `<section class="te-pl-sec" id="plMat"><div class="te-pl-sec-head"><span class="te-pl-no">1</span><span class="te-section-title">원료칭량</span>${frozen ? '<span class="te-pl-chip-link">작성완료 때 고정</span>' : ''}<span class="badge badge-neutral" id="plMatChip">BOM 없음</span></div>
          <div class="te-empty">이 배치에 BOM 정보가 없습니다. 생산지시에서 BOM을 지정하면 원료가 여기에 표시됩니다.</div></section>`;
      }
      const stock = rows.filter((m) => m.is_stock_managed);
      const left = stock.filter((m) => !m.input_count).length;
      const chip = frozen ? '<span class="te-pl-chip-link">작성완료 때 고정</span>'
        : (left === stock.length && stock.length ? `<span class="badge badge-neutral" id="plMatChip">투입 전 0/${stock.length}</span>`
          : (left ? `<span class="te-pl-chip-warn" id="plMatChip">투입 ${stock.length - left}/${stock.length} · 미투입 ${left}</span>` : `<span class="te-pl-chip-ok" id="plMatChip">투입 ${stock.length}/${stock.length}</span>`));
      const dates = rows.map((m) => m.first_date).filter(Boolean).sort();
      const dis = ro ? ' disabled' : '';
      const unlinked = !frozen && L.linked.unlinked_usage_count ? `<div class="te-pl-warn" id="plUnlinked">BOM에 없는 투입 ${L.linked.unlinked_usage_count}건 — 표에 넣지 않았습니다</div>` : '';
      const body = rows.map((m) => {
        const mine = this.mats[m.bom_line_id] ? this.mats[m.bom_line_id].values : {};
        const direct = !frozen && m.is_stock_managed === false;
        let used;
        if (direct) {
          used = ro ? esc(blank(mine.used) ? '-' : mine.used) : `<input class="form-control te-pl-num" data-mat="${m.bom_line_id}" data-key="used" inputmode="decimal" value="${esc(blank(mine.used) ? '' : mine.used)}" aria-label="${esc(m.item_name)} 사용량">`;
          used += ' <span class="badge badge-neutral">직접 입력</span>';
        } else if (m.used_e6 === null || m.used_e6 === undefined) {
          used = '<span class="te-pl-unused">미투입</span>';
        } else {
          const diff = m.standard_e6 !== null && m.standard_e6 !== undefined && m.used_e6 !== m.standard_e6;
          used = `<span class="${diff ? 'te-pl-diff' : ''}">${esc(q6(m.used_e6))}</span>`;
        }
        const alt = m.alternatives && m.alternatives.length ? `<div class="te-hint">대체: ${esc(m.alternatives.join(', '))}</div>` : '';
        const unconv = m.unconvertible_count ? `<div class="te-pl-miss">단위 환산 불가 투입 ${m.unconvertible_count}건</div>` : '';
        const worker = frozen || ro ? T.personHtml(mine.worker) : `<select class="form-control te-pl-sel" data-mat="${m.bom_line_id}" data-key="worker" aria-label="${esc(m.item_name)} 작업자">${T.staffOptions(mine.worker)}</select>`;
        const note = frozen || ro ? esc(mine.note || '') : `<input class="form-control" data-mat="${m.bom_line_id}" data-key="note" maxlength="100" value="${esc(mine.note || '')}" aria-label="${esc(m.item_name)} 비고">`;
        return `<tr data-line="${m.bom_line_id}"><td class="mono">${esc(m.item_code)}</td><td>${esc(m.item_name)}${alt}</td><td>${m.origin ? esc(m.origin) : '<span class="te-hint">—</span>'}</td>
          <td class="te-r">${pct(m.ratio_e6) || '<span class="te-hint">—</span>'}</td><td class="te-r">${esc(q6(m.standard_e6)) || '<span class="te-hint">—</span>'}</td>
          <td class="te-r" data-used>${used}${unconv}</td><td>${esc(m.unit || '')}</td><td>${m.first_date ? esc(m.first_date.slice(5)) : '<span class="te-hint">—</span>'}</td>
          <td>${worker}</td><td>${note}</td></tr>`;
      }).join('');
      // 합계 줄(화면 3.4): 단위가 모두 같을 때만 투입량·사용량 합
      const units = new Set(rows.map((m) => m.unit));
      const sum = (key) => rows.reduce((a, m) => a + (m[key] || 0), 0);
      const foot = `<tfoot><tr id="plMatSum"><td colspan="3">합계</td><td class="te-r">${pct(sum('ratio_e6'))}</td>
        <td class="te-r">${units.size === 1 ? esc(q6(sum('standard_e6'))) : '<span class="te-hint">단위 다름</span>'}</td>
        <td class="te-r">${units.size === 1 ? esc(q6(sum('used_e6'))) : '<span class="te-hint">—</span>'}</td><td colspan="4"></td></tr></tfoot>`;
      const allSame = ro || frozen ? '' : '<button class="btn btn-secondary btn-sm" id="plMatSame" title="첫 줄 작업자를 모든 원료에">모두 같은 사람</button>';
      return `<section class="te-pl-sec" id="plMat"><div class="te-pl-sec-head"><span class="te-pl-no">1</span><span class="te-section-title">원료칭량</span><span class="te-pl-chip-link">원료 투입에서 연동</span>${chip}<span class="te-pl-grow"></span>${allSame}</div>
        <div class="te-hint">작업일 ${dates.length ? esc(dates[0]) : '투입 전'} · 원료 투입 기록을 그대로 보여 줍니다(여기서는 고칠 수 없음). 투입 LOT 번호는 표시하지 않습니다.</div>${unlinked}
        <div class="te-table-wrap"><table class="data-table te-pl-mat"><thead><tr><th>원료코드</th><th>원료명</th><th>원산지</th><th class="te-r">비율</th><th class="te-r">투입량</th><th class="te-r">사용량</th><th>단위</th><th>투입일</th><th>작업자</th><th>비고</th></tr></thead>
        <tbody>${body}</tbody>${foot}</table></div></section>`;
    },

    processHeadHtml(ro) {
      const t = this.info.template_name;
      const last = this.linked && this.linked.last_template;
      const head = `<div class="te-pl-sec-head"><span class="te-section-title">공정</span>${t ? `<span class="te-pl-chip-info" id="plTpl">템플릿: ${esc(t)}</span><span class="te-hint">${esc(T.fmtDateTime(this.info.template_at))} 불러옴</span>` : '<span class="badge badge-neutral" id="plTpl">템플릿 없음</span>'}<span class="te-pl-grow"></span>
        ${ro ? (this.completed && !this.cancelled && this.mayWrite && this.steps.length ? '<button class="btn btn-secondary btn-sm" id="plSaveTpl">템플릿으로 저장</button>' : '') : `<button class="btn btn-secondary btn-sm" id="plLoad">공정 템플릿 불러오기</button><button class="btn btn-secondary btn-sm" id="plSaveTpl"${this.steps.length ? '' : ' disabled'}>템플릿으로 저장</button>`}</div>`;
      const empty = this.steps.length ? '' : `<div class="te-pl-empty" id="plEmpty"><div>아직 공정이 없습니다. 공정 템플릿을 불러오면 등록해 둔 공정 순서가 그대로 깔리고, 아래 [+ 공정 추가]로 하나씩 넣을 수도 있습니다.</div>
        ${last && !ro ? `<div><span class="te-hint">이 품목의 지난 배치에서 쓴 템플릿</span> <span class="te-pl-chip-info">${esc(last.name)}</span> <button class="btn btn-primary btn-sm" id="plQuick" data-tid="${last.process_template_id}">바로 불러오기</button></div>` : ''}
        ${ro ? '' : '<button class="btn btn-secondary btn-sm" id="plPick">템플릿 고르기</button>'}</div>`;
      return `<section class="te-pl-sec" id="plProc">${head}${empty}</section>`;
    },

    stepHtml(s, i, ro) {
      const v = s.values;
      const K = KIND[v.kind] || KIND.GEN;
      const errs = this.check ? stepMissing(v) : [];
      const er = (k) => (errs.includes(k) ? ' te-field-error' : '');
      const dis = ro ? ' disabled' : '';
      const id = `s${i}`;
      const state = stepState(v);
      const tag = K.ccp ? `<span class="te-pl-chip-ccp">${K.tag}</span>`
        : (v.kind === 'GEN' ? (v.process_id ? `<span class="badge badge-neutral">일반 · ${esc(MODES[v.mode] || '-')}</span>` : `<span class="te-pl-chip-warn">일지 한정 · ${esc(MODES[v.mode] || '-')}</span>`) : `<span class="te-pl-chip-info">${K.tag}</span>`);
      const name = ro ? `<b>${esc(v.name || '')}</b>` : `<input class="form-control te-pl-name${er('name')}" data-step="${i}" data-key="name" maxlength="40" value="${esc(v.name || '')}" placeholder="공정명" aria-label="공정 표시명">`;
      const tools = ro ? '' : `<span class="te-pl-tools"><button class="btn btn-secondary btn-sm" data-move="${i}" data-dir="-1" aria-label="위로"${i === 0 ? ' disabled' : ''}>↑</button><button class="btn btn-secondary btn-sm" data-move="${i}" data-dir="1" aria-label="아래로"${i === this.steps.length - 1 ? ' disabled' : ''}>↓</button><button class="btn btn-secondary btn-sm" data-del="${i}">삭제</button></span>`;
      const units = ['분', '시간', '일'].map((u) => `<option${v.dur_unit === u ? ' selected' : ''}>${u}</option>`).join('');
      let body = `<div class="te-pl-grid">
        <div class="form-group"><label class="form-label" for="${id}d">작업일 *</label><input type="date" class="form-control${er('work_date')}" id="${id}d" data-step="${i}" data-key="work_date" value="${esc(v.work_date || '')}"${dis}></div>
        <div class="form-group"><label class="form-label" for="${id}w">작업자 *</label><select class="form-control${er('worker')}" id="${id}w" data-step="${i}" data-key="worker"${dis}>${T.staffOptions(v.worker)}</select></div>
        <div class="form-group"><label class="te-check"><input type="checkbox" data-step="${i}" data-key="dur_on"${v.dur_on ? ' checked' : ''}${dis}> 소요기간 기록</label>
          <div class="te-pl-inline"><input type="number" min="0" step="0.5" class="form-control${er('dur_value')}" data-step="${i}" data-key="dur_value" value="${esc(v.dur_on && !blank(v.dur_value) ? v.dur_value : '')}" placeholder="${v.dur_on ? '' : '기록 안 함'}" aria-label="소요기간"${ro || !v.dur_on ? ' disabled' : ''}>
          <select class="form-control te-pl-unit${er('dur_unit')}" data-step="${i}" data-key="dur_unit" aria-label="소요기간 단위"${ro || !v.dur_on ? ' disabled' : ''}><option value="">-</option>${units}</select></div></div>
        ${v.kind === 'GEN' ? `<div class="form-group"><label class="form-label" for="${id}m">입력 방식</label><select class="form-control${er('mode')}" id="${id}m" data-step="${i}" data-key="mode" data-confirm-mode${dis}>${Object.entries(MODES).map(([k, l]) => `<option value="${k}"${v.mode === k ? ' selected' : ''}>${l}</option>`).join('')}</select></div>` : ''}
        <div class="form-group te-pl-full"><label class="form-label" for="${id}x">공정 설명</label><textarea class="form-control" id="${id}x" data-step="${i}" data-key="desc" rows="2" maxlength="300"${dis}>${esc(v.desc || '')}</textarea></div></div>`;
      if (v.kind === 'GEN' && !v.process_id && !ro) {
        body += `<div class="te-pl-warn" data-register-box="${i}">이 일지에서만 쓰는 공정입니다. <button class="btn btn-secondary btn-sm" data-register="${i}">공정 목록에도 등록</button></div>`;
      }
      body += this.kindHtml(s, i, er, ro);
      const pulled = v.ccp_pulled_at ? `<div class="te-hint" data-pulled>CCP 일지에서 가져옴 · ${esc(T.fmtDateTime(v.ccp_pulled_at))}</div>` : '';
      return `<section class="te-pl-step te-pl-step-${state}" id="plStep${i}" data-step-card="${i}">
        <div class="te-pl-step-head"><span class="te-pl-no">${i + 2}</span>${name}${tag}<span class="te-pl-state te-pl-state-${state}">${STATE_LABEL[state]}</span><span class="te-pl-grow"></span>${tools}</div>
        ${body}${pulled}</section>`;
    },

    kindHtml(s, i, er, ro) {
      const v = s.values;
      const K = KIND[v.kind] || KIND.GEN;
      const dis = ro ? ' disabled' : '';
      const qtyUnit = (key) => {
        const opts = QTY_UNITS.includes(v[key]) || blank(v[key]) ? QTY_UNITS : [v[key], ...QTY_UNITS];
        return `<select class="form-control te-pl-unit${er(key)}" data-step="${i}" data-key="${key}" aria-label="단위"${dis}><option value="">-</option>${opts.map((u) => `<option${v[key] === u ? ' selected' : ''}>${esc(u)}</option>`).join('')}</select>`;
      };
      const tt = () => {
        const h = blank(v.time_min) ? '' : Math.floor(v.time_min / 60);
        const m = blank(v.time_min) ? '' : v.time_min % 60;
        return `<div class="te-pl-grid"><div class="form-group"><label class="form-label">온도 *</label><div class="te-pl-inline"><input type="number" step="0.1" class="form-control${er('temp')}" data-step="${i}" data-key="temp" value="${esc(blank(v.temp) ? '' : v.temp)}" aria-label="온도"${dis}><span>℃</span></div></div>
          <div class="form-group"><label class="form-label">시간 *</label><div class="te-pl-inline"><input type="number" min="0" class="form-control${er('time_min')}" data-step="${i}" data-key="time_h" value="${esc(h)}" aria-label="시간"${dis}><span>시간</span><input type="number" min="0" max="59" class="form-control${er('time_min')}" data-step="${i}" data-key="time_m" value="${esc(m)}" aria-label="분"${dis}><span>분</span></div></div>
          <div class="form-group"><span class="form-label">판정</span><span class="te-hint">기준·판정 없음(값만 기록)</span></div></div>`;
      };
      if (K.ccp) {
        const docId = this.ccpDocs[v.kind];
        const input = v.kind === 'CCP-2B' ? tt() : `<div class="form-group"><span class="form-label">결과 *</span>${this.seg(`step:${i}:verdict`, v.verdict, ro, er('verdict'))}</div>`;
        return `${input}<div class="te-pl-inline te-pl-ccp-tools">${docId && !ro ? `<button class="btn btn-secondary btn-sm" data-pull="${i}">CCP 일지 값 가져오기</button>` : ''}${docId ? `<button class="btn btn-secondary btn-sm" data-open-ccp="${docId}">일지 열기 ↗</button>` : `<span class="te-pl-miss">이 배치의 ${K.doc}가 없습니다</span>`}
          <span class="te-hint">출력에는 여기 입력한 값이 들어갑니다. CCP 일지와 같은지는 검사하지 않습니다.</span></div>`;
      }
      if (v.kind === 'INNER' || (v.kind === 'GEN' && v.mode === 'QTY')) {
        return `<div class="te-pl-grid"><div class="form-group"><label class="form-label">${v.kind === 'INNER' ? '작업 수량' : '수량'} *</label><div class="te-pl-inline"><input type="number" min="0" class="form-control${er('qty')}" data-step="${i}" data-key="qty" value="${esc(blank(v.qty) ? '' : v.qty)}" aria-label="수량"${dis}>${qtyUnit('qty_unit')}</div></div>
          ${v.kind === 'INNER' ? `<div class="form-group"><label class="form-label">포장 규격</label><input class="form-control" data-step="${i}" data-key="spec" maxlength="40" value="${esc(v.spec || '')}" placeholder="예: 1환 3.75 g"${dis}></div>` : ''}</div>`;
      }
      if (v.kind === 'OUTER') {
        return `<div class="te-pl-grid"><div class="form-group"><label class="form-label">포장재질 *</label><input class="form-control${er('material')}" data-step="${i}" data-key="material" maxlength="100" value="${esc(v.material || '')}"${dis}></div>
          <div class="form-group"><label class="form-label">소비기한 *</label><input type="date" class="form-control${er('expiry')}" data-step="${i}" data-key="expiry" value="${esc(v.expiry || '')}"${dis}></div>
          <div class="form-group"><label class="form-label">완제품수량 *</label><div class="te-pl-inline"><input type="number" min="0" class="form-control${er('fg_qty')}" data-step="${i}" data-key="fg_qty" value="${esc(blank(v.fg_qty) ? '' : v.fg_qty)}" aria-label="완제품수량"${dis}>${qtyUnit('fg_unit')}</div></div>
          <div class="form-group te-pl-full"><label class="form-label">특이사항</label><textarea class="form-control" data-step="${i}" data-key="remark" rows="2" maxlength="300"${dis}>${esc(v.remark || '')}</textarea></div></div>`;
      }
      if (v.mode === 'TEMP_TIME') return tt();
      return `<div class="form-group"><span class="form-label">결과 *</span>${this.seg(`step:${i}:verdict`, v.verdict, ro, er('verdict'))}</div>`;
    },

    menuHtml() {
      const have = new Set(this.steps.map((s) => s.values.kind));
      const builtins = this.procs.filter((p) => p.is_builtin);
      const general = this.procs.filter((p) => !p.is_builtin && p.is_active);
      const missing = builtins.filter((p) => KIND[p.kind] && KIND[p.kind].ccp && !this.ccpDocs[p.kind]);
      const btn = (p) => {
        const used = have.has(p.kind);
        const noDoc = KIND[p.kind].ccp && !this.ccpDocs[p.kind];
        const note = used ? '이미 있음' : (noDoc ? `${p.kind} 일지 없음` : (KIND[p.kind].ccp ? `${p.kind} 일지 연동` : '고정 입력'));
        return `<button type="button" data-add-proc="${p.process_id}"${used || noDoc ? ' disabled' : ''}><span>${esc(p.name)}</span><span class="te-hint">${esc(note)}</span></button>`;
      };
      return `<div class="te-pl-menu" role="menu" id="plMenu"><div class="te-pl-menu-grp">기본 제공</div>${builtins.map(btn).join('')}
        ${missing.length ? '<div class="te-pl-menu-note">CCP 공정은 이 배치에 CCP 일지가 있을 때만 넣을 수 있습니다.</div>' : ''}
        <div class="te-pl-menu-grp">일반 공정 (공정 목록)</div>${general.map((p) => `<button type="button" data-add-proc="${p.process_id}"><span>${esc(p.name)}</span><span class="te-hint">${esc(MODES[p.mode] || '')}</span></button>`).join('') || '<div class="te-pl-menu-note">사용 중인 일반 공정이 없습니다</div>'}
        <button type="button" data-add-custom><span>직접 입력</span><span class="te-hint">이름·입력 방식 직접</span></button>
        <button type="button" data-manage="process"><span>공정 목록 관리 ↗</span><span class="te-hint">생산 기준정보</span></button></div>`;
    },

    // ------------------------------------------------------------ 이벤트
    bind() {
      const $ = (sel) => this.root.querySelector(sel);
      const all = (sel) => this.root.querySelectorAll(sel);
      $('#plList').addEventListener('click', async () => {
        if (this.dirty && !(await T.confirm('저장 안 된 변경', '저장하지 않은 변경이 있습니다. 나갈까요?', '나가기', 'btn-danger'))) return;
        this.dirty = false;
        this.host.goBack();
      });
      $('#plSave')?.addEventListener('click', () => this.save());
      $('#plComplete')?.addEventListener('click', () => this.complete());
      $('#plReopen')?.addEventListener('click', () => this.reopen());
      $('#plLoad')?.addEventListener('click', () => this.openLoad());
      $('#plPick')?.addEventListener('click', () => this.openLoad());
      $('#plQuick')?.addEventListener('click', (e) => this.applyTemplate(Number(e.currentTarget.dataset.tid), 'replace'));
      $('#plSaveTpl')?.addEventListener('click', () => this.openSaveTemplate());
      $('#plAdd')?.addEventListener('click', () => { this.menu = !this.menu; this.render(); });
      $('#plMatSame')?.addEventListener('click', () => this.sameWorker());
      all('[data-goto]').forEach((a) => a.addEventListener('click', (e) => {
        e.preventDefault();
        const el = this.root.querySelector(`#${a.dataset.goto}`);
        if (el) el.scrollIntoView({ block: 'start', behavior: 'smooth' });
      }));
      all('[data-reload]').forEach((b) => b.addEventListener('click', () => this.refresh()));
      all('[data-seg] button').forEach((b) => b.addEventListener('click', () => {
        const key = b.closest('[data-seg]').dataset.seg.split(':');
        const value = b.dataset.v;
        if (key[0] === 'info') this.info[key[1]] = this.info[key[1]] === value ? null : value;
        else this.steps[Number(key[1])].values[key[2]] = this.steps[Number(key[1])].values[key[2]] === value ? null : value;
        this.markDirty();
        this.render();
      }));
      all('[data-info]').forEach((el) => el.addEventListener('change', () => {
        this.info[el.dataset.info] = el.value ? Number(el.value) : null;
        this.markDirty();
      }));
      all('[data-mat]').forEach((el) => el.addEventListener(el.tagName === 'SELECT' ? 'change' : 'input', () => {
        const line = Number(el.dataset.mat);
        const key = el.dataset.key;
        const row = this.mats[line] || (this.mats[line] = { sid: null, values: { bom_line_id: line }, orig: {} });
        row.values[key] = key === 'worker' ? (el.value ? Number(el.value) : null) : (key === 'used' ? num(el.value) : (el.value || null));
        this.markDirty();
      }));
      all('[data-step]').forEach((el) => {
        const event = el.type === 'checkbox' || el.tagName === 'SELECT' ? 'change' : 'input';
        el.addEventListener(event, () => this.onStepInput(el));
      });
      all('[data-move]').forEach((b) => b.addEventListener('click', () => {
        const i = Number(b.dataset.move);
        const j = i + Number(b.dataset.dir);
        [this.steps[i], this.steps[j]] = [this.steps[j], this.steps[i]];
        this.markDirty();
        this.render();
      }));
      all('[data-del]').forEach((b) => b.addEventListener('click', async () => {
        const s = this.steps[Number(b.dataset.del)];
        const K = KIND[s.values.kind] || KIND.GEN;
        if (!(await T.confirm('공정 삭제', `${esc(s.values.name || '이 공정')}을(를) 지울까요?${K.ccp ? ` 공정을 빼도 ${K.doc}는 남습니다.` : ''} [저장]을 눌러야 반영됩니다.`, '지우기', 'btn-danger'))) return;
        this.steps.splice(Number(b.dataset.del), 1);
        this.markDirty();
        this.render();
      }));
      all('[data-add-proc]').forEach((b) => b.addEventListener('click', () => this.addProcess(Number(b.dataset.addProc))));
      all('[data-add-custom]').forEach((b) => b.addEventListener('click', () => this.addRow({ kind: 'GEN', process_id: null, name: '', mode: 'JUDGE' })));
      all('[data-manage]').forEach((b) => b.addEventListener('click', () => this.manage(b.dataset.manage)));
      all('[data-register]').forEach((b) => b.addEventListener('click', () => this.registerProcess(Number(b.dataset.register))));
      all('[data-pull]').forEach((b) => b.addEventListener('click', () => this.pullCcp(Number(b.dataset.pull))));
      all('[data-open-ccp]').forEach((b) => b.addEventListener('click', async () => {
        if (this.dirty && !(await T.confirm('저장 안 된 변경', '저장하지 않은 변경이 있습니다. CCP 일지로 갈까요?', '이동', 'btn-danger'))) return;
        this.dirty = false;
        T.open('doc-box', { documentId: Number(b.dataset.openCcp), back: { page: 'doc-box', intent: { documentId: this.id } } });
      }));
      // A5(S5a r1): 사이드바 등 다른 화면으로 갈 때도 저장 안 한 변경 확인(뒤로 가기 기록 이동은 제외)
      if (typeof App !== 'undefined' && !App._plGuard) {  // eslint-disable-line no-undef — 시제품 app.js의 const App
        const original = App.navigate;
        App._plGuard = true;
        // r2(재검토 B1): 확인을 기다리는 동안 다른 이동(뒤로 가기 포함)이 오면 그 확인은 버림 — 늦은 [나가기]가 이동하지 않게
        let seq = 0;
        let pending = null;
        App.navigate = async function (page, updateNav = true, fromHistory = false) {
          const mine = ++seq;
          if (pending) { pending.remove(); pending = null; }
          if (!fromHistory && PL.dirty && document.querySelector('.te-pl')) {
            const asked = T.confirm('저장 안 된 변경', '저장하지 않은 생산일지 변경이 있습니다. 이 화면을 나갈까요?', '나가기', 'btn-danger');
            pending = [...document.querySelectorAll('.te-modal-wrap')].pop() || null;
            const ok = await asked;
            if (mine !== seq) return undefined;
            pending = null;
            if (!ok) return undefined;
          }
          PL.dirty = false;
          return original.call(this, page, updateNav, fromHistory);
        };
      }
      if (!this._unload) {
        this._unload = (e) => { if (this.dirty && document.querySelector('.te-pl')) { e.preventDefault(); e.returnValue = ''; } };
        window.addEventListener('beforeunload', this._unload);
      }
    },

    async onStepInput(el) {
      const i = Number(el.dataset.step);
      const v = this.steps[i].values;
      const key = el.dataset.key;
      if (key === 'dur_on') {
        v.dur_on = el.checked;
        if (!el.checked) { v.dur_value = null; v.dur_unit = null; }
        this.markDirty();
        this.render();
        return;
      }
      if (key === 'mode') {
        const filled = ['verdict', 'temp', 'time_min', 'qty', 'qty_unit'].some((k) => !blank(v[k]));
        if (filled && !(await T.confirm('입력 방식 바꾸기', '이 공정에 입력한 결과 값이 있습니다. 입력 방식을 바꿀까요? (값은 지우지 않습니다)', '바꾸기'))) {
          el.value = v.mode;
          return;
        }
        v.mode = el.value;
        this.markDirty();
        this.render();
        return;
      }
      if (key === 'time_h' || key === 'time_m') {
        const card = el.closest('[data-step-card]');
        const h = card.querySelector('[data-key="time_h"]').value;
        const m = card.querySelector('[data-key="time_m"]').value;
        v.time_min = blank(h) && blank(m) ? null : (Number(h || 0) * 60 + Number(m || 0));
      } else if (['temp', 'qty', 'fg_qty', 'dur_value'].includes(key)) v[key] = num(el.value);
      else if (key === 'worker') v[key] = el.value ? Number(el.value) : null;
      else v[key] = el.value === '' ? null : el.value;
      this.markDirty();
      this.refreshState(i);
      if (key === 'name') {
        const toc = this.root.querySelectorAll('.te-pl-toc a')[4 + i];
        if (toc) toc.lastElementChild.textContent = v.name || '공정명 없음';
      }
    },

    // C1(S5a r1): 입력할 때 그 카드·목차의 상태 점만 다시
    refreshState(i) {
      const state = stepState(this.steps[i].values);
      const card = this.root.querySelector(`#plStep${i}`);
      if (card) {
        card.classList.remove('te-pl-step-ok', 'te-pl-step-doing', 'te-pl-step-idle');
        card.classList.add(`te-pl-step-${state}`);
        const label = card.querySelector('.te-pl-state');
        if (label) { label.className = `te-pl-state te-pl-state-${state}`; label.textContent = STATE_LABEL[state]; }
      }
      const dot = this.root.querySelectorAll('.te-pl-toc a')[4 + i]?.querySelector('.te-pl-dot');
      if (dot) dot.className = `te-pl-dot te-pl-dot-${state}`;
    },

    sameWorker() {
      const rows = this.matRows();
      const first = rows.length && this.mats[rows[0].bom_line_id] ? this.mats[rows[0].bom_line_id].values.worker : null;
      if (!first) { T.toast('첫 줄 작업자를 먼저 고르세요.', 'error'); return; }
      rows.forEach((m) => {
        const row = this.mats[m.bom_line_id] || (this.mats[m.bom_line_id] = { sid: null, values: { bom_line_id: m.bom_line_id }, orig: {} });
        row.values.worker = first;
      });
      this.markDirty();
      this.render();
    },

    // ------------------------------------------------------------ 공정 넣기
    newValues(p) {
      const v = { kind: p.kind, process_id: p.process_id, name: p.name, work_date: this.workDate, desc: p.description || null, dur_on: !!p.std_duration };
      if (p.kind === 'GEN') v.mode = p.mode;
      if (p.std_duration) { v.dur_value = p.std_duration.value; v.dur_unit = p.std_duration.unit; }
      return v;
    },

    addRow(values) {
      const v = { work_date: this.workDate, ...values };
      const outer = this.steps.findIndex((s) => s.values.kind === 'OUTER');
      const at = outer >= 0 && v.kind !== 'OUTER' ? outer : this.steps.length;
      this.steps.splice(at, 0, { sid: null, values: v, orig: {} });
      this.menu = false;
      this.markDirty();
      this.render();
      const el = this.root.querySelector(`#plStep${at}`);
      if (el) el.scrollIntoView({ block: 'center' });
    },

    addProcess(processId) {
      const p = this.procs.find((x) => x.process_id === processId);
      if (p) this.addRow(this.newValues(p));
    },

    async registerProcess(i, confirmSimilar = false) {
      const v = this.steps[i].values;
      if (blank(v.name)) { T.toast('공정 이름을 먼저 입력하세요.', 'error'); return; }
      const r = await api.post(`production-logs/${this.id}/register-process`, { name: v.name, mode: v.mode || 'JUDGE', confirm_similar: confirmSimilar });
      if (!r.ok) {
        if (r.data && r.data.code === 'PLG_SIMILAR_NAME') {
          const names = (r.data.details || []).map((x) => x.name).filter(Boolean).join(', ');
          if (await T.confirm('비슷한 이름', `공정 목록에 비슷한 이름이 있습니다: <b>${esc(names)}</b>. 그래도 등록할까요?`, '그래도 등록')) this.registerProcess(i, true);
          return;
        }
        T.toast(T.errorText(r), 'error');
        return;
      }
      const p = r.data.process;
      v.process_id = p.process_id;
      v.mode = p.mode;
      if (!this.procs.some((x) => x.process_id === p.process_id)) this.procs.push(p);
      T.toast(r.data.linked_existing ? `공정 목록의 "${p.name}"에 연결했습니다. [저장]을 눌러 반영하세요.` : `공정 목록에 "${p.name}"을(를) 등록했습니다. [저장]을 눌러 반영하세요.`);
      this.markDirty();
      this.render();
    },

    // S5b: 생산 기준정보로(저장 안 한 변경은 화면 이동 확인이 받음), [뒤로]는 사이드바·문서함으로
    manage(tab) {
      this.menu = false;
      T.open('prod-master', { tab });
    },

    async pullCcp(i) {
      const v = this.steps[i].values;
      const r = await api.get(`production-logs/${this.id}/ccp-values?kind=${encodeURIComponent(v.kind)}`);
      if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
      if (v.kind === 'CCP-2B') {
        if (blank(r.data.temp) && blank(r.data.time_min)) { T.toast('CCP 일지에 종료 전 측정 값이 없습니다.', 'error'); return; }
        v.temp = r.data.temp;
        v.time_min = r.data.time_min;
      } else {
        if (!r.data.verdict) { T.toast('CCP 일지에 측정 값이 없습니다.', 'error'); return; }
        v.verdict = r.data.verdict;
      }
      v.ccp_pulled_at = nowText();
      this.markDirty();
      this.render();
      T.toast(`CCP 일지 #${r.data.source_document_id} 값을 가져왔습니다. [저장]을 눌러 반영하세요.`);
    },

    // ------------------------------------------------------------ 저장
    stepValues(v) {
      const out = {};
      Object.entries(v).forEach(([k, x]) => { if (k !== 'done' && !blank(x)) out[k] = x; });
      return out;
    },

    payload() {
      const update = [];
      const add = [];
      const del = [];
      const infoPatch = {};
      Object.keys({ ...this.info, ...this.infoOrig }).forEach((k) => {
        if ((this.info[k] ?? null) !== (this.infoOrig[k] ?? null)) infoPatch[k] = blank(this.info[k]) ? null : this.info[k];
      });
      if (Object.keys(infoPatch).length && this.infoSid) update.push({ section_id: this.infoSid, values: infoPatch });
      const directLines = new Set(((this.linked && this.linked.linked && this.linked.linked.materials) || []).filter((m) => m.is_stock_managed === false).map((m) => m.bom_line_id));
      Object.values(this.mats).forEach((m) => {
        const values = { ...m.values };
        if (!directLines.has(values.bom_line_id)) delete values.used;
        const patch = {};
        ['worker', 'note', 'used'].forEach((k) => { if (k in values && (values[k] ?? null) !== (m.orig[k] ?? null)) patch[k] = blank(values[k]) ? null : values[k]; });
        if (m.sid) { if (Object.keys(patch).length) update.push({ section_id: m.sid, values: patch }); }
        else if (Object.values(patch).some((x) => !blank(x))) add.push({ section_def: 'materials', values: this.stepValues({ bom_line_id: values.bom_line_id, ...patch }) });
      });
      // 공정: 남은 기존 행 순서가 그대로이고 새 행이 모두 뒤에 있으면 행별로, 아니면 모두 지우고 다시(S5a-C1)
      const kept = this.steps.filter((s) => s.sid).map((s) => s.sid);
      const removed = this.origSids.filter((sid) => !kept.includes(sid));
      const sameOrder = kept.join(',') === this.origSids.filter((sid) => kept.includes(sid)).join(',');
      const firstNew = this.steps.findIndex((s) => !s.sid);
      const lastOld = this.steps.map((s) => !!s.sid).lastIndexOf(true);
      const tailOnly = firstNew < 0 || firstNew > lastOld;
      if (sameOrder && tailOnly) {
        removed.forEach((sid) => del.push(sid));
        this.steps.forEach((s) => {
          if (!s.sid) { add.push({ section_def: 'steps', values: this.stepValues(s.values) }); return; }
          const patch = {};
          Object.keys({ ...s.values, ...s.orig }).forEach((k) => {
            if (k === 'done') return;
            if ((s.values[k] ?? null) !== (s.orig[k] ?? null)) patch[k] = blank(s.values[k]) ? null : s.values[k];
          });
          if (Object.keys(patch).length) update.push({ section_id: s.sid, values: patch });
        });
      } else {
        this.origSids.forEach((sid) => del.push(sid));
        this.steps.forEach((s) => add.push({ section_def: 'steps', values: this.stepValues(s.values) }));
      }
      const sections = {};
      if (update.length) sections.update = update;
      if (add.length) sections.add = add;
      if (del.length) sections.delete = del;
      return sections;
    },

    async save({ quiet = false } = {}) {
      const sections = this.payload();
      if (!Object.keys(sections).length) {
        if (!quiet) T.toast('바뀐 내용이 없습니다.');
        this.dirty = false;
        return true;
      }
      const r = await api.patch(`documents/${this.id}`, { expected_version: this.d.version, sections });
      if (!r.ok) {
        this.showErrors(r, '저장하지 못했습니다');
        return false;
      }
      await this.refresh();
      if (!quiet) T.toast('저장했습니다.');
      return true;
    },

    async refresh() {
      const [d, linked] = await Promise.all([api.get(`documents/${this.id}`), api.get(`production-logs/${this.id}/linked`)]);
      if (!d.ok) { T.toast(T.errorText(d), 'error'); return; }
      this.d = d.data;
      this.linked = linked.ok ? linked.data : null;
      this.load();
      this.render();
    },

    // 서버 details 경로 → 화면 문구(sections[steps#n].x · sections.add[i].values.x · sections.update[i].values.x)
    detailText(e) {
      const path = e.path || '';
      const field = (path.match(/\.([a-z_]+)$/) || [])[1];
      const label = FIELD_LABEL[field] || field || '';
      let m = path.match(/^sections\[steps#(\d+)\]/);
      if (m) {
        const i = this.steps.findIndex((s) => s.rowNo === Number(m[1]));
        return { text: `${i >= 0 ? `${i + 2}. ${this.steps[i].values.name || '공정'}` : `공정 ${m[1]}행`}: ${label} — ${e.message}`, target: i >= 0 ? `plStep${i}` : 'plProc' };
      }
      if (/^sections\[info\]/.test(path)) return { text: `작업 전 점검: ${label} — ${e.message}`, target: 'plPre' };
      if (/^sections\[steps\]/.test(path)) return { text: e.message, target: 'plProc' };
      if (/materials/.test(path)) return { text: `원료칭량: ${label} — ${e.message}`, target: 'plMat' };
      if (/steps/.test(path) || /sections\.(add|update)/.test(path)) return { text: `공정: ${label} — ${e.message}`, target: 'plProc' };
      return { text: `${path ? `${path}: ` : ''}${e.message}`, target: '' };
    },

    showErrors(r, title) {
      const data = r.data || {};
      if (data.code === 'VERSION_CONFLICT') {
        T.toast('다른 사용자가 먼저 고쳤습니다. 최신 내용을 다시 불러옵니다.', 'error');
        this.refresh();
        return;
      }
      this.check = { title: `${title} — ${T.errorText(r)}`, items: (data.details || []).map((e) => this.detailText(e)) };
      this.render();
      this.root.querySelector('#plCheck')?.scrollIntoView({ block: 'center' });
    },

    async complete() {
      if (this.dirty && !(await this.save({ quiet: true }))) return;
      const r = await api.post(`documents/${this.id}/complete`, { expected_version: this.d.version });
      if (!r.ok) {
        if (r.data && r.data.code === 'COMPLETION_INCOMPLETE') {
          this.check = { title: `필수 칸이 비어 있습니다 — ${(r.data.details || []).length}건 (필수값 외에는 검사하지 않음)`, items: (r.data.details || []).map((e) => this.detailText(e)) };
          this.render();
          this.root.querySelector('#plCheck')?.scrollIntoView({ block: 'center' });
          return;
        }
        if (r.data && r.data.code === 'PLG_LINKED_UNAVAILABLE') {
          this.check = { title: '연동 값을 불러온 뒤 작성완료할 수 있습니다', items: [] };
          this.render();
          return;
        }
        this.showErrors(r, '작성완료하지 못했습니다');
        return;
      }
      await this.refresh();
      T.toast('작성완료했습니다 · 연동 값을 지금 시점으로 고정했습니다.');
    },

    async reopen() {
      const r = await api.post(`documents/${this.id}/reopen`, { expected_version: this.d.version });
      if (!r.ok) { this.showErrors(r, '작성 재개하지 못했습니다'); return; }
      await this.refresh();
      T.toast('작성중으로 돌렸습니다. 연동 값은 다시 실시간으로 보입니다.');
    },

    // ------------------------------------------------------------ PLG-SC-02 템플릿 불러오기
    async openLoad() {
      const r = await api.get('process-templates?status=active');
      if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
      const items = r.data.items;
      const last = this.linked && this.linked.last_template;
      const st = { q: '', sel: last && items.some((t) => t.process_template_id === last.process_template_id) ? last.process_template_id : (items[0] && items[0].process_template_id), detail: null, mode: 'replace' };
      const filled = this.steps.filter((s) => ['worker', 'verdict', 'temp', 'qty', 'fg_qty'].some((k) => !blank(s.values[k]))).length;
      const wrap = modal({ title: '공정 템플릿 불러오기', body: '<div id="plLoadBody"></div>', wide: true });
      const draw = async () => {
        if (st.sel && (!st.detail || st.detail.process_template_id !== st.sel)) {
          const t = await api.get(`process-templates/${st.sel}`);
          st.detail = t.ok ? t.data : null;
        }
        const list = items.filter((t) => !st.q || t.name.includes(st.q));
        const preview = st.detail ? st.detail.steps.map((s, i) => {
          const noDoc = KIND[s.kind] && KIND[s.kind].ccp && !this.ccpDocs[s.kind];
          return `<li class="${noDoc ? 'te-pl-struck' : ''}"><span class="te-pl-no">${i + 2}</span>${esc(s.resolved.name)} <span class="te-hint">${esc(KIND[s.kind] ? KIND[s.kind].tag : s.kind)}</span>${s.process_is_active ? '' : ' <span class="te-pl-chip-warn">중지됨</span>'}${noDoc ? ' <span class="te-pl-miss">일지 없음 · 빠짐</span>' : ''}</li>`;
        }).join('') : '';
        wrap.querySelector('#plLoadBody').innerHTML = `<div class="te-pl-load">
          <div class="te-pl-load-list"><input class="form-control" id="plLoadQ" placeholder="이름 검색" value="${esc(st.q)}">
            <div class="te-pl-load-items">${list.map((t) => `<button type="button" class="te-pl-load-item${t.process_template_id === st.sel ? ' on' : ''}" data-tpl="${t.process_template_id}"><b>${esc(t.name)}</b>${last && last.process_template_id === t.process_template_id ? ' <span class="te-pl-chip-info">지난 배치</span>' : ''}<br><span class="te-hint">공정 ${t.step_count}개${t.ccp_kinds && t.ccp_kinds.length ? ` · ${esc(t.ccp_kinds.join('·'))}` : ''} · 최근 ${esc(T.fmtDateTime(t.last_used_at))}</span></button>`).join('') || '<div class="te-empty">템플릿이 없습니다</div>'}</div>
            <a href="#" class="te-hint" data-manage="template">템플릿 관리 ↗</a></div>
          <div class="te-pl-load-preview"><div class="te-section-title">${st.detail ? esc(st.detail.name) : '미리보기'}</div><ol class="te-pl-preview">${preview}</ol></div></div>
          ${this.steps.length ? `<div class="te-pl-load-mode"><label class="te-check"><input type="radio" name="plMode" value="replace"${st.mode === 'replace' ? ' checked' : ''}> 바꾸기${filled ? ` <span class="te-pl-miss">입력값 있는 공정 ${filled}개가 사라집니다</span>` : ''}</label>
            <label class="te-check"><input type="radio" name="plMode" value="append"${st.mode === 'append' ? ' checked' : ''}> 덧붙이기(외포장 앞, 이미 있는 기본 제공 건너뜀)</label></div>` : ''}
          <div class="te-modal-footer"><button class="btn btn-secondary" data-close>취소</button><button class="btn btn-primary" id="plLoadGo"${st.sel ? '' : ' disabled'}>불러오기</button></div>`;
        wrap.querySelector('#plLoadQ').addEventListener('change', (e) => { st.q = e.target.value.trim(); draw(); });
        wrap.querySelectorAll('[data-tpl]').forEach((b) => b.addEventListener('click', () => { st.sel = Number(b.dataset.tpl); draw(); }));
        wrap.querySelectorAll('[name="plMode"]').forEach((b) => b.addEventListener('change', () => { st.mode = b.value; }));
        wrap.querySelector('[data-close]').addEventListener('click', () => wrap.remove());
        wrap.querySelector('[data-manage]').addEventListener('click', (e) => { e.preventDefault(); wrap.remove(); this.manage('template'); });
        wrap.querySelector('#plLoadGo').addEventListener('click', async () => {
          wrap.remove();
          await this.applyTemplate(st.sel, this.steps.length ? st.mode : 'replace');
        });
      };
      draw();
    },

    async applyTemplate(templateId, mode) {
      const r = await api.post(`production-logs/${this.id}/template-rows`, { template_id: templateId, mode });
      if (!r.ok) { T.toast(T.errorText(r), 'error'); return; }
      const rows = r.data.rows.map((v) => ({ sid: null, values: v, orig: {} }));
      if (mode === 'replace') this.steps = rows;
      else {
        const outer = this.steps.findIndex((s) => s.values.kind === 'OUTER');
        const at = outer >= 0 ? outer : this.steps.length;
        const before = rows.filter((x) => x.values.kind !== 'OUTER');
        const outerRows = rows.filter((x) => x.values.kind === 'OUTER');
        this.steps.splice(at, 0, ...before);
        this.steps.push(...outerRows);
      }
      const t = r.data.template;
      Object.assign(this.info, { template_id: t.process_template_id, template_name: t.name, template_at: t.at });
      this.markDirty();
      this.render();
      const extra = [r.data.skipped_ccp.length ? `CCP 일지 없는 공정 ${r.data.skipped_ccp.length}개 빠짐` : '', r.data.skipped_dup.length ? `이미 있는 공정 ${r.data.skipped_dup.length}개 건너뜀` : ''].filter(Boolean).join(' · ');
      T.toast(`"${t.name}" 공정 ${r.data.rows.length}개를 불러왔습니다${extra ? ` (${extra})` : ''}. [저장]을 눌러 반영하세요.`);
    },

    // ------------------------------------------------------------ PLG-SC-03 템플릿으로 저장
    openSaveTemplate() {
      const name0 = this.info.template_name || (this.batch && this.batch.item_name) || '';
      const wrap = modal({ title: '템플릿으로 저장', body: '<div id="plSaveBody"></div>', wide: true });
      const st = { name: name0, taken: null, similar: null };
      const draw = () => {
        wrap.querySelector('#plSaveBody').innerHTML = `<div class="form-group"><label class="form-label" for="plTplName">이름 *</label><input class="form-control" id="plTplName" maxlength="40" value="${esc(st.name)}"><div class="te-hint">품목명·분류를 넣으면 찾기 쉽습니다(예: "[환] 효력환")</div></div>
          <div class="te-section-title">저장될 순서</div><ol class="te-pl-preview">${this.steps.map((s, i) => `<li class="${s.values.process_id ? '' : 'te-pl-struck'}"><span class="te-pl-no">${i + 2}</span>${esc(s.values.name || '공정명 없음')} <span class="te-hint">${esc((KIND[s.values.kind] || KIND.GEN).tag)}</span>${s.values.process_id ? '' : ' <span class="te-pl-miss">공정 목록에 없음 — 빠짐</span>'}</li>`).join('')}</ol>
          <div class="te-hint">순서·표시명·설명·입력 방식·소요기간·포장 정보(공정 기본값과 다른 것만)를 저장합니다. 작업일·작업자·결과는 저장하지 않습니다.</div>
          ${st.taken ? `<div class="te-pl-warn" id="plTaken">같은 이름 템플릿이 있습니다. 덮어쓸까요? <button class="btn btn-warning btn-sm" id="plOverwrite">덮어쓰기</button></div>` : ''}
          ${st.similar ? `<div class="te-pl-warn" id="plSimilar">비슷한 이름이 있습니다: <b>${esc(st.similar)}</b> <button class="btn btn-secondary btn-sm" id="plSimilarOk">그래도 저장</button></div>` : ''}
          <div class="te-modal-footer"><button class="btn btn-secondary" data-close>취소</button><button class="btn btn-primary" id="plSaveGo">저장</button></div>`;
        const input = wrap.querySelector('#plTplName');
        input.addEventListener('input', () => { st.name = input.value; });
        wrap.querySelector('[data-close]').addEventListener('click', () => wrap.remove());
        wrap.querySelector('#plSaveGo').addEventListener('click', () => go({}));
        wrap.querySelector('#plOverwrite')?.addEventListener('click', () => go({ overwrite: true, expected_version: st.taken.version }));
        wrap.querySelector('#plSimilarOk')?.addEventListener('click', () => go({ confirm_similar: true }));
      };
      const go = async (extra) => {
        const body = { name: st.name.trim(), steps: this.steps.map((s) => this.stepValues(s.values)), ...extra };
        const r = await api.post(`production-logs/${this.id}/save-template`, body);
        if (!r.ok) {
          const code = r.data && r.data.code;
          if (code === 'PLG_NAME_TAKEN') { st.taken = (r.data.details || [])[0] || {}; st.similar = null; draw(); return; }
          if (code === 'PLG_SIMILAR_NAME') { st.similar = (r.data.details || []).map((x) => x.name).filter(Boolean).join(', ') || '있음'; draw(); return; }
          T.toast(T.errorText(r), 'error');
          return;
        }
        wrap.remove();
        T.toast(`템플릿 "${r.data.template.name}"을(를) ${r.data.overwritten ? '덮어썼' : '저장했'}습니다(공정 ${r.data.template.step_count}개${r.data.skipped_rows ? `, 일지 한정 ${r.data.skipped_rows}개 빠짐` : ''}).`);
      };
      draw();
    },
  };

  window.TempEntryProdLog = PL;
})();
