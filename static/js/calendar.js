(function () {
    "use strict";

    const Calendar = window.KabinetCalendar || {};
    window.KabinetCalendar = Calendar;

    function getCalendarMemoryContext() {
        const url = new URL(window.location.href);
        const isPlanningContext = url.searchParams.get("from") === "schedule_planning";
        return {
            isPlanningContext: isPlanningContext,
            calendarPathStorageKey: isPlanningContext ? "schedule-planning:calendar-path" : "calendar:path",
            calendarScrollStorageKey: isPlanningContext ? "planning-scroll:calendar-board-state" : "calendar:board-scroll-state",
            calendarUrlStorageKey: isPlanningContext ? "schedule-planning:calendar-last-url" : "calendar:last-url",
        };
    }

    function collectCalendarContext(filtersForm, signal) {
        const monthSelect = filtersForm.querySelector("select[name='month']");
        const balanceNode = document.getElementById("calendar-balance");
        const chargePreview = Calendar.readJsonScript("calendar-charge-preview", {});
        const vacationForm = document.getElementById("vacation-plan-form");
        const memoryContext = getCalendarMemoryContext();

        const context = {
            signal: signal,
            filtersForm: filtersForm,
            segmentedControl: filtersForm.querySelector(".calendar-segmented"),
            viewInputs: filtersForm.querySelectorAll("input[name='view']"),
            issueSegmentedControl: filtersForm.querySelector("[data-calendar-issue-segmented]"),
            issueInputs: filtersForm.querySelectorAll("input[name='issue']"),
            yearSelect: filtersForm.querySelector("select[name='year']"),
            monthSelect: monthSelect,
            departmentSelect: filtersForm.querySelector("select[name='department']"),
            searchWrapper: filtersForm.querySelector("[data-calendar-search]"),
            searchInput: filtersForm.querySelector("[data-calendar-search-input]"),
            searchToggle: filtersForm.querySelector("[data-calendar-search-toggle]"),
            searchClear: filtersForm.querySelector("[data-calendar-search-clear]"),
            monthFilter: monthSelect ? monthSelect.closest(".calendar-filter") : null,
            stepButtons: filtersForm.querySelectorAll("[data-step-control]"),
            customSelects: Array.from(document.querySelectorAll("[data-filter-select], [data-modal-select]")),
            resultsContainer: document.querySelector("[data-calendar-results]"),
            detailsDataNode: document.getElementById("calendar-details-data"),
            monthDetailsDataNode: document.getElementById("calendar-month-details-data"),
            isPlanningContext: memoryContext.isPlanningContext,
            calendarPathStorageKey: memoryContext.calendarPathStorageKey,
            calendarScrollStorageKey: memoryContext.calendarScrollStorageKey,
            calendarUrlStorageKey: memoryContext.calendarUrlStorageKey,
            calendarPath: window.location.pathname,
            rows: Array.from(document.querySelectorAll("[data-employee-id]")),
            detailsData: Calendar.readJsonScript("calendar-details-data", {}),
            monthDetailsData: Calendar.readJsonScript("calendar-month-details-data", {}),
            currentFiltersStateKey: null,

            detailModal: document.getElementById("calendar-detail-drawer"),
            detailName: document.getElementById("calendar-detail-name"),
            detailMeta: document.getElementById("calendar-detail-meta"),
            detailProfileLink: document.getElementById("calendar-detail-profile-link"),
            detailPosition: document.getElementById("calendar-detail-position"),
            detailDepartment: document.getElementById("calendar-detail-department"),
            detailGroup: document.getElementById("calendar-detail-group"),
            detailManagementBadges: document.getElementById("calendar-detail-management-badges"),
            detailIssue: document.getElementById("calendar-detail-issue"),
            detailIssueLabel: document.getElementById("calendar-detail-issue-label"),
            detailIssueDescription: document.getElementById("calendar-detail-issue-description"),
            detailIssueReasons: document.getElementById("calendar-detail-risk-reasons"),
            detailPeriod: document.getElementById("calendar-detail-period"),
            detailSchedule: document.getElementById("calendar-detail-schedule"),
            detailRequests: document.getElementById("calendar-detail-requests"),
            detailChanged: document.getElementById("calendar-detail-changed"),
            detailUpcoming: document.getElementById("calendar-detail-upcoming"),
            detailUpcomingStatus: document.getElementById("calendar-detail-upcoming-status"),
            detailUpcomingAction: document.getElementById("calendar-detail-upcoming-action"),
            detailContentGrid: document.getElementById("calendar-detail-content-grid"),
            primaryTitle: document.getElementById("calendar-primary-title"),
            primaryList: document.getElementById("calendar-primary-list"),
            secondarySection: document.getElementById("calendar-secondary-section"),
            secondaryTitle: document.getElementById("calendar-secondary-title"),
            secondaryList: document.getElementById("calendar-secondary-list"),
            selectedList: document.getElementById("calendar-selected-list"),
            yearList: document.getElementById("calendar-year-list"),
            monthSummaryModal: document.getElementById("calendar-month-summary-drawer"),
            monthSummaryTitle: document.getElementById("calendar-month-summary-title"),
            monthSummarySubtitle: document.getElementById("calendar-month-summary-subtitle"),
            monthSummaryEmployees: document.getElementById("calendar-month-summary-employees"),
            monthSummaryDaysTotal: document.getElementById("calendar-month-summary-days-total"),
            monthSummaryRisks: document.getElementById("calendar-month-summary-risks"),
            monthSummaryConflicts: document.getElementById("calendar-month-summary-conflicts"),
            monthSummaryDays: document.getElementById("calendar-month-summary-days"),
            monthSummaryIssuesSection: document.getElementById("calendar-month-summary-issues-section"),
            monthSummaryProblems: document.getElementById("calendar-month-summary-problems"),
            monthSummaryGroups: document.getElementById("calendar-month-summary-groups"),
            monthSummaryOpenAction: document.querySelector("[data-calendar-month-open]"),
            monthSummaryConflictsAction: document.querySelector("[data-calendar-month-conflicts]"),
            monthTotalButtons: Array.from(document.querySelectorAll("[data-calendar-month-summary-open]")),
            legend: document.querySelector("[data-calendar-legend]"),
            legendToggle: document.querySelector("[data-calendar-legend-toggle]"),
            legendPopover: document.querySelector("[data-calendar-legend-popover]"),

            modal: document.getElementById("vacation-modal"),
            vacationForm: vacationForm,
            transferModal: document.getElementById("schedule-transfer-modal"),
            transferForm: document.getElementById("schedule-transfer-form"),
            transferCurrentPeriod: document.getElementById("transfer-current-period"),
            startDateInput: document.getElementById("start_date"),
            endDateInput: document.getElementById("end_date"),
            submitButton: document.getElementById("submit-vacation-btn"),
            countDays: document.getElementById("count_days"),
            chargeableDaysNode: document.getElementById("chargeable_days"),
            availableOnStart: document.getElementById("available_on_start"),
            remainingBalance: document.getElementById("remaining_balance"),
            riskPreview: document.getElementById("vacation-risk-preview"),
            riskLabel: document.getElementById("vacation-risk-label"),
            riskReason: document.getElementById("vacation-risk-reason"),
            riskAction: document.getElementById("vacation-risk-action"),
            entitlementSourceLabel: document.getElementById("entitlement_source_label"),
            entitlementSourceList: document.getElementById("entitlement_source_list"),
            balanceNode: balanceNode,
            vacationTypeSelect: document.getElementById("type_vacation_select"),
            vacationFormHint: document.getElementById("vacation-form-hint"),
            chargePreviewNode: document.getElementById("calendar-charge-preview"),
            chargePreview: chargePreview,
            previewUrl: vacationForm ? vacationForm.dataset.previewUrl || "" : "",
            holidayDates: new Set(chargePreview.holiday_dates || []),
        };

        context.availableBalance = Calendar.parseNumber(
            balanceNode ? balanceNode.dataset.balance : undefined,
            Calendar.parseNumber(chargePreview.available_balance, 0)
        );

        return context;
    }

    function initCalendarPage() {
        const previousController = window.__calendarPageController;
        if (previousController) {
            previousController.abort();
        }

        const filtersForm = document.getElementById("calendar-filters-form");
        if (!filtersForm) {
            Calendar.setCalendarPageState(false);
            return;
        }

        Calendar.setCalendarPageState(true);

        const controller = new AbortController();
        const signal = controller.signal;
        window.__calendarPageController = controller;

        const context = collectCalendarContext(filtersForm, signal);
        let boardController = null;
        let formsController = null;

        const controlsController = Calendar.createControlsController(context, {
            requestCalendarResults: function () {
                if (boardController) {
                    boardController.requestCalendarResults();
                }
            },
            flushBoardScrollState: function () {
                if (boardController) {
                    boardController.flushBoardScrollState();
                }
            },
        });

        const drawerController = Calendar.createDrawerController(context, {
            closeCustomSelects: function () {
                controlsController.closeCustomSelects();
            },
            closeVacationModal: function () {
                if (formsController) {
                    formsController.closeVacationModal();
                }
            },
        });
        const monthSummaryController = Calendar.createMonthSummaryController(context);

        boardController = Calendar.createBoardController(context, {
            buildFiltersUrl: function () {
                return controlsController.buildFiltersUrl();
            },
            getFiltersStateKey: function () {
                return controlsController.getFiltersStateKey();
            },
            getCachedFiltersStateKey: function () {
                return controlsController.getCachedFiltersStateKey();
            },
            closeCustomSelects: function () {
                controlsController.closeCustomSelects();
            },
            closeCalendarDetailDrawer: function () {
                drawerController.closeCalendarDetailDrawer();
            },
            closeCalendarMonthSummaryDrawer: function () {
                monthSummaryController.closeMonthSummaryDrawer();
            },
            updateDetailsData: function (nextDetailsData) {
                drawerController.updateDetailsData(nextDetailsData);
            },
            updateMonthDetailsData: function (nextMonthDetailsData) {
                monthSummaryController.updateMonthDetailsData(nextMonthDetailsData);
            },
            bindRows: function () {
                drawerController.bindRows();
            },
            bindMonthTotals: function () {
                monthSummaryController.bindMonthTotals();
            },
            submitFilters: function () {
                controlsController.submitFilters();
            },
        });

        formsController = Calendar.createFormsController(context, {
            closeCustomSelects: function () {
                controlsController.closeCustomSelects();
            },
            closeDetailModal: function () {
                drawerController.closeDetailModal();
            },
            syncFormNavigationFields: function (form) {
                controlsController.syncFormNavigationFields(form);
            },
        });

        controlsController.init();
        formsController.init();
        boardController.init();
        monthSummaryController.bindMonthTotals();
        drawerController.restoreDetailDrawerFromUrl();
        drawerController.restoreEntryFocusFromUrl();
        monthSummaryController.restoreMonthSummaryFromUrl();

        document.addEventListener("app:section-sidebar-repeat", function (event) {
            if (!event.detail || event.detail.sectionKey !== "calendar") {
                return;
            }

            event.preventDefault();
            if (boardController) {
                boardController.scrollBoardToTop();
            }
        }, { signal: signal });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initCalendarPage, { once: true });
    } else {
        initCalendarPage();
    }

    document.addEventListener("app:navigation", initCalendarPage);
})();
