(function () {
    "use strict";

    const Calendar = window.KabinetCalendar || {};
    window.KabinetCalendar = Calendar;

    Calendar.createFormsController = function (context, dependencies) {
        const signal = context.signal;
        let previewRequestId = 0;
        let previewAbortController = null;
        let latestPreviewCanSubmit = false;

        function closeVacationModal() {
            dependencies.closeCustomSelects();
            if (!context.modal) {
                return;
            }
            if (!window.appModal || typeof window.appModal.close !== "function") {
                return;
            }

            window.appModal.close(context.modal);
        }

        function updateVacationHint(message, isError, isLoading) {
            if (!context.vacationFormHint) {
                return;
            }

            context.vacationFormHint.textContent = message || context.vacationFormHint.dataset.defaultHint || "";
            context.vacationFormHint.classList.toggle("is-error", Boolean(isError));
            context.vacationFormHint.classList.toggle("is-loading", Boolean(isLoading));
        }

        function formatDaysValue(value) {
            return Calendar.formatDays(Calendar.parseNumber(value, 0)) + " д.";
        }

        function syncDateInputState(input) {
            if (!input || input.type !== "date") {
                return;
            }

            input.classList.toggle("is-empty", !input.value);
        }

        function updateEntitlementSource(payload) {
            const label = payload && payload.entitlement_source_label
                ? payload.entitlement_source_label
                : "Выберите даты, чтобы определить рабочий год списания.";
            const allocations = payload && Array.isArray(payload.entitlement_allocations)
                ? payload.entitlement_allocations
                : [];

            if (context.entitlementSourceLabel) {
                context.entitlementSourceLabel.textContent = label;
            }
            if (!context.entitlementSourceList) {
                return;
            }

            context.entitlementSourceList.replaceChildren();
            if (!allocations.length) {
                context.entitlementSourceList.hidden = true;
                return;
            }

            allocations.forEach(function (allocation) {
                const item = document.createElement("li");
                const period = document.createElement("span");
                const days = document.createElement("strong");

                period.textContent = allocation.period_label || "";
                days.textContent = "Списывается: " + formatDaysValue(allocation.days);
                item.append(period, days);
                context.entitlementSourceList.appendChild(item);
            });
            context.entitlementSourceList.hidden = false;
        }

        function updateRiskPreview(payload) {
            const explanation = payload && payload.risk_explanation ? payload.risk_explanation : null;
            const level = explanation ? explanation.level : "low";
            const isConflict = explanation ? Boolean(explanation.is_conflict) : false;
            const label = payload && payload.risk_label ? payload.risk_label : "Низкий";
            const score = payload && payload.risk_score ? payload.risk_score : 0;

            if (context.riskPreview) {
                context.riskPreview.classList.toggle("calendar-modal__risk--medium", level === "medium");
                context.riskPreview.classList.toggle("calendar-modal__risk--high", level === "high" && !isConflict);
                context.riskPreview.classList.toggle("calendar-modal__risk--conflict", isConflict);
                context.riskPreview.dataset.scheduleStatusTooltip = "";
                context.riskPreview.dataset.scheduleStatusVariant = isConflict
                    ? "conflict"
                    : (level === "high" ? "risk" : (level === "medium" ? "medium" : "planned"));
                context.riskPreview.dataset.tooltipTitle = "Оценка риска";
                context.riskPreview.dataset.tooltipText = explanation
                    ? explanation.short_reason
                    : "Выберите даты, чтобы увидеть влияние заявки на состав, баланс и график.";
            }
            if (context.riskLabel) {
                context.riskLabel.textContent = label + " · " + score + "%";
            }
            if (context.riskReason) {
                context.riskReason.textContent = explanation
                    ? explanation.short_reason
                    : "Выберите даты, чтобы увидеть влияние на состав и график.";
            }
            if (context.riskAction) {
                context.riskAction.textContent = explanation
                    ? explanation.recommended_action
                    : "Период можно согласовывать по обычному маршруту.";
            }
        }

        function clearModuleAlternatives() {
            if (context.moduleAlternativesList) {
                context.moduleAlternativesList.replaceChildren();
            }
            if (context.moduleAlternatives) {
                context.moduleAlternatives.hidden = true;
            }
        }

        function renderModuleAlternatives(alternatives) {
            clearModuleAlternatives();
            if (!context.moduleAlternatives || !context.moduleAlternativesList || !alternatives || !alternatives.length) {
                return;
            }

            alternatives.forEach(function (alternative) {
                const button = document.createElement("button");
                const main = document.createElement("span");
                const period = document.createElement("strong");
                const days = document.createElement("small");
                const metrics = document.createElement("span");
                const score = document.createElement("strong");
                const risk = document.createElement("small");

                button.type = "button";
                button.className = "calendar-modal__alternative";
                button.dataset.vacationAlternative = "true";
                button.dataset.startDate = alternative.start_date || "";
                button.dataset.endDate = alternative.end_date || "";

                main.className = "calendar-modal__alternative-main";
                period.textContent = alternative.period_label || "Период";
                days.textContent = (alternative.calendar_days || 0) + " календ. д.";
                if (alternative.chargeable_days) {
                    days.textContent += " · списывается " + formatDaysValue(alternative.chargeable_days);
                }
                main.append(period, days);

                metrics.className = "calendar-modal__alternative-metrics";
                score.textContent = alternative.module_score_label || "0,00%";
                risk.textContent = (alternative.risk_label || "Низкий") + " · " + (alternative.risk_score || 0) + "%";
                metrics.append(score, risk);

                button.append(main, metrics);
                context.moduleAlternativesList.appendChild(button);
            });
            context.moduleAlternatives.hidden = false;
        }

        function updateModulePreview(payload) {
            const hasModule = Boolean(payload && payload.module_score_label);
            const recommendation = hasModule ? payload.module_recommendation || "" : "";
            const recommendationLabel = hasModule ? payload.module_recommendation_label || "Можно отправлять" : "Выберите даты";
            const scoreLabel = hasModule ? payload.module_score_label || "0,00%" : "";

            if (context.modulePreview) {
                context.modulePreview.classList.toggle("calendar-modal__module--prefer", recommendation === "prefer");
                context.modulePreview.classList.toggle("calendar-modal__module--normal", recommendation === "normal");
                context.modulePreview.classList.toggle("calendar-modal__module--avoid", recommendation === "avoid");
                context.modulePreview.classList.toggle("calendar-modal__module--blocked", recommendation === "blocked");
                context.modulePreview.dataset.scheduleStatusTooltip = "";
                context.modulePreview.dataset.scheduleStatusVariant = recommendation === "blocked" || recommendation === "avoid"
                    ? "risk"
                    : (recommendation === "prefer" ? "planned" : "info");
                context.modulePreview.dataset.tooltipTitle = "Оценка модуля";
                context.modulePreview.dataset.tooltipText = hasModule
                    ? payload.module_action || payload.module_explanation || ""
                    : "Выберите даты, чтобы получить подсказку нейромодуля.";
            }
            if (context.moduleLabel) {
                context.moduleLabel.textContent = hasModule
                    ? recommendationLabel + " · " + scoreLabel
                    : "Выберите даты";
            }
            if (context.moduleReason) {
                context.moduleReason.textContent = hasModule
                    ? payload.module_explanation || "Модуль оценил выбранный период."
                    : "Модуль оценит выбранный период после проверки заявки.";
            }
            if (context.moduleAction) {
                context.moduleAction.textContent = hasModule
                    ? payload.module_action || "Подсказка не заменяет жесткие правила отправки."
                    : "Подсказка не заменяет жесткие правила отправки.";
            }

            renderModuleAlternatives(hasModule ? payload.module_alternatives || [] : []);
        }

        function setSubmitState(canSubmit) {
            latestPreviewCanSubmit = Boolean(canSubmit);
            if (context.submitButton) {
                context.submitButton.disabled = !latestPreviewCanSubmit;
            }
        }

        function setPreviewValues(payload) {
            const vacationType = context.vacationTypeSelect ? context.vacationTypeSelect.value : "paid";

            if (context.countDays) {
                context.countDays.textContent = (payload.calendar_days || 0) + " д.";
            }
            if (context.chargeableDaysNode) {
                context.chargeableDaysNode.textContent = vacationType === "paid"
                    ? (payload.chargeable_days || 0) + " д."
                    : "Не списывается";
            }
            if (context.availableOnStart) {
                context.availableOnStart.textContent = formatDaysValue(payload.available_on_start);
            }
            if (context.remainingBalance) {
                context.remainingBalance.textContent = formatDaysValue(payload.remaining_after_request);
            }
            if (context.balanceNode && payload.balance_today !== undefined) {
                context.availableBalance = Calendar.parseNumber(payload.balance_today, context.availableBalance || 0);
                context.balanceNode.dataset.balance = String(context.availableBalance);
                context.balanceNode.textContent = formatDaysValue(context.availableBalance);
            }
            updateRiskPreview(payload);
            updateModulePreview(payload);
            updateEntitlementSource(payload);
        }

        function resetVacationPreview(message, isError) {
            if (
                !context.startDateInput ||
                !context.endDateInput ||
                !context.countDays ||
                !context.remainingBalance ||
                !context.chargeableDaysNode ||
                !context.availableOnStart
            ) {
                return;
            }

            const defaultHint = context.vacationFormHint ? context.vacationFormHint.dataset.defaultHint : "";

            context.countDays.textContent = "0 д.";
            context.chargeableDaysNode.textContent = "0 д.";
            context.availableOnStart.textContent = "0 д.";
            context.remainingBalance.textContent = formatDaysValue(context.availableBalance);
            updateRiskPreview(null);
            updateModulePreview(null);
            updateEntitlementSource(null);
            updateVacationHint(message || defaultHint, Boolean(isError), false);
            setSubmitState(false);
        }

        function calculateVacationForm() {
            if (!context.startDateInput || !context.endDateInput || !context.previewUrl) {
                resetVacationPreview("Не удалось найти адрес проверки заявки.", true);
                return;
            }

            const startValue = context.startDateInput.value;
            const endValue = context.endDateInput.value;

            if (!startValue || !endValue) {
                resetVacationPreview("", false);
                return;
            }

            const start = new Date(startValue + "T00:00:00");
            const end = new Date(endValue + "T00:00:00");
            if (end < start) {
                resetVacationPreview("Дата окончания не может быть раньше даты начала.", true);
                return;
            }

            const vacationType = context.vacationTypeSelect ? context.vacationTypeSelect.value : "paid";
            const requestId = previewRequestId + 1;
            previewRequestId = requestId;
            setSubmitState(false);
            updateVacationHint("Проверяем данные...", false, true);

            if (previewAbortController) {
                previewAbortController.abort();
            }
            previewAbortController = new AbortController();

            const params = new URLSearchParams({
                start_date: startValue,
                end_date: endValue,
                vacation_type: vacationType,
            });

            fetch(context.previewUrl + "?" + params.toString(), {
                credentials: "same-origin",
                headers: {
                    "X-Requested-With": "XMLHttpRequest",
                },
                signal: previewAbortController.signal,
            })
                .then(function (response) {
                    return response.json().catch(function () {
                        return {
                            can_submit: false,
                            message: "Не удалось прочитать ответ проверки заявки.",
                        };
                    }).then(function (payload) {
                        return { ok: response.ok, payload: payload };
                    });
                })
                .then(function (result) {
                    if (signal.aborted || requestId !== previewRequestId) {
                        return;
                    }

                    const payload = result.payload || {};
                    setPreviewValues(payload);
                    setSubmitState(result.ok && payload.can_submit);
                    updateVacationHint(
                        payload.message || "Проверка завершена.",
                        !(result.ok && payload.can_submit),
                        false
                    );
                })
                .catch(function (error) {
                    if (error && error.name === "AbortError") {
                        return;
                    }
                    if (signal.aborted || requestId !== previewRequestId) {
                        return;
                    }
                    resetVacationPreview("Не удалось проверить заявку. Попробуйте ещё раз.", true);
                });
        }

        function init() {
            if (context.modal) {
                context.modal.addEventListener("app-modal:open", function () {
                    dependencies.closeDetailModal();
                    dependencies.closeCustomSelects();
                    const vacationForm = context.vacationForm || document.getElementById("vacation-plan-form");
                    dependencies.syncFormNavigationFields(vacationForm);
                    calculateVacationForm();
                }, { signal: signal });
            }

            const vacationForm = context.vacationForm || document.getElementById("vacation-plan-form");
            if (vacationForm) {
                vacationForm.addEventListener("submit", function (event) {
                    if (!latestPreviewCanSubmit) {
                        event.preventDefault();
                        calculateVacationForm();
                        return;
                    }
                    dependencies.syncFormNavigationFields(vacationForm);
                }, { signal: signal });
            }
            if (context.transferForm) {
                context.transferForm.addEventListener("submit", function () {
                    dependencies.syncFormNavigationFields(context.transferForm);
                }, { signal: signal });
            }

            if (context.startDateInput) {
                context.startDateInput.addEventListener("change", calculateVacationForm, { signal: signal });
            }
            if (context.endDateInput) {
                context.endDateInput.addEventListener("change", calculateVacationForm, { signal: signal });
            }
            if (context.vacationTypeSelect) {
                context.vacationTypeSelect.addEventListener("change", calculateVacationForm, { signal: signal });
            }
            if (context.moduleAlternativesList) {
                context.moduleAlternativesList.addEventListener("click", function (event) {
                    const option = event.target.closest("[data-vacation-alternative]");
                    if (!option || !context.startDateInput || !context.endDateInput) {
                        return;
                    }

                    context.startDateInput.value = option.dataset.startDate || "";
                    context.endDateInput.value = option.dataset.endDate || "";
                    syncDateInputState(context.startDateInput);
                    syncDateInputState(context.endDateInput);
                    calculateVacationForm();
                }, { signal: signal });
            }
        }

        return {
            init: init,
            closeVacationModal: closeVacationModal,
        };
    };
})();
