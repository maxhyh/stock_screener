(() => {
    const {
        chip,
        escapeHtml,
        fetchJson,
        formatDateToken,
        formatNumber,
        formatPercent,
        initChart,
        pick,
        setError,
        setLoading,
        tableHtml,
        toneFromStatus,
        toneFromValue,
        toNumber,
    } = window.QuantUI;

    const state = {
        selectedDate: "",
        overview: null,
        health: null,
        latestRun: null,
        experiments: [],
    };

    function numeric(record, keys, fallback = 0) {
        return toNumber(pick(record, keys, fallback), fallback);
    }

    function text(record, keys, fallback = "--") {
        return String(pick(record, keys, fallback) ?? fallback);
    }

    function stockAnchor(code, name) {
        const normalized = String(code || "").trim();
        const display = normalized || "--";
        return `<a href="#" class="mono stock-link" data-code="${escapeHtml(normalized)}" data-name="${escapeHtml(name || display)}">${escapeHtml(display)}</a>`;
    }

    function renderHero() {
        const overview = state.overview || {};
        const daily = overview.daily_summary || {};
        const backtest = overview.backtest_summary || {};
        const health = state.health || {};
        const latestRun = state.latestRun || {};
        const experiments = state.experiments || [];

        const heroTitle = document.getElementById("heroTitle");
        const heroCopy = document.getElementById("heroCopy");
        const heroChips = document.getElementById("heroChips");
        const heroMetrics = document.getElementById("heroMetrics");

        if (heroTitle) {
            heroTitle.textContent = `${overview.date || "--"} 决策摘要：${text(daily, ["market_state"], "市场状态待判定")}`;
        }
        if (heroCopy) {
            heroCopy.textContent = `今日推荐 ${formatNumber(daily.count || 0)} 只，建议仓位 ${text(daily, ["position"], "--")}，平台最新运行 ${text(health, ["latest_run_status"], "missing")}。`;
        }
        if (heroChips) {
            heroChips.innerHTML = [
                chip(`市场状态 ${text(daily, ["market_state"], "--")}`, toneFromStatus(daily.market_state)),
                chip(`建议仓位 ${text(daily, ["position"], "--")}`, "accent"),
                chip(`单票上限 ${text(daily, ["single_cap"], "--")}`, "info"),
                chip(`持有天数 ${text(daily, ["hold_days"], "--")}`, "warning"),
                chip(`Run ${text(latestRun, ["run_id"], text(health, ["latest_run_id"], "--"))}`, toneFromStatus(health.latest_run_status)),
                chip(`实验 ${formatNumber(experiments.length, 0)} 个`, experiments.length > 0 ? "positive" : "warning"),
            ].join("");
        }
        if (heroMetrics) {
            const annualReturn = numeric(backtest, ["annual_return_pct"], NaN);
            heroMetrics.innerHTML = [
                ["今日推荐", formatNumber(daily.count || 0), "覆盖经过门禁后的最终推荐池"],
                ["数据覆盖", formatNumber(overview.coverage || 0), "当前目标交易日的候选覆盖数"],
                ["平台运行", text(health, ["latest_run_status"], "--"), `最新运行 ${text(health, ["latest_run_id"], "--")}`],
                ["回测年化", Number.isFinite(annualReturn) ? formatPercent(annualReturn, 2) : "--", "来自组合回测汇总"],
            ].map(([label, value, detail]) => `
                <div class="glass-card">
                    <div class="status-title">${escapeHtml(label)}</div>
                    <div class="status-value ${toneFromValue(annualReturn)}">${escapeHtml(String(value))}</div>
                    <div class="small">${escapeHtml(detail)}</div>
                </div>
            `).join("");
        }
    }

    function renderStatusGrid() {
        const overview = state.overview || {};
        const health = state.health || {};
        const latestRun = state.latestRun || {};
        const experiments = state.experiments || [];
        const grid = document.getElementById("statusGrid");
        if (!grid) {
            return;
        }
        const items = [
            ["数据日期", overview.date || "--", `目标覆盖 ${formatNumber(overview.coverage || 0, 0)}`],
            ["最新 Run", text(latestRun, ["run_id"], text(health, ["latest_run_id"], "--")), text(health, ["latest_run_status"], "--")],
            ["平台健康", text(health, ["latest_run_status"], "--"), health.platform_output_exists ? "platform output ready" : "platform output missing"],
            ["实验注册", formatNumber(experiments.length, 0), experiments[0] ? text(experiments[0], ["name", "experiment_id"], "--") : "暂无实验登记"],
        ];
        grid.innerHTML = items.map(([label, value, detail]) => `
            <div class="status-card">
                <div class="status-title">${escapeHtml(label)}</div>
                <div class="status-value">${escapeHtml(String(value))}</div>
                <div class="small">${escapeHtml(String(detail))}</div>
            </div>
        `).join("");
    }

    function renderMetricGrid() {
        const overview = state.overview || {};
        const daily = overview.daily_summary || {};
        const verify = overview.verify_stats || {};
        const backtest = overview.backtest_summary || {};
        const lastEquity = overview.equity_curve?.length ? overview.equity_curve[overview.equity_curve.length - 1].equity : null;
        const cards = [
            { label: "建议仓位", value: text(daily, ["position"], "--"), detail: text(daily, ["market_state"], "市场状态"), tone: "accent" },
            { label: "单票上限", value: text(daily, ["single_cap"], "--"), detail: `建议持有 ${text(daily, ["hold_days"], "--")} 天`, tone: "info" },
            { label: "历史验证胜率", value: verify.count ? formatPercent(verify.win_rate_pct, 1) : "--", detail: `样本 ${formatNumber(verify.count || 0, 0)}`, tone: toneFromValue(verify.win_rate_pct - 50) },
            { label: "验证平均收益", value: verify.count ? formatPercent(verify.avg_return_pct, 2) : "--", detail: `最大 ${formatPercent(verify.max_return_pct, 2)}`, tone: toneFromValue(verify.avg_return_pct) },
            { label: "回测年化", value: backtest.annual_return_pct !== undefined ? formatPercent(backtest.annual_return_pct, 2) : "--", detail: `换手 ${formatPercent(backtest.annual_turnover_pct, 1)}`, tone: toneFromValue(backtest.annual_return_pct) },
            { label: "最大回撤", value: backtest.max_drawdown_pct !== undefined ? formatPercent(backtest.max_drawdown_pct, 2) : "--", detail: "越低越稳", tone: toneFromValue(backtest.max_drawdown_pct, true) },
            { label: "Sharpe", value: backtest.sharpe !== undefined ? formatNumber(backtest.sharpe, 2) : "--", detail: `超额 ${backtest.exposure_adjusted_excess_return_pct !== undefined ? formatPercent(backtest.exposure_adjusted_excess_return_pct, 2) : "--"}`, tone: toneFromValue(backtest.sharpe) },
            { label: "最近权益", value: lastEquity !== null ? formatNumber(lastEquity, 3) : "--", detail: overview.equity_curve?.length ? `截至 ${overview.equity_curve[overview.equity_curve.length - 1].date}` : "暂无权益曲线", tone: toneFromValue(lastEquity ? lastEquity - 1 : 0) },
        ];
        const grid = document.getElementById("metricGrid");
        if (!grid) {
            return;
        }
        grid.innerHTML = cards.map((card) => `
            <article class="metric-card">
                <div class="metric-label">${escapeHtml(card.label)}</div>
                <div class="metric-value ${escapeHtml(card.tone)}">${escapeHtml(String(card.value))}</div>
                <div class="metric-detail">${escapeHtml(String(card.detail))}</div>
            </article>
        `).join("");
    }

    function renderEquityChart() {
        const chart = initChart("equityChart");
        if (!chart) {
            return;
        }
        const series = state.overview?.equity_curve || [];
        if (!series.length) {
            chart.clear();
            document.getElementById("equityChart").innerHTML = `<div class="empty-state">暂无权益曲线数据</div>`;
            return;
        }
        chart.setOption({
            backgroundColor: "transparent",
            tooltip: { trigger: "axis" },
            grid: { left: 48, right: 24, top: 28, bottom: 36 },
            xAxis: { type: "category", data: series.map((item) => item.date), axisLabel: { color: "#9bb1c4" } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [{
                type: "line",
                smooth: true,
                showSymbol: false,
                data: series.map((item) => item.equity),
                lineStyle: { width: 3, color: "#4dd2c4" },
                areaStyle: { color: "rgba(77, 210, 196, 0.16)" },
            }],
        });
    }

    function renderVerificationChart() {
        const chart = initChart("verificationChart");
        if (!chart) {
            return;
        }
        const rows = state.overview?.history_recent || [];
        if (!rows.length) {
            document.getElementById("verificationChart").innerHTML = `<div class="empty-state">暂无历史验证数据</div>`;
            return;
        }
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#9bb1c4" } },
            grid: { left: 50, right: 24, top: 48, bottom: 36 },
            xAxis: { type: "category", data: rows.map((row) => row.date), axisLabel: { color: "#9bb1c4" } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [
                { name: "整体胜率", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.win_rate_pct), lineStyle: { color: "#4dd2c4", width: 3 } },
                { name: "平均收益", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.avg_return_pct), lineStyle: { color: "#f2b766", width: 2 } },
                { name: "Top10胜率", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.top10_win_rate_pct), lineStyle: { color: "#60a5fa", width: 2 } },
            ],
        });
    }

    function renderMonthlyReturnChart() {
        const chart = initChart("monthlyReturnChart");
        if (!chart) {
            return;
        }
        const rows = state.overview?.returns_drilldown?.monthly || [];
        if (!rows.length) {
            document.getElementById("monthlyReturnChart").innerHTML = `<div class="empty-state">暂无月度收益钻取</div>`;
            return;
        }
        chart.setOption({
            tooltip: { trigger: "axis" },
            grid: { left: 50, right: 24, top: 28, bottom: 36 },
            xAxis: { type: "category", data: rows.map((row) => row.month), axisLabel: { color: "#9bb1c4", rotate: 30 } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [{
                type: "bar",
                data: rows.map((row) => ({
                    value: row.return_pct,
                    itemStyle: { color: row.return_pct >= 0 ? "#31c48d" : "#ff7b72" },
                })),
                barMaxWidth: 28,
            }],
        });
    }

    function renderDailyTable() {
        const rows = state.overview?.daily_top || [];
        const meta = document.getElementById("dailyMeta");
        if (meta) {
            meta.textContent = `Top ${formatNumber(rows.length, 0)}`;
        }
        document.getElementById("dailyTable").innerHTML = tableHtml(
            [
                { label: "代码", render: (row) => stockAnchor(text(row, ["代码"]), text(row, ["名称"])) },
                { label: "名称", render: (row) => escapeHtml(text(row, ["名称"])) },
                { label: "信号", render: (row) => escapeHtml(text(row, ["信号"])) },
                { label: "评分", render: (row) => escapeHtml(text(row, ["Alpha评分", "ML评分"])) },
                { label: "收盘价", render: (row) => escapeHtml(formatNumber(numeric(row, ["收盘价", "close"], NaN), 2)) },
                { label: "涨跌", render: (row) => `<span class="tone-${toneFromValue(numeric(row, ["涨幅%", "涨跌幅%"], 0))}">${escapeHtml(formatPercent(numeric(row, ["涨幅%", "涨跌幅%"], 0), 2))}</span>` },
                { label: "RSI", render: (row) => escapeHtml(formatNumber(numeric(row, ["RSI"], NaN), 1)) },
                { label: "量比", render: (row) => escapeHtml(formatNumber(numeric(row, ["量比", "Vol比"], NaN), 2)) },
            ],
            rows,
            "暂无推荐数据"
        );
    }

    function renderScanTable() {
        const rows = state.overview?.scan_top || [];
        const meta = document.getElementById("scanMeta");
        if (meta) {
            meta.textContent = `Top ${formatNumber(rows.length, 0)}`;
        }
        document.getElementById("scanTable").innerHTML = tableHtml(
            [
                { label: "代码", render: (row) => stockAnchor(text(row, ["代码"]), text(row, ["名称"])) },
                { label: "名称", render: (row) => escapeHtml(text(row, ["名称"])) },
                { label: "信号", render: (row) => escapeHtml(text(row, ["信号"])) },
                { label: "超跌等级", render: (row) => escapeHtml(text(row, ["超跌等级"])) },
                { label: "评分", render: (row) => escapeHtml(text(row, ["Alpha评分", "score", "ML评分"])) },
                { label: "涨跌", render: (row) => `<span class="tone-${toneFromValue(numeric(row, ["涨幅%", "涨跌幅%"], 0))}">${escapeHtml(formatPercent(numeric(row, ["涨幅%", "涨跌幅%"], 0), 2))}</span>` },
            ],
            rows,
            "暂无扫描信号"
        );
    }

    function renderTradeTable() {
        const rows = state.overview?.trade_records || [];
        document.getElementById("tradeTable").innerHTML = tableHtml(
            [
                { label: "信号日", render: (row) => escapeHtml(text(row, ["signal_date"])) },
                { label: "状态", render: (row) => `<span class="chip ${toneFromStatus(text(row, ["state"], ""))}">${escapeHtml(text(row, ["state"]))}</span>` },
                { label: "持仓数", render: (row) => escapeHtml(formatNumber(numeric(row, ["selected_count"], 0), 0)) },
                { label: "总暴露", render: (row) => escapeHtml(formatPercent(numeric(row, ["total_exposure"], 0) * 100, 1)) },
                { label: "组合收益", render: (row) => `<span class="tone-${toneFromValue(numeric(row, ["portfolio_ret"], 0))}">${escapeHtml(formatPercent(numeric(row, ["portfolio_ret"], 0) * 100, 2))}</span>` },
                { label: "权益", render: (row) => escapeHtml(formatNumber(numeric(row, ["equity"], NaN), 3)) },
                { label: "持仓", render: (row) => {
                    const positions = Array.isArray(row.positions) ? row.positions.slice(0, 4) : [];
                    if (!positions.length) {
                        return `<span class="small">--</span>`;
                    }
                    const chips = positions.map((item) => `<span class="table-pill">${stockAnchor(item.code, item.name)}</span>`).join("");
                    return `<div class="chip-row">${chips}</div>`;
                } },
            ],
            rows,
            "暂无交易流水"
        );
    }

    function renderOptimizeTable() {
        const rows = state.overview?.optimize_top || [];
        document.getElementById("optimizeTable").innerHTML = tableHtml(
            [
                { label: "Rank", render: (row) => escapeHtml(formatNumber(numeric(row, ["rank"], 0), 0)) },
                { label: "硬门槛", render: (row) => `<span class="chip ${row.pass_hard_filters ? "positive" : "warning"}">${row.pass_hard_filters ? "通过" : "待审"}</span>` },
                { label: "TopN", render: (row) => escapeHtml(formatNumber(numeric(row, ["top_n"], 0), 0)) },
                { label: "持有", render: (row) => escapeHtml(`${formatNumber(numeric(row, ["holding_days"], 0), 0)} 天`) },
                { label: "单票上限", render: (row) => escapeHtml(formatPercent(numeric(row, ["max_single_pos"], 0) * 100, 1)) },
                { label: "年化", render: (row) => `<span class="tone-${toneFromValue(numeric(row, ["annual_return_pct"], 0))}">${escapeHtml(formatPercent(numeric(row, ["annual_return_pct"], 0), 2))}</span>` },
                { label: "回撤", render: (row) => escapeHtml(formatPercent(numeric(row, ["max_drawdown_pct"], 0), 2)) },
                { label: "Sharpe", render: (row) => escapeHtml(formatNumber(numeric(row, ["sharpe"], 0), 2)) },
            ],
            rows,
            "暂无优化结果"
        );
    }

    function renderOpsPanel() {
        const health = state.health || {};
        const latestRun = state.latestRun || {};
        const experiments = state.experiments || [];
        const container = document.getElementById("opsPanel");
        if (!container) {
            return;
        }
        container.innerHTML = `
            <div class="list-stack">
                <div class="list-item">
                    <strong>最新运行</strong>
                    <div class="small">Run ID: ${escapeHtml(text(latestRun, ["run_id"], text(health, ["latest_run_id"], "--")))}</div>
                    <div class="chip-row" style="margin-top: 10px;">
                        ${chip(`状态 ${text(health, ["latest_run_status"], "--")}`, toneFromStatus(health.latest_run_status))}
                        ${chip(`实验 ${formatNumber(experiments.length, 0)} 个`, experiments.length ? "positive" : "warning")}
                    </div>
                </div>
                <div class="list-item">
                    <strong>最近实验</strong>
                    <div class="small">${experiments[0] ? `${escapeHtml(text(experiments[0], ["name", "experiment_id"]))} · ${escapeHtml(text(experiments[0], ["created_at"], "--"))}` : "暂无实验登记"}</div>
                </div>
                <div class="list-item">
                    <strong>查看更完整运维视图</strong>
                    <div class="small"><a href="/platform/ops">打开平台运维页，查看告警、暴露、容量和一致性摘要。</a></div>
                </div>
            </div>
        `;
    }

    function renderStockSnapshot(snapshot) {
        const container = document.getElementById("stockSnapshot");
        if (!container) {
            return;
        }
        const rows = [
            ["股票", `${snapshot.name || snapshot.code} (${snapshot.code || "--"})`],
            ["最新日期", snapshot.last_date || "--"],
            ["收盘", snapshot.last_close !== null && snapshot.last_close !== undefined ? formatNumber(snapshot.last_close, 2) : "--"],
            ["开盘", snapshot.last_open !== null && snapshot.last_open !== undefined ? formatNumber(snapshot.last_open, 2) : "--"],
            ["最高/最低", snapshot.last_high !== null && snapshot.last_low !== null ? `${formatNumber(snapshot.last_high, 2)} / ${formatNumber(snapshot.last_low, 2)}` : "--"],
        ];
        container.innerHTML = rows.map(([label, value]) => `
            <div class="list-item">
                <strong>${escapeHtml(label)}</strong>
                <div class="small">${escapeHtml(String(value))}</div>
            </div>
        `).join("");
    }

    function renderStockTrades(trades) {
        const container = document.getElementById("stockTrades");
        if (!container) {
            return;
        }
        container.innerHTML = tableHtml(
            [
                { label: "信号日", render: (row) => escapeHtml(text(row, ["signal_date"])) },
                { label: "入场", render: (row) => escapeHtml(text(row, ["entry_date"])) },
                { label: "离场", render: (row) => escapeHtml(text(row, ["exit_date"])) },
                { label: "组合收益", render: (row) => `<span class="tone-${toneFromValue(numeric(row, ["portfolio_ret"], 0))}">${escapeHtml(formatPercent(numeric(row, ["portfolio_ret"], 0) * 100, 2))}</span>` },
                { label: "权益", render: (row) => escapeHtml(formatNumber(numeric(row, ["equity"], NaN), 3)) },
            ],
            trades || [],
            "暂无关联交易记录"
        );
    }

    async function openStockModal(code, name) {
        const modal = document.getElementById("stockModal");
        if (!modal || !code) {
            return;
        }
        modal.classList.add("open");
        document.getElementById("stockTitle").textContent = `${name || code} · ${code}`;
        document.getElementById("stockSubtitle").textContent = "最近 180 天价格走势与关联交易记录。";
        setLoading("stockChart", "读取行情走势...");
        setLoading("stockSnapshot", "读取最新快照...");
        setLoading("stockTrades", "读取关联交易...");
        try {
            const payload = await fetchJson(`/api/stock_data/${encodeURIComponent(code)}`);
            const chartNode = document.getElementById("stockChart");
            if (chartNode) {
                const chart = initChart("stockChart");
                chart.setOption({
                    tooltip: { trigger: "axis" },
                    axisPointer: { link: [{ xAxisIndex: "all" }] },
                    grid: [{ left: 48, right: 24, top: 24, height: "60%" }, { left: 48, right: 24, top: "72%", height: "16%" }],
                    xAxis: [
                        { type: "category", data: payload.data.dates, scale: true, axisLabel: { color: "#9bb1c4" } },
                        { type: "category", gridIndex: 1, data: payload.data.dates, scale: true, axisLabel: { show: false } },
                    ],
                    yAxis: [
                        { scale: true, axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
                        { gridIndex: 1, axisLabel: { color: "#9bb1c4" }, splitLine: { show: false } },
                    ],
                    series: [
                        { type: "candlestick", data: payload.data.ohlc, itemStyle: { color: "#31c48d", color0: "#ff7b72", borderColor: "#31c48d", borderColor0: "#ff7b72" } },
                        { type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: payload.data.vols, itemStyle: { color: "rgba(96,165,250,0.75)" } },
                    ],
                });
            }
            renderStockSnapshot(payload.snapshot || {});
            renderStockTrades(payload.related_trades || []);
        } catch (error) {
            setError("stockChart", error);
            setError("stockSnapshot", error);
            setError("stockTrades", error);
        }
    }

    function closeStockModal() {
        const modal = document.getElementById("stockModal");
        if (modal) {
            modal.classList.remove("open");
        }
    }

    async function loadTradingDays() {
        const select = document.getElementById("tradeDate");
        if (!select) {
            return;
        }
        try {
            const payload = await fetchJson("/api/trading_days?lookback_days=240");
            const days = payload.trading_days || [];
            if (!days.length) {
                select.innerHTML = `<option value="">暂无交易日</option>`;
                return;
            }
            state.selectedDate = state.selectedDate || days[days.length - 1];
            select.innerHTML = days.map((day) => `<option value="${escapeHtml(day)}"${day === state.selectedDate ? " selected" : ""}>${escapeHtml(day)}</option>`).join("");
        } catch (error) {
            select.innerHTML = `<option value="">交易日加载失败</option>`;
        }
    }

    async function loadDashboard(date) {
        const containers = ["dailyTable", "scanTable", "tradeTable", "optimizeTable", "opsPanel", "equityChart", "verificationChart", "monthlyReturnChart"];
        containers.forEach((id) => setLoading(id, "加载平台数据中..."));
        const query = date ? `?date=${encodeURIComponent(date)}` : "";
        const settled = await Promise.allSettled([
            fetchJson(`/api/platform/overview${query}`),
            fetchJson("/api/platform/health"),
            fetchJson("/api/platform/latest_run"),
            fetchJson("/api/platform/experiments"),
        ]);
        if (settled[0].status !== "fulfilled") {
            throw settled[0].reason;
        }
        state.overview = settled[0].value;
        state.health = settled[1].status === "fulfilled" ? settled[1].value : {};
        state.latestRun = settled[2].status === "fulfilled" ? (settled[2].value.run || {}) : {};
        state.experiments = settled[3].status === "fulfilled" ? (settled[3].value.items || []) : [];
        state.selectedDate = state.overview?.date || date || state.selectedDate;

        renderHero();
        renderStatusGrid();
        renderMetricGrid();
        renderEquityChart();
        renderVerificationChart();
        renderMonthlyReturnChart();
        renderDailyTable();
        renderScanTable();
        renderTradeTable();
        renderOptimizeTable();
        renderOpsPanel();
    }

    function bindEvents() {
        document.getElementById("refreshBtn")?.addEventListener("click", async () => {
            try {
                await loadDashboard(document.getElementById("tradeDate")?.value || state.selectedDate);
            } catch (error) {
                ["dailyTable", "scanTable", "tradeTable", "optimizeTable", "opsPanel"].forEach((id) => setError(id, error));
            }
        });
        document.getElementById("tradeDate")?.addEventListener("change", async (event) => {
            state.selectedDate = event.target.value;
            try {
                await loadDashboard(state.selectedDate);
            } catch (error) {
                ["dailyTable", "scanTable", "tradeTable", "optimizeTable", "opsPanel"].forEach((id) => setError(id, error));
            }
        });
        document.addEventListener("click", (event) => {
            const link = event.target.closest(".stock-link");
            if (link) {
                event.preventDefault();
                openStockModal(link.dataset.code, link.dataset.name);
                return;
            }
            if (event.target.id === "closeModal" || event.target.id === "stockModal") {
                closeStockModal();
            }
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeStockModal();
            }
        });
    }

    async function bootstrap() {
        bindEvents();
        try {
            await loadTradingDays();
            await loadDashboard(state.selectedDate);
            const select = document.getElementById("tradeDate");
            if (select && state.selectedDate) {
                select.value = state.selectedDate;
            }
        } catch (error) {
            ["dailyTable", "scanTable", "tradeTable", "optimizeTable", "opsPanel", "equityChart", "verificationChart", "monthlyReturnChart"].forEach((id) => setError(id, error));
        }
    }

    bootstrap();
})();
