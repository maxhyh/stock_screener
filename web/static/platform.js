window.QuantUI = (() => {
    function toNumber(value, fallback = 0) {
        const n = Number(value);
        return Number.isFinite(n) ? n : fallback;
    }

    function formatNumber(value, digits = 0) {
        if (value === null || value === undefined || value === "") {
            return "--";
        }
        const n = Number(value);
        if (!Number.isFinite(n)) {
            return "--";
        }
        return n.toLocaleString("zh-CN", {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        });
    }

    function formatPercent(value, digits = 1) {
        if (value === null || value === undefined || value === "") {
            return "--";
        }
        const n = Number(value);
        if (!Number.isFinite(n)) {
            return "--";
        }
        return `${formatNumber(n, digits)}%`;
    }

    function formatDateToken(value) {
        if (!value) {
            return "--";
        }
        const s = String(value).trim();
        if (/^\d{8}$/.test(s)) {
            return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
        }
        return s;
    }

    function escapeHtml(value) {
        return String(value ?? "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function pick(record, keys, fallback = "--") {
        for (const key of keys) {
            if (record && record[key] !== undefined && record[key] !== null && record[key] !== "") {
                return record[key];
            }
        }
        return fallback;
    }

    function toneFromValue(value, inverse = false) {
        const n = Number(value);
        if (!Number.isFinite(n)) {
            return "info";
        }
        if (n === 0) {
            return "info";
        }
        if (inverse) {
            return n > 0 ? "negative" : "positive";
        }
        return n > 0 ? "positive" : "negative";
    }

    function toneFromStatus(value) {
        const s = String(value || "").toLowerCase();
        if (!s) {
            return "info";
        }
        if (["healthy", "success", "passed", "normal", "filled"].some((item) => s.includes(item))) {
            return "positive";
        }
        if (["warning", "partial", "pending", "stale"].some((item) => s.includes(item))) {
            return "warning";
        }
        if (["failed", "error", "blocked", "rejected", "unhealthy"].some((item) => s.includes(item))) {
            return "negative";
        }
        return "accent";
    }

    function chip(label, tone = "info") {
        return `<span class="chip ${tone}">${escapeHtml(label)}</span>`;
    }

    function tableHtml(columns, rows, emptyText = "暂无数据") {
        if (!rows || rows.length === 0) {
            return `<div class="empty-state">${escapeHtml(emptyText)}</div>`;
        }
        const head = columns.map((col) => `<th>${escapeHtml(col.label)}</th>`).join("");
        const body = rows.map((row) => {
            const classes = row.__className ? ` class="${escapeHtml(row.__className)}"` : "";
            return `<tr${classes}>${columns.map((col) => `<td>${col.render(row)}</td>`).join("")}</tr>`;
        }).join("");
        return `<div class="table-wrap"><table class="data-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
    }

    async function fetchJson(url) {
        const response = await fetch(url);
        const payload = await response.json();
        if (!response.ok || payload.success === false) {
            throw new Error(payload.error || `请求失败: ${response.status}`);
        }
        return payload;
    }

    function setLoading(id, text = "加载中...") {
        const el = document.getElementById(id);
        if (el) {
            el.innerHTML = `<div class="loading-state">${escapeHtml(text)}</div>`;
        }
    }

    function setError(id, error) {
        const el = document.getElementById(id);
        if (el) {
            el.innerHTML = `<div class="error-state">${escapeHtml(error?.message || error || "加载失败")}</div>`;
        }
    }

    function initChart(id) {
        const node = document.getElementById(id);
        if (!node) {
            return null;
        }
        const chart = echarts.init(node);
        window.addEventListener("resize", () => chart.resize());
        return chart;
    }

    return {
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
        toNumber,
        toneFromStatus,
        toneFromValue,
    };
})();
