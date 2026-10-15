// =============================================
// 개발 검증 › 작성 요구 (P5 REQ 사용 화면)
// 화면: REQ-SC-01 작성 요구 테스트 · 02 테스트 입고 모달 · 03 테스트 배치 모달 · 04 호출 결과 패널
//       05 LOT별 연결 문서(P7: 입고일 → 육안검사 묶음 상세 DOC-SC-10 링크)
//       REQ-SC-05 LOT별 연결 문서(문서 상세의 LOT 링크로도 들어온다)
//       P9(C4 S5): REQ-SC-07 주기 문서 만들기 모달 · 08 주기 생성 결과 패널(04 자리) — doc-requirements/p9-s1-screens.md 2~4장, API REQ-A05·A07
// 설계: dev-notes/doc-requirements/s1-screens.md, API: s2-spec.md 2.2(A01·A02, 개발 D01~D07)
// 수불·생산이 할 호출(입고 등록·생산 시작 + 작성 요구)을 개발용 가상 데이터로 흉내 낸다.
// =============================================
(function () {
  const T = window.TempEntry;
  const api = window.HaccpApi;
  const esc = (v) => T.esc(v);
  const DEV = '/api/dev/req';

  const RESULT = { created: '새로 만듦', existing: '이미 있음' };
  const BATCH_STATUS = { PLANNED: '계획', IN_PROGRESS: '진행 중', COMPLETED: '완료', CANCELLED: '취소' };
  const PROCESS = { MANUFACTURE: '제조', PACKAGING: '포장' };
  const VERDICT = { PASS: '적합(PASS)', FAIL: '부적합(FAIL)' };
  const today = () => new Date().toLocaleDateString('sv-SE');
  const mmdd = (iso) => (iso || '').slice(5, 10).replace('-', '');

  // SC-04 결과 문구: D03도 D01·D02와 같은 "새로 만듦 / 이미 있음"(P6a-S1 REQ-SC-04).
  // 육안검사를 함께 보냈을 때만(sentInspection) 검사 값 채움 여부를 붙인다(P6a-S1 3.3).
  // 서버는 inspection을 보내지 않아도 D03에 inspection_applied: false를 주므로 그 값만으로 고르지 않는다
  // (P7 S6 A1 실패 — 새로 만든 D03이 "이미 있음"으로 보임, ISS-024)
  const resultText = (item, sentInspection = false) => {
    if (item.type_code === 'D03' && sentInspection && typeof item.inspection_applied === 'boolean') {
      return item.inspection_applied ? 'D03 새로 만듦 · 검사 값 채움' : 'D03 이미 있음 — 검사 값 채우지 않음';
    }
    return RESULT[item.result] || item.result;
  };

  // D03 최신 양식의 검사 섹션(P6 D-080: 형식은 문서 쪽이 정함 — 항목·선택지를 양식에서 읽는다)
  let inspectionSection;
  async function loadInspectionSection() {
    if (inspectionSection !== undefined) return inspectionSection;
    inspectionSection = null;
    const list = await api.get('templates');
    const d03 = (list.ok ? list.data.items : []).filter((t) => t.type_code === 'D03').sort((a, b) => b.version - a.version)[0];
    if (!d03) return null;
    const t = await api.get(`templates/${d03.template_id}`);
    inspectionSection = (t.ok && t.data.schema.sections.find((x) => x.key === 'inspection')) || null;
    return inspectionSection;
  }
  const inspectionFields = (section) => section.fields.filter((fd) => !fd.readonly && !fd.computed);
  function inspectionHtml(section) {
    if (!section) return '<p class="te-hint">D03 양식에 검사 섹션이 없어 육안검사를 함께 입력할 수 없습니다.</p>';
    const input = (fd) => (fd.options
      ? `<select class="form-control" name="insp_${fd.key}"><option value="">-</option>${fd.options.map((o) => `<option value="${esc(o)}">${esc((fd.option_labels && fd.option_labels[o]) || o)}</option>`).join('')}</select>`
      : `<input class="form-control" name="insp_${fd.key}" ${fd.max_length ? `maxlength="${fd.max_length}"` : ''}>`);
    return `<label class="te-check"><input type="checkbox" name="with_inspection" id="reqWithInspection"> 육안검사 함께 입력</label>
      <div class="te-form-grid" id="reqInspection" hidden>${inspectionFields(section).map((fd) => `
        <div class="te-field"><label>${esc(fd.label)}${fd.required ? ' *' : ''}</label>${input(fd)}</div>`).join('')}</div>`;
  }

  // 양식 이름(type_code → name). /api/v1/templates 에서 한 번 읽는다
  let templateNames = null;
  async function loadTemplateNames() {
    if (templateNames) return templateNames;
    const r = await api.get('templates');
    templateNames = {};
    (r.ok ? r.data.items : []).forEach((t) => { templateNames[t.type_code] = t.name; });
    return templateNames;
  }
  const formName = (code) => `${esc((templateNames && templateNames[code]) || code)} ${esc(code)}`;

  // ---------------------------------------------------------------- P9 주기 (REQ-SC-07·08)
  const WEEKDAY = ['일', '월', '화', '수', '목', '금', '토'];
  const seoulToday = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
  const dowOf = (day) => WEEKDAY[new Date(`${day}T00:00:00Z`).getUTCDay()];
  const daysBetween = (a, b) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / 86400000);
  // 규칙 설명: 요일(1=월 … 7=일) + 주기. 월~금 연속이면 "월~금"
  function ruleText(rule) {
    const days = rule.weekdays.map((n) => WEEKDAY[n % 7]);
    const same = (a) => a.length === rule.weekdays.length && a.every((n, i) => n === rule.weekdays[i]);
    const span = same([1, 2, 3, 4, 5]) ? '월~금' : same([1, 2, 3, 4, 5, 6, 7]) ? '매일' : days.join('·');
    return rule.cadence === 'weekly' ? `매주 — 그 주 월요일 문서, 대상 요일 ${span}` : `${span} 매일`;
  }
  const PRD_RESULT = { created: '새로 만듦', existing: '이미 있음', failed: '실패' };
  function skipText(line) {
    if (line.reason === 'before_start') return '대상 아님(시작 전)';
    if (line.reason === 'disabled') return '대상 아님(꺼진 규칙)';
    return `대상 아님(${line.type_code === 'D11' || line.reason !== 'weekday' ? '요일' : dowOf(line.work_date)})`;
  }
  // 호출 전체 오류(4장) — 아무것도 만들지 않음
  function periodicErrorText(record) {
    const d = record.data || {};
    if (d.code === 'RULES_INVALID') return `주기 규칙 파일에 오류가 있습니다: ${d.message}. 아무것도 만들지 않았습니다.`;
    if (d.code === 'STAFF_HEADER_MISSING' || d.code === 'INVALID_STAFF') return '현재 사용자를 찾을 수 없습니다. 사용자를 다시 고르세요.';
    if (d.code === 'VALIDATION_ERROR') {
      const first = (d.details || [])[0] || {};
      const text = { future: '미래 날짜는 만들 수 없습니다(오늘까지).', order: '시작일이 끝일보다 늦습니다.', max: '한 번에 31일까지 만들 수 있습니다.' }[first.code];
      return `${text || first.message || d.message} 아무것도 만들지 않았습니다.`;
    }
    return `${T.errorText(record)} 아무것도 만들지 않았습니다.`;
  }
  // REQ-SC-08 주기 생성 결과 패널
  function periodicResultHtml(r) {
    const body = r.record.data || {};
    const traceLink = T.config.devConsole && r.traceId ? `<a class="btn btn-secondary btn-sm" target="_blank" rel="noopener" id="reqTraceLink" href="${T.config.devConsoleUrl}?trace=${encodeURIComponent(r.traceId)}">개발 콘솔에서 보기 ↗</a>` : '';
    if (!r.ok) {
      return `<div class="te-req-result te-req-fail" id="teReqResult">
        <div class="te-req-result-head"><b>주기 생성 결과</b> <span class="te-hint">${esc(r.at)} · ${r.ms}ms</span> ${traceLink}</div>
        <div class="te-reject-reason" id="prdError"><b>${esc(periodicErrorText(r.record))}</b></div></div>`;
    }
    const t = body.totals;
    const range = body.date_from === body.date_to ? body.date_from : `${body.date_from} ~ ${body.date_to.slice(5)}`;
    const fold = !r.unfolded && body.lines.length > 25;
    const shown = fold ? body.lines.filter((x) => x.result !== 'skipped_rule') : body.lines;
    const hidden = body.lines.length - shown.length;
    const rows = shown.map((x) => `
      <tr data-prd="${esc(x.record_key)}" class="te-prd-${esc(x.result)}">
        <td>${esc(x.work_date.slice(5))}(${dowOf(x.work_date)})</td><td>${esc(x.type_code)}</td>
        <td class="te-req-res-${esc(x.result)}">${x.result === 'skipped_rule' ? esc(skipText(x)) : x.result === 'failed' ? `실패 — [${esc(x.code)}] ${esc(x.message)}` : esc(PRD_RESULT[x.result] || x.result)}</td>
        <td>${x.document_id ? `<a href="#" data-open-doc="${x.document_id}">#${x.document_id}</a> ${T.statusBadge(x.status)}` : '<span class="te-hint">–</span>'}</td>
      </tr>`).join('');
    return `<div class="te-req-result" id="teReqResult">
      <div class="te-req-result-head"><b>주기 생성 결과</b> <span>${esc(range)} · 실행 staff ${esc(body.actor_id)}</span>
        <span id="prdTotals">만듦 ${t.created} · 이미 있음 ${t.existing} · 대상 아님 ${t.skipped_rule} · <span class="${t.failed ? 'te-prd-failcount' : ''}">실패 ${t.failed}</span></span>
        <span class="te-hint">${esc(r.at)} · ${r.ms}ms</span> ${traceLink}</div>
      ${t.failed ? `<div class="te-prd-failnote" id="prdFailNote">실패 ${t.failed}건 — 나머지는 만들어졌습니다.</div>` : ''}
      <div class="te-table-wrap"><table class="data-table" id="prdLines">
        <thead><tr><th>날짜</th><th>양식</th><th>결과</th><th>문서</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4" class="te-hint">줄이 없습니다.</td></tr>'}</tbody></table></div>
      ${hidden ? `<div class="te-actions"><button class="btn btn-secondary btn-sm" id="prdUnfold">대상 아님 ${hidden}줄 펼치기</button></div>` : ''}
    </div>`;
  }

  // ---------------------------------------------------------------- 모달(입력 오류가 있으면 닫지 않는다)
  function formModal({ title, body, okLabel, onSubmit, wide }) {
    const wrap = document.createElement('div');
    wrap.className = 'te-modal-wrap';
    wrap.innerHTML = `
      <div class="te-modal ${wide ? 'te-modal-wide' : ''}" role="dialog" aria-modal="true">
        <div class="modal-header"><div class="modal-title">${esc(title)}</div></div>
        <div class="te-modal-body">${body}<div class="te-form-error" id="reqFormError"></div></div>
        <div class="te-modal-footer">
          <button class="btn btn-secondary" data-act="cancel">취소</button>
          <button class="btn btn-primary" data-act="ok">${esc(okLabel)}</button>
        </div>
      </div>`;
    document.body.appendChild(wrap);
    const close = () => wrap.remove();
    wrap.addEventListener('click', async (e) => {
      if (e.target === wrap || e.target.closest('[data-act=cancel]')) { close(); return; }
      const ok = e.target.closest('[data-act=ok]');
      if (!ok) return;
      ok.disabled = true;
      try {
        const keep = await onSubmit(wrap);
        if (!keep) close();
      } finally { ok.disabled = false; }
    });
    wrap.querySelector('input, select')?.focus();
    return wrap;
  }

  function showFieldErrors(wrap, record) {
    wrap.querySelectorAll('.te-field-error').forEach((el) => el.remove());
    wrap.querySelectorAll('.is-invalid').forEach((el) => el.classList.remove('is-invalid'));
    const details = (record.data && record.data.details) || [];
    details.forEach((d) => {
      const name = (d.path || '').startsWith('inspection.') ? `insp_${d.path.slice(11)}` : d.path; // P6 육안검사 칸
      const field = wrap.querySelector(`[name="${name}"]`);
      if (!field) return;
      field.classList.add('is-invalid');
      const msg = document.createElement('div');
      msg.className = 'te-field-error';
      msg.textContent = d.message;
      field.closest('.te-field')?.appendChild(msg);
    });
    wrap.querySelector('#reqFormError').textContent = details.length ? '입력값을 확인하세요.' : T.errorText(record);
  }

  // ================================================= REQ-SC-01 작성 요구 테스트
  const Req = {
    title: '작성 요구',
    root: null,
    day: '',
    lastResult: null,

    async start(root) {
      this.root = root;
      if (this.day === '') this.day = today();
      await loadTemplateNames();
      this.render();
    },

    async render() {
      const q = this.day ? `?date=${this.day}` : '';
      const [lots, batches] = await Promise.all([api.get(`${DEV}/lots${q}`), api.get(`${DEV}/batches${q}`)]);
      if (lots.status === 404) {
        this.root.innerHTML = `${T.topBar('작성 요구', '')}<div class="empty-state"><h3>개발 설정에서만 쓸 수 있습니다</h3><p>개발 콘솔(HACCP_DEV_CONSOLE)이 켜져 있어야 합니다.</p></div>`;
        return;
      }
      const noStaff = !api.staffId;
      this.root.innerHTML = `
        <div class="fade-in" id="teReq">
          ${T.topBar('작성 요구', '수불·생산 앱이 할 호출을 흉내 냅니다. 여기서 만드는 LOT·배치는 개발용 가상 데이터입니다.')}
          <div class="card">
            <div class="te-req-actions">
              <button class="btn btn-primary" id="btnNewLot" ${noStaff ? 'disabled' : ''}>LOT 생성</button>
              <button class="btn btn-primary" id="btnNewBatch" ${noStaff ? 'disabled' : ''}>생산 시작</button>
              <button class="btn btn-primary" id="btnPeriodic" ${noStaff ? 'disabled' : ''} title="운영에서는 관리 명령(make_periodic_documents)이 하루 한 번 만듭니다 — 예약 실행 설정은 deployment.md 3.1">주기 문서 만들기</button>
              <span class="te-hint">LOT 생성 = 입고 등록 + require_for_lot, 생산 시작 = 배치 진행 중 + require_for_batch (한 트랜잭션)</span>
              <label class="te-req-day">작업일 <input type="date" class="form-control" id="reqDay" value="${esc(this.day)}"></label>
              <button class="btn btn-secondary btn-sm" id="reqAllDays">전체</button>
            </div>
            <h3 class="te-sub">테스트 입고 LOT</h3>
            ${this.lotTable(lots.ok ? lots.data.items : [])}
            <h3 class="te-sub">테스트 생산 배치</h3>
            ${this.batchTable(batches.ok ? batches.data.items : [])}
            <div id="reqResult">${this.lastResult ? this.resultHtml(this.lastResult) : ''}</div>
          </div>
        </div>`;
      T.bindTopBar(this.root, () => this.render());
      const $ = (sel) => this.root.querySelector(sel);
      $('#btnNewLot').addEventListener('click', () => this.openLotModal());
      $('#btnNewBatch').addEventListener('click', () => this.openBatchModal());
      $('#btnPeriodic').addEventListener('click', () => this.openPeriodicModal());
      $('#reqDay').addEventListener('change', (e) => { this.day = e.target.value; this.render(); });
      $('#reqAllDays').addEventListener('click', () => { this.day = null; this.render(); });
      this.root.querySelectorAll('[data-recall-lot]').forEach((b) => b.addEventListener('click', () => this.recall('lot', b.dataset.recallLot)));
      this.root.querySelectorAll('[data-recall-batch]').forEach((b) => b.addEventListener('click', () => this.recall('batch', b.dataset.recallBatch)));
      this.root.querySelectorAll('[data-lot-docs]').forEach((b) => b.addEventListener('click', () => T.open('temp-lot-docs', { lotId: Number(b.dataset.lotDocs), back: { page: 'temp-req' } })));
      this.bindResult();
    },

    lotSummary(docs) {
      if (!docs.length) return '<span class="te-hint">–</span>';
      const has = (code) => docs.some((d) => d.type_code === code);
      const parts = ['D01', 'D02', 'D03'].filter(has);
      return `${parts.join('·')}${parts.length === 3 ? ' ✓' : ''}`;
    },

    batchSummary(batch) {
      const docs = batch.documents;
      if (!docs.length) return batch.process_type === 'PACKAGING' ? '<span class="te-hint">요구되는 CCP 문서 없음</span>' : '<span class="te-hint">–</span>';
      return `CCP-${docs.map((d) => d.process_code).join('·')} ✓`;
    },

    lotTable(items) {
      if (!items.length) return `<div class="te-empty">아직 테스트 입고가 없습니다. [LOT 생성]을 누르세요.</div>`;
      return `
        <div class="te-table-wrap"><table class="data-table" id="reqLots">
          <thead><tr><th>LOT</th><th>품목</th><th>매입처</th><th>구분</th><th>입고일</th><th>중량</th><th>작성 요구 문서</th><th></th></tr></thead>
          <tbody>${items.map((l) => `
            <tr data-lot="${l.lot_id}">
              <td class="mono">${esc(l.lot_number)}</td><td>${esc(l.item_name)}</td><td>${esc(l.supplier_name)}</td>
              <td>${esc(l.material_kind)}</td><td>${esc((l.received_date || '').slice(5))}</td>
              <td>${esc(l.quantity)}${esc(l.unit)}</td>
              <td>${this.lotSummary(l.documents)}</td>
              <td class="te-nowrap">
                <button class="btn btn-secondary btn-sm" data-recall-lot="${l.lot_id}" ${api.staffId ? '' : 'disabled'}>다시 호출</button>
                <button class="btn btn-secondary btn-sm" data-lot-docs="${l.lot_id}">연결 문서</button>
              </td>
            </tr>`).join('')}</tbody>
        </table></div>`;
    },

    batchTable(items) {
      if (!items.length) return `<div class="te-empty">아직 테스트 배치가 없습니다. [생산 시작]을 누르세요.</div>`;
      return `
        <div class="te-table-wrap"><table class="data-table" id="reqBatches">
          <thead><tr><th>배치</th><th>품목</th><th>공정 유형</th><th>생산일</th><th>상태</th><th>생산량</th><th>작성 요구 문서</th><th></th></tr></thead>
          <tbody>${items.map((b) => `
            <tr data-batch="${b.production_batch_id}">
              <td class="mono">${esc(b.batch_number)}</td><td>${esc(b.item_name)}</td>
              <td>${esc(PROCESS[b.process_type] || b.process_type)}</td><td>${esc((b.manufactured_date || '-').slice(5))}</td>
              <td>${esc(BATCH_STATUS[b.status] || b.status)}</td>
              <td>${b.quantity_kg === null ? '-' : `${esc(b.quantity_kg)}kg`}</td>
              <td>${this.batchSummary(b)}</td>
              <td><button class="btn btn-secondary btn-sm" data-recall-batch="${b.production_batch_id}" ${api.staffId && b.status !== 'CANCELLED' ? '' : 'disabled'}>다시 호출</button></td>
            </tr>`).join('')}</tbody>
        </table></div>`;
    },

    // ================================================= REQ-SC-04 호출 결과
    resultHtml(r) {
      if (r.kind === 'periodic') return periodicResultHtml(r);
      const head = `<div class="te-req-result-head"><b>호출 결과</b> <span class="mono">${esc(r.call)}</span>
        <span class="te-hint">${esc(r.at)} · ${r.ms}ms</span>
        ${T.config.devConsole && r.traceId ? `<a class="btn btn-secondary btn-sm" target="_blank" rel="noopener" id="reqTraceLink" href="${T.config.devConsoleUrl}?trace=${encodeURIComponent(r.traceId)}">개발 콘솔에서 보기 ↗</a>` : ''}</div>`;
      if (!r.ok) {
        return `<div class="te-req-result te-req-fail" id="teReqResult">${head}
          <div class="te-reject-reason"><b>${esc(T.errorText(r.record))}</b><br>${r.rolledBack}</div></div>`;
      }
      const docs = r.documents;
      const rows = docs.length ? docs.map((d) => `
        <tr data-doc="${d.document_id}">
          <td>#${d.document_id}</td><td>${formName(d.type_code)}</td><td class="mono">${esc(d.record_key)}</td>
          <td class="te-req-res-${esc(d.result)}">${esc(resultText(d, r.sentInspection))}</td>
          <td><button class="btn btn-secondary btn-sm" data-open-doc="${d.document_id}">문서 열기</button></td>
        </tr>`).join('') : '<tr><td colspan="5" class="te-hint">요구되는 문서가 없습니다(예: 포장 배치는 CCP 공정 없음).</td></tr>';
      return `<div class="te-req-result" id="teReqResult">${head}
        <div class="te-table-wrap"><table class="data-table">
          <thead><tr><th>문서</th><th>양식</th><th>요구 키</th><th>결과</th><th></th></tr></thead>
          <tbody>${rows}</tbody></table></div></div>`;
    },

    bindResult() {
      this.root.querySelectorAll('[data-open-doc]').forEach((b) => b.addEventListener('click', (e) => { e.preventDefault(); T.open('temp-doc', { documentId: Number(b.dataset.openDoc) }); }));
      this.root.querySelector('#prdUnfold')?.addEventListener('click', () => { this.lastResult.unfolded = true; this.render(); });
    },

    async remember(call, record, rolledBack, sentInspection = false) {
      const body = record.data || {};
      const result = body.result || body;
      this.lastResult = {
        call, record, ok: record.ok, ms: record.ms, traceId: record.traceId,
        at: new Date().toTimeString().slice(0, 8),
        documents: record.ok ? (result.documents || []) : [],
        rolledBack, sentInspection,
      };
      if (record.ok) {
        // 새로 만든 LOT·배치가 보이도록 그 날짜로 이동
        const day = body.lot ? body.lot.received_date : body.batch ? body.batch.manufactured_date : null;
        if (day && this.day) this.day = day;
      }
      await this.render();
      this.root.querySelector('#teReqResult')?.scrollIntoView({ block: 'nearest' });
    },

    async recall(kind, id) {
      const record = await api.post(`${DEV}/${kind === 'lot' ? 'lots' : 'batches'}/${id}/require`, {});
      const fn = kind === 'lot' ? 'require_for_lot' : 'require_for_batch';
      await this.remember(`${fn}(staff ${api.staffId}, ${kind} ${id}) — 다시 호출`, record, '아무것도 바뀌지 않았습니다(롤백).');
    },

    // ================================================= REQ-SC-07 주기 문서 만들기 모달 (P9)
    async openPeriodicModal() {
      const r = await api.get('periodic-rules');
      if (!r.ok) {
        // 규칙 파일 오류(RULES_INVALID)는 모달 대신 결과 패널 머리에(REQ-SC-08)
        this.rememberPeriodic(null, r);
        return;
      }
      const rules = r.data.rules.filter((x) => x.enabled);
      const day = seoulToday();
      formModal({
        title: '주기 문서 만들기',
        okLabel: '만들기',
        body: `
          <div class="te-field"><label>날짜</label>
            <div class="te-radio te-prd-dates">
              <label><input type="radio" name="prd_mode" value="day" checked> 하루 <input type="date" class="form-control" name="prd_day" value="${day}" max="${day}"></label>
              <label><input type="radio" name="prd_mode" value="range"> 기간 <input type="date" class="form-control" name="prd_from" value="${day}" max="${day}"> ~ <input type="date" class="form-control" name="prd_to" value="${day}" max="${day}"></label>
            </div></div>
          <div class="te-field"><label>양식</label>
            ${rules.length ? rules.map((x) => `<label class="te-check"><input type="checkbox" name="prd_type" value="${esc(x.type_code)}" checked> ${esc(x.type_code)} ${esc(x.name || '(사용 중인 양식 없음)')} <span class="te-hint">(${esc(ruleText(x))})</span></label>`).join('')
              : '<p class="te-hint">켜진 주기 규칙이 없습니다(periodic_rules.json).</p>'}</div>
          <div class="te-field"><label>실행자</label><div class="te-ro-block">staff ${esc(api.staffId)} (현재 사용자)</div></div>
          <p class="te-status-note">이미 있는 날은 건드리지 않습니다. 미래 날짜는 만들 수 없습니다.</p>`,
        onSubmit: async (wrap) => {
          const v = (name) => wrap.querySelector(`[name="${name}"]`);
          const range = wrap.querySelector('[name=prd_mode]:checked').value === 'range';
          const from = range ? v('prd_from').value : v('prd_day').value;
          const to = range ? v('prd_to').value : v('prd_day').value;
          const types = [...wrap.querySelectorAll('[name=prd_type]:checked')].map((x) => x.value);
          const today = seoulToday();
          const err = wrap.querySelector('#reqFormError');
          // 3장 입력 오류(호출 전)
          let msg = '';
          if (!from || !to) msg = '날짜를 고르세요.';
          else if (from > today || to > today) msg = '미래 날짜는 만들 수 없습니다(오늘까지).';
          else if (from > to) msg = '시작일이 끝일보다 늦습니다.';
          else if (daysBetween(from, to) + 1 > 31) msg = '한 번에 31일까지 만들 수 있습니다.';
          else if (!types.length) msg = '양식을 하나 이상 고르세요.';
          err.textContent = msg;
          if (msg) return true;
          const record = await api.post('periodic-runs', { date_from: from, date_to: to, type_codes: types });
          this.rememberPeriodic({ from, to }, record);
          return false;
        },
      });
    },

    async rememberPeriodic(range, record) {
      this.lastResult = {
        kind: 'periodic', call: `run_periodic(staff ${api.staffId}${range ? `, ${range.from} ~ ${range.to}` : ''})`,
        record, ok: record.ok, ms: record.ms, traceId: record.traceId, staff: api.staffId,
        at: new Date().toTimeString().slice(0, 8), unfolded: false,
      };
      await this.render();
      this.root.querySelector('#teReqResult')?.scrollIntoView({ block: 'nearest' });
    },

    // ================================================= REQ-SC-02 테스트 입고 모달
    async openLotModal() {
      // C2: 수불 품목 중 입고 품목(원료·포장재)만. 구분·단위·원산지는 품목 값이라 입력하지 않는다
      const items = await api.get(`${DEV}/items`);
      const receivable = (items.ok ? items.data.items : []).filter((i) => i.receivable);
      const options = receivable.map((i) => `<option value="${i.id}" data-unit="${esc(i.base_unit)}">${esc(i.name)} (${i.item_type === 'RAW' ? '원료' : '부자재'})</option>`).join('');
      const day = this.day || today();
      const section = await loadInspectionSection();
      const modal = formModal({
        title: '테스트 입고 (LOT 생성)',
        okLabel: '입고 + 작성 요구',
        body: `
          <div class="te-form-grid">
            <div class="te-field"><label>품목</label><select class="form-control" name="item_id">${options}</select></div>
            <div class="te-field"><label>매입처</label><input class="form-control" name="supplier_name" maxlength="60" value="고흥농협"></div>
            <div class="te-field"><label>입고일 <span class="te-hint">(오늘 이전 — 수불 규칙)</span></label><input type="date" class="form-control" name="received_date" value="${day}" max="${today()}"></div>
            <div class="te-field"><label>수량 <span class="te-hint" id="reqLotUnit">(${esc((receivable[0] || {}).base_unit || '')})</span></label>
              <input type="number" class="form-control" name="quantity" min="0" step="any" value="500"></div>
            <div class="te-field"><label>소비기한 <span class="te-hint">(선택)</span></label><input type="date" class="form-control" name="expiration_date"></div>
            <div class="te-field"><label>LOT 번호</label><div class="te-ro-block">수불 규칙으로 자동(LOT 약어 + 입고일)</div></div>
          </div>
          ${inspectionHtml(section)}
          <label class="te-check te-fail-after"><input type="checkbox" name="fail_after"> 작성 요구 중 오류 내기(롤백 확인용)</label>`,
        onSubmit: async (wrap) => {
          const v = (name) => wrap.querySelector(`[name="${name}"]`);
          const qty = v('quantity').value;
          const body = {
            item_id: Number(v('item_id').value),
            supplier_name: v('supplier_name').value, received_date: v('received_date').value,
            quantity: qty === '' ? null : Number(qty),
          };
          if (v('expiration_date').value) body.expiration_date = v('expiration_date').value;
          if (v('fail_after').checked) body.fail_after = true;
          if (section && v('with_inspection').checked) {
            // 빈 값은 보내지 않는다(필수 누락은 서버 REQ-LOT-00b가 inspection.<키>로 알려 준다)
            body.inspection = {};
            inspectionFields(section).forEach((fd) => { if (v(`insp_${fd.key}`).value) body.inspection[fd.key] = v(`insp_${fd.key}`).value; });
          }
          const record = await api.post(`${DEV}/lots`, body);
          if (record.status === 400) { showFieldErrors(wrap, record); return true; }
          await this.remember(`require_for_lot(staff ${api.staffId}, lot ${record.ok ? record.data.lot.lot_id : '?'}${body.inspection ? ', inspection' : ''})`, record,
            'LOT·문서 모두 만들어지지 않았습니다(롤백).', !!body.inspection);
          return false;
        },
      });
      modal.querySelector('[name=item_id]').addEventListener('change', (e) => {
        document.getElementById('reqLotUnit').textContent = `(${e.target.selectedOptions[0]?.dataset.unit || ''})`;
      });
      modal.querySelector('#reqWithInspection')?.addEventListener('change', (e) => {
        modal.querySelector('#reqInspection').hidden = !e.target.checked;
      });
    },

    // ================================================= REQ-SC-03 테스트 배치 모달
    async openBatchModal() {
      const items = await api.get(`${DEV}/items`);
      const options = (items.ok ? items.data.items : []).map((i) => `<option value="${i.id}">${esc(i.name)}</option>`).join('');
      const day = this.day || today();
      formModal({
        title: '테스트 배치 (생산 시작)',
        okLabel: '생산 시작 + 작성 요구',
        body: `
          <div class="te-form-grid">
            <div class="te-field"><label>품목</label><select class="form-control" name="item_id">${options}</select></div>
            <div class="te-field"><label>공정 유형</label><div class="te-radio">
              <label><input type="radio" name="process_type" value="MANUFACTURE" checked> 제조</label>
              <label><input type="radio" name="process_type" value="PACKAGING"> 포장</label></div></div>
            <div class="te-field"><label>생산일</label><input type="date" class="form-control" name="manufactured_date" value="${day}"></div>
            <div class="te-field"><label>생산량(kg)</label><input type="number" class="form-control" name="quantity_kg" min="0" step="any" value="1000"></div>
            <div class="te-field"><label>배치 번호</label><div class="te-ro-block">PB-${mmdd(day)}-nn (자동)</div></div>
          </div>
          <div class="te-status-note">품목별 CCP 공정 목록은 코드 상수입니다. 개발 기본값: 제조 배치는 1P·2B·3P, 포장 배치는 없음.</div>
          <label class="te-check te-fail-after"><input type="checkbox" name="fail_after"> 작성 요구 중 오류 내기(롤백 확인용)</label>`,
        onSubmit: async (wrap) => {
          const v = (name) => wrap.querySelector(`[name="${name}"]`);
          const qty = v('quantity_kg').value;
          const body = {
            item_id: Number(v('item_id').value), process_type: wrap.querySelector('[name=process_type]:checked').value,
            manufactured_date: v('manufactured_date').value, quantity_kg: qty === '' ? null : Number(qty),
          };
          if (v('fail_after').checked) body.fail_after = true;
          const record = await api.post(`${DEV}/batches`, body);
          if (record.status === 400) { showFieldErrors(wrap, record); return true; }
          await this.remember(`require_for_batch(staff ${api.staffId}, batch ${record.ok ? record.data.batch.production_batch_id : '?'})`, record,
            '배치·문서 모두 만들어지지 않았습니다(롤백).');
          return false;
        },
      });
    },
  };

  // ================================================= REQ-SC-05 LOT별 연결 문서
  const LotDocs = {
    title: 'LOT별 연결 문서',
    root: null,
    back: null,

    async start(root) {
      this.root = root;
      const intent = T.takeIntent() || {};
      this.back = intent.back || null;
      await loadTemplateNames();
      if (!intent.lotId) {
        root.innerHTML = '<div class="empty-state"><h3>LOT을 고르세요</h3><p>작성 요구 화면의 [연결 문서] 또는 문서 상세의 LOT 링크로 들어옵니다.</p></div>';
        return;
      }
      this.show(intent.lotId);
    },

    async show(lotId) {
      const r = await api.get(`lots/${lotId}/documents`);
      const back = this.back ? '<button class="btn btn-secondary btn-sm" id="btnBack">뒤로</button>' : '';
      if (!r.ok) {
        this.root.innerHTML = `${T.topBar('LOT별 연결 문서', '')}<div class="card"><div class="te-reject-reason">${esc(T.errorText(r))}</div><div class="te-actions">${back}</div></div>`;
        this.bindBack();
        return;
      }
      const { lot, documents } = r.data;
      const rows = documents.map((d) => `
        <tr data-doc="${d.document_id}">
          <td>#${d.document_id}</td><td>${formName(d.type_code)}</td>
          <td>${T.statusBadge(d.status)}${d.correcting && d.status !== 'correcting' ? ' <span class="badge te-chip-fix">정정</span>' : ''}</td>
          <td class="${d.verdict === 'FAIL' ? 'te-judge-ng' : d.verdict === 'PASS' ? 'te-judge-ok' : ''}">${d.verdict ? esc(VERDICT[d.verdict] || d.verdict) : '<span class="te-hint">–</span>'}</td>
          <td>${d.correcting ? `정정 중${d.correction_reason ? ` <span class="te-hint te-ellipsis" title="${esc(d.correction_reason)}">(${esc(d.correction_reason.length > 20 ? `${d.correction_reason.slice(0, 20)}…` : d.correction_reason)})</span>` : ''}` : '<span class="te-hint">–</span>'}</td>
          <td><button class="btn btn-secondary btn-sm" data-open-doc="${d.document_id}">문서 열기</button></td>
        </tr>`).join('');
      this.root.innerHTML = `
        <div class="fade-in" id="teLotDocs">
          ${T.topBar(`LOT ${lot.lot_number} 연결 문서`, '이 LOT에 연결된 문서와 승인본 기준 판정')}
          <div class="card">
            <div class="card-header"><div class="te-meta" id="teLotHead">
              <span>품목 <b>${esc(lot.item_name)}</b></span><span>매입처 <b>${esc(lot.supplier_name)}</b></span>
              <span>입고 <b>${lot.received_date ? `<a href="#" class="te-lot-link" id="teBundleLink" title="이 입고일의 육안검사 묶음 상세(DOC-SC-10)">${esc(lot.received_date.slice(5))}</a>` : '-'}</b></span></div>
              <div class="page-actions">${back}</div></div>
            ${documents.length ? `
              <div class="te-table-wrap"><table class="data-table">
                <thead><tr><th>문서</th><th>양식</th><th>상태</th><th>승인본 기준 판정</th><th>정정 중</th><th></th></tr></thead>
                <tbody>${rows}</tbody></table></div>
              <p class="te-hint">승인본 기준 판정은 승인된 회차의 스냅샷에 있는 육안검사 최종판정입니다. 승인본이 없으면 "–"(작성 중인 값은 쓰지 않음).</p>`
              : '<div class="te-empty">이 LOT에 연결된 문서가 없습니다</div>'}
          </div>
        </div>`;
      T.bindTopBar(this.root, () => this.show(lotId));
      this.bindBack();
      // P7 REQ-SC-05: 입고일 → 그 입고일 묶음 상세. 묶음 상세의 [뒤로]는 이 화면으로(이 화면의 뒤로도 유지)
      this.root.querySelector('#teBundleLink')?.addEventListener('click', (e) => {
        e.preventDefault();
        T.open('temp-doc', { bundleDay: lot.received_date, origin: { page: 'temp-lot-docs', lotId, back: this.back } });
      });
      this.root.querySelectorAll('[data-open-doc]').forEach((b) => b.addEventListener('click', () => T.open('temp-doc', { documentId: Number(b.dataset.openDoc) })));
    },

    bindBack() {
      this.root.querySelector('#btnBack')?.addEventListener('click', () => T.open(this.back.page, this.back));
    },
  };

  T.register('temp-req', Req);
  T.register('temp-lot-docs', LotDocs);
  window.TempEntryRequirement = { Req, LotDocs, resultText };
})();
