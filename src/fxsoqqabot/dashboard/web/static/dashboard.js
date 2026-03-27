/**
 * FXSoqqaBot Web Dashboard - Vanilla JS
 *
 * WebSocket connection with auto-reconnect, chart rendering,
 * trade table population, kill/pause controls, and tab switching.
 */

(function () {
    "use strict";

    // ---- State ----
    var ws = null;
    var reconnectDelay = 1000;
    var maxReconnectDelay = 8000;
    var refreshTimer = null;
    var priceChart = null;
    var priceSeries = null;

    // ---- DOM References ----
    var statusDot = document.getElementById("status-dot");
    var statusText = document.getElementById("status-text");
    var errorBanner = document.getElementById("error-banner");

    // Summary bar
    var summaryRegime = document.getElementById("summary-regime");
    var summaryEquity = document.getElementById("summary-equity");
    var summaryPnl = document.getElementById("summary-pnl");
    var summaryWinrate = document.getElementById("summary-winrate");
    var summarySpread = document.getElementById("summary-spread");

    // Filters
    var filterStart = document.getElementById("filter-start");
    var filterEnd = document.getElementById("filter-end");
    var filterRegime = document.getElementById("filter-regime");
    var filterOutcome = document.getElementById("filter-outcome");
    var filterConfidence = document.getElementById("filter-confidence");
    var confidenceValue = document.getElementById("confidence-value");

    // ---- WebSocket Connection ----

    function connectWebSocket() {
        var protocol = location.protocol === "https:" ? "wss:" : "ws:";
        var url = protocol + "//" + location.host + "/ws/live";

        ws = new WebSocket(url);

        ws.onopen = function () {
            reconnectDelay = 1000;
            setConnected(true);
        };

        ws.onmessage = function (event) {
            try {
                var data = JSON.parse(event.data);
                updateSummaryBar(data);
            } catch (e) {
                console.error("Failed to parse WebSocket message:", e);
            }
        };

        ws.onclose = function () {
            setConnected(false);
            scheduleReconnect();
        };

        ws.onerror = function () {
            setConnected(false);
        };
    }

    function scheduleReconnect() {
        setTimeout(function () {
            connectWebSocket();
            reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
        }, reconnectDelay);
    }

    function setConnected(connected) {
        if (connected) {
            statusDot.classList.add("connected");
            statusText.textContent = "Live";
        } else {
            statusDot.classList.remove("connected");
            statusText.textContent = "Disconnected";
        }
    }

    // ---- Summary Bar Updates ----

    function updateSummaryBar(data) {
        // Regime badge
        var regime = data.regime || "ranging";
        var regimeDisplay = regime.toUpperCase().replace("_", " ");
        summaryRegime.innerHTML =
            '<span class="regime-badge ' + regime + '">' + regimeDisplay + "</span>";

        // Equity
        var equity = data.equity || 0;
        summaryEquity.textContent = "$" + equity.toFixed(2);

        // Today P&L
        var pnl = data.daily_pnl || 0;
        summaryPnl.textContent = (pnl >= 0 ? "+$" : "-$") + Math.abs(pnl).toFixed(2);
        summaryPnl.className = "summary-value mono " + (pnl >= 0 ? "positive" : "negative");

        // Win rate
        var winRate = data.daily_win_rate || 0;
        summaryWinrate.textContent = Math.round(winRate * 100) + "%";

        // Spread
        var spread = data.spread || 0;
        summarySpread.textContent = spread.toFixed(2);
    }

    // ---- Tab Switching ----

    function initTabs() {
        var tabBtns = document.querySelectorAll(".tab-btn");
        tabBtns.forEach(function (btn) {
            btn.addEventListener("click", function () {
                var tabId = btn.getAttribute("data-tab");
                switchTab(tabId);
            });
        });
    }

    function switchTab(tabId) {
        // Deactivate all tabs
        document.querySelectorAll(".tab-btn").forEach(function (b) {
            b.classList.remove("active");
        });
        document.querySelectorAll(".tab-content").forEach(function (c) {
            c.classList.remove("active");
        });

        // Activate selected
        var btn = document.querySelector('.tab-btn[data-tab="' + tabId + '"]');
        var content = document.getElementById("tab-" + tabId);
        if (btn) btn.classList.add("active");
        if (content) content.classList.add("active");

        // Trigger data load for newly visible tab
        if (tabId === "trades") {
            loadTrades();
        } else if (tabId === "evolution") {
            loadModuleWeights();
        }
    }

    // ---- Data Fetching ----

    function fetchJSON(url) {
        return fetch(url)
            .then(function (resp) {
                if (!resp.ok) throw new Error("HTTP " + resp.status);
                return resp.json();
            })
            .catch(function (err) {
                showError();
                throw err;
            });
    }

    function showError() {
        errorBanner.classList.add("visible");
        setTimeout(function () {
            errorBanner.classList.remove("visible");
        }, 5000);
    }

    // ---- Equity Chart ----

    function loadEquityChart() {
        if (typeof Plotly === "undefined") return;

        fetchJSON("/api/equity").then(function (resp) {
            var data = resp.data || [];
            if (data.length === 0) return;

            var indices = data.map(function (d) { return d.index; });
            var equities = data.map(function (d) { return d.equity; });

            var trace = {
                x: indices,
                y: equities,
                mode: "lines",
                name: "Equity",
                line: { color: "#22c55e", width: 2 },
            };

            var layout = {
                paper_bgcolor: "#0f1117",
                plot_bgcolor: "#1a1d27",
                font: { color: "#e1e4eb" },
                margin: { l: 50, r: 20, t: 10, b: 40 },
                yaxis: { title: "Equity ($)", gridcolor: "#252836" },
                xaxis: { gridcolor: "#252836" },
                showlegend: false,
            };

            Plotly.newPlot("equity-chart", [trace], layout, { responsive: true });
        }).catch(function () { /* handled by fetchJSON */ });
    }

    // ---- Price Chart (lightweight-charts) ----

    function initPriceChart() {
        if (typeof LightweightCharts === "undefined") {
            // Library not loaded -- show message (already visible in HTML)
            return;
        }

        var container = document.getElementById("price-chart");
        var emptyMsg = document.getElementById("price-chart-empty");
        if (emptyMsg) emptyMsg.style.display = "none";

        priceChart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 300,
            layout: {
                background: { color: "#1a1d27" },
                textColor: "#e1e4eb",
            },
            grid: {
                vertLines: { color: "#252836" },
                horzLines: { color: "#252836" },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
            },
        });

        priceSeries = priceChart.addCandlestickSeries({
            upColor: "#22c55e",
            downColor: "#ef4444",
            borderUpColor: "#22c55e",
            borderDownColor: "#ef4444",
            wickUpColor: "#22c55e",
            wickDownColor: "#ef4444",
        });

        // Resize handling
        window.addEventListener("resize", function () {
            if (priceChart) {
                priceChart.applyOptions({ width: container.clientWidth });
            }
        });
    }

    // ---- Regime Timeline ----

    function loadRegimeTimeline() {
        if (typeof Plotly === "undefined") return;

        fetchJSON("/api/regime-timeline").then(function (resp) {
            var data = resp.data || [];
            if (data.length === 0) return;

            var regimeColors = {
                trending_up: "#22c55e",
                trending_down: "#22c55e",
                ranging: "#eab308",
                high_chaos: "#ef4444",
                pre_bifurcation: "#ef4444",
            };

            var timestamps = data.map(function (d) { return d.timestamp; });
            var colors = data.map(function (d) {
                return regimeColors[d.regime] || "#8b8fa3";
            });
            var labels = data.map(function (d) { return d.regime; });

            var trace = {
                x: timestamps,
                y: data.map(function () { return 1; }),
                type: "bar",
                marker: { color: colors },
                text: labels,
                textposition: "inside",
                hovertemplate: "%{x}<br>%{text}<extra></extra>",
                showlegend: false,
            };

            var layout = {
                paper_bgcolor: "#0f1117",
                plot_bgcolor: "#1a1d27",
                font: { color: "#e1e4eb" },
                margin: { l: 20, r: 20, t: 10, b: 40 },
                yaxis: { visible: false },
                xaxis: { gridcolor: "#252836" },
                bargap: 0,
            };

            Plotly.newPlot("regime-chart", [trace], layout, { responsive: true });
        }).catch(function () { /* handled by fetchJSON */ });
    }

    // ---- Trade History ----

    function loadTrades() {
        var params = [];
        var regime = filterRegime.value;
        var outcome = filterOutcome.value;
        var start = filterStart.value;
        var end = filterEnd.value;
        var conf = parseInt(filterConfidence.value, 10);

        if (regime) params.push("regime=" + encodeURIComponent(regime));
        if (outcome) params.push("outcome=" + encodeURIComponent(outcome));
        if (start) params.push("start_date=" + encodeURIComponent(start));
        if (end) params.push("end_date=" + encodeURIComponent(end));
        if (conf > 0) params.push("min_confidence=" + (conf / 100).toFixed(2));

        var url = "/api/trades" + (params.length ? "?" + params.join("&") : "");

        fetchJSON(url).then(function (trades) {
            renderTradeTable(trades);
        }).catch(function () { /* handled by fetchJSON */ });
    }

    function renderTradeTable(trades) {
        var tbody = document.getElementById("trades-body");
        if (!trades || trades.length === 0) {
            tbody.innerHTML =
                '<tr><td colspan="9" class="empty-state">No trades match your filters.</td></tr>';
            return;
        }

        var html = "";
        trades.forEach(function (t) {
            var pnl = t.pnl || 0;
            var pnlClass = pnl >= 0 ? "positive" : "negative";
            var pnlStr = (pnl >= 0 ? "+" : "") + pnl.toFixed(2);
            var conf = t.fused_confidence || 0;

            html +=
                "<tr>" +
                "<td>" + (t.timestamp || "-") + "</td>" +
                "<td>" + (t.action || "-") + "</td>" +
                "<td>" + (t.lot_size || "-") + "</td>" +
                "<td>" + (t.entry_price || "-") + "</td>" +
                "<td>" + (t.exit_price || "-") + "</td>" +
                '<td class="' + pnlClass + '">' + pnlStr + "</td>" +
                "<td>" + (t.regime || "-") + "</td>" +
                "<td>" + Math.round(conf * 100) + "%</td>" +
                "<td>" + (t.variant_id || "live") + "</td>" +
                "</tr>";
        });
        tbody.innerHTML = html;
    }

    // ---- Filter Events ----

    function initFilters() {
        var controls = [filterStart, filterEnd, filterRegime, filterOutcome, filterConfidence];
        controls.forEach(function (ctrl) {
            if (ctrl) {
                ctrl.addEventListener("change", function () {
                    if (ctrl === filterConfidence) {
                        confidenceValue.textContent = ctrl.value + "%";
                    }
                    loadTrades();
                });
            }
        });
    }

    // ---- Module Performance ----

    function loadModuleWeights() {
        if (typeof Plotly === "undefined") return;

        fetchJSON("/api/module-weights").then(function (resp) {
            var data = resp.data || [];
            if (data.length === 0) {
                var el = document.getElementById("module-chart");
                if (el) el.innerHTML = '<div class="empty-state">No module weight data yet.</div>';
                return;
            }

            var timestamps = data.map(function (d) { return d.timestamp; });

            var traces = [
                {
                    x: timestamps,
                    y: data.map(function (d) { return d.chaos; }),
                    mode: "lines",
                    name: "Chaos",
                    line: { color: "#ef4444", width: 2 },
                },
                {
                    x: timestamps,
                    y: data.map(function (d) { return d.flow; }),
                    mode: "lines",
                    name: "Flow",
                    line: { color: "#3b82f6", width: 2 },
                },
                {
                    x: timestamps,
                    y: data.map(function (d) { return d.timing; }),
                    mode: "lines",
                    name: "Timing",
                    line: { color: "#22c55e", width: 2 },
                },
            ];

            var layout = {
                paper_bgcolor: "#0f1117",
                plot_bgcolor: "#1a1d27",
                font: { color: "#e1e4eb" },
                margin: { l: 50, r: 20, t: 10, b: 40 },
                yaxis: { title: "Weight", gridcolor: "#252836" },
                xaxis: { gridcolor: "#252836" },
                legend: { x: 0, y: 1.1, orientation: "h" },
            };

            Plotly.newPlot("module-chart", traces, layout, { responsive: true });
        }).catch(function () { /* handled by fetchJSON */ });
    }

    // ---- Kill Switch ----

    window.showKillModal = function () {
        document.getElementById("kill-modal").classList.add("active");
        document.getElementById("kill-api-key").value = "";
        document.getElementById("kill-api-key").focus();
    };

    window.hideKillModal = function () {
        document.getElementById("kill-modal").classList.remove("active");
    };

    window.confirmKill = function () {
        var apiKey = document.getElementById("kill-api-key").value;
        if (!apiKey) return;

        fetch("/api/kill?api_key=" + encodeURIComponent(apiKey), { method: "POST" })
            .then(function (resp) {
                if (!resp.ok) {
                    alert("Kill failed: Invalid API key or server error.");
                    return;
                }
                return resp.json();
            })
            .then(function (data) {
                if (data && data.status === "killed") {
                    hideKillModal();
                    alert("All positions killed. Trading halted.");
                }
            })
            .catch(function () {
                alert("Kill failed: Could not reach server.");
            });
    };

    // ---- Pause/Resume ----

    window.handlePause = function () {
        var apiKey = prompt("Enter API key to pause/resume trading:");
        if (!apiKey) return;

        fetch("/api/pause?api_key=" + encodeURIComponent(apiKey), { method: "POST" })
            .then(function (resp) {
                if (!resp.ok) {
                    alert("Invalid API key.");
                    return;
                }
                return resp.json();
            })
            .then(function (data) {
                if (data) {
                    var btn = document.getElementById("btn-pause");
                    if (data.status === "paused") {
                        btn.textContent = "Resume Trading";
                    } else {
                        btn.textContent = "Pause Trading";
                    }
                }
            })
            .catch(function () {
                alert("Failed to reach server.");
            });
    };

    // ---- Auto-Refresh ----

    function startAutoRefresh() {
        refreshTimer = setInterval(function () {
            loadEquityChart();
            loadRegimeTimeline();
        }, 30000); // Every 30 seconds
    }

    // ---- Initialization ----

    function init() {
        initTabs();
        initFilters();
        connectWebSocket();
        initPriceChart();
        loadEquityChart();
        loadRegimeTimeline();
        startAutoRefresh();
    }

    // Start when DOM is ready
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
