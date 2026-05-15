const token = new URLSearchParams(window.location.search).get("token") || "";
const charts = {};

const money = (value, digits = 2) => `${Number(value || 0).toLocaleString("uk-UA", {
  minimumFractionDigits: digits,
  maximumFractionDigits: digits,
})} USDT`;

const number = (value, digits = 2) => Number(value || 0).toLocaleString("uk-UA", {
  minimumFractionDigits: digits,
  maximumFractionDigits: digits,
});

const btc = (value) => Number(value || 0).toLocaleString("uk-UA", {
  minimumFractionDigits: 8,
  maximumFractionDigits: 8,
});

function colorFor(value) {
  return Number(value || 0) >= 0 ? "var(--green)" : "var(--red)";
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderSummary(data) {
  const s = data.summary;
  const meta = data.meta;
  const totalLiquid = Number(s.btc_value || 0) + Number(s.usdt_reserve || 0);
  const btcShare = totalLiquid > 0 ? Number(s.btc_value || 0) / totalLiquid * 100 : 0;
  const reserveShare = totalLiquid > 0 ? Number(s.usdt_reserve || 0) / totalLiquid * 100 : 0;
  setText("systemStatus", `Оновлено ${new Date(meta.updated_at).toLocaleTimeString("uk-UA", {hour: "2-digit", minute: "2-digit"})}`);
  setText("portfolioValue", money(s.portfolio_value));
  setText("portfolioMeta", `${meta.symbol} · внесено ${money(s.total_deposited)}`);
  setText("progressPercent", `${number(s.progress_percent, 1)}%`);
  setText("progressText", `${money(s.portfolio_value)} з ${money(s.target_value)}`);
  document.querySelector(".ring")?.style.setProperty("--progress", Math.max(0, Math.min(100, s.progress_percent)));

  setText("totalPnl", money(s.total_pnl));
  setText("totalPnlPercent", `${number(s.total_pnl_percent, 2)}%`);
  document.getElementById("totalPnl").style.color = colorFor(s.total_pnl);
  setText("usdtReserve", money(s.usdt_reserve));
  setText("btcAmount", `${btc(s.btc_amount)} BTC`);
  setText("btcValue", `Вартість: ${money(s.btc_value)}`);
  setText("currentPrice", money(s.current_price));
  setText("avgPrice", `Середня ціна покупки: ${money(s.avg_price)}`);
  setText("btcShareText", `${number(btcShare, 1)}%`);
  setText("reserveShareText", `${number(reserveShare, 1)}%`);
}

function renderDecision(data) {
  const signal = data.latest_signal;
  if (!signal) {
    setText("decisionTitle", "Активних сигналів немає");
    setText("decisionText", "Стратегія очікує нових умов для купівлі або продажу.");
    return;
  }
  setText("decisionTitle", `${signal.title} · ${signal.status}`);
  const parts = [
    signal.level ? `Рівень: ${number(signal.level, 0)}%` : "",
    signal.signal_price ? `Ціна сигналу: ${money(signal.signal_price)}` : "",
    signal.amount_usdt ? `Сума: ${money(signal.amount_usdt)}` : "",
    signal.amount_btc_percent ? `Частка позиції: ${number(signal.amount_btc_percent, 2)}%` : "",
  ].filter(Boolean);
  setText("decisionText", parts.join(" · ") || signal.recommendation || "Перевір останній сигнал.");
}

function renderStrategy(data) {
  setText("strategyName", data.strategy.name);
  const items = [
    ["Сигнали", data.strategy.signals_enabled ? "Увімкнено" : "Вимкнено"],
    ["BUY cooldown", data.strategy.buy_cooldown_active ? "Активний" : "Не активний"],
    ["BUYBACK cycles", `${data.strategy.buyback_open_count}`],
    ["BUY_DIP", data.strategy.buy_dip_blocked ? "Заблоковано" : "Доступний"],
  ];
  document.getElementById("strategyState").innerHTML = items.map(([label, value]) => `
    <div class="state"><span>${label}</span><strong>${value}</strong></div>
  `).join("");
}

function renderCycles(cycles) {
  setText("cycleCount", cycles.length ? `${cycles.length} відкрито` : "немає");
  document.getElementById("cyclesList").innerHTML = cycles.length ? cycles.map(c => `
    <div class="item">
      <div class="item-row">
        <div class="item-title">BUYBACK #${c.id}</div>
        <span class="badge warn">${c.status}</span>
      </div>
      <div class="item-meta">
        Ціна продажу: ${money(c.sell_price)}<br>
        Залишилось викупити: ${btc(c.remaining_btc)} BTC<br>
        Рівень -2%: ${c.level_2_done ? "виконано" : "очікує"} · Рівень -4%: ${c.level_4_done ? "виконано" : "очікує"}
      </div>
    </div>
  `).join("") : `<div class="item"><div class="item-title">Відкритих циклів немає</div><div class="item-meta">BUY_DIP доступний, якщо інші умови виконані.</div></div>`;
}

function badgeClass(status) {
  if (status === "Виконано") return "good";
  if (status === "Очікує дії" || status === "Пропущено") return "warn";
  if (status === "Відхилено") return "bad";
  return "";
}

function renderSignals(signals) {
  document.getElementById("signalsList").innerHTML = signals.map(s => `
    <div class="item">
      <div class="item-row">
        <div class="item-title">${s.title}</div>
        <span class="badge ${badgeClass(s.status)}">${s.status}</span>
      </div>
      <div class="item-meta">
        ${s.created_at} · Ціна сигналу: ${money(s.signal_price)}
        ${s.amount_usdt ? `<br>Сума: ${money(s.amount_usdt)}` : ""}
        ${s.amount_btc_percent ? `<br>Частка позиції: ${number(s.amount_btc_percent, 2)}%` : ""}
      </div>
    </div>
  `).join("") || `<div class="item"><div class="item-title">Сигналів ще немає</div></div>`;
}

function renderTransactions(transactions) {
  document.getElementById("transactionsList").innerHTML = transactions.map(t => `
    <div class="item">
      <div class="item-row">
        <div class="item-title">${t.title}</div>
        <span class="badge">${t.created_at}</span>
      </div>
      <div class="item-meta">
        ${money(t.usdt_amount)} · ${btc(t.coin_amount)} ${t.coin}<br>
        Ціна: ${money(t.price)} · Комісія: ${number(t.fee, t.fee_asset === "USDT" ? 4 : 8)} ${t.fee_asset}
      </div>
    </div>
  `).join("") || `<div class="item"><div class="item-title">Угод ще немає</div></div>`;
}

function makeChart(id, type, data, options) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), { type, data, options });
}

function chartOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { labels: { color: "#d0d5dd", boxWidth: 10, usePointStyle: true } },
      tooltip: { backgroundColor: "#111315", borderColor: "#2b3035", borderWidth: 1 },
    },
    scales: {
      x: { ticks: { color: "#98a2b3", maxTicksLimit: 5 }, grid: { color: "rgba(255,255,255,.04)" } },
      y: { ticks: { color: "#98a2b3" }, grid: { color: "rgba(255,255,255,.06)" } },
    },
    ...extra,
  };
}

function renderCharts(data) {
  const labels = data.charts.labels;
  makeChart("portfolioChart", "line", {
    labels,
    datasets: [
      { label: "Вартість портфеля", data: data.charts.portfolio.portfolio_value, borderColor: "#42d392", backgroundColor: "rgba(66,211,146,.12)", tension: .35, fill: true },
      { label: "Внесено коштів", data: data.charts.portfolio.total_deposited, borderColor: "#6ea8fe", tension: .35 },
      { label: "Ціль", data: data.charts.portfolio.target_value, borderColor: "#f4c95d", borderDash: [6, 6], tension: 0 },
    ],
  }, chartOptions());

  makeChart("pnlChart", "line", {
    labels,
    datasets: [
      { label: "Загальний PnL", data: data.charts.pnl.total_pnl, borderColor: "#42d392", tension: .35 },
      { label: "Реалізований PnL", data: data.charts.pnl.realized_pnl, borderColor: "#6ea8fe", tension: .35 },
      { label: "Нереалізований PnL", data: data.charts.pnl.unrealized_pnl, borderColor: "#f4c95d", tension: .35 },
    ],
  }, chartOptions());

  makeChart("priceChart", "line", {
    labels,
    datasets: [
      { label: "Поточна ціна", data: data.charts.price.current_price, borderColor: "#4dd0c8", tension: .35 },
      { label: "Середня ціна покупки", data: data.charts.price.avg_price, borderColor: "#f4c95d", tension: .35 },
    ],
  }, chartOptions());

  makeChart("reserveChart", "line", {
    labels,
    datasets: [
      { label: "USDT резерв", data: data.charts.reserve.usdt_reserve, borderColor: "#6ea8fe", backgroundColor: "rgba(110,168,254,.14)", tension: .35, fill: true },
    ],
  }, chartOptions());

  makeChart("allocationChart", "doughnut", {
    labels: ["BTC", "USDT резерв"],
    datasets: [{
      data: [data.summary.btc_value, data.summary.usdt_reserve],
      backgroundColor: ["#42d392", "#6ea8fe"],
      borderColor: "#181b1e",
      borderWidth: 4,
    }],
  }, {
    responsive: true,
    maintainAspectRatio: false,
    cutout: "56%",
    plugins: { legend: { display: false } },
  });
}

async function loadDashboard() {
  const res = await fetch(`/api/dashboard?token=${encodeURIComponent(token)}`, { cache: "no-store" });
  if (!res.ok) throw new Error("Dashboard API error");
  const data = await res.json();
  renderSummary(data);
  renderDecision(data);
  renderStrategy(data);
  renderCycles(data.buyback_cycles);
  renderSignals(data.signals);
  renderTransactions(data.transactions);
  renderCharts(data);
}

loadDashboard().catch(() => setText("systemStatus", "Помилка оновлення"));
setInterval(() => loadDashboard().catch(() => setText("systemStatus", "Помилка оновлення")), 30000);
