// =============================================
// BIODOT HACCP - 자동 문서 생성 엔진
// AutoDocEngine: 생산일지 입력 → 전 문서 자동 생성
// =============================================

const AutoDocEngine = {

  // ─────────────────────────────────────────
  // 핵심 계산 함수: BOM × 수량 → 투입량 산출
  // ─────────────────────────────────────────
  calcRawNeeds(product, planQty) {
    // BOM은 1,000개 기준 → 비례 계산
    return product.rawBom.map(bom => {
      const base  = (bom.qty / 1000) * planQty;
      const total = parseFloat((base * (1 + bom.lossRate)).toFixed(4));
      return {
        rmId:     bom.rmId,
        name:     bom.name,
        unit:     bom.unit,
        planQty:  parseFloat(base.toFixed(4)),
        totalQty: total,          // 손실률 포함
        lossQty:  parseFloat((total - base).toFixed(4)),
        lossRate: bom.lossRate,
      };
    });
  },

  calcSubNeeds(product, planQty) {
    return product.subBom.map(bom => {
      const total = Math.ceil((bom.qty / 1000) * planQty);
      return {
        smId:    bom.smId,
        name:    bom.name,
        unit:    bom.unit,
        qty:     total,
        note:    bom.note || '',
      };
    });
  },

  // ─────────────────────────────────────────
  // 재고 충족 여부 검사
  // ─────────────────────────────────────────
  checkStock(rawNeeds, subNeeds) {
    const warnings = [];
    rawNeeds.forEach(r => {
      const stock = HACCP_DATA.currentStock.raw.find(s => s.id === r.rmId);
      if (!stock) { warnings.push({ type: 'raw', id: r.rmId, name: r.name, need: r.totalQty, have: 0, unit: r.unit, ok: false }); return; }
      const ok = stock.balance >= r.totalQty;
      if (!ok) warnings.push({ type: 'raw', id: r.rmId, name: r.name, need: r.totalQty, have: stock.balance, unit: r.unit, ok: false });
    });
    subNeeds.forEach(s => {
      const stock = HACCP_DATA.currentStock.sub.find(st => st.id === s.smId);
      if (!stock) { warnings.push({ type: 'sub', id: s.smId, name: s.name, need: s.qty, have: 0, unit: s.unit, ok: false }); return; }
      const ok = stock.balance >= s.qty;
      if (!ok) warnings.push({ type: 'sub', id: s.smId, name: s.name, need: s.qty, have: stock.balance, unit: s.unit, ok: false });
    });
    return warnings;
  },

  // ─────────────────────────────────────────
  // LOT 번호 자동 생성
  // ─────────────────────────────────────────
  generateLot(productId, date) {
    const d = date.replace(/-/g, '').slice(2); // YYMMDD
    const seq = String(HACCP_DATA.productionLogs.length + 1).padStart(3, '0');
    return `P${seq}-${d}`;
  },

  // ─────────────────────────────────────────
  // 유통기한 계산
  // ─────────────────────────────────────────
  calcExpiryDate(productionDate, shelfDays) {
    const d = new Date(productionDate);
    d.setDate(d.getDate() + shelfDays);
    return d.toISOString().split('T')[0];
  },

  // ─────────────────────────────────────────
  // CCP 일지 템플릿 생성 (측정 슬롯)
  // ─────────────────────────────────────────
  generateCCPTemplate(product, date, lot) {
    const interval = 2; // 2시간 간격
    const slots = ['08:00','10:00','12:00','14:00','16:00'];
    const logs = [];
    product.ccpIds.forEach(ccpId => {
      const ccp = HACCP_DATA.ccpPoints.find(c => c.id === ccpId);
      if (!ccp) return;
      // 각 측정 슬롯에 대해 임시 측정값 + "기록 필요" 슬롯 생성
      slots.forEach(time => {
        logs.push({
          date, time, ccpId, lot,
          value: null,          // 실제 측정 후 입력
          status: 'pending',    // pending | ok | warning | danger
          action: '',
          recorder: '',
          approver: '',
          criticalMin: ccp.criticalMin,
          criticalMax: ccp.criticalMax,
          unit: ccp.unit,
          ccpName: ccp.name,
          parameter: ccp.parameter,
        });
      });
    });
    return logs;
  },

  // ─────────────────────────────────────────
  // 품질검사 기준서로 검사항목 자동 생성
  // ─────────────────────────────────────────
  generateQualityChecklist(product, lot, date) {
    return product.qualityStandards.map(qs => ({
      date, lot, product: product.name, productId: product.id,
      testItem: qs.item, standard: qs.standard, method: qs.method,
      result: '', status: 'pending', tester: '',
    }));
  },

  // ─────────────────────────────────────────
  // 재고 반영 (수불대장 자동 생성 + 재고 차감)
  // ─────────────────────────────────────────
  applyToLedger(productionInfo, rawNeeds, subNeeds, lot) {
    const { date, product, planQty, operator } = productionInfo;
    const newRawEntries = [];
    const newSubEntries = [];

    // 원료 불출 수불
    rawNeeds.forEach((r, i) => {
      // 재고에서 차감 (FIFO: 최초 LOT 선택 - 여기서는 현재 재고에서 단순 차감)
      const stock = HACCP_DATA.currentStock.raw.find(s => s.id === r.rmId);
      if (stock) {
        const prevBalance = stock.balance;
        stock.balance = parseFloat((stock.balance - r.totalQty).toFixed(4));
        newRawEntries.push({
          id: `RL-AUTO-${Date.now()}-${i}`,
          date, rmId: r.rmId, name: r.name,
          type: 'out', qty: r.totalQty, unit: r.unit,
          expiryDate: '', lot: stock.expiryAlert ? stock.expiryAlert.replace(/-/g,'').slice(2) : '-',
          supplier: '', inspector: operator,
          note: `자동불출 - 생산LOT:${lot} (손실 ${r.lossQty}${r.unit} 포함)`,
          balance: Math.max(0, stock.balance),
          autoGenerated: true,
        });
      }
    });

    // 부자재 불출 수불
    subNeeds.forEach((s, i) => {
      const stock = HACCP_DATA.currentStock.sub.find(st => st.id === s.smId);
      if (stock) {
        stock.balance = stock.balance - s.qty;
        newSubEntries.push({
          id: `SL-AUTO-${Date.now()}-${i}`,
          date, smId: s.smId, name: s.name,
          type: 'out', qty: s.qty, unit: s.unit,
          lot: '-', supplier: '', inspector: operator,
          note: `자동불출 - 생산LOT:${lot}`,
          balance: Math.max(0, stock.balance),
          autoGenerated: true,
        });
      }
    });

    // 완제품 입고 수불
    const expiryDate = productionInfo.expiryDate ||
                       this.calcExpiryDate(date, product.shelfDays);
    const foodType   = productionInfo.foodType || '';
    const finishedEntry = {
      id: `FL-AUTO-${Date.now()}`,
      date, productId: product.id, name: product.name,
      type: 'in', qty: planQty,
      lot, expiryDate,
      ...(foodType ? { foodType } : {}),
      inspector: operator,
      note: `생산완료 자동등록`,
      balance: 0,
      autoGenerated: true,
    };
    const fStock = HACCP_DATA.currentStock.finished.find(f => f.id === product.id);
    if (fStock) {
      fStock.balance += planQty;
      fStock.lot = lot;
      fStock.expiryDate = expiryDate;
      if (foodType) fStock.foodType = foodType;   // 식품유형 갱신
      finishedEntry.balance = fStock.balance;
    }

    // 원장에 push
    HACCP_DATA.rawLedger.unshift(...newRawEntries);
    HACCP_DATA.subLedger.unshift(...newSubEntries);
    HACCP_DATA.finishedLedger.unshift(finishedEntry);

    return { rawEntries: newRawEntries, subEntries: newSubEntries, finishedEntry };
  },

  // ─────────────────────────────────────────
  // 생산일지 객체 생성
  // ─────────────────────────────────────────
  buildProductionLog(formData, product, rawNeeds, lot) {
    return {
      id: `PL${String(HACCP_DATA.productionLogs.length + 1).padStart(3,'0')}`,
      date: formData.date,
      lot,
      product: product.name,
      productId: product.id,
      planQty: formData.planQty,
      actualQty: formData.planQty, // 실 생산량은 나중에 입력
      defectQty: 0,
      line: formData.line || product.line,
      startTime: formData.startTime,
      endTime: formData.endTime || '',
      workers: formData.workers || [],
      materials: rawNeeds.map(r => ({
        id: r.rmId, name: r.name,
        planQty: r.planQty, actualQty: r.totalQty,
        unit: r.unit, lot: '-',
      })),
      status: 'in-progress',
      ccp: product.ccpIds,
      note: formData.note || '',
      autoGenerated: true,
    };
  },

  // ─────────────────────────────────────────
  // 전체 자동 생성 실행
  // ─────────────────────────────────────────
  generate(formData) {
    const product = HACCP_DATA.products.find(p => p.id === formData.productId);
    if (!product) return { success: false, error: '제품을 찾을 수 없습니다.' };

    const lot       = this.generateLot(formData.productId, formData.date);
    const rawNeeds  = formData.customRawNeeds || this.calcRawNeeds(product, formData.planQty);
    const subNeeds  = formData.customSubNeeds || this.calcSubNeeds(product, formData.planQty);
    const stockWarn = this.checkStock(rawNeeds, subNeeds);

    // 재고 부족시에도 생성은 진행 (경고만 표시)
    const ccpTemplate   = this.generateCCPTemplate(product, formData.date, lot);
    const qualityChecks = this.generateQualityChecklist(product, lot, formData.date);
    const ledgerResult  = this.applyToLedger({
      date: formData.date, product, planQty: formData.planQty,
      operator: formData.operator,
      foodType: formData.foodType || '',
      expiryDate: formData.expiryDate || '',
    }, rawNeeds, subNeeds, lot);
    const productionLog = this.buildProductionLog(formData, product, rawNeeds, lot);

    // 생산일지에 추가
    HACCP_DATA.productionLogs.unshift(productionLog);
    // CCP 일지 템플릿 추가 (대기 상태)
    if (ccpTemplate && ccpTemplate.length > 0) {
      HACCP_DATA.ccpLogs.unshift(...ccpTemplate);
    }

    // 자동생성 이력 추가
    const historyEntry = {
      id: `AG${String(HACCP_DATA.autoGenHistory.length + 1).padStart(3,'0')}`,
      generatedAt: new Date().toLocaleString('ko-KR'),
      productionLotId: productionLog.id,
      lot,
      product: product.name,
      qty: formData.planQty,
      operator: formData.operator,
      documents: [
        { type: 'raw_ledger',      label: '원료 수불 (불출)',   count: ledgerResult.rawEntries.length, status: 'done' },
        { type: 'sub_ledger',      label: '부자재 수불 (불출)', count: ledgerResult.subEntries.length, status: 'done' },
        { type: 'ccp_log',         label: 'CCP 모니터링 일지', count: ccpTemplate.length,             status: 'pending' },
        { type: 'quality_check',   label: '자가품질검사 목록',  count: qualityChecks.length,           status: 'pending' },
        { type: 'finished_ledger', label: '완제품 입고 등록',   count: 1,                              status: 'done' },
      ]
    };
    HACCP_DATA.autoGenHistory.unshift(historyEntry);

    // 필수 점검 연동: 일일 생산일지 기록 (PT01) 완료 처리
    const dailyTask = HACCP_DATA.periodicTasks?.find(t => t.id === 'PT01');
    if (dailyTask) {
      dailyTask.status = 'completed';
    }

    return {
      success: true,
      lot,
      product,
      planQty: formData.planQty,
      rawNeeds,
      subNeeds,
      stockWarnings: stockWarn,
      ccpTemplate,
      qualityChecks,
      ledgerResult,
      productionLog,
      historyEntry,
    };
  }
};
