"use strict";

const refreshButton = document.querySelector("#refresh-status");
const lastChecked = document.querySelector("#last-checked");

async function checkEndpoint(path, elementId, key) {
  const element = document.getElementById(elementId);
  element.dataset.state = "pending";
  element.textContent = "확인 중";
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  try {
    const response = await fetch(path, { cache: "no-store", signal: controller.signal });
    const result = await response.json();
    const healthy = response.ok && result.status === "ok" && result[key] === "ok";
    element.dataset.state = healthy ? "ok" : "error";
    element.textContent = healthy ? "정상 연결" : "준비 상태 확인 필요";
  } catch {
    element.dataset.state = "error";
    element.textContent = "연결할 수 없음";
  } finally {
    clearTimeout(timeout);
  }
}

async function refreshStatus() {
  refreshButton.disabled = true;
  await Promise.all([
    checkEndpoint("/health/live/", "live-status", "status"),
    checkEndpoint("/health/ready/", "ready-status", "database"),
  ]);
  lastChecked.textContent = `마지막 확인 · ${new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).format(new Date())}`;
  refreshButton.disabled = false;
}

refreshButton.addEventListener("click", refreshStatus);
refreshStatus();

