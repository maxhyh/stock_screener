(() => {
    const { chip, escapeHtml, fetchJson, formatNumber, formatPercent, initChart, pick, setError, setLoading, tableHtml, toneFromValue, toNumber } = window.QuantUI;

    function num(row, keys, fallback = 0) {
        return toNumber(pick(row, keys, fallback), fallback);
    }

    function renderHero(summary) {
        document.getElementById("backtestHeroTitle").textContent = `已加载 ${formatNumber(summary.total_days || 0, 0)} 个回测样本日`;
        document.getElementById("backtestHeroCopy").textContent = "把样本深度、命中率和多持有周期收益放在同一页里看，避免被单个漂亮指标误导。";
        document.getElementById("backtestHeroChips").innerHTML = [
            chip(`平均选股 ${formatNumber(summary.avg_picks || 0, 1)}`, "info"),
            chip(`T+1 胜率 ${formatPercent(summary.t1_avg_win || 0, 1)}`, toneFromValue((summary.t1_avg_win || 0) - 50)),
            chip(`T+5 胜率 ${formatPercent(summary.t5_avg_win || 0, 1)}`, toneFromValue((summary.t5_avg_win || 0) - 50)),
            chip(`T+10 胜率 ${formatPercent(summary.t10_avg_win || 0, 1)}`, toneFromValue((summary.t10_avg_win || 0) - 50)),
        ].join("");
        document.getElementById("backtestHeroMetrics").innerHTML = [
            ["样本天数", formatNumber(summary.total_days || 0, 0), "回测日频样本深度"],
            ["平均选股数", formatNumber(summary.avg_picks || 0, 1), "平均每个交易日选出的候选"],
            ["T+1 胜率", formatPercent(summary.t1_avg_win || 0, 1), "短持有命中率"],
            ["T+10 胜率", formatPercent(summary.t10_avg_win || 0, 1), "延迟兑现能力"],
        ].map(([label, value, detail]) => `
            <div class="glass-card">
                <div class="status-title">${escapeHtml(label)}</div>
                <div class="status-value">${escapeHtml(String(value))}</div>
                <div class="small">${escapeHtml(detail)}</div>
            </div>
        `).join("");
    }

    function renderMetricGrid(summary) {
        const grid = document.getElementById("backtestMetricGrid");
        if (!grid) {
            return;
        }
        const cards = [
            { label: "回测天数", value: formatNumber(summary.total_days || 0, 0), detail: "样本越深越可靠", tone: "accent" },
            { label: "平均选股数", value: formatNumber(summary.avg_picks || 0, 1), detail: "反映信号广度", tone: "info" },
            { label: "T+1 平均收益", value: formatPercent(summary.t1_avg_return || 0, 2), detail: `胜率 ${formatPercent(summary.t1_avg_win || 0, 1)}`, tone: toneFromValue(summary.t1_avg_return || 0) },
            { label: "T+5 平均收益", value: formatPercent(summary.t5_avg_return || 0, 2), detail: `胜率 ${formatPercent(summary.t5_avg_win || 0, 1)}`, tone: toneFromValue(summary.t5_avg_return || 0) },
        ];
        grid.innerHTML = cards.map((card) => `
            <article class="metric-card">
                <div class="metric-label">${escapeHtml(card.label)}</div>
                <div class="metric-value ${escapeHtml(card.tone)}">${escapeHtml(String(card.value))}</div>
                <div class="metric-detail">${escapeHtml(card.detail)}</div>
            </article>
        `).join("");
    }

    function renderWinChart(rows) {
        const chart = initChart("backtestWinChart");
        if (!chart) {
            return;
        }
        if (!rows.length) {
            document.getElementById("backtestWinChart").innerHTML = `<div class="empty-state">暂无回测胜率曲线</div>`;
            return;
        }
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#9bb1c4" } },
            grid: { left: 48, right: 24, top: 48, bottom: 36 },
            xAxis: { type: "category", data: rows.map((row) => row.date), axisLabel: { color: "#9bb1c4", rotate: 18 } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [
                { name: "T+1 胜率", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.t1_win), lineStyle: { color: "#4dd2c4", width: 3 } },
                { name: "T+5 胜率", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.t5_win), lineStyle: { color: "#60a5fa", width: 2 } },
                { name: "T+10 胜率", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.t10_win), lineStyle: { color: "#f2b766", width: 2 } },
            ],
        });
    }

    function renderReturnChart(rows) {
        const chart = initChart("backtestReturnChart");
        if (!chart) {
            return;
        }
        if (!rows.length) {
            document.getElementById("backtestReturnChart").innerHTML = `<div class="empty-state">暂无回测收益结构</div>`;
            return;
        }
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#9bb1c4" } },
            grid: { left: 48, right: 24, top: 48, bottom: 36 },
            xAxis: { type: "category", data: rows.map((row) => row.date), axisLabel: { color: "#9bb1c4", rotate: 18 } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [
                { name: "T+1 平均收益", type: "bar", data: rows.map((row) => row.t1_avg), itemStyle: { color: "#4dd2c4" } },
                { name: "T+5 平均收益", type: "bar", data: rows.map((row) => row.t5_avg), itemStyle: { color: "#60a5fa" } },
                { name: "T+10 平均收益", type: "bar", data: rows.map((row) => row.t10_avg), itemStyle: { color: "#f2b766" } },
            ],
        });
    }

    function renderTable(rows) {
        document.getElementById("backtestTableMeta").textContent = `${formatNumber(rows.length, 0)} rows`;
        document.getElementById("backtestTable").innerHTML = tableHtml(
            [
                { label: "日期", render: (row) => escapeHtml(String(row.date || "--")) },
                { label: "选股数", render: (row) => escapeHtml(formatNumber(row.picks || 0, 0)) },
                { label: "T+1 胜率", render: (row) => escapeHtml(formatPercent(row.t1_win || 0, 1)) },
                { label: "T+1 平均", render: (row) => `<span class="tone-${toneFromValue(row.t1_avg || 0)}">${escapeHtml(formatPercent(row.t1_avg || 0, 2))}</span>` },
                { label: "T+5 胜率", render: (row) => escapeHtml(formatPercent(row.t5_win || 0, 1)) },
                { label: "T+5 平均", render: (row) => `<span class="tone-${toneFromValue(row.t5_avg || 0)}">${escapeHtml(formatPercent(row.t5_avg || 0, 2))}</span>` },
                { label: "T+10 胜率", render: (row) => escapeHtml(formatPercent(row.t10_win || 0, 1)) },
                { label: "T+10 平均", render: (row) => `<span class="tone-${toneFromValue(row.t10_avg || 0)}">${escapeHtml(formatPercent(row.t10_avg || 0, 2))}</span>` },
            ],
            rows,
            "暂无回测明细"
        );
    }

    async function loadBacktestPage() {
        setLoading("backtestTable", "加载回测明细...");
        setLoading("backtestWinChart", "加载胜率曲线...");
        setLoading("backtestReturnChart", "加载收益结构...");
        const payload = await fetchJson("/api/backtest/mfts");
        renderHero(payload.summary || {});
        renderMetricGrid(payload.summary || {});
        renderWinChart(payload.data || []);
        renderReturnChart(payload.data || []);
        renderTable(payload.data || []);
    }

    function bind() {
        document.getElementById("reloadBacktest")?.addEventListener("click", async () => {
            try {
                await loadBacktestPage();
            } catch (error) {
                ["backtestTable", "backtestWinChart", "backtestReturnChart"].forEach((id) => setError(id, error));
            }
        });
    }

    async function bootstrap() {
        bind();
        try {
            await loadBacktestPage();
        } catch (error) {
            ["backtestTable", "backtestWinChart", "backtestReturnChart"].forEach((id) => setError(id, error));
        }
    }

    bootstrap();
})();
