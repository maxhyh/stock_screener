(() => {
    const { chip, escapeHtml, fetchJson, formatNumber, formatPercent, initChart, pick, setError, setLoading, tableHtml, toneFromValue, toNumber } = window.QuantUI;

    function num(row, keys, fallback = 0) {
        return toNumber(pick(row, keys, fallback), fallback);
    }

    function txt(row, keys, fallback = "--") {
        return String(pick(row, keys, fallback) ?? fallback);
    }

    function renderHero(payload, summary) {
        const results = payload.results || [];
        const stats = payload.stats || {};
        const headline = document.getElementById("mlHeroTitle");
        const copy = document.getElementById("mlHeroCopy");
        const chips = document.getElementById("mlHeroChips");
        const metrics = document.getElementById("mlHeroMetrics");
        const first = results[0] || {};
        if (headline) {
            headline.textContent = `${payload.date || "--"} 最新推荐 ${formatNumber(results.length, 0)} 只`;
        }
        if (copy) {
            copy.textContent = `当前推荐按 ML 评分排序。历史验证胜率 ${summary ? formatPercent(summary.overall_win_rate, 1) : "--"}，T+1 快速验证 ${formatPercent(stats.verification_rate || 0, 1)}。`;
        }
        if (chips) {
            chips.innerHTML = [
                chip(`市场状态 ${txt(first, ["市场状态"], "--")}`, "accent"),
                chip(`建议仓位 ${txt(first, ["建议仓位"], "--")}`, "info"),
                chip(`单票上限 ${txt(first, ["单票上限"], "--")}`, "warning"),
                chip(`T+1 胜率 ${formatPercent(stats.verification_rate || 0, 1)}`, toneFromValue((stats.verification_rate || 0) - 50)),
            ].join("");
        }
        if (metrics) {
            metrics.innerHTML = [
                ["推荐数量", formatNumber(results.length, 0), "最新执行候选"],
                ["历史胜率", summary ? formatPercent(summary.overall_win_rate, 1) : "--", "来自 history_stats 摘要"],
                ["平均收益", summary ? formatPercent(summary.avg_return, 2) : "--", "历史验证均值"],
                ["Top10 胜率", summary ? formatPercent(summary.top10_win_rate, 1) : "--", "聚焦前排候选"],
            ].map(([label, value, detail]) => `
                <div class="glass-card">
                    <div class="status-title">${escapeHtml(label)}</div>
                    <div class="status-value">${escapeHtml(String(value))}</div>
                    <div class="small">${escapeHtml(detail)}</div>
                </div>
            `).join("");
        }
    }

    function renderMetrics(payload, summary) {
        const results = payload.results || [];
        const stats = payload.stats || {};
        const grid = document.getElementById("mlMetricGrid");
        if (!grid) {
            return;
        }
        const cards = [
            { label: "推荐数量", value: formatNumber(results.length, 0), detail: "最新日选股输出", tone: "accent" },
            { label: "最新日期", value: payload.date || "--", detail: "当前展示交易日", tone: "info" },
            { label: "历史胜率", value: summary ? formatPercent(summary.overall_win_rate, 1) : "--", detail: `Top10 ${summary ? formatPercent(summary.top10_win_rate, 1) : "--"}`, tone: toneFromValue((summary?.overall_win_rate || 0) - 50) },
            { label: "平均收益", value: summary ? formatPercent(summary.avg_return, 2) : "--", detail: `T+5 ${formatPercent(stats.t5_rate || 0, 1)}`, tone: toneFromValue(summary?.avg_return || 0) },
        ];
        grid.innerHTML = cards.map((card) => `
            <article class="metric-card">
                <div class="metric-label">${escapeHtml(card.label)}</div>
                <div class="metric-value ${escapeHtml(card.tone)}">${escapeHtml(String(card.value))}</div>
                <div class="metric-detail">${escapeHtml(card.detail)}</div>
            </article>
        `).join("");
    }

    function renderScoreChart(results) {
        const chart = initChart("mlScoreChart");
        if (!chart) {
            return;
        }
        if (!results.length) {
            document.getElementById("mlScoreChart").innerHTML = `<div class="empty-state">暂无推荐评分数据</div>`;
            return;
        }
        const top = results.slice(0, 12);
        chart.setOption({
            tooltip: { trigger: "axis" },
            grid: { left: 48, right: 24, top: 24, bottom: 42 },
            xAxis: { type: "category", data: top.map((row) => txt(row, ["名称", "代码"])), axisLabel: { color: "#9bb1c4", rotate: 20 } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [{
                type: "bar",
                data: top.map((row) => ({ value: num(row, ["ML评分", "Alpha评分"], 0), itemStyle: { color: "#4dd2c4" } })),
                barMaxWidth: 28,
            }],
        });
    }

    function renderTrackChart(summary) {
        const chart = initChart("mlTrackRecordChart");
        if (!chart) {
            return;
        }
        const rows = summary?.recent_10 || [];
        if (!rows.length) {
            document.getElementById("mlTrackRecordChart").innerHTML = `<div class="empty-state">暂无最近验证窗口</div>`;
            return;
        }
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#9bb1c4" } },
            grid: { left: 48, right: 24, top: 48, bottom: 36 },
            xAxis: { type: "category", data: rows.map((row) => row["验证日期"]), axisLabel: { color: "#9bb1c4" } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [
                { name: "整体胜率", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => num(row, ["整体胜率%"], 0)), lineStyle: { color: "#4dd2c4", width: 3 } },
                { name: "平均收益", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => num(row, ["平均收益%"], 0)), lineStyle: { color: "#f2b766", width: 2 } },
                { name: "Top10胜率", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => num(row, ["Top10胜率%"], 0)), lineStyle: { color: "#60a5fa", width: 2 } },
            ],
        });
    }

    function renderTable(results) {
        const meta = document.getElementById("mlTableMeta");
        if (meta) {
            meta.textContent = `${formatNumber(results.length, 0)} rows`;
        }
        document.getElementById("mlResultsTable").innerHTML = tableHtml(
            [
                { label: "排名", render: (row) => escapeHtml(formatNumber(num(row, ["排名"], 0), 0)) },
                { label: "代码", render: (row) => `<span class="mono">${escapeHtml(txt(row, ["代码"]))}</span>` },
                { label: "名称", render: (row) => escapeHtml(txt(row, ["名称"])) },
                { label: "ML评分", render: (row) => escapeHtml(formatNumber(num(row, ["ML评分", "Alpha评分"], 0), 4)) },
                { label: "收盘价", render: (row) => escapeHtml(formatNumber(num(row, ["收盘价"], 0), 2)) },
                { label: "涨跌幅", render: (row) => `<span class="tone-${toneFromValue(num(row, ["涨跌幅%", "涨幅%"], 0))}">${escapeHtml(formatPercent(num(row, ["涨跌幅%", "涨幅%"], 0), 2))}</span>` },
                { label: "BIAS", render: (row) => escapeHtml(formatNumber(num(row, ["BIAS-20", "BIAS"], 0), 2)) },
                { label: "RSI", render: (row) => escapeHtml(formatNumber(num(row, ["RSI"], 0), 1)) },
                { label: "量比", render: (row) => escapeHtml(formatNumber(num(row, ["量比", "Vol比"], 0), 2)) },
            ],
            results,
            "暂无 ML 推荐结果"
        );
    }

    async function loadMlPage() {
        setLoading("mlResultsTable", "加载今日推荐中...");
        setLoading("mlScoreChart", "加载评分排序...");
        setLoading("mlTrackRecordChart", "加载验证轨迹...");
        const [combined, summaryResp] = await Promise.allSettled([
            fetchJson("/api/ml/results_combined"),
            fetchJson("/api/ml/stats/summary"),
        ]);
        if (combined.status !== "fulfilled") {
            throw combined.reason;
        }
        const payload = combined.value;
        const summary = summaryResp.status === "fulfilled" ? summaryResp.value.summary : null;
        renderHero(payload, summary);
        renderMetrics(payload, summary);
        renderScoreChart(payload.results || []);
        renderTrackChart(summary);
        renderTable(payload.results || []);
    }

    function bind() {
        document.getElementById("reloadMl")?.addEventListener("click", async () => {
            try {
                await loadMlPage();
            } catch (error) {
                ["mlResultsTable", "mlScoreChart", "mlTrackRecordChart"].forEach((id) => setError(id, error));
            }
        });
    }

    async function bootstrap() {
        bind();
        try {
            await loadMlPage();
        } catch (error) {
            ["mlResultsTable", "mlScoreChart", "mlTrackRecordChart"].forEach((id) => setError(id, error));
        }
    }

    bootstrap();
})();
