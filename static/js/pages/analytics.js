(function () {
    function destroyCharts() {
        if (!Array.isArray(window.__analyticsCharts)) {
            return;
        }

        window.__analyticsCharts.forEach(function (chart) {
            if (chart && typeof chart.destroy === "function") {
                chart.destroy();
            }
        });
        window.__analyticsCharts = [];
    }

    function readPayload() {
        const payloadNode = document.getElementById("analytics-chart-payload");
        if (!payloadNode) {
            return null;
        }

        try {
            return JSON.parse(payloadNode.textContent || "{}");
        } catch (error) {
            return null;
        }
    }

    function getArray(source, fallbackLength) {
        if (Array.isArray(source)) {
            return source.map(function (value) {
                return Number(value) || 0;
            });
        }
        return Array.from({ length: fallbackLength }, function () {
            return 0;
        });
    }

    function buildChartOptions(title, stacked) {
        return {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                intersect: false,
                mode: "index"
            },
            plugins: {
                title: {
                    display: true,
                    text: title,
                    color: "rgba(255, 255, 255, 0.92)",
                    align: "start",
                    font: {
                        size: 14,
                        weight: "700",
                        family: "'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
                    },
                    padding: {
                        bottom: 16
                    }
                },
                legend: {
                    position: "bottom",
                    labels: {
                        color: "rgba(219, 228, 242, 0.78)",
                        boxWidth: 12,
                        boxHeight: 12,
                        usePointStyle: true,
                        font: {
                            size: 12,
                            weight: "700",
                            family: "'Inter', system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
                        }
                    }
                },
                tooltip: {
                    backgroundColor: "rgba(11, 14, 22, 0.94)",
                    titleColor: "#ffffff",
                    bodyColor: "rgba(219, 228, 242, 0.9)",
                    borderColor: "rgba(56, 200, 255, 0.24)",
                    borderWidth: 1,
                    displayColors: true,
                    callbacks: {
                        label: function (context) {
                            const suffix = context.dataset.analyticsSuffix || "";
                            return context.dataset.label + ": " + context.formattedValue + suffix;
                        }
                    }
                }
            },
            scales: {
                x: {
                    stacked: stacked,
                    grid: {
                        color: "rgba(255, 255, 255, 0.045)"
                    },
                    ticks: {
                        color: "rgba(219, 228, 242, 0.74)",
                        font: {
                            weight: "700"
                        }
                    }
                },
                y: {
                    stacked: stacked,
                    beginAtZero: true,
                    grid: {
                        color: "rgba(255, 255, 255, 0.075)"
                    },
                    ticks: {
                        precision: 0,
                        color: "rgba(219, 228, 242, 0.74)",
                        font: {
                            weight: "700"
                        }
                    }
                }
            }
        };
    }

    function createCharts(payload) {
        const sourceCanvas = document.getElementById("analytics-source-chart");
        const riskCanvas = document.getElementById("analytics-risk-chart");
        if (!sourceCanvas || !riskCanvas || typeof Chart === "undefined") {
            return;
        }

        const labels = Array.isArray(payload.labels) ? payload.labels : [];
        const sourceData = payload.sources || {};
        const riskData = payload.risks || {};
        const labelCount = labels.length || 12;

        const sourceChart = new Chart(sourceCanvas.getContext("2d"), {
            type: "bar",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: "Годовой график",
                        analyticsSuffix: " д.",
                        data: getArray(sourceData.schedule, labelCount),
                        backgroundColor: "rgba(56, 200, 255, 0.72)",
                        borderColor: "rgba(56, 200, 255, 0.96)",
                        borderWidth: 1,
                        borderRadius: 8,
                        borderSkipped: false
                    },
                    {
                        label: "Заявки",
                        analyticsSuffix: " д.",
                        data: getArray(sourceData.requests, labelCount),
                        backgroundColor: "rgba(165, 216, 125, 0.68)",
                        borderColor: "rgba(165, 216, 125, 0.95)",
                        borderWidth: 1,
                        borderRadius: 8,
                        borderSkipped: false
                    },
                    {
                        label: "Переносы",
                        analyticsSuffix: " д.",
                        data: getArray(sourceData.changes, labelCount),
                        backgroundColor: "rgba(154, 106, 250, 0.64)",
                        borderColor: "rgba(154, 106, 250, 0.9)",
                        borderWidth: 1,
                        borderRadius: 8,
                        borderSkipped: false
                    }
                ]
            },
            options: buildChartOptions("Дни отпусков по источникам", true)
        });

        const riskChart = new Chart(riskCanvas.getContext("2d"), {
            type: "bar",
            data: {
                labels: labels,
                datasets: [
                    {
                        label: "Средний риск",
                        data: getArray(riskData.medium, labelCount),
                        backgroundColor: "rgba(255, 191, 71, 0.58)",
                        borderColor: "rgba(255, 191, 71, 0.95)",
                        borderWidth: 1,
                        borderRadius: 8,
                        borderSkipped: false
                    },
                    {
                        label: "Высокий риск",
                        data: getArray(riskData.high, labelCount),
                        backgroundColor: "rgba(255, 79, 130, 0.58)",
                        borderColor: "rgba(255, 79, 130, 0.95)",
                        borderWidth: 1,
                        borderRadius: 8,
                        borderSkipped: false
                    },
                    {
                        label: "Конфликты",
                        data: getArray(riskData.conflicts, labelCount),
                        backgroundColor: "rgba(255, 255, 255, 0.2)",
                        borderColor: "rgba(255, 255, 255, 0.62)",
                        borderWidth: 1,
                        borderRadius: 8,
                        borderSkipped: false
                    }
                ]
            },
            options: buildChartOptions("Риски и конфликты по месяцам", true)
        });

        window.__analyticsCharts = [sourceChart, riskChart];
    }

    function bindFilters(controller) {
        const form = document.querySelector("[data-analytics-filters]");
        if (!form) {
            return;
        }

        form.querySelectorAll("select").forEach(function (select) {
            select.addEventListener("change", function () {
                const formData = new FormData(form);
                const params = new URLSearchParams();
                formData.forEach(function (value, key) {
                    if (value !== "" && value !== "all") {
                        params.set(key, value);
                    }
                });

                const targetUrl = form.action || window.location.pathname;
                const url = new URL(targetUrl, window.location.origin);
                url.search = params.toString();

                if (window.KabinetNavigation && window.KabinetNavigation.navigate(url.href)) {
                    return;
                }

                window.location.href = url.href;
            }, { signal: controller.signal });
        });
    }

    function initAnalyticsPage() {
        const existingController = window.__analyticsPageController;
        if (existingController) {
            existingController.abort();
        }

        destroyCharts();

        const page = document.querySelector("[data-analytics-page]");
        if (!page) {
            return;
        }

        const controller = new AbortController();
        window.__analyticsPageController = controller;
        bindFilters(controller);

        const payload = readPayload();
        if (!payload) {
            return;
        }

        createCharts(payload);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initAnalyticsPage, { once: true });
    } else {
        initAnalyticsPage();
    }

    document.addEventListener("app:navigation", initAnalyticsPage);
})();
