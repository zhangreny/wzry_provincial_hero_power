const REFRESH_MS = 10 * 60 * 1000;
const POLL_MS = 2000;
const PLATFORM = "ios_wx";

const rowsEl = document.querySelector("#rankRows");
const emptyEl = document.querySelector("#emptyState");
const statusEl = document.querySelector("#status");
const refreshButton = document.querySelector("#refreshButton");
const heroCountEl = document.querySelector("#heroCount");
const okCountEl = document.querySelector("#okCount");
const failedCountEl = document.querySelector("#failedCount");

let ranks = [];
let latestRanks = new Map();
let refreshing = false;
let pollTimer = null;

function formatNumber(value) {
  return typeof value === "number" ? value.toLocaleString("zh-CN") : "--";
}

function formatUpdatedAt(value) {
  return value || "--";
}

function sortRanks(items) {
  return [...items].sort((left, right) => {
    const leftPower = typeof left.provincePower === "number" ? left.provincePower : -1;
    const rightPower = typeof right.provincePower === "number" ? right.provincePower : -1;
    return rightPower - leftPower || left.name.localeCompare(right.name, "zh-CN");
  });
}

function mergeRanks(items) {
  for (const item of items) {
    const oldItem = latestRanks.get(item.heroId);
    latestRanks.set(item.heroId, item.ok || !oldItem ? item : { ...oldItem, ok: false, pending: false, error: item.error });
  }
  ranks = sortRanks([...latestRanks.values()]);
}

function updateSummary() {
  const okCount = ranks.filter((item) => item.ok).length;
  const failedCount = ranks.filter((item) => !item.ok && !item.pending).length;
  heroCountEl.textContent = ranks.length ? String(ranks.length) : "--";
  okCountEl.textContent = ranks.length ? String(okCount) : "--";
  failedCountEl.textContent = ranks.length ? String(failedCount) : "--";
}

function render() {
  rowsEl.innerHTML = "";
  emptyEl.classList.toggle("hidden", ranks.length > 0);
  updateSummary();

  for (const rank of ranks) {
    const row = document.createElement("tr");
    if (!rank.ok) {
      row.classList.add("failed-row");
    }
    if (rank.pending) {
      row.classList.add("pending-row");
    }

    const heroCell = document.createElement("td");
    heroCell.className = "hero-cell";

    if (rank.photo) {
      const image = document.createElement("img");
      image.src = rank.photo;
      image.alt = "";
      image.loading = "lazy";
      heroCell.append(image);
    }

    const heroText = document.createElement("div");
    const heroName = document.createElement("strong");
    heroName.textContent = rank.name || "--";
    const heroAlias = document.createElement("span");
    heroAlias.textContent = rank.alias || rank.platform || "";
    heroText.append(heroName, heroAlias);
    heroCell.append(heroText);

    const provinceCell = document.createElement("td");
    provinceCell.textContent = rank.province || "--";
    if (rank.province === "北京市" || rank.province === "北京") {
      provinceCell.className = "beijing";
    }

    const powerCell = document.createElement("td");
    powerCell.className = "power-cell";
    powerCell.textContent = formatNumber(rank.provincePower);

    const nationalCell = document.createElement("td");
    nationalCell.className = "value-cell";
    nationalCell.textContent = formatNumber(rank.nationalPower);

    const updatedCell = document.createElement("td");
    updatedCell.className = "updated-cell";
    if (rank.pending) {
      updatedCell.textContent = "后台刷新中";
    } else {
      updatedCell.textContent = rank.ok ? formatUpdatedAt(rank.updatedAt) : `失败：${rank.error || "获取失败"}`;
    }
    if (!rank.ok) {
      updatedCell.title = rank.error || "获取失败";
    }

    row.append(heroCell, provinceCell, powerCell, nationalCell, updatedCell);
    rowsEl.append(row);
  }
}

async function fetchRanksWithRetry(force = false) {
  let lastError;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      const refreshParam = force ? "&refresh=1" : "";
      const response = await fetch(`/api/ranks?platform=${encodeURIComponent(PLATFORM)}${refreshParam}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      return response.json();
    } catch (error) {
      lastError = error;
      await new Promise((resolve) => setTimeout(resolve, 600 * (attempt + 1)));
    }
  }
  throw lastError;
}

function scheduleRefreshPoll() {
  if (pollTimer) {
    return;
  }
  pollTimer = setTimeout(() => {
    pollTimer = null;
    refreshRanks({ polling: true });
  }, POLL_MS);
}

async function refreshRanks({ force = false, polling = false } = {}) {
  if (refreshing) {
    return;
  }

  refreshing = true;
  refreshButton.disabled = true;
  statusEl.textContent = polling ? "正在读取后台刷新结果..." : "正在读取苹果微信全英雄省标...";

  try {
    const data = await fetchRanksWithRetry(force);
    mergeRanks(Array.isArray(data.ranks) ? data.ranks : []);
    render();

    if (data.refreshing) {
      statusEl.textContent = data.cached ? "已显示缓存，后台刷新中..." : "已显示英雄列表，后台刷新中...";
      scheduleRefreshPoll();
    } else {
      const refreshedAt = data.cachedAt
        ? new Date(data.cachedAt * 1000).toLocaleTimeString("zh-CN", { hour12: false })
        : new Date().toLocaleTimeString("zh-CN", { hour12: false });
      statusEl.textContent = `已刷新 ${refreshedAt}`;
    }
  } catch (error) {
    statusEl.textContent = `刷新失败：${error.message}`;
    render();
  } finally {
    refreshing = false;
    refreshButton.disabled = false;
  }
}

refreshButton.addEventListener("click", () => refreshRanks({ force: true }));

render();
refreshRanks();
setInterval(() => refreshRanks({ force: true }), REFRESH_MS);
