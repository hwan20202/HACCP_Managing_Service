// =============================================
// 개발 검증 › 작성 요구 (P5 REQ 사용 화면)
// 화면: REQ-SC-01 작성 요구 테스트 · 02 테스트 입고 모달 · 03 테스트 배치 모달 · 04 호출 결과 패널
//       REQ-SC-05 LOT별 연결 문서(문서 상세의 LOT 링크로도 들어온다)
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

  // SC-04 결과 문구: D03도 D01·D02와 같은 "새로 만듦 / 이미 있음"(P6a-S1 REQ-SC-04)
  const resultText = (item) => RESULT[item.result] || item.result;

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
      const field = wrap.querySelector(`[name="${d.path}"]`);
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
        this.root.innerHTML = `${T.topBar('작성 요구', '')}<div class="empty-state"><h3>개발 설정에서만 쓸 수 있습니다</h3><p>개발 콘솔(HACCP_DEV_CONSOLE)과 개발용 수불 임시 테이블(devstock)이 켜져 있어야 합니다.</p></div>`;
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
          <td class="te-req-res-${esc(d.result)}">${esc(resultText(d))}</td>
          <td><button class="btn btn-secondary btn-sm" data-open-doc="${d.document_id}">문서 열기</button></td>
        </tr>`).join('') : '<tr><td colspan="5" class="te-hint">요구되는 문서가 없습니다(예: 포장 배치는 CCP 공정 없음).</td></tr>';
      return `<div class="te-req-result" id="teReqResult">${head}
        <div class="te-table-wrap"><table class="data-table">
          <thead><tr><th>문서</th><th>양식</th><th>요구 키</th><th>결과</th><th></th></tr></thead>
          <tbody>${rows}</tbody></table></div></div>`;
    },

    bindResult() {
      this.root.querySelectorAll('[data-open-doc]').forEach((b) => b.addEventListener('click', () => T.open('temp-doc', { documentId: Number(b.dataset.openDoc) })));
    },

    async remember(call, record, rolledBack) {
      const body = record.data || {};
      const result = body.result || body;
      this.lastResult = {
        call, record, ok: record.ok, ms: record.ms, traceId: record.traceId,
        at: new Date().toTimeString().slice(0, 8),
        documents: record.ok ? (result.documents || []) : [],
        rolledBack,
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

    // ================================================= REQ-SC-02 테스트 입고 모달
    async openLotModal() {
      const items = await api.get(`${DEV}/items`);
      const options = (items.ok ? items.data.items : []).map((i) => `<option value="${i.id}">${esc(i.name)}</option>`).join('');
      const day = this.day || today();
      formModal({
        title: '테스트 입고 (LOT 생성)',
        okLabel: '입고 + 작성 요구',
        body: `
          <div class="te-form-grid">
            <div class="te-field"><label>품목</label><select class="form-control" name="item_id">${options}</select></div>
            <div class="te-field"><label>구분</label><div class="te-radio">
              <label><input type="radio" name="material_kind" value="원료" checked> 원료</label>
              <label><input type="radio" name="material_kind" value="부자재"> 부자재</label></div></div>
            <div class="te-field"><label>매입처</label><input class="form-control" name="supplier_name" maxlength="60" value="고흥농협"></div>
            <div class="te-field"><label>입고일</label><input type="date" class="form-control" name="received_date" value="${day}"></div>
            <div class="te-field"><label>중량</label><div class="te-inline">
              <input type="number" class="form-control" name="quantity" min="0" step="any" value="500">
              <select class="form-control" name="unit"><option>kg</option><option>g</option><option>box</option><option>ea</option></select></div></div>
            <div class="te-field"><label>소비기한 <span class="te-hint">(선택)</span></label><input type="date" class="form-control" name="expiration_date"></div>
            <div class="te-field"><label>원산지 <span class="te-hint">(선택)</span></label><select class="form-control" name="origin"><option value="">-</option><option>국내</option><option>수입</option></select></div>
            <div class="te-field"><label>LOT 번호</label><div class="te-ro-block" id="reqLotNumber">RM-${mmdd(day)}-nn (자동)</div></div>
          </div>
          <label class="te-check te-fail-after"><input type="checkbox" name="fail_after"> 작성 요구 중 오류 내기(롤백 확인용)</label>`,
        onSubmit: async (wrap) => {
          const v = (name) => wrap.querySelector(`[name="${name}"]`);
          const qty = v('quantity').value;
          const body = {
            item_id: Number(v('item_id').value), material_kind: wrap.querySelector('[name=material_kind]:checked').value,
            supplier_name: v('supplier_name').value, received_date: v('received_date').value,
            quantity: qty === '' ? null : Number(qty), unit: v('unit').value,
          };
          if (v('expiration_date').value) body.expiration_date = v('expiration_date').value;
          if (v('origin').value) body.origin = v('origin').value;
          if (v('fail_after').checked) body.fail_after = true;
          const record = await api.post(`${DEV}/lots`, body);
          if (record.status === 400) { showFieldErrors(wrap, record); return true; }
          await this.remember(`require_for_lot(staff ${api.staffId}, lot ${record.ok ? record.data.lot.lot_id : '?'})`, record,
            'LOT·문서 모두 만들어지지 않았습니다(롤백).');
          return false;
        },
      }).querySelector('[name=received_date]').addEventListener('change', (e) => {
        document.getElementById('reqLotNumber').textContent = `RM-${mmdd(e.target.value)}-nn (자동)`;
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
          <td>${T.statusBadge(d.status)}</td>
          <td class="${d.verdict === 'FAIL' ? 'te-judge-ng' : d.verdict === 'PASS' ? 'te-judge-ok' : ''}">${d.verdict ? esc(VERDICT[d.verdict] || d.verdict) : '<span class="te-hint">–</span>'}</td>
          <td>${d.correcting ? '정정 중' : '<span class="te-hint">–</span>'}</td>
          <td><button class="btn btn-secondary btn-sm" data-open-doc="${d.document_id}">문서 열기</button></td>
        </tr>`).join('');
      this.root.innerHTML = `
        <div class="fade-in" id="teLotDocs">
          ${T.topBar(`LOT ${lot.lot_number} 연결 문서`, '이 LOT에 연결된 문서와 승인본 기준 판정')}
          <div class="card">
            <div class="card-header"><div class="te-meta" id="teLotHead">
              <span>품목 <b>${esc(lot.item_name)}</b></span><span>매입처 <b>${esc(lot.supplier_name)}</b></span>
              <span>입고 <b>${esc((lot.received_date || '').slice(5))}</b></span></div>
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
