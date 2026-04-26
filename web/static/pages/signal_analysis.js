(() => {
    const { chip, escapeHtml, fetchJson, formatNumber, formatPercent, initChart, setError, setLoading, tableHtml, toneFromValue, toNumber } = window.QuantUI;

    const state = { payload: null };

    function normalizeGroupMap(groupMap) {
        return Object.entries(groupMap || {}).map(([key, value]) => ({
            key,
            count: toNumber(value?.count, 0),
            t1_avg_return: toNumber(value?.t1_avg_return, 0),
            t1_win_rate: toNumber(value?.t1_win_rate, 0),
            t5_avg_return: toNumber(value?.t5_avg_return, 0),
            t5_win_rate: toNumber(value?.t5_win_rate, 0),
            t10_avg_return: toNumber(value?.t10_avg_return, 0),
            t10_win_rate: toNumber(value?.t10_win_rate, 0),
        }));
    }

    function monthRows(period) {
        const raw = Object.entries(state.payload?.by_month || {}).map(([month, value]) => ({
            month,
            total_signals: toNumber(value?.total_signals, 0),
            t1_avg_return: toNumber(value?.t1_avg_return, 0),
            t1_win_rate: toNumber(value?.t1_win_rate, 0),
            t5_avg_return: toNumber(value?.t5_avg_return, 0),
            t5_win_rate: toNumber(value?.t5_win_rate, 0),
        })).sort((a, b) => a.month.localeCompare(b.month));
        if (period === "all") {
            return raw;
        }
        const keepMonths = Math.max(parseInt(period, 10) || 6, 1);
        return raw.slice(-keepMonths);
    }

    function renderHero(period) {
        const overall = state.payload?.overall || {};
        const months = monthRows(period);
        document.getElementById("signalHeroTitle").textContent = `${formatNumber(overall.total_signals || 0, 0)} 条规则信号样本`;
        document.getElementById("signalHeroCopy").textContent = period === "all"
            ? "当前展示全样本信号统计。月度曲线与类型对比用于识别哪些信号真正有 edge。"
            : `当前按最近 ${period} 个月展示月度走势，类型与超跌等级表仍基于最新统计快照。`;
        document.getElementById("signalHeroChips").innerHTML = [
            chip(`样本 ${formatNumber(overall.total_signals || 0, 0)}`, "info"),
            chip(`T+1 ${formatPercent(overall.t1_avg_return || 0, 2)}`, toneFromValue(overall.t1_avg_return || 0)),
            chip(`T+1 胜率 ${formatPercent(overall.t1_win_rate || 0, 1)}`, toneFromValue((overall.t1_win_rate || 0) - 50)),
            chip(`月度窗口 ${months.length}`, "accent"),
        ].join("");
        document.getElementById("signalHeroMetrics").innerHTML = [
            ["样本总数", formatNumber(overall.total_signals || 0, 0), "全样本信号数"],
            ["T+1 收益", formatPercent(overall.t1_avg_return || 0, 2), "短线平均收益"],
            ["T+1 胜率", formatPercent(overall.t1_win_rate || 0, 1), "短线命中率"],
            ["T+5 胜率", formatPercent(overall.t5_win_rate || 0, 1), "延长持有命中率"],
        ].map(([label, value, detail]) => `
            <div class="glass-card">
                <div class="status-title">${escapeHtml(label)}</div>
                <div class="status-value">${escapeHtml(String(value))}</div>
                <div class="small">${escapeHtml(detail)}</div>
            </div>
        `).join("");
    }

    function renderMetrics(period) {
        const overall = state.payload?.overall || {};
        const range = state.payload?.date_range || {};
        const grid = document.getElementById("signalMetricGrid");
        if (!grid) {
            return;
        }
        const cards = [
            { label: "样本总数", value: formatNumber(overall.total_signals || 0, 0), detail: `交易日 ${formatNumber(range.trading_days || 0, 0)}`, tone: "accent" },
            { label: "T+1 收益", value: formatPercent(overall.t1_avg_return || 0, 2), detail: `胜率 ${formatPercent(overall.t1_win_rate || 0, 1)}`, tone: toneFromValue(overall.t1_avg_return || 0) },
            { label: "T+5 收益", value: formatPercent(overall.t5_avg_return || 0, 2), detail: `胜率 ${formatPercent(overall.t5_win_rate || 0, 1)}`, tone: toneFromValue(overall.t5_avg_return || 0) },
            { label: "时间范围", value: period === "all" ? "全样本" : `最近 ${period} 月`, detail: `${range.start_date || "--"} ~ ${range.end_date || "--"}`, tone: "info" },
        ];
        grid.innerHTML = cards.map((card) => `
            <article class="metric-card">
                <div class="metric-label">${escapeHtml(card.label)}</div>
                <div class="metric-value ${escapeHtml(card.tone)}">${escapeHtml(String(card.value))}</div>
                <div class="metric-detail">${escapeHtml(card.detail)}</div>
            </article>
        `).join("");
    }

    function renderMonthlyChart(period) {
        const chart = initChart("signalMonthlyChart");
        if (!chart) {
            return;
        }
        const rows = monthRows(period);
        if (!rows.length) {
            document.getElementById("signalMonthlyChart").innerHTML = `<div class="empty-state">暂无月度信号趋势</div>`;
            return;
        }
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#9bb1c4" } },
            grid: { left: 48, right: 24, top: 48, bottom: 36 },
            xAxis: { type: "category", data: rows.map((row) => row.month), axisLabel: { color: "#9bb1c4" } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [
                { name: "T+1 收益", type: "bar", data: rows.map((row) => row.t1_avg_return), itemStyle: { color: "#4dd2c4" } },
                { name: "T+1 胜率", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.t1_win_rate), lineStyle: { color: "#60a5fa", width: 2 } },
                { name: "T+5 胜率", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.t5_win_rate), lineStyle: { color: "#f2b766", width: 2 } },
            ],
        });
    }

    function renderTypeChart() {
        const chart = initChart("signalTypeChart");
        if (!chart) {
            return;
        }
        const rows = normalizeGroupMap(state.payload?.by_signal_type).sort((a, b) => b.t1_avg_return - a.t1_avg_return).slice(0, 10);
        if (!rows.length) {
            document.getElementById("signalTypeChart").innerHTML = `<div class="empty-state">暂无信号类型对比</div>`;
            return;
        }
        chart.setOption({
            tooltip: { trigger: "axis" },
            grid: { left: 48, right: 24, top: 24, bottom: 60 },
            xAxis: { type: "category", data: rows.map((row) => row.key), axisLabel: { color: "#9bb1c4", rotate: 25 } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [{ type: "bar", data: rows.map((row) => ({ value: row.t1_avg_return, itemStyle: { color: row.t1_avg_return >= 0 ? "#31c48d" : "#ff7b72" } })), barMaxWidth: 24 }],
        });
    }

    function renderTables() {
        const typeRows = normalizeGroupMap(state.payload?.by_signal_type).sort((a, b) => b.count - a.count);
        const levelRows = normalizeGroupMap(state.payload?.by_oversold_level).sort((a, b) => b.count - a.count);
        document.getElementById("signalTypeTable").innerHTML = tableHtml(
            [
                { label: "类型", render: (row) => escapeHtml(row.key) },
                { label: "样本数", render: (row) => escapeHtml(formatNumber(row.count, 0)) },
                { label: "T+1 收益", render: (row) => `<span class="tone-${toneFromValue(row.t1_avg_return)}">${escapeHtml(formatPercent(row.t1_avg_return, 2))}</span>` },
                { label: "T+1 胜率", render: (row) => escapeHtml(formatPercent(row.t1_win_rate, 1)) },
                { label: "T+5 收益", render: (row) => `<span class="tone-${toneFromValue(row.t5_avg_return)}">${escapeHtml(formatPercent(row.t5_avg_return, 2))}</span>` },
                { label: "T+5 胜率", render: (row) => escapeHtml(formatPercent(row.t5_win_rate, 1)) },
            ],
            typeRows,
            "暂无信号类型统计"
        );
        document.getElementById("signalLevelTable").innerHTML = tableHtml(
            [
                { label: "超跌等级", render: (row) => escapeHtml(row.key) },
                { label: "样本数", render: (row) => escapeHtml(formatNumber(row.count, 0)) },
                { label: "T+1 收益", render: (row) => `<span class="tone-${toneFromValue(row.t1_avg_return)}">${escapeHtml(formatPercent(row.t1_avg_return, 2))}</span>` },
                { label: "T+1 胜率", render: (row) => escapeHtml(formatPercent(row.t1_win_rate, 1)) },
                { label: "T+5 收益", render: (row) => `<span class="tone-${toneFromValue(row.t5_avg_return)}">${escapeHtml(formatPercent(row.t5_avg_return, 2))}</span>` },
                { label: "T+5 胜率", render: (row) => escapeHtml(formatPercent(row.t5_win_rate, 1)) },
            ],
            levelRows,
            "暂无超跌等级统计"
        );
    }

    async function loadSignalPage() {
        setLoading("signalTypeTable", "加载信号类型统计...");
        setLoading("signalLevelTable", "加载超跌等级统计...");
        setLoading("signalMonthlyChart", "加载月度趋势...");
        setLoading("signalTypeChart", "加载类型对比...");
        state.payload = await fetchJson("/api/signal/stats");
        const period = document.getElementById("periodSelect")?.value || "6";
        renderHero(period);
        renderMetrics(period);
        renderMonthlyChart(period);
        renderTypeChart();
        renderTables();
    }

    function bind() {
        const reload = async () => {
            try {
                await loadSignalPage();
            } catch (error) {
                ["signalTypeTable", "signalLevelTable", "signalMonthlyChart", "signalTypeChart"].forEach((id) => setError(id, error));
            }
        };
        document.getElementById("reloadSignal")?.addEventListener("click", reload);
        document.getElementById("periodSelect")?.addEventListener("change", () => {
            if (state.payload) {
                const period = document.getElementById("periodSelect").value;
                renderHero(period);
                renderMetrics(period);
                renderMonthlyChart(period);
            }
        });
    }

    async function bootstrap() {
        bind();
        try {
            await loadSignalPage();
        } catch (error) {
            ["signalTypeTable", "signalLevelTable", "signalMonthlyChart", "signalTypeChart"].forEach((id) => setError(id, error));
        }
    }

    bootstrap();
})();
