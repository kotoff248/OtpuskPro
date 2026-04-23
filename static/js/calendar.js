document.addEventListener("DOMContentLoaded", function () {
    const filtersForm = document.getElementById("calendar-filters-form");
    if (!filtersForm) {
        return;
    }

    const segmentedControl = filtersForm.querySelector(".calendar-segmented");
    const viewInputs = filtersForm.querySelectorAll("input[name='view']");
    const yearSelect = filtersForm.querySelector("select[name='year']");
    const monthSelect = filtersForm.querySelector("select[name='month']");
    const monthFilter = monthSelect.closest(".calendar-filter");
    const stepButtons = filtersForm.querySelectorAll("[data-step-control]");
    const customSelects = Array.from(document.querySelectorAll("[data-filter-select], [data-modal-select]"));
    const rows = document.querySelectorAll("[data-employee-id]");
    const detailsData = JSON.parse(document.getElementById("calendar-details-data").textContent || "{}");

    const detailModal = document.getElementById("calendar-detail-drawer");
    const detailName = document.getElementById("calendar-detail-name");
    const detailMeta = document.getElementById("calendar-detail-meta");
    const detailPeriod = document.getElementById("calendar-detail-period");
    const detailApproved = document.getElementById("calendar-detail-approved");
    const detailPending = document.getElementById("calendar-detail-pending");
    const detailRejected = document.getElementById("calendar-detail-rejected");
    const detailUpcoming = document.getElementById("calendar-detail-upcoming");
    const detailUpcomingStatus = document.getElementById("calendar-detail-upcoming-status");
    const selectedList = document.getElementById("calendar-selected-list");
    const yearList = document.getElementById("calendar-year-list");

    const modal = document.getElementById("vacation-modal");
    const startDateInput = document.getElementById("start_date");
    const endDateInput = document.getElementById("end_date");
    const submitButton = document.getElementById("submit-vacation-btn");
    const countDays = document.getElementById("count_days");
    const chargeableDaysNode = document.getElementById("chargeable_days");
    const remainingBalance = document.getElementById("remaining_balance");
    const balanceNode = document.getElementById("calendar-balance");
    const vacationTypeSelect = document.getElementById("type_vacation_select");
    const vacationFormHint = document.getElementById("vacation-form-hint");
    const chargePreviewNode = document.getElementById("calendar-charge-preview");
    const chargePreview = chargePreviewNode ? JSON.parse(chargePreviewNode.textContent || "{}") : {};
    const holidayDates = new Set(chargePreview.holiday_dates || []);

    function parseNumber(value, fallbackValue) {
        if (typeof value === "number" && Number.isFinite(value)) {
            return value;
        }

        if (typeof value === "string") {
            const normalizedValue = value.replace(/\s+/g, "").replace(",", ".");
            const parsedValue = Number(normalizedValue);
            if (Number.isFinite(parsedValue)) {
                return parsedValue;
            }
        }

        return fallbackValue;
    }

    const availableBalance = parseNumber(
        balanceNode ? balanceNode.dataset.balance : undefined,
        parseNumber(chargePreview.available_balance, 0)
    );

    function formatDays(value) {
        return value.toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1");
    }

    function submitFilters() {
        if (monthSelect.disabled) {
            monthSelect.disabled = false;
        }
        filtersForm.submit();
    }

    function syncViewSegmentedState() {
        const activeInput = filtersForm.querySelector("input[name='view']:checked");
        if (!activeInput) {
            return;
        }

        segmentedControl.dataset.activeView = activeInput.value;
        viewInputs.forEach(function (input) {
            const item = input.closest(".calendar-segmented__item");
            if (item) {
                item.classList.toggle("is-active", input.checked);
            }
        });
    }

    function closeCustomSelects(exceptSelect) {
        customSelects.forEach(function (selectWrapper) {
            if (exceptSelect && selectWrapper === exceptSelect) {
                return;
            }
            selectWrapper.classList.remove("is-open");
            const trigger = selectWrapper.querySelector("[data-select-trigger]");
            if (trigger) {
                trigger.setAttribute("aria-expanded", "false");
            }
        });
    }

    function syncCustomSelect(selectWrapper) {
        if (!selectWrapper) {
            return;
        }

        const nativeSelect = selectWrapper.querySelector("select");
        const trigger = selectWrapper.querySelector("[data-select-trigger]");
        const valueNode = selectWrapper.querySelector("[data-select-value]");
        const selectedOption = nativeSelect.options[nativeSelect.selectedIndex];

        if (valueNode && selectedOption) {
            valueNode.textContent = selectedOption.textContent;
        }

        if (trigger) {
            trigger.disabled = nativeSelect.disabled;
            trigger.setAttribute("aria-expanded", selectWrapper.classList.contains("is-open") ? "true" : "false");
        }

        selectWrapper.classList.toggle("is-disabled", nativeSelect.disabled);
        selectWrapper.querySelectorAll("[data-select-option]").forEach(function (optionButton) {
            const isSelected = optionButton.dataset.value === nativeSelect.value;
            optionButton.classList.toggle("is-selected", isSelected);
            optionButton.setAttribute("aria-selected", isSelected ? "true" : "false");
        });
    }

    function syncCustomSelectFromNative(selectElement) {
        syncCustomSelect(selectElement.closest("[data-filter-select], [data-modal-select]"));
    }

    function syncMonthFilterState() {
        const isMonthMode = filtersForm.querySelector("input[name='view']:checked").value === "month";
        monthSelect.disabled = !isMonthMode;
        monthFilter.classList.toggle("is-disabled", !isMonthMode);

        if (!isMonthMode) {
            closeCustomSelects();
        }

        stepButtons.forEach(function (button) {
            if (button.dataset.stepControl === "month") {
                button.disabled = !isMonthMode;
            }
        });
        syncCustomSelectFromNative(monthSelect);
    }

    function stepSelect(selectElement, direction) {
        const nextIndex = selectElement.selectedIndex + direction;
        if (nextIndex < 0 || nextIndex >= selectElement.options.length) {
            return;
        }

        selectElement.selectedIndex = nextIndex;
        syncCustomSelectFromNative(selectElement);
        submitFilters();
    }

    function stepMonth(direction) {
        const nextMonthIndex = monthSelect.selectedIndex + direction;

        if (nextMonthIndex >= 0 && nextMonthIndex < monthSelect.options.length) {
            monthSelect.selectedIndex = nextMonthIndex;
            syncCustomSelectFromNative(monthSelect);
            submitFilters();
            return;
        }

        const nextYearIndex = yearSelect.selectedIndex + direction;
        if (nextYearIndex < 0 || nextYearIndex >= yearSelect.options.length) {
            return;
        }

        yearSelect.selectedIndex = nextYearIndex;
        monthSelect.selectedIndex = direction > 0 ? 0 : monthSelect.options.length - 1;
        syncCustomSelectFromNative(yearSelect);
        syncCustomSelectFromNative(monthSelect);
        submitFilters();
    }

    function renderEntriesSafe(container, entries, emptyText) {
        container.innerHTML = "";
        if (!entries.length) {
            const placeholder = document.createElement("p");
            placeholder.className = "calendar-detail-placeholder";
            placeholder.textContent = emptyText;
            container.appendChild(placeholder);
            return;
        }

        entries.forEach(function (item) {
            const article = document.createElement("article");
            article.className = "calendar-drawer__entry status-" + item.status;

            const main = document.createElement("div");
            main.className = "calendar-drawer__entry-main";
            const strong = document.createElement("strong");
            strong.textContent = item.period_label;
            const type = document.createElement("span");
            type.textContent = item.vacation_type_label;
            main.appendChild(strong);
            main.appendChild(type);

            const side = document.createElement("div");
            side.className = "calendar-drawer__entry-side";
            const status = document.createElement("span");
            status.textContent = item.status_label;
            const days = document.createElement("strong");
            days.textContent = item.days + " д.";
            side.appendChild(status);
            side.appendChild(days);

            article.appendChild(main);
            article.appendChild(side);
            container.appendChild(article);
        });
    }

    function openDetailModal() {
        if (!detailModal) {
            return;
        }

        closeVacationModal();
        closeCustomSelects();
        window.appModal.open(detailModal);
    }

    function closeDetailModal() {
        if (!detailModal) {
            return;
        }

        window.appModal.close(detailModal);
    }

    function updateDetailCard(employeeId) {
        const detail = detailsData[String(employeeId)];
        if (!detail) {
            return;
        }

        rows.forEach(function (row) {
            row.classList.toggle("is-active", row.dataset.employeeId === String(employeeId));
        });

        detailName.textContent = detail.employee_name;
        detailMeta.textContent = detail.position + " • " + detail.department;
        detailPeriod.textContent = detail.selected_period_label;
        detailApproved.textContent = detail.selected_approved_days + " д.";
        detailPending.textContent = detail.selected_pending_days + " д.";
        detailRejected.textContent = detail.selected_rejected_days + " д.";
        detailUpcoming.textContent = detail.upcoming_label;
        detailUpcomingStatus.textContent = detail.upcoming_status || "";
        renderEntriesSafe(selectedList, detail.selected_entries || [], "В выбранном периоде отпусков нет.");
        renderEntriesSafe(yearList, detail.year_entries || [], "За этот год записей пока нет.");
        openDetailModal();
    }

    function closeVacationModal() {
        closeCustomSelects();
        if (!modal) {
            return;
        }

        window.appModal.close(modal);
    }

    function getDateRange(start, end) {
        const dates = [];
        const cursor = new Date(start.getTime());
        while (cursor <= end) {
            dates.push(new Date(cursor.getTime()));
            cursor.setDate(cursor.getDate() + 1);
        }
        return dates;
    }

    function toIsoDate(value) {
        const year = value.getFullYear();
        const month = String(value.getMonth() + 1).padStart(2, "0");
        const day = String(value.getDate()).padStart(2, "0");
        return year + "-" + month + "-" + day;
    }

    function calculateChargeableDays(start, end, vacationType) {
        if (vacationType !== "paid") {
            return 0;
        }

        return getDateRange(start, end).filter(function (currentDate) {
            return !holidayDates.has(toIsoDate(currentDate));
        }).length;
    }

    function updateVacationHint(message, isError) {
        if (!vacationFormHint) {
            return;
        }

        vacationFormHint.textContent = message || vacationFormHint.dataset.defaultHint || "";
        vacationFormHint.classList.toggle("is-error", Boolean(isError));
    }

    function calculateVacationForm() {
        if (!startDateInput || !endDateInput || !submitButton || !countDays || !remainingBalance || !chargeableDaysNode) {
            return;
        }

        const startValue = startDateInput.value;
        const endValue = endDateInput.value;
        const defaultHint = vacationFormHint ? vacationFormHint.dataset.defaultHint : "";

        if (!startValue || !endValue) {
            countDays.textContent = "0 д.";
            chargeableDaysNode.textContent = "0 д.";
            remainingBalance.textContent = formatDays(availableBalance) + " д.";
            updateVacationHint(defaultHint, false);
            submitButton.disabled = true;
            return;
        }

        const start = new Date(startValue + "T00:00:00");
        const end = new Date(endValue + "T00:00:00");
        if (end < start) {
            countDays.textContent = "0 д.";
            chargeableDaysNode.textContent = "0 д.";
            remainingBalance.textContent = formatDays(availableBalance) + " д.";
            updateVacationHint("Дата окончания не может быть раньше даты начала.", true);
            submitButton.disabled = true;
            return;
        }

        const vacationType = vacationTypeSelect ? vacationTypeSelect.value : "paid";
        const calendarDays = Math.floor((end - start) / (1000 * 60 * 60 * 24)) + 1;
        const chargeableDays = calculateChargeableDays(start, end, vacationType);
        const remaining = vacationType === "paid" ? availableBalance - chargeableDays : availableBalance;

        countDays.textContent = calendarDays + " д.";
        chargeableDaysNode.textContent = chargeableDays + " д.";
        remainingBalance.textContent = formatDays(remaining) + " д.";

        if (vacationType !== "paid") {
            updateVacationHint("Неоплачиваемый и учебный отпуск не уменьшают оплачиваемый баланс.", false);
            submitButton.disabled = false;
            return;
        }

        if (remaining < 0) {
            updateVacationHint("Недостаточно доступных дней для этой заявки.", true);
            submitButton.disabled = true;
            return;
        }

        if (chargeableDays === 0) {
            updateVacationHint("В выбранном периоде нет дней, которые спишутся с баланса.", true);
            submitButton.disabled = true;
            return;
        }

        updateVacationHint(defaultHint, false);
        submitButton.disabled = false;
    }

    customSelects.forEach(function (selectWrapper) {
        const trigger = selectWrapper.querySelector("[data-select-trigger]");
        const nativeSelect = selectWrapper.querySelector("select");

        syncCustomSelect(selectWrapper);

        trigger.addEventListener("click", function (event) {
            event.stopPropagation();
            if (trigger.disabled) {
                return;
            }

            const willOpen = !selectWrapper.classList.contains("is-open");
            closeCustomSelects(selectWrapper);
            selectWrapper.classList.toggle("is-open", willOpen);
            trigger.setAttribute("aria-expanded", willOpen ? "true" : "false");
        });

        selectWrapper.querySelectorAll("[data-select-option]").forEach(function (optionButton) {
            optionButton.addEventListener("click", function (event) {
                event.stopPropagation();
                nativeSelect.value = optionButton.dataset.value;
                syncCustomSelect(selectWrapper);
                closeCustomSelects();
                if (selectWrapper.hasAttribute("data-filter-select")) {
                    submitFilters();
                } else {
                    nativeSelect.dispatchEvent(new Event("change", { bubbles: true }));
                }
            });
        });
    });

    document.addEventListener("click", function (event) {
        if (!event.target.closest("[data-filter-select], [data-modal-select]")) {
            closeCustomSelects();
        }
    });

    syncViewSegmentedState();
    syncMonthFilterState();

    viewInputs.forEach(function (input) {
        input.addEventListener("change", function () {
            syncViewSegmentedState();
            syncMonthFilterState();
            window.setTimeout(submitFilters, 220);
        });
    });

    yearSelect.addEventListener("change", function () {
        syncCustomSelectFromNative(yearSelect);
        submitFilters();
    });

    monthSelect.addEventListener("change", function () {
        syncCustomSelectFromNative(monthSelect);
        submitFilters();
    });

    stepButtons.forEach(function (button) {
        button.addEventListener("click", function () {
            const direction = Number(button.dataset.direction || 0);
            if (!direction) {
                return;
            }

            closeCustomSelects();

            if (button.dataset.stepControl === "year") {
                stepSelect(yearSelect, direction);
                return;
            }

            if (!monthSelect.disabled) {
                stepMonth(direction);
            }
        });
    });

    rows.forEach(function (row) {
        row.addEventListener("click", function () {
            updateDetailCard(row.dataset.employeeId);
        });
    });

    if (modal) {
        modal.addEventListener("app-modal:open", function () {
            closeDetailModal();
            closeCustomSelects();
            calculateVacationForm();
        });
    }

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            closeCustomSelects();
        }
    });

    if (startDateInput) {
        startDateInput.addEventListener("change", calculateVacationForm);
    }
    if (endDateInput) {
        endDateInput.addEventListener("change", calculateVacationForm);
    }
    if (vacationTypeSelect) {
        vacationTypeSelect.addEventListener("change", calculateVacationForm);
    }
});
