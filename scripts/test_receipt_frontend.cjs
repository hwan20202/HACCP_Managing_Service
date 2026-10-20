// Receipt entry/cancellation UI checks. No business data or server writes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const receipt = {
  id: 7, lot_id: 10, lot_number: 'TEST-LOT', received_date: '2026-10-20',
  item: {id: 1, name: '테스트 원료'}, quantity: '2', unit: 'kg',
  supplier: {name: '테스트 공급처'}, staff: {name: '입고 담당'}, receipt_status: 'COMPLETED',
};
const form = {reportValidity: () => true};
const button = {disabled: false};
const errorBox = {textContent: ''};
const modal = {innerHTML: ''};
const elements = {receiptCancelForm: form, receiptCancelSave: button, receiptCancelError: errorBox};
let values = {staff_id: '3', reason: '  오입력  '};
let confirm = true;
let confirmations = 0;
let requests = [];
let resolveResponse;
let refreshes = 0;
const toasts = [];
const context = vm.createContext({
  console, URLSearchParams, setTimeout: () => {},
  document: {
    cookie: 'csrftoken=test%2Dcsrf',
    getElementById: id => elements[id] || null,
    querySelector: () => modal,
  },
  window: {confirm: () => { confirmations++; return confirm; }},
  FormData: class { [Symbol.iterator]() {return Object.entries(values)[Symbol.iterator]();} },
  App: {showToast: (...args) => toasts.push(args)},
  fetch: async (url, options) => {
    requests.push({url, options});
    return new Promise(resolve => {resolveResponse = resolve;});
  },
});
vm.runInContext(fs.readFileSync('frontend/static/prototype/js/modules/inventory-api.js', 'utf8') + '\nthis.page = InventoryApiPage;', context);
const page = context.page;
page.receiptDetail = receipt;
page.receiptSerial = 1;
page.load = () => {refreshes++;};

(async () => {
  // Entry is visible without QA flags or developer tools.
  for (const type of ['raw', 'sub', 'finished']) assert.match(page.render(type), /id="qaReceiptOpen"[^>]*>입고 등록/);
  assert.match(page.renderReceipt(receipt), /id="receiptCancelOpen"/);
  const cancelled = {...receipt, receipt_status: 'CANCELLED', cancel_reason: '<오입력>', cancelled_at: '2026-10-20T12:00:00+09:00'};
  const html = page.renderReceipt(cancelled);
  assert.doesNotMatch(html, /receiptCancelOpen|입고 연결 문서/);
  assert.match(html, /취소됨/);
  assert.match(html, /&lt;오입력&gt;/);

  values.reason = '   ';
  await page.cancelReceipt(7);
  assert.equal(requests.length, 0);
  assert.equal(confirmations, 0);
  assert.match(errorBox.textContent, /취소 사유/);
  values.reason = '  오입력  ';
  confirm = false;
  await page.cancelReceipt(7);
  assert.equal(requests.length, 0);

  confirm = true;
  const first = page.cancelReceipt(7);
  assert.equal(button.disabled, true);
  await page.cancelReceipt(7);
  assert.equal(requests.length, 1, 'Repeated submission must not send another cancellation.');
  assert.equal(requests[0].url, '/api/v1/inventory/receipts/7/cancel/');
  assert.deepEqual(JSON.parse(requests[0].options.body), {staff_id: 3, reason: '오입력'});
  assert.equal(requests[0].options.headers['X-CSRFToken'], 'test-csrf');
  resolveResponse({ok: false, json: async () => ({error: {message: '결재 중 문서가 있어 취소할 수 없습니다.'}})});
  await first;
  assert.match(errorBox.textContent, /결재 중/);
  assert.equal(button.disabled, false);
  assert.equal(page.receiptDetail.receipt_status, 'COMPLETED');
  assert.equal(refreshes, 0);

  const retry = page.cancelReceipt(7);
  resolveResponse({ok: true, json: async () => cancelled});
  await retry;
  assert.equal(page.receiptDetail.receipt_status, 'CANCELLED');
  assert.doesNotMatch(modal.innerHTML, /receiptCancelOpen/);
  assert.equal(refreshes, 1);
  assert.equal(toasts[0][0], 'success');
  assert.equal(page.receiptCancelling, false);
  console.log('Receipt UI checks passed: visible entry, cancellation, validation, CSRF, duplicate submission, blocker errors and refresh.');
})().catch(error => {console.error(error); process.exitCode = 1;});
