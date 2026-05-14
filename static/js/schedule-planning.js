(function () {
    "use strict";

    const POLL_INTERVAL_MS = 1500;
    let pollTimer = null;

    function clearPollTimer() {
        if (pollTimer) {
            window.clearTimeout(pollTimer);
            pollTimer = null;
        }
    }

    function clampPercent(value) {
        const numericValue = Number(value);
        if (!Number.isFinite(numericValue)) {
            return 0;
        }
        return Math.max(0, Math.min(100, Math.round(numericValue)));
    }

    function setText(node, value) {
        if (node) {
            node.textContent = value === undefined || value === null || value === "" ? "—" : String(value);
        }
    }

    function updateJobClass(job, status) {
        job.classList.remove(
            "schedule-planning-auto-job--queued",
            "schedule-planning-auto-job--running",
            "schedule-planning-auto-job--succeeded",
            "schedule-planning-auto-job--failed",
        );
        job.classList.add("schedule-planning-auto-job--" + (status || "running"));
        job.dataset.status = status || "running";
    }

    function renderJob(job, payload) {
        const status = payload.status || "running";
        const percent = clampPercent(payload.progress_percent);
        updateJobClass(job, status);
        setText(job.querySelector("[data-planning-auto-job-stage]"), payload.stage_label || "Добрать незакрытые дни");
        setText(job.querySelector("[data-planning-auto-job-percent]"), percent + "%");
        setText(
            job.querySelector("[data-planning-auto-job-message]"),
            payload.error_message || payload.message || "Система добирает незакрытые дни и проверяет ограничения состава.",
        );
        setText(
            job.querySelector("[data-planning-auto-job-processed]"),
            (payload.processed_employees || 0) + " / " + (payload.total_employees || 0),
        );
        setText(job.querySelector("[data-planning-auto-job-placed]"), payload.placed_count || 0);
        setText(job.querySelector("[data-planning-auto-job-unresolved]"), payload.unresolved_count || 0);
        const bar = job.querySelector("[data-planning-auto-job-bar]");
        if (bar) {
            bar.style.width = percent + "%";
        }
    }

    function fetchStatus(statusUrl) {
        return fetch(statusUrl, {
            method: "GET",
            credentials: "same-origin",
            headers: {
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        }).then(function (response) {
            return response.json().then(function (payload) {
                if (!response.ok || payload.ok === false) {
                    throw new Error(payload.message || payload.error_message || "Не удалось получить статус добора.");
                }
                return payload;
            });
        });
    }

    function reloadPlanningPage() {
        window.setTimeout(function () {
            window.location.reload();
        }, 1200);
    }

    function schedulePoll(job, statusUrl, delayMs) {
        clearPollTimer();
        pollTimer = window.setTimeout(function () {
            fetchStatus(statusUrl)
                .then(function (payload) {
                    renderJob(job, payload);
                    if (payload.status === "succeeded") {
                        setText(job.querySelector("[data-planning-auto-job-message]"), "Готово. Обновляю показатели черновика.");
                        clearPollTimer();
                        reloadPlanningPage();
                        return;
                    }
                    if (payload.status === "failed") {
                        clearPollTimer();
                        return;
                    }
                    schedulePoll(job, statusUrl, POLL_INTERVAL_MS);
                })
                .catch(function (error) {
                    renderJob(job, {
                        status: "failed",
                        progress_percent: 0,
                        stage_label: "Ошибка статуса",
                        error_message: error.message || "Не удалось получить статус добора.",
                    });
                    clearPollTimer();
                });
        }, delayMs);
    }

    function initPlanningAutoJob() {
        const previousController = window.__schedulePlanningAutoJobController;
        if (previousController) {
            previousController.abort();
            window.__schedulePlanningAutoJobController = null;
        }
        clearPollTimer();

        const root = document.querySelector("[data-page='schedule-planning']");
        const job = root ? root.querySelector("[data-planning-auto-job]") : null;
        if (!job) {
            return;
        }

        const controller = new AbortController();
        window.__schedulePlanningAutoJobController = controller;
        controller.signal.addEventListener("abort", clearPollTimer, { once: true });

        const statusUrl = job.dataset.statusUrl || "";
        const status = job.dataset.status || "";
        if (!statusUrl || status === "failed") {
            return;
        }
        if (status === "succeeded") {
            reloadPlanningPage();
            return;
        }
        schedulePoll(job, statusUrl, 250);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initPlanningAutoJob, { once: true });
    } else {
        initPlanningAutoJob();
    }

    document.addEventListener("app:navigation", initPlanningAutoJob);
})();
