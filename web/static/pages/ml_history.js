(() => {
    const { chip, escapeHtml, fetchJson, formatNumber, formatPercent, initChart, pick, setError, setLoading, tableHtml, toneFromValue, toNumber } = window.QuantUI;

    function num(row, keys, fallback = 0) {
        return toNumber(pick(row, keys, fallback), fallback);
    }

    function txt(row, keys, fallback = "--") {
        return String(pick(row, keys, fallback) ?? fallback);
    }

    function average(rows, key) {
        const nums = rows.map((row) => num(row, [key], NaN)).filter((value) => Number.isFinite(value));
        if (!nums.length) {
            return null;
        }
        return nums.reduce((sum, value) => sum + value, 0) / nums.length;
    }

    function normalizeDetailDate(raw) {
        const value = String(raw || "").trim();
        if (/^\d{8}$/.test(value)) {
            return [value];
        }
        if (/^\d{4}-\d{2}-\d{2}$/.test(value)) {
            return [value, value.replace(/-/g, "")];
        }
        return [value];
    }

    function renderHero(rows) {
        const title = document.getElementById("historyHeroTitle");
        const copy = document.getElementById("historyHeroCopy");
        const chips = document.getElementById("historyHeroChips");
        const metrics = document.getElementById("historyHeroMetrics");
        const t1 = average(rows, "T+1胜率%");
        const t5 = average(rows, "T+5胜率%");
        const t10 = average(rows, "T+10胜率%");
        if (title) {
            title.textContent = `已加载 ${formatNumber(rows.length, 0)} 个验证窗口`;
        }
        if (copy) {
            copy.textContent = "通过多窗口胜率和平均收益，看这套日选股是否只在局部行情里有效。";
        }
        if (chips) {
            const latest = rows[0] || {};
            chips.innerHTML = [
                chip(`最新验证日 ${txt(latest, ["日期"], "--")}`, "info"),
                chip(`T+1 ${t1 !== null ? formatPercent(t1, 1) : "--"}`, toneFromValue((t1 || 0) - 50)),
                chip(`T+5 ${t5 !== null ? formatPercent(t5, 1) : "--"}`, toneFromValue((t5 || 0) - 50)),
                chip(`T+10 ${t10 !== null ? formatPercent(t10, 1) : "--"}`, toneFromValue((t10 || 0) - 50)),
            ].join("");
        }
        if (metrics) {
            metrics.innerHTML = [
                ["验证天数", formatNumber(rows.length, 0), "历史样本数量"],
                ["T+1 胜率", t1 !== null ? formatPercent(t1, 1) : "--", "短持有表现"],
                ["T+5 胜率", t5 !== null ? formatPercent(t5, 1) : "--", "中段表现"],
                ["T+10 胜率", t10 !== null ? formatPercent(t10, 1) : "--", "延迟兑现能力"],
            ].map(([label, value, detail]) => `
                <div class="glass-card">
                    <div class="status-title">${escapeHtml(label)}</div>
                    <div class="status-value">${escapeHtml(String(value))}</div>
                    <div class="small">${escapeHtml(detail)}</div>
                </div>
            `).join("");
        }
    }

    function renderMetricGrid(rows) {
        const grid = document.getElementById("historyMetricGrid");
        if (!grid) {
            return;
        }
        const t1 = average(rows, "T+1胜率%");
        const t5 = average(rows, "T+5胜率%");
        const t10 = average(rows, "T+10胜率%");
        const cards = [
            { label: "验证天数", value: formatNumber(rows.length, 0), detail: "越长越能识别市场阶段差异", tone: "accent" },
            { label: "T+1 胜率", value: t1 !== null ? formatPercent(t1, 1) : "--", detail: `均值 ${average(rows, "T+1平均%") !== null ? formatPercent(average(rows, "T+1平均%"), 2) : "--"}`, tone: toneFromValue((t1 || 0) - 50) },
            { label: "T+5 胜率", value: t5 !== null ? formatPercent(t5, 1) : "--", detail: `均值 ${average(rows, "T+5平均%") !== null ? formatPercent(average(rows, "T+5平均%"), 2) : "--"}`, tone: toneFromValue((t5 || 0) - 50) },
            { label: "T+10 胜率", value: t10 !== null ? formatPercent(t10, 1) : "--", detail: `均值 ${average(rows, "T+10平均%") !== null ? formatPercent(average(rows, "T+10平均%"), 2) : "--"}`, tone: toneFromValue((t10 || 0) - 50) },
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
        const chart = initChart("historyWinChart");
        if (!chart) {
            return;
        }
        if (!rows.length) {
            document.getElementById("historyWinChart").innerHTML = `<div class="empty-state">暂无胜率趋势数据</div>`;
            return;
        }
        const ordered = [...rows].reverse();
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#9bb1c4" } },
            grid: { left: 48, right: 24, top: 48, bottom: 36 },
            xAxis: { type: "category", data: ordered.map((row) => txt(row, ["日期"])), axisLabel: { color: "#9bb1c4", rotate: 18 } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [
                { name: "T+1 胜率", type: "line", smooth: true, showSymbol: false, data: ordered.map((row) => num(row, ["T+1胜率%"], 0)), lineStyle: { color: "#4dd2c4", width: 3 } },
                { name: "T+5 胜率", type: "line", smooth: true, showSymbol: false, data: ordered.map((row) => num(row, ["T+5胜率%"], 0)), lineStyle: { color: "#60a5fa", width: 2 } },
                { name: "T+10 胜率", type: "line", smooth: true, showSymbol: false, data: ordered.map((row) => num(row, ["T+10胜率%"], 0)), lineStyle: { color: "#f2b766", width: 2 } },
            ],
        });
    }

    function renderReturnChart(rows) {
        const chart = initChart("historyReturnChart");
        if (!chart) {
            return;
        }
        if (!rows.length) {
            document.getElementById("historyReturnChart").innerHTML = `<div class="empty-state">暂无平均收益结构</div>`;
            return;
        }
        const ordered = [...rows].reverse();
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#9bb1c4" } },
            grid: { left: 48, right: 24, top: 48, bottom: 36 },
            xAxis: { type: "category", data: ordered.map((row) => txt(row, ["日期"])), axisLabel: { color: "#9bb1c4", rotate: 18 } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [
                { name: "T+1 平均", type: "bar", data: ordered.map((row) => num(row, ["T+1平均%"], 0)), itemStyle: { color: "#4dd2c4" } },
                { name: "T+5 平均", type: "bar", data: ordered.map((row) => num(row, ["T+5平均%"], 0)), itemStyle: { color: "#60a5fa" } },
                { name: "T+10 平均", type: "bar", data: ordered.map((row) => num(row, ["T+10平均%"], 0)), itemStyle: { color: "#f2b766" } },
            ],
        });
    }

    function renderTable(rows) {
        const meta = document.getElementById("historyTableMeta");
        if (meta) {
            meta.textContent = `${formatNumber(rows.length, 0)} rows`;
        }
        document.getElementById("historyTable").innerHTML = tableHtml(
            [
                { label: "日期", render: (row) => `<a href="#" class="mono history-detail-link" data-date="${escapeHtml(txt(row, ["日期"]))}">${escapeHtml(txt(row, ["日期"]))}</a>` },
                { label: "推荐数", render: (row) => escapeHtml(formatNumber(num(row, ["推荐数"], 0), 0)) },
                { label: "T+1 胜率", render: (row) => escapeHtml(formatPercent(num(row, ["T+1胜率%"], 0), 1)) },
                { label: "T+1 平均", render: (row) => `<span class="tone-${toneFromValue(num(row, ["T+1平均%"], 0))}">${escapeHtml(formatPercent(num(row, ["T+1平均%"], 0), 2))}</span>` },
                { label: "T+5 胜率", render: (row) => escapeHtml(formatPercent(num(row, ["T+5胜率%"], 0), 1)) },
                { label: "T+5 平均", render: (row) => `<span class="tone-${toneFromValue(num(row, ["T+5平均%"], 0))}">${escapeHtml(formatPercent(num(row, ["T+5平均%"], 0), 2))}</span>` },
                { label: "T+10 胜率", render: (row) => escapeHtml(formatPercent(num(row, ["T+10胜率%"], 0), 1)) },
                { label: "T+10 平均", render: (row) => `<span class="tone-${toneFromValue(num(row, ["T+10平均%"], 0))}">${escapeHtml(formatPercent(num(row, ["T+10平均%"], 0), 2))}</span>` },
            ],
            rows,
            "暂无历史验证汇总"
        );
    }

    async function openDetail(rawDate) {
        const modal = document.getElementById("detailModal");
        if (!modal) {
            return;
        }
        modal.classList.add("open");
        document.getElementById("detailTitle").textContent = `${rawDate} 验证日详情`;
        document.getElementById("detailSubtitle").textContent = "展开单日扩展验证记录。";
        setLoading("detailTableContainer", "加载验证详情...");
        let lastError = null;
        for (const dateToken of normalizeDetailDate(rawDate)) {
            try {
                const payload = await fetchJson(`/api/ml/history/detail/${encodeURIComponent(dateToken)}`);
                document.getElementById("detailTableContainer").innerHTML = tableHtml(
                    Object.keys(payload.data?.[0] || {}).slice(0, 8).map((key) => ({
                        label: key,
                        render: (row) => escapeHtml(String(row[key] ?? "--")),
                    })),
                    payload.data || [],
                    "暂无验证详情"
                );
                return;
            } catch (error) {
                lastError = error;
            }
        }
        setError("detailTableContainer", lastError || "加载详情失败");
    }

    function closeDetail() {
        document.getElementById("detailModal")?.classList.remove("open");
    }

    async function loadHistory() {
        setLoading("historyTable", "加载历史验证中...");
        setLoading("historyWinChart", "加载胜率趋势...");
        setLoading("historyReturnChart", "加载收益结构...");
        const payload = await fetchJson("/api/ml/history/summary");
        const rows = payload.data || [];
        renderHero(rows);
        renderMetricGrid(rows);
        renderWinChart(rows);
        renderReturnChart(rows);
        renderTable(rows);
    }

    function bind() {
        document.getElementById("reloadHistory")?.addEventListener("click", async () => {
            try {
                await loadHistory();
            } catch (error) {
                ["historyTable", "historyWinChart", "historyReturnChart"].forEach((id) => setError(id, error));
            }
        });
        document.addEventListener("click", (event) => {
            const detailLink = event.target.closest(".history-detail-link");
            if (detailLink) {
                event.preventDefault();
                openDetail(detailLink.dataset.date);
                return;
            }
            if (event.target.id === "closeDetailModal" || event.target.id === "detailModal") {
                closeDetail();
            }
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape") {
                closeDetail();
            }
        });
    }

    async function bootstrap() {
        bind();
        try {
            await loadHistory();
        } catch (error) {
            ["historyTable", "historyWinChart", "historyReturnChart"].forEach((id) => setError(id, error));
        }
    }

    bootstrap();
})();
