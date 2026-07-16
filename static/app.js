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

function formatNumber(value) {
  return typeof value === "number" ? value.toLocaleString("zh-CN") : "--";
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

    const heroCell = document.createElement("td");
    heroCell.className = "hero-cell";

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

    const macauCell = document.createElement("td");
    macauCell.className = "power-cell";
    macauCell.textContent = formatNumber(rank.macauPower);

    if (!rank.ok) {
      powerCell.textContent = rank.error || "获取失败";
      powerCell.title = rank.error || "获取失败";
    }

    row.append(heroCell, provinceCell, powerCell, macauCell);
    rowsEl.append(row);
  }
}

async function refreshRanks({ force = false } = {}) {
  if (refreshing) {
    return;
  }

  refreshing = true;
  refreshButton.disabled = true;
  ranks = [];
  latestRanks = new Map();
  render();
  statusEl.textContent = "正在抓取全英雄苹果微信省标...";

  try {
    const refreshParam = force ? "&refresh=1" : "";
    const response = await fetch(`/api/ranks/stream?platform=${encodeURIComponent(PLATFORM)}${refreshParam}`, {
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    if (!response.body) {
      throw new Error("当前浏览器不支持流式读取");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let total = 0;
    let done = 0;

    while (true) {
      const { value, done: streamDone } = await reader.read();
      if (streamDone) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.trim()) {
          continue;
        }
        const event = JSON.parse(line);
        if (event.type === "meta") {
          total = event.total || 0;
          statusEl.textContent = total ? `已发现 ${total} 个英雄，正在抓取...` : "正在抓取...";
          updateSummary();
        } else if (event.type === "rank") {
          done = event.done || done + 1;
          total = event.total || total;
          mergeRanks([event.rank]);
          render();
          statusEl.textContent = total ? `正在抓取 ${done}/${total}` : `正在抓取 ${done}`;
        } else if (event.type === "error") {
          throw new Error(event.error || "流式抓取失败");
        }
      }
    }

    if (buffer.trim()) {
      const event = JSON.parse(buffer);
      if (event.type === "rank") {
        mergeRanks([event.rank]);
        render();
      }
    }

    const refreshedAt = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    statusEl.textContent = `已刷新 ${refreshedAt}`;
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
