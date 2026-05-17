(function () {
    "use strict";

    const MONTH_NAMES = [
        "Январь",
        "Февраль",
        "Март",
        "Апрель",
        "Май",
        "Июнь",
        "Июль",
        "Август",
        "Сентябрь",
        "Октябрь",
        "Ноябрь",
        "Декабрь",
    ];
    const WEEKDAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
    const DAY_MS = 24 * 60 * 60 * 1000;
    const PAIR_SCOPE_SELECTOR = [
        "[data-draft-period-row]",
        ".preferences-dates",
        ".calendar-modal__dates",
        ".schedule-transfer-form__dates",
        ".schedule-draft-placement-form__dates",
        ".schedule-draft-urgent-manual",
        ".urgent-closure-decision-form__dates",
    ].join(",");
    const DATA_ENDPOINT = "/calendar/date-picker-periods/";

    let popover = null;
    let activeInput = null;
    let activeField = null;
    let visibleDate = null;
    let activeOptions = {};
    let activeData = { holidayDates: new Set(), periods: [] };
    let dataCache = new Map();
    let requestToken = 0;
    let dataState = "idle";

    function pad(value) {
        return String(value).padStart(2, "0");
    }

    function parseIsoDate(value) {
        const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
        if (!match) {
            return null;
        }
        const year = Number(match[1]);
        const month = Number(match[2]) - 1;
        const day = Number(match[3]);
        const date = new Date(year, month, day);
        if (date.getFullYear() !== year || date.getMonth() !== month || date.getDate() !== day) {
            return null;
        }
        return date;
    }

    function formatIsoDate(date) {
        if (!(date instanceof Date)) {
            return "";
        }
        return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate());
    }

    function addDays(date, days) {
        return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
    }

    function compareIso(first, second) {
        return String(first || "").localeCompare(String(second || ""));
    }

    function formatReadableDate(isoDate) {
        const date = parseIsoDate(isoDate);
        if (!date) {
            return "";
        }
        return date.toLocaleDateString("ru-RU", {
            day: "numeric",
            month: "long",
            year: "numeric",
        });
    }

    function dispatchDateEvents(input) {
        if (!input) {
            return;
        }
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function syncInputState(input) {
        if (input && input.type === "date") {
            input.classList.toggle("is-empty", !input.value);
        }
    }

    function setInputValue(input, value, options) {
        if (!input || input.value === value) {
            syncInputState(input);
            return false;
        }
        input.value = value || "";
        syncInputState(input);
        if (options && options.dispatch) {
            dispatchDateEvents(input);
        }
        return true;
    }

    function inputKind(input) {
        if (!input) {
            return "";
        }
        if (input.hasAttribute("data-period-start") || input.hasAttribute("data-urgent-closure-preview-start")) {
            return "start";
        }
        if (input.hasAttribute("data-period-end") || input.hasAttribute("data-urgent-closure-preview-end")) {
            return "end";
        }
        const marker = [
            input.name,
            input.id,
            input.dataset.datePickerRole,
        ].filter(Boolean).join(" ").toLowerCase();
        if (marker.includes("start") || marker.includes("начал")) {
            return "start";
        }
        if (marker.includes("end") || marker.includes("оконч")) {
            return "end";
        }
        return "";
    }

    function pairScope(input) {
        return input.closest(PAIR_SCOPE_SELECTOR) || input.closest("form") || document;
    }

    function pairedInput(input, expectedKind) {
        const scope = pairScope(input);
        return Array.from(scope.querySelectorAll('input[type="date"]')).find(function (candidate) {
            return candidate !== input && inputKind(candidate) === expectedKind;
        }) || null;
    }

    function syncPairedEndDate(startInput, options) {
        if (inputKind(startInput) !== "start" || !startInput.value) {
            return;
        }
        const endInput = pairedInput(startInput, "end");
        if (!endInput || endInput.disabled || endInput.readOnly) {
            return;
        }
        if (!endInput.value || compareIso(endInput.value, startInput.value) < 0) {
            setInputValue(endInput, startInput.value, options);
        }
    }

    function dataFromAncestors(input, key) {
        let node = input;
        while (node && node.nodeType === 1) {
            if (node.dataset && node.dataset[key]) {
                return node.dataset[key];
            }
            node = node.parentElement;
        }
        return "";
    }

    function getOptions(input) {
        return {
            employeeId: dataFromAncestors(input, "datePickerEmployeeId"),
            year: dataFromAncestors(input, "datePickerYear"),
            excludeScheduleItem: dataFromAncestors(input, "datePickerExcludeScheduleItem"),
            url: dataFromAncestors(input, "datePickerUrl") || DATA_ENDPOINT,
        };
    }

    function getBoundary(input, name) {
        return parseIsoDate(input.getAttribute(name));
    }

    function initialVisibleDate(input) {
        const ownValue = parseIsoDate(input.value);
        if (ownValue) {
            return ownValue;
        }
        if (inputKind(input) === "end") {
            const startInput = pairedInput(input, "start");
            const startValue = parseIsoDate(startInput && startInput.value);
            if (startValue) {
                return startValue;
            }
        }
        const minValue = getBoundary(input, "min");
        if (minValue) {
            return minValue;
        }
        const configuredYear = Number(getOptions(input).year);
        if (Number.isFinite(configuredYear) && configuredYear >= 2000 && configuredYear <= 2100) {
            return new Date(configuredYear, 0, 1);
        }
        return new Date();
    }

    function inputFromTarget(target) {
        if (!(target instanceof Element)) {
            return null;
        }
        if (target.matches('[data-date-field] input[type="date"]')) {
            return target;
        }
        const field = target.closest("[data-date-field]");
        return field ? field.querySelector('input[type="date"]') : null;
    }

    function ensurePopover() {
        if (popover) {
            return popover;
        }
        popover = document.createElement("div");
        popover.className = "date-picker";
        popover.hidden = true;
        popover.setAttribute("role", "dialog");
        popover.setAttribute("aria-label", "Выбор даты");
        document.body.appendChild(popover);
        popover.addEventListener("click", handlePopoverClick);
        return popover;
    }

    function cacheKey(options, year) {
        return [
            options.employeeId || "",
            year,
            options.excludeScheduleItem || "",
            options.url || DATA_ENDPOINT,
        ].join("|");
    }

    function normalizePayload(payload) {
        return {
            holidayDates: new Set(Array.isArray(payload.holiday_dates) ? payload.holiday_dates : []),
            periods: Array.isArray(payload.periods) ? payload.periods : [],
        };
    }

    function loadDataForVisibleYear() {
        const picker = ensurePopover();
        const year = visibleDate.getFullYear();
        if (!activeOptions.employeeId) {
            activeData = { holidayDates: new Set(), periods: [] };
            dataState = "ready";
            render();
            return;
        }

        const key = cacheKey(activeOptions, year);
        if (dataCache.has(key)) {
            activeData = dataCache.get(key);
            dataState = "ready";
            render();
            return;
        }

        const token = requestToken + 1;
        requestToken = token;
        dataState = "loading";
        render();

        const url = new URL(activeOptions.url || DATA_ENDPOINT, window.location.origin);
        url.searchParams.set("employee_id", activeOptions.employeeId);
        url.searchParams.set("year", String(year));
        if (activeOptions.excludeScheduleItem) {
            url.searchParams.set("exclude_schedule_item", activeOptions.excludeScheduleItem);
        }

        fetch(url.toString(), {
            method: "GET",
            credentials: "same-origin",
            headers: {
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
        })
            .then(function (response) {
                return response.json().then(function (payload) {
                    if (!response.ok) {
                        throw new Error(payload && payload.message ? payload.message : "Не удалось загрузить занятые дни.");
                    }
                    return payload;
                });
            })
            .then(function (payload) {
                if (token !== requestToken) {
                    return;
                }
                activeData = normalizePayload(payload || {});
                dataCache.set(key, activeData);
                dataState = "ready";
                render();
            })
            .catch(function () {
                if (token !== requestToken) {
                    return;
                }
                activeData = { holidayDates: new Set(), periods: [] };
                dataState = "error";
                picker.dataset.state = "error";
                render();
            });
    }

    function isBusyDate(isoDate) {
        return activeData.periods.some(function (period) {
            return compareIso(period.start_date, isoDate) <= 0 && compareIso(period.end_date, isoDate) >= 0;
        });
    }

    function busyLabelsForDate(isoDate) {
        return activeData.periods
            .filter(function (period) {
                return compareIso(period.start_date, isoDate) <= 0 && compareIso(period.end_date, isoDate) >= 0;
            })
            .map(function (period) {
                return [period.status_label, period.label].filter(Boolean).join(": ");
            });
    }

    function selectedRange() {
        if (!activeInput) {
            return { start: "", end: "" };
        }
        const kind = inputKind(activeInput);
        if (kind === "start") {
            const endInput = pairedInput(activeInput, "end");
            return { start: activeInput.value, end: endInput ? endInput.value : activeInput.value };
        }
        if (kind === "end") {
            const startInput = pairedInput(activeInput, "start");
            return { start: startInput ? startInput.value : activeInput.value, end: activeInput.value };
        }
        return { start: activeInput.value, end: activeInput.value };
    }

    function dayAriaLabel(isoDate, isBusy, isHoliday) {
        const parts = [formatReadableDate(isoDate)];
        if (isBusy) {
            const labels = busyLabelsForDate(isoDate);
            parts.push(labels.length ? "уже есть отпуск: " + labels.join(", ") : "уже есть отпуск");
        }
        if (isHoliday) {
            parts.push("праздничный день");
        }
        return parts.filter(Boolean).join(", ");
    }

    function isOutsideBounds(input, isoDate) {
        const minDate = getBoundary(input, "min");
        const maxDate = getBoundary(input, "max");
        if (minDate && compareIso(isoDate, formatIsoDate(minDate)) < 0) {
            return true;
        }
        if (maxDate && compareIso(isoDate, formatIsoDate(maxDate)) > 0) {
            return true;
        }
        return false;
    }

    function createButton(className, icon, label) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = className;
        button.setAttribute("aria-label", label);
        const span = document.createElement("span");
        span.className = "material-icons-sharp";
        span.setAttribute("aria-hidden", "true");
        span.textContent = icon;
        button.appendChild(span);
        return button;
    }

    function render() {
        if (!popover || !activeInput || !visibleDate) {
            return;
        }

        const year = visibleDate.getFullYear();
        const month = visibleDate.getMonth();
        const range = selectedRange();
        const todayIso = formatIsoDate(new Date());
        const firstDay = new Date(year, month, 1);
        const leadingDays = (firstDay.getDay() + 6) % 7;
        const gridStart = addDays(firstDay, -leadingDays);

        popover.replaceChildren();
        popover.dataset.state = dataState;

        const header = document.createElement("div");
        header.className = "date-picker__header";
        const prev = createButton("date-picker__nav", "chevron_left", "Предыдущий месяц");
        prev.dataset.datePickerPrev = "true";
        const title = document.createElement("strong");
        title.className = "date-picker__title";
        title.textContent = MONTH_NAMES[month] + " " + year;
        const next = createButton("date-picker__nav", "chevron_right", "Следующий месяц");
        next.dataset.datePickerNext = "true";
        header.append(prev, title, next);

        const weekdays = document.createElement("div");
        weekdays.className = "date-picker__weekdays";
        WEEKDAY_NAMES.forEach(function (name) {
            const item = document.createElement("span");
            item.textContent = name;
            weekdays.appendChild(item);
        });

        const grid = document.createElement("div");
        grid.className = "date-picker__grid";
        for (let index = 0; index < 42; index += 1) {
            const currentDate = addDays(gridStart, index);
            const isoDate = formatIsoDate(currentDate);
            const isOutsideMonth = currentDate.getMonth() !== month;
            const isWeekend = currentDate.getDay() === 0 || currentDate.getDay() === 6;
            const isHoliday = activeData.holidayDates.has(isoDate);
            const isBusy = isBusyDate(isoDate);
            const isSelected = activeInput.value === isoDate;
            const hasRange = range.start && range.end && compareIso(range.end, range.start) >= 0;
            const isInRange = hasRange && compareIso(isoDate, range.start) >= 0 && compareIso(isoDate, range.end) <= 0;
            const isDisabled = isOutsideBounds(activeInput, isoDate);

            const day = document.createElement("button");
            day.type = "button";
            day.className = "date-picker__day";
            day.dataset.datePickerDay = isoDate;
            day.disabled = isDisabled;
            day.setAttribute("aria-label", dayAriaLabel(isoDate, isBusy, isHoliday));
            day.classList.toggle("is-outside", isOutsideMonth);
            day.classList.toggle("is-weekend", isWeekend);
            day.classList.toggle("is-holiday", isHoliday);
            day.classList.toggle("is-busy", isBusy);
            day.classList.toggle("is-today", isoDate === todayIso);
            day.classList.toggle("is-selected", isSelected);
            day.classList.toggle("is-in-range", Boolean(isInRange));
            day.classList.toggle("is-range-start", range.start === isoDate);
            day.classList.toggle("is-range-end", range.end === isoDate);

            const value = document.createElement("span");
            value.className = "date-picker__day-value";
            value.textContent = String(currentDate.getDate());
            day.appendChild(value);
            if (isBusy) {
                const marker = document.createElement("span");
                marker.className = "date-picker__day-marker";
                marker.setAttribute("aria-hidden", "true");
                day.appendChild(marker);
            }
            grid.appendChild(day);
        }

        const footer = document.createElement("div");
        footer.className = "date-picker__footer";
        const hint = document.createElement("span");
        if (dataState === "loading") {
            hint.textContent = "Загружаем занятые дни...";
        } else if (dataState === "error") {
            hint.textContent = "Занятые дни не загрузились.";
        } else if (activeOptions.employeeId) {
            hint.textContent = "Бирюзовая точка - уже есть отпуск.";
        } else {
            hint.textContent = "Выберите дату.";
        }
        footer.appendChild(hint);

        popover.append(header, weekdays, grid, footer);
        positionPopover();
    }

    function positionPopover() {
        if (!popover || popover.hidden || !activeField) {
            return;
        }
        const rect = activeField.getBoundingClientRect();
        const margin = 10;
        const width = Math.min(336, window.innerWidth - margin * 2);
        popover.style.width = width + "px";
        const height = popover.offsetHeight || 390;
        const topBelow = rect.bottom + 8;
        const topAbove = rect.top - height - 8;
        const top = topBelow + height + margin <= window.innerHeight ? topBelow : Math.max(margin, topAbove);
        const left = Math.min(
            Math.max(margin, rect.left),
            Math.max(margin, window.innerWidth - width - margin)
        );
        popover.style.top = top + "px";
        popover.style.left = left + "px";
    }

    function open(input) {
        if (!input || input.disabled || input.readOnly || input.type !== "date") {
            return;
        }
        const nextField = input.closest("[data-date-field]") || input;
        if (activeField && activeField !== nextField) {
            activeField.classList.remove("is-date-picker-open");
        }
        activeInput = input;
        activeField = nextField;
        activeOptions = getOptions(input);
        visibleDate = initialVisibleDate(input);
        visibleDate = new Date(visibleDate.getFullYear(), visibleDate.getMonth(), 1);
        ensurePopover();
        popover.hidden = false;
        popover.classList.add("is-open");
        activeField.classList.add("is-date-picker-open");
        loadDataForVisibleYear();
        window.requestAnimationFrame(positionPopover);
    }

    function close() {
        if (activeField) {
            activeField.classList.remove("is-date-picker-open");
        }
        activeField = null;
        activeInput = null;
        activeOptions = {};
        requestToken += 1;
        if (popover) {
            popover.classList.remove("is-open");
            popover.hidden = true;
        }
    }

    function shiftMonth(delta) {
        if (!visibleDate) {
            return;
        }
        const oldYear = visibleDate.getFullYear();
        visibleDate = new Date(visibleDate.getFullYear(), visibleDate.getMonth() + delta, 1);
        if (visibleDate.getFullYear() !== oldYear) {
            loadDataForVisibleYear();
        } else {
            render();
        }
    }

    function selectDate(isoDate) {
        if (!activeInput || !isoDate) {
            return;
        }
        setInputValue(activeInput, isoDate, { dispatch: false });
        if (inputKind(activeInput) === "start") {
            syncPairedEndDate(activeInput, { dispatch: false });
        }
        dispatchDateEvents(activeInput);
        const endInput = inputKind(activeInput) === "start" ? pairedInput(activeInput, "end") : null;
        if (endInput && endInput.value === isoDate) {
            dispatchDateEvents(endInput);
        }
        close();
    }

    function handlePopoverClick(event) {
        event.stopPropagation();
        const target = event.target instanceof Element ? event.target : null;
        if (!target) {
            return;
        }
        const prev = target.closest("[data-date-picker-prev]");
        if (prev) {
            event.preventDefault();
            shiftMonth(-1);
            return;
        }
        const next = target.closest("[data-date-picker-next]");
        if (next) {
            event.preventDefault();
            shiftMonth(1);
            return;
        }
        const day = target.closest("[data-date-picker-day]");
        if (day && !day.disabled) {
            event.preventDefault();
            selectDate(day.dataset.datePickerDay);
        }
    }

    function handleDocumentClick(event) {
        const target = event.target instanceof Element ? event.target : null;
        if (!target) {
            return;
        }
        if (popover && popover.contains(target)) {
            return;
        }
        const input = inputFromTarget(target);
        if (input) {
            open(input);
            return;
        }
        if (popover && !popover.hidden) {
            close();
        }
    }

    function handlePointerDown(event) {
        const target = event.target instanceof Element ? event.target : null;
        if (!target || (popover && popover.contains(target))) {
            return;
        }
        const input = inputFromTarget(target);
        if (!input || input.disabled || input.readOnly) {
            return;
        }
        event.preventDefault();
        input.focus({ preventScroll: true });
        open(input);
    }

    function handleFocusIn(event) {
        const input = inputFromTarget(event.target);
        if (input) {
            open(input);
        }
    }

    function handleKeydown(event) {
        const input = inputFromTarget(event.target);
        if (input && (event.key === "Enter" || event.key === " " || event.key === "ArrowDown")) {
            event.preventDefault();
            open(input);
            return;
        }
        if (event.key === "Escape" && popover && !popover.hidden) {
            close();
        }
    }

    function handleInputMutation(event) {
        const input = event.target instanceof HTMLInputElement ? event.target : null;
        if (!input || input.type !== "date") {
            return;
        }
        syncInputState(input);
        if (inputKind(input) === "start") {
            syncPairedEndDate(input, { dispatch: true });
        }
    }

    function init() {
        document.querySelectorAll('[data-date-field] input[type="date"]').forEach(syncInputState);
    }

    document.addEventListener("click", handleDocumentClick);
    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("focusin", handleFocusIn);
    document.addEventListener("keydown", handleKeydown);
    document.addEventListener("input", handleInputMutation);
    document.addEventListener("change", handleInputMutation);
    window.addEventListener("resize", positionPopover);
    window.addEventListener("scroll", positionPopover, true);
    document.addEventListener("DOMContentLoaded", init, { once: true });
    document.addEventListener("app:navigation", init);

    window.KabinetDatePicker = {
        init: init,
        open: open,
        close: close,
        syncInputState: syncInputState,
        clearCache: function () {
            dataCache = new Map();
        },
    };
})();
