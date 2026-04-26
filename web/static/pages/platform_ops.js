(() => {
    const { chip, escapeHtml, fetchJson, formatDateToken, formatNumber, formatPercent, initChart, pick, setError, setLoading, tableHtml, toneFromStatus, toneFromValue, toNumber } = window.QuantUI;

    function num(row, keys, fallback = 0) {
        return toNumber(pick(row, keys, fallback), fallback);
    }

    function txt(row, keys, fallback = "--") {
        return String(pick(row, keys, fallback) ?? fallback);
    }

    function promotionTone(decision, changeRequired) {
        if (changeRequired || decision === "promote") {
            return "warning";
        }
        if (decision === "keep") {
            return "positive";
        }
        return "info";
    }

    function renderHero(payload) {
        const platform = payload.platform || {};
        const alertSummary = payload.alert_summary || {};
        const exec = payload.risk?.exec_consistency || {};
        document.getElementById("opsHeroTitle").textContent = `${txt(platform, ["latest_run_id"], "未发现 run")} · ${txt(platform, ["latest_run_status"], "missing")}`;
        document.getElementById("opsHeroCopy").textContent = alertSummary.total
            ? `当前共发现 ${formatNumber(alertSummary.total || 0, 0)} 条平台告警，需要优先检查执行一致性、风控对齐和容量压力。`
            : "当前没有触发平台级告警，运行态、风险暴露和容量摘要处于健康区间。";
        document.getElementById("opsHeroChips").innerHTML = [
            chip(`运行 ${txt(platform, ["latest_run_status"], "--")}`, toneFromStatus(platform.latest_run_status)),
            chip(`Critical ${formatNumber(alertSummary.critical || 0, 0)}`, (alertSummary.critical || 0) ? "negative" : "positive"),
            chip(`Warning ${formatNumber(alertSummary.warning || 0, 0)}`, (alertSummary.warning || 0) ? "warning" : "positive"),
            chip(`一致性覆盖 ${formatPercent(exec.coverage_pct || 0, 1)}`, toneFromValue((exec.coverage_pct || 0) - 95)),
        ].join("");
        document.getElementById("opsHeroMetrics").innerHTML = [
            ["最新 Run", txt(platform, ["latest_run_id"], "--"), txt(platform, ["latest_run_status"], "--")],
            ["实验数", formatNumber(platform.experiment_count || 0, 0), "最近登记实验数量"],
            ["一致性", exec.consistency_pass === undefined ? "--" : (exec.consistency_pass ? "通过" : "失败"), `覆盖 ${formatPercent(exec.coverage_pct || 0, 1)}`],
            ["风险拦截率", exec.risk_block_rate_mean_pct !== undefined ? formatPercent(exec.risk_block_rate_mean_pct, 1) : "--", `主因 ${txt(exec, ["primary_driver_top"], "--")}`],
        ].map(([label, value, detail]) => `
            <div class="glass-card">
                <div class="status-title">${escapeHtml(label)}</div>
                <div class="status-value">${escapeHtml(String(value))}</div>
                <div class="small">${escapeHtml(String(detail))}</div>
            </div>
        `).join("");
    }

    function renderAlerts(payload) {
        const container = document.getElementById("opsAlerts");
        if (!container) {
            return;
        }
        const alerts = payload.alerts || [];
        if (!alerts.length) {
            container.innerHTML = `<div class="list-item"><strong>当前无平台告警</strong><div class="small">运行、执行一致性、前置风控、暴露和容量摘要都处于健康区间。</div></div>`;
            return;
        }
        container.innerHTML = `
            <div class="alert-stack">
                ${alerts.map((alert) => `
                    <div class="alert-item ${escapeHtml(alert.severity || "info")}">
                        <div class="alert-head">
                            <div class="chip ${escapeHtml(alert.severity || "info")}">${escapeHtml(String(alert.severity || "info").toUpperCase())}</div>
                            <div class="small">${escapeHtml(txt(alert, ["domain"], "--"))}</div>
                        </div>
                        <strong>${escapeHtml(txt(alert, ["title"], "--"))}</strong>
                        <div class="small">${escapeHtml(txt(alert, ["message"], "--"))}</div>
                        <div class="alert-meta">
                            <span>Observed: ${escapeHtml(String(alert.observed_value ?? "--"))}</span>
                            <span>Threshold: ${escapeHtml(typeof alert.threshold === "object" ? JSON.stringify(alert.threshold) : String(alert.threshold ?? "--"))}</span>
                            <span>Metric: ${escapeHtml(txt(alert, ["metric_path"], "--"))}</span>
                        </div>
                    </div>
                `).join("")}
            </div>
        `;
    }

    function renderMetrics(payload) {
        const platform = payload.platform || {};
        const exec = payload.risk?.exec_consistency || {};
        const pretrade = payload.risk?.pretrade_alignment?.metrics || {};
        const trend = payload.alert_trends || {};
        const grid = document.getElementById("opsMetricGrid");
        if (!grid) {
            return;
        }
        const cards = [
            { label: "最新 Run", value: txt(platform, ["latest_run_id"], "--"), detail: txt(platform, ["latest_run_started_at"], "--"), tone: toneFromStatus(platform.latest_run_status) },
            { label: "实验注册", value: formatNumber(platform.experiment_count || 0, 0), detail: payload.experiments?.[0] ? txt(payload.experiments[0], ["name", "experiment_id"], "--") : "暂无实验", tone: platform.experiment_count ? "accent" : "warning" },
            { label: "收益偏差", value: exec.ret_gap_mae_pct !== undefined ? formatPercent(exec.ret_gap_mae_pct, 2) : "--", detail: `coverage ${formatPercent(exec.coverage_pct || 0, 1)}`, tone: toneFromValue(exec.ret_gap_mae_pct || 0, true) },
            {
                label: "告警趋势",
                value: formatNumber(trend.total_alerts?.latest || 0, 0),
                detail: trend.total_alerts?.delta === null || trend.total_alerts?.delta === undefined
                    ? "暂无上期对比"
                    : `较上次 ${trend.total_alerts.delta > 0 ? "+" : ""}${formatNumber(trend.total_alerts.delta, 0)}`,
                tone: toneFromValue(trend.total_alerts?.delta || 0, true),
            },
        ];
        grid.innerHTML = cards.map((card) => `
            <article class="metric-card">
                <div class="metric-label">${escapeHtml(card.label)}</div>
                <div class="metric-value ${escapeHtml(card.tone)}">${escapeHtml(String(card.value))}</div>
                <div class="metric-detail">${escapeHtml(card.detail)}</div>
            </article>
        `).join("");
    }

    function renderAlertTrend(payload) {
        const chart = initChart("opsAlertTrendChart");
        if (!chart) {
            return;
        }
        const rows = payload.alert_trends?.series || [];
        if (!rows.length) {
            document.getElementById("opsAlertTrendChart").innerHTML = `<div class="empty-state">暂无告警历史趋势</div>`;
            return;
        }
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#9bb1c4" } },
            grid: { left: 48, right: 24, top: 48, bottom: 36 },
            xAxis: { type: "category", data: rows.map((row) => row.as_of_date), axisLabel: { color: "#9bb1c4" } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [
                { name: "总告警", type: "bar", data: rows.map((row) => row.total_alerts), itemStyle: { color: "#60a5fa" } },
                { name: "严重告警", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.critical), lineStyle: { color: "#ff7b72", width: 2 } },
                { name: "前置匹配率", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.pretrade_match_rate_pct), lineStyle: { color: "#4dd2c4", width: 2 } },
            ],
        });
    }

    function renderPromotionTrend(payload) {
        const chart = initChart("promotionTrendChart");
        if (!chart) {
            return;
        }
        const rows = payload.governance?.promotion_trends?.series || [];
        if (!rows.length) {
            document.getElementById("promotionTrendChart").innerHTML = `<div class="empty-state">暂无主档挑战趋势</div>`;
            return;
        }
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#9bb1c4" } },
            grid: { left: 48, right: 24, top: 48, bottom: 36 },
            xAxis: { type: "category", data: rows.map((row) => row.as_of_date), axisLabel: { color: "#9bb1c4" } },
            yAxis: [
                { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
                { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { show: false } },
            ],
            series: [
                { name: "挑战分差", type: "bar", data: rows.map((row) => row.score_margin), itemStyle: { color: "#60a5fa" } },
                { name: "候选执行分", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.candidate_ops_score), lineStyle: { color: "#ff7b72", width: 2 } },
                { name: "主档执行分", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.main_ops_score), lineStyle: { color: "#4dd2c4", width: 2 } },
                { name: "待晋升", type: "line", yAxisIndex: 1, smooth: true, step: "middle", showSymbol: false, data: rows.map((row) => row.change_required ? 1 : 0), lineStyle: { color: "#f2b766", width: 2 } },
            ],
        });
    }

    function renderIndustryChart(rows) {
        const chart = initChart("industryExposureChart");
        if (!chart) {
            return;
        }
        if (!rows.length) {
            document.getElementById("industryExposureChart").innerHTML = `<div class="empty-state">暂无行业暴露数据</div>`;
            return;
        }
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#9bb1c4" } },
            grid: { left: 56, right: 24, top: 48, bottom: 36 },
            xAxis: { type: "category", data: rows.map((row) => row.industry), axisLabel: { color: "#9bb1c4", rotate: 18 } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [
                { name: "平均权重", type: "bar", data: rows.map((row) => row.avg_weight_pct), itemStyle: { color: "#4dd2c4" } },
                { name: "峰值权重", type: "line", smooth: true, showSymbol: false, data: rows.map((row) => row.max_weight_pct), lineStyle: { color: "#f2b766", width: 2 } },
            ],
        });
    }

    function renderCapacityChart(rows) {
        const chart = initChart("capacityChart");
        if (!chart) {
            return;
        }
        if (!rows.length) {
            document.getElementById("capacityChart").innerHTML = `<div class="empty-state">暂无容量压力数据</div>`;
            return;
        }
        const ordered = [...rows].reverse();
        chart.setOption({
            tooltip: { trigger: "axis" },
            legend: { top: 0, textStyle: { color: "#9bb1c4" } },
            grid: { left: 56, right: 24, top: 48, bottom: 36 },
            xAxis: { type: "category", data: ordered.map((row) => formatDateToken(row.signal_date)), axisLabel: { color: "#9bb1c4" } },
            yAxis: { type: "value", axisLabel: { color: "#9bb1c4" }, splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } } },
            series: [
                { name: "参与率", type: "bar", data: ordered.map((row) => row.max_participation_pct), itemStyle: { color: "#60a5fa" } },
                { name: "容量倍数", type: "line", smooth: true, showSymbol: false, data: ordered.map((row) => row.capacity_multiple), lineStyle: { color: "#4dd2c4", width: 2 } },
                { name: "往返成本", type: "line", smooth: true, showSymbol: false, data: ordered.map((row) => row.estimated_roundtrip_cost_bps), lineStyle: { color: "#f2b766", width: 2 } },
            ],
        });
    }

    function renderPanels(payload) {
        const exec = payload.risk?.exec_consistency || {};
        const pretrade = payload.risk?.pretrade_alignment || {};
        const metrics = pretrade.metrics || {};
        const promotion = payload.governance?.promotion_decision || {};
        document.getElementById("consistencyPanel").innerHTML = `
            <div class="list-stack">
                <div class="list-item">
                    <strong>一致性结果</strong>
                    <div class="chip-row" style="margin-top: 10px;">
                        ${chip(exec.consistency_pass ? "PASS" : "FAIL", exec.consistency_pass ? "positive" : "negative")}
                        ${chip(`coverage ${formatPercent(exec.coverage_pct || 0, 1)}`, "info")}
                        ${chip(`ret gap ${formatPercent(exec.ret_gap_mae_pct || 0, 2)}`, toneFromValue(exec.ret_gap_mae_pct || 0, true))}
                    </div>
                </div>
                <div class="list-item">
                    <strong>执行摩擦</strong>
                    <div class="small">订单阻塞率 ${formatPercent(exec.order_block_rate_mean_pct || 0, 1)}，风险拦截率 ${formatPercent(exec.risk_block_rate_mean_pct || 0, 1)}。</div>
                    <div class="small">主导偏差原因：${escapeHtml(txt(exec, ["primary_driver_top"], "--"))}</div>
                </div>
            </div>
        `;
        document.getElementById("alignmentPanel").innerHTML = `
            <div class="list-stack">
                <div class="list-item">
                    <strong>对齐窗口</strong>
                    <div class="small">${escapeHtml(txt(pretrade, ["window_start"], "--"))} ~ ${escapeHtml(txt(pretrade, ["window_end"], "--"))}</div>
                </div>
                <div class="list-item">
                    <strong>关键指标</strong>
                    <div class="small">匹配率 ${formatPercent(metrics.match_rate_pct || 0, 1)}，P2 风险拦截率 ${formatPercent(metrics.mean_p2_risk_blocked_rate_pct || 0, 1)}。</div>
                    <div class="small">主因：${escapeHtml(txt(metrics, ["top_p2_risk_block_reason"], "--"))}</div>
                </div>
            </div>
        `;
        const promotionToneValue = promotionTone(txt(promotion, ["decision"], ""), Boolean(promotion.change_required));
        const evidence = promotion.evidence || {};
        const artifacts = promotion.artifacts || {};
        document.getElementById("promotionGatePanel").innerHTML = Object.keys(promotion).length
            ? `
                <div class="list-stack">
                    <div class="list-item">
                        <strong>最新治理结论</strong>
                        <div class="chip-row" style="margin-top: 10px;">
                            ${chip(`决策 ${txt(promotion, ["decision"], "--")}`, promotionToneValue)}
                            ${chip(`主档 ${txt(promotion, ["final_default_profile"], "--")}`, "info")}
                            ${chip(`挑战者 ${txt(promotion, ["candidate_profile"], "--")}`, "accent")}
                            ${chip(`变更 ${promotion.change_required ? "required" : "not required"}`, promotion.change_required ? "warning" : "positive")}
                        </div>
                    </div>
                    <div class="list-item">
                        <strong>原因与解释</strong>
                        <div class="small">原因码 ${escapeHtml(txt(promotion, ["reason_code"], "--"))}</div>
                        <div class="small">${escapeHtml(txt(promotion, ["rationale"], "暂无说明"))}</div>
                    </div>
                    <div class="list-item">
                        <strong>关键证据</strong>
                        <div class="small">研究分 ${escapeHtml(formatNumber(num(evidence, ["winner_research_score"], 0), 2))}，执行分 ${escapeHtml(formatNumber(num(evidence, ["winner_ops_score"], 0), 2))}，分差 ${escapeHtml(formatNumber(num(evidence, ["score_margin"], 0), 2))}。</div>
                        <div class="small">P2 执行天数 ${escapeHtml(formatNumber(num(evidence, ["candidate_p2_executed_days_total", "winner_p2_executed_days_total"], 0), 0))}，门槛 ${escapeHtml(formatNumber(num(evidence, ["min_p2_executed_days"], 0), 0))}。</div>
                        <div class="small">生成时间 ${escapeHtml(txt(promotion, ["generated_at"], "--"))}</div>
                    </div>
                    <div class="list-item">
                        <strong>工件</strong>
                        <div class="small mono">${escapeHtml(txt(artifacts, ["review_csv"], "--"))}</div>
                        <div class="small mono">${escapeHtml(txt(artifacts, ["review_meta_json"], "--"))}</div>
                    </div>
                </div>
            `
            : `
                <div class="list-item">
                    <strong>暂无 promotion gate 决策</strong>
                    <div class="small">系统尚未找到 latest 决策文件，当前 default_profile 缺少最新治理凭据。</div>
                </div>
            `;
    }

    function renderTables(payload) {
        const risk = payload.risk || {};
        document.getElementById("exposureTable").innerHTML = tableHtml(
            [
                { label: "状态", render: (row) => escapeHtml(txt(row, ["state"])) },
                { label: "交易笔数", render: (row) => escapeHtml(formatNumber(num(row, ["trades"], 0), 0)) },
                { label: "平均暴露", render: (row) => escapeHtml(formatPercent(num(row, ["avg_exposure_pct"], 0), 1)) },
                { label: "平均持仓", render: (row) => escapeHtml(formatNumber(num(row, ["avg_positions"], 0), 1)) },
                { label: "胜率", render: (row) => escapeHtml(formatPercent(num(row, ["win_rate_pct"], 0), 1)) },
                { label: "组合收益", render: (row) => `<span class="tone-${toneFromValue(num(row, ["avg_portfolio_ret_pct"], 0))}">${escapeHtml(formatPercent(num(row, ["avg_portfolio_ret_pct"], 0), 2))}</span>` },
                { label: "HHI", render: (row) => escapeHtml(formatNumber(num(row, ["avg_hhi"], 0), 3)) },
            ],
            risk.exposure_summary || [],
            "暂无组合暴露摘要"
        );
        document.getElementById("experimentTable").innerHTML = tableHtml(
            [
                { label: "实验 ID", render: (row) => `<span class="mono">${escapeHtml(txt(row, ["experiment_id"]))}</span>` },
                { label: "名称", render: (row) => escapeHtml(txt(row, ["name"])) },
                { label: "创建时间", render: (row) => escapeHtml(txt(row, ["created_at"])) },
                { label: "模型", render: (row) => escapeHtml(txt(row, ["model_id", "model"])) },
            ],
            payload.experiments || [],
            "暂无实验登记"
        );
        document.getElementById("capacityTable").innerHTML = tableHtml(
            [
                { label: "日期", render: (row) => escapeHtml(formatDateToken(txt(row, ["signal_date"]))) },
                { label: "状态", render: (row) => `<span class="chip ${toneFromStatus(txt(row, ["state"], ""))}">${escapeHtml(txt(row, ["state"]))}</span>` },
                { label: "总暴露", render: (row) => escapeHtml(formatPercent(num(row, ["total_exposure_pct"], 0), 1)) },
                { label: "持仓数", render: (row) => escapeHtml(formatNumber(num(row, ["position_count"], 0), 0)) },
                { label: "最大参与率", render: (row) => escapeHtml(formatPercent(num(row, ["max_participation_pct"], 0), 1)) },
                { label: "往返成本", render: (row) => escapeHtml(formatNumber(num(row, ["estimated_roundtrip_cost_bps"], 0), 1)) },
                { label: "容量倍数", render: (row) => escapeHtml(formatNumber(num(row, ["capacity_multiple"], 0), 2)) },
                { label: "组合收益", render: (row) => `<span class="tone-${toneFromValue(num(row, ["portfolio_ret_pct"], 0))}">${escapeHtml(formatPercent(num(row, ["portfolio_ret_pct"], 0), 2))}</span>` },
            ],
            risk.capacity_recent || [],
            "暂无容量记录"
        );
        document.getElementById("promotionHistoryTable").innerHTML = tableHtml(
            [
                { label: "快照时间", render: (row) => escapeHtml(txt(row, ["generated_at"])) },
                { label: "决策", render: (row) => `<span class="chip ${promotionTone(txt(row, ["promotion_decision"], ""), Boolean(num(row, ["promotion_change_required"], 0)))}">${escapeHtml(txt(row, ["promotion_decision"], "--"))}</span>` },
                { label: "主档", render: (row) => `<span class="mono">${escapeHtml(txt(row, ["promotion_final_default_profile"], "--"))}</span>` },
                { label: "挑战者", render: (row) => `<span class="mono">${escapeHtml(txt(row, ["promotion_candidate_profile"], "--"))}</span>` },
                { label: "原因码", render: (row) => escapeHtml(txt(row, ["promotion_reason_code"], "--")) },
                { label: "分差", render: (row) => escapeHtml(formatNumber(num(row, ["promotion_score_margin"], 0), 2)) },
                { label: "候选执行分", render: (row) => `<span class="tone-${toneFromValue(num(row, ["promotion_candidate_ops_score"], 0))}">${escapeHtml(formatNumber(num(row, ["promotion_candidate_ops_score"], 0), 2))}</span>` },
                { label: "P2 天数", render: (row) => escapeHtml(formatNumber(num(row, ["promotion_candidate_p2_days"], 0), 0)) },
            ],
            (payload.governance?.promotion_history || []).slice().reverse(),
            "暂无主档挑战历史"
        );
        document.getElementById("opsAlertHistoryTable").innerHTML = tableHtml(
            [
                { label: "快照时间", render: (row) => escapeHtml(txt(row, ["generated_at"])) },
                { label: "Run", render: (row) => `<span class="mono">${escapeHtml(txt(row, ["latest_run_id"]))}</span>` },
                { label: "状态", render: (row) => `<span class="chip ${toneFromStatus(txt(row, ["latest_run_status"], ""))}">${escapeHtml(txt(row, ["latest_run_status"]))}</span>` },
                { label: "总告警", render: (row) => escapeHtml(formatNumber(num(row, ["total_alerts"], 0), 0)) },
                { label: "Critical", render: (row) => `<span class="tone-negative">${escapeHtml(formatNumber(num(row, ["critical"], 0), 0))}</span>` },
                { label: "Warning", render: (row) => `<span class="tone-warning">${escapeHtml(formatNumber(num(row, ["warning"], 0), 0))}</span>` },
                { label: "执行覆盖", render: (row) => escapeHtml(formatPercent(num(row, ["exec_coverage_pct"], 0), 1)) },
                { label: "前置匹配", render: (row) => escapeHtml(formatPercent(num(row, ["pretrade_match_rate_pct"], 0), 1)) },
            ],
            (payload.alert_history || []).slice().reverse(),
            "暂无告警历史快照"
        );
    }

    async function loadOpsPage() {
        setLoading("opsAlerts", "加载平台告警...");
        setLoading("promotionGatePanel", "加载档位晋升治理...");
        setLoading("promotionTrendChart", "加载主档挑战趋势...");
        setLoading("promotionHistoryTable", "加载主档挑战历史...");
        setLoading("opsAlertTrendChart", "加载告警趋势...");
        setLoading("opsAlertHistoryTable", "加载告警历史...");
        setLoading("consistencyPanel", "加载执行一致性摘要...");
        setLoading("alignmentPanel", "加载前置风控对齐摘要...");
        setLoading("exposureTable", "加载组合暴露摘要...");
        setLoading("experimentTable", "加载实验登记...");
        setLoading("capacityTable", "加载容量记录...");
        setLoading("industryExposureChart", "加载行业暴露...");
        setLoading("capacityChart", "加载容量压力...");
        const payload = await fetchJson("/api/platform/ops_overview");
        renderHero(payload);
        renderAlerts(payload);
        renderMetrics(payload);
        renderAlertTrend(payload);
        renderPromotionTrend(payload);
        renderIndustryChart(payload.risk?.industry_top || []);
        renderCapacityChart(payload.risk?.capacity_recent || []);
        renderPanels(payload);
        renderTables(payload);
    }

    function bind() {
        document.getElementById("reloadOps")?.addEventListener("click", async () => {
            try {
                await loadOpsPage();
            } catch (error) {
                ["opsAlerts", "promotionGatePanel", "promotionTrendChart", "promotionHistoryTable", "opsAlertTrendChart", "opsAlertHistoryTable", "consistencyPanel", "alignmentPanel", "exposureTable", "experimentTable", "capacityTable", "industryExposureChart", "capacityChart"].forEach((id) => setError(id, error));
            }
        });
    }

    async function bootstrap() {
        bind();
        try {
            await loadOpsPage();
        } catch (error) {
            ["opsAlerts", "promotionGatePanel", "promotionTrendChart", "promotionHistoryTable", "opsAlertTrendChart", "opsAlertHistoryTable", "consistencyPanel", "alignmentPanel", "exposureTable", "experimentTable", "capacityTable", "industryExposureChart", "capacityChart"].forEach((id) => setError(id, error));
        }
    }

    bootstrap();
})();
