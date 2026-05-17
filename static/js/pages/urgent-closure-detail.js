(function () {
    "use strict";

    const formSelector = "[data-urgent-closure-employee-preview-form]";
    const invalidClass = "is-invalid";
    const validClass = "is-valid";
    const loadingClass = "is-loading";

    function parseNumber(value) {
        const parsed = Number(String(value || "0").replace(",", "."));
        return Number.isFinite(parsed) ? parsed : 0;
    }

    function formatDays(value) {
        const number = parseNumber(value);
        const formatted = Math.abs(number - Math.round(number)) < 0.001
            ? String(Math.round(number))
            : number.toLocaleString("ru-RU", { maximumFractionDigits: 2 });
        return formatted + " д.";
    }

    function setPanelState(panel, stateClass) {
        if (!panel) {
            return;
        }
        panel.classList.remove(invalidClass, validClass, loadingClass);
        if (stateClass) {
            panel.classList.add(stateClass);
        }
    }

    function initEmployeePreviewForm(form) {
        if (!form || form.dataset.urgentClosurePreviewReady === "true") {
            return;
        }
        form.dataset.urgentClosurePreviewReady = "true";

        const previewUrl = form.dataset.previewUrl || "";
        const requiredDays = parseNumber(form.dataset.requiredDays);
        const requiredDaysLabel = form.dataset.requiredDaysLabel || formatDays(requiredDays);
        const startInput = form.querySelector("[data-urgent-closure-preview-start]");
        const endInput = form.querySelector("[data-urgent-closure-preview-end]");
        const submitButton = form.querySelector("[data-urgent-closure-propose-submit]");
        const panel = form.querySelector("[data-urgent-closure-live-preview]");
        const statusNode = form.querySelector("[data-urgent-closure-days-status]");
        const messageNode = form.querySelector("[data-urgent-closure-preview-message]");
        const metricsNode = form.querySelector("[data-urgent-closure-preview-metrics]");
        const chargeableNode = form.querySelector("[data-urgent-closure-chargeable-days]");
        const scoreNode = form.querySelector("[data-urgent-closure-module-score]");
        const confidenceNode = form.querySelector("[data-urgent-closure-module-confidence]");
        let controller = null;
        let requestId = 0;
        let debounceTimer = 0;

        function setSubmitEnabled(enabled) {
            if (submitButton) {
                submitButton.disabled = !enabled;
            }
        }

        function setMessage(text) {
            if (messageNode) {
                messageNode.textContent = text || "";
            }
        }

        function setStatus(text) {
            if (statusNode) {
                statusNode.textContent = text || "";
            }
        }

        function hideMetrics() {
            if (metricsNode) {
                metricsNode.hidden = true;
            }
        }

        function showMetrics(payload) {
            if (metricsNode) {
                metricsNode.hidden = false;
            }
            if (chargeableNode) {
                chargeableNode.textContent = formatDays(payload.chargeable_days);
            }
            if (scoreNode) {
                scoreNode.textContent = payload.module_score_label || (payload.module_score ? `${payload.module_score}%` : "—");
            }
            if (confidenceNode) {
                confidenceNode.textContent = payload.module_confidence_label || (payload.module_confidence ? `${payload.module_confidence}%` : "—");
            }
        }

        function resetPreview() {
            if (controller) {
                controller.abort();
                controller = null;
            }
            requestId += 1;
            setPanelState(panel, "");
            setStatus("Нужно выбрать " + requiredDaysLabel);
            setMessage("Выберите даты, чтобы проверить количество дней и оценку модуля.");
            hideMetrics();
            setSubmitEnabled(false);
        }

        function updateFromPayload(payload) {
            const chargeableDays = parseNumber(payload.chargeable_days);
            const exactDays = Math.abs(chargeableDays - requiredDays) < 0.001;
            const canSubmit = Boolean(payload.can_submit) && exactDays;
            const message = payload.message || (
                canSubmit
                    ? "Период подходит для отправки руководителю."
                    : "Нужно выбрать ровно " + requiredDaysLabel + "."
            );

            showMetrics(payload);
            setStatus("Выбрано " + formatDays(chargeableDays) + " из " + requiredDaysLabel);
            setMessage(message);
            setPanelState(panel, canSubmit ? validClass : invalidClass);
            setSubmitEnabled(canSubmit);
        }

        function requestPreview() {
            const startDate = startInput ? startInput.value : "";
            const endDate = endInput ? endInput.value : "";
            if (!previewUrl || !startDate || !endDate) {
                resetPreview();
                return;
            }

            requestId += 1;
            const currentRequestId = requestId;
            if (controller) {
                controller.abort();
            }
            controller = new AbortController();

            setPanelState(panel, loadingClass);
            setStatus("Проверяю период...");
            setMessage("Считаю списываемые дни, риск и оценку модуля.");
            hideMetrics();
            setSubmitEnabled(false);

            const params = new URLSearchParams({
                start_date: startDate,
                end_date: endDate,
            });

            fetch(previewUrl + "?" + params.toString(), {
                method: "GET",
                credentials: "same-origin",
                headers: {
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                },
                signal: controller.signal,
            })
                .then(function (response) {
                    return response.json();
                })
                .then(function (payload) {
                    if (currentRequestId !== requestId) {
                        return;
                    }
                    updateFromPayload(payload || {});
                })
                .catch(function (error) {
                    if (error && error.name === "AbortError") {
                        return;
                    }
                    if (currentRequestId !== requestId) {
                        return;
                    }
                    setPanelState(panel, invalidClass);
                    setStatus("Не удалось проверить период");
                    setMessage("Попробуйте изменить даты или отправить форму позже.");
                    hideMetrics();
                    setSubmitEnabled(false);
                });
        }

        function schedulePreview() {
            if (debounceTimer) {
                window.clearTimeout(debounceTimer);
            }
            debounceTimer = window.setTimeout(requestPreview, 180);
        }

        [startInput, endInput].forEach(function (input) {
            if (input) {
                input.addEventListener("input", schedulePreview);
                input.addEventListener("change", schedulePreview);
            }
        });

        resetPreview();
    }

    function initUrgentClosureDetail() {
        document.querySelectorAll(formSelector).forEach(initEmployeePreviewForm);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initUrgentClosureDetail, { once: true });
    } else {
        initUrgentClosureDetail();
    }
    document.addEventListener("app:navigation", initUrgentClosureDetail);
})();
