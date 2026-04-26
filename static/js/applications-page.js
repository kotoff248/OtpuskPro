function initApplicationsPage() {
    const existingController = window.__applicationsPageController;
    if (existingController) {
        existingController.abort();
    }

    const root = document.querySelector("[data-applications-page]");
    if (!root) {
        return;
    }

    const controller = new AbortController();
    const signal = controller.signal;
    window.__applicationsPageController = controller;

    const statusForms = Array.from(root.querySelectorAll("[data-applications-status-form]"));
    const buttons = Array.from(root.querySelectorAll("[data-applications-status-form] button[name='status']"));
    const transferList = document.getElementById("changeRequestsCardsList");
    const requestList = document.getElementById("vacationsCardsList");
    const transferScrollShell = root.querySelector("[data-applications-transfer-scroll]");
    const requestScrollShell = root.querySelector("[data-applications-request-scroll]");
    const departmentSelect = document.getElementById("department");
    const scrollStorageKey = "applications:list-scroll-state";

    if (!statusForms.length || !buttons.length || !transferList || !requestList) {
        return;
    }

    let currentStatus = (buttons.find(function (button) {
        return button.classList.contains("active");
    }) || buttons[0]).value;

    function getDepartmentValue() {
        return departmentSelect ? departmentSelect.value : "all";
    }

    function getCurrentListState() {
        return {
            status: currentStatus,
            department: getDepartmentValue(),
        };
    }

    function readScrollState() {
        try {
            return JSON.parse(sessionStorage.getItem(scrollStorageKey) || "null");
        } catch (error) {
            return null;
        }
    }

    function writeScrollState(selectedVacationId) {
        const state = getCurrentListState();
        state.transferTop = transferScrollShell ? transferScrollShell.scrollTop : 0;
        state.requestTop = requestScrollShell ? requestScrollShell.scrollTop : 0;

        if (selectedVacationId) {
            state.selectedVacationId = selectedVacationId;
        }

        try {
            sessionStorage.setItem(scrollStorageKey, JSON.stringify(state));
        } catch (error) {
        }
    }

    function clearScrollState() {
        try {
            sessionStorage.removeItem(scrollStorageKey);
        } catch (error) {
        }
    }

    function restoreScrollState() {
        const savedState = readScrollState();
        const currentState = getCurrentListState();
        if (
            !savedState
            || savedState.status !== currentState.status
            || savedState.department !== currentState.department
        ) {
            return;
        }

        requestAnimationFrame(function () {
            if (transferScrollShell) {
                transferScrollShell.scrollTop = Number(savedState.transferTop) || 0;
            }

            if (requestScrollShell) {
                requestScrollShell.scrollTop = Number(savedState.requestTop) || 0;
            }

            if (!savedState.selectedVacationId || !requestScrollShell) {
                return;
            }

            const selectedCard = requestList.querySelector('[data-vacation-id="' + savedState.selectedVacationId + '"]');
            if (!selectedCard) {
                return;
            }

            const shellBounds = requestScrollShell.getBoundingClientRect();
            const cardBounds = selectedCard.getBoundingClientRect();
            if (cardBounds.top < shellBounds.top || cardBounds.bottom > shellBounds.bottom) {
                selectedCard.scrollIntoView({ block: "center", behavior: "auto" });
            }
        });
    }

    function syncHiddenDepartmentInputs() {
        statusForms.forEach(function (form) {
            let input = form.querySelector('input[name="department"]');
            const departmentValue = getDepartmentValue();

            if (!departmentValue || departmentValue === "all") {
                if (input) {
                    input.remove();
                }
                return;
            }

            if (!input) {
                input = document.createElement("input");
                input.type = "hidden";
                input.name = "department";
                form.appendChild(input);
            }
            input.value = departmentValue;
        });
    }

    function syncHeaderStatusInput() {
        const statusInput = document.querySelector('#applications-department-form input[name="status"]');
        if (statusInput) {
            statusInput.value = currentStatus;
        }
    }

    function syncActiveHoverState(form) {
        const activeButton = Array.from(form.querySelectorAll("button[name='status']")).find(function (button) {
            return button.classList.contains("active");
        });

        form.classList.toggle("is-active-hover", Boolean(activeButton && activeButton.matches(":hover")));
    }

    function setActiveButton(value) {
        statusForms.forEach(function (form) {
            form.dataset.activeStatus = value;
            form.querySelectorAll("button[name='status']").forEach(function (button) {
                button.classList.toggle("active", button.value === value);
            });
            syncActiveHoverState(form);
        });
        syncHiddenDepartmentInputs();
        syncHeaderStatusInput();
    }

    function createLabel(text) {
        const label = document.createElement("span");
        label.className = "application-card__label";
        label.textContent = text;
        return label;
    }

    function createValue(text, extraClass) {
        const value = document.createElement("span");
        value.className = "application-card__value" + (extraClass ? " " + extraClass : "");
        value.textContent = text || "Не указано";
        return value;
    }

    function createMuted(text) {
        const muted = document.createElement("span");
        muted.className = "application-card__muted";
        muted.textContent = text || "Не указан";
        return muted;
    }

    function createCell(labelText, valueText) {
        const cell = document.createElement("div");
        cell.className = "application-card__cell";
        cell.appendChild(createLabel(labelText));
        cell.appendChild(createValue(valueText));
        return cell;
    }

    function createPrimary(employeeName, departmentName) {
        const primary = document.createElement("div");
        primary.className = "application-card__primary";
        primary.appendChild(createLabel("Сотрудник"));

        const nameNode = document.createElement("strong");
        nameNode.className = "application-card__value application-card__value--name";
        nameNode.textContent = employeeName;
        primary.appendChild(nameNode);
        primary.appendChild(createMuted(departmentName));
        return primary;
    }

    function createStatusBadge(item) {
        const badge = document.createElement("span");
        badge.className = item.status_css_class || "";

        if (item.status_icon) {
            const icon = document.createElement("span");
            icon.className = "material-icons-sharp";
            icon.textContent = item.status_icon;
            badge.appendChild(icon);
            badge.appendChild(document.createTextNode(" "));
        }

        badge.appendChild(document.createTextNode(item.status_label || item.status || ""));
        return badge;
    }

    function createStatus(item) {
        const status = document.createElement("div");
        status.className = "application-card__status";
        status.appendChild(createLabel("Статус"));
        status.appendChild(createStatusBadge(item));
        return status;
    }

    function createEmptyState(text) {
        const empty = document.createElement("div");
        empty.className = "applications-cards-empty";

        const paragraph = document.createElement("p");
        paragraph.className = "table-empty";
        paragraph.textContent = text;
        empty.appendChild(paragraph);
        return empty;
    }

    function getCsrfToken() {
        const tokenInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (tokenInput) {
            return tokenInput.value;
        }

        const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function createTransferActions(changeRequest) {
        const actions = document.createElement("div");
        actions.className = "application-card__actions";

        if (!changeRequest.can_approve) {
            const muted = document.createElement("span");
            muted.className = "applications-transfer-muted";
            muted.textContent = "Нет действий";
            actions.appendChild(muted);
            return actions;
        }

        [
            ["approve_url", "Одобрить", "applications-transfer-action applications-transfer-action--approve"],
            ["reject_url", "Отклонить", "applications-transfer-action applications-transfer-action--reject"],
        ].forEach(function (config) {
            const form = document.createElement("form");
            form.method = "post";
            form.action = changeRequest[config[0]];

            const token = document.createElement("input");
            token.type = "hidden";
            token.name = "csrfmiddlewaretoken";
            token.value = getCsrfToken();

            const button = document.createElement("button");
            button.type = "submit";
            button.className = config[2];
            button.textContent = config[1];

            form.appendChild(token);
            form.appendChild(button);
            actions.appendChild(form);
        });

        return actions;
    }

    function formatRisk(item) {
        const score = Number(item.risk_score);
        if (Number.isNaN(score)) {
            return item.risk_label || "Не рассчитан";
        }
        return (item.risk_label || "Риск") + " · " + score + "%";
    }

    function createTransferCard(changeRequest) {
        const article = document.createElement("article");
        article.className = "application-card application-card--transfer";
        article.dataset.changeRequestId = changeRequest.id;

        const meta = document.createElement("div");
        meta.className = "application-card__meta application-card__meta--transfer";
        meta.appendChild(createCell("Старый период", changeRequest.old_period_label));
        meta.appendChild(createCell("Новый период", changeRequest.new_period_label));
        meta.appendChild(createCell("Риск", formatRisk(changeRequest)));

        article.appendChild(createPrimary(changeRequest.employee_name, changeRequest.employee_department));
        article.appendChild(meta);
        article.appendChild(createStatus(changeRequest));
        article.appendChild(createTransferActions(changeRequest));
        return article;
    }

    function createRequestCard(vacation) {
        const article = document.createElement("article");
        article.className = "application-card application-card--request is-clickable";
        article.dataset.href = vacation.detail_url;
        article.dataset.vacationId = vacation.id;
        article.tabIndex = 0;
        article.setAttribute("role", "link");

        const meta = document.createElement("div");
        meta.className = "application-card__meta";
        meta.appendChild(createCell("Период", vacation.period_label || (vacation.start_date_formatted + " - " + vacation.end_date_formatted)));
        meta.appendChild(createCell("Тип", vacation.vacation_type_label));
        meta.appendChild(createCell("Риск", formatRisk(vacation)));

        article.appendChild(createPrimary(vacation.employee_name, vacation.employee_department));
        article.appendChild(meta);
        article.appendChild(createStatus(vacation));
        return article;
    }

    function renderChangeRequests(changeRequests) {
        transferList.innerHTML = "";

        if (!changeRequests.length) {
            transferList.appendChild(createEmptyState("Переносы графика по выбранным фильтрам не найдены."));
            return;
        }

        changeRequests.forEach(function (changeRequest) {
            transferList.appendChild(createTransferCard(changeRequest));
        });
    }

    function renderVacationRequests(vacations) {
        requestList.innerHTML = "";

        if (!vacations.length) {
            requestList.appendChild(createEmptyState("Заявки по выбранным фильтрам не найдены."));
            return;
        }

        vacations.forEach(function (vacation) {
            requestList.appendChild(createRequestCard(vacation));
        });
    }

    function updateUrl(status, department) {
        const params = new URLSearchParams(window.location.search);
        params.set("status", status);
        if (department && department !== "all") {
            params.set("department", department);
        } else {
            params.delete("department");
        }

        const query = params.toString();
        window.history.replaceState({}, "", query ? window.location.pathname + "?" + query : window.location.pathname);
    }

    function resetListScroll() {
        if (transferScrollShell) {
            transferScrollShell.scrollTop = 0;
        }
        if (requestScrollShell) {
            requestScrollShell.scrollTop = 0;
        }
    }

    function fetchApplications() {
        const selectedDepartment = getDepartmentValue();
        const url = new URL(window.location.href);
        url.searchParams.set("status", currentStatus);

        if (selectedDepartment && selectedDepartment !== "all") {
            url.searchParams.set("department", selectedDepartment);
        } else {
            url.searchParams.delete("department");
        }

        fetch(url.toString(), {
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
        })
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                renderChangeRequests(data.change_requests || []);
                renderVacationRequests(data.vacations || []);
                updateUrl(currentStatus, selectedDepartment);
                resetListScroll();
                clearScrollState();
            })
            .catch(function (error) {
                console.error("Error fetching applications:", error);
            });
    }

    setActiveButton(currentStatus);

    buttons.forEach(function (button) {
        const form = button.closest("[data-applications-status-form]");

        button.addEventListener("mouseenter", function () {
            if (form) {
                syncActiveHoverState(form);
            }
        }, { signal: signal });

        button.addEventListener("mouseleave", function () {
            if (form) {
                syncActiveHoverState(form);
            }
        }, { signal: signal });

        button.addEventListener("focus", function () {
            if (form) {
                syncActiveHoverState(form);
            }
        }, { signal: signal });

        button.addEventListener("blur", function () {
            if (form) {
                syncActiveHoverState(form);
            }
        }, { signal: signal });

        button.addEventListener("click", function () {
            currentStatus = button.value;
            setActiveButton(currentStatus);
            clearScrollState();
            fetchApplications();
        }, { signal: signal });
    });

    if (departmentSelect) {
        departmentSelect.addEventListener("change", function () {
            syncHiddenDepartmentInputs();
            clearScrollState();
            fetchApplications();
        }, { signal: signal });
    }

    [transferScrollShell, requestScrollShell].forEach(function (scrollShell) {
        if (!scrollShell) {
            return;
        }
        scrollShell.addEventListener("scroll", function () {
            writeScrollState();
        }, { passive: true, signal: signal });
    });

    requestList.addEventListener("click", function (event) {
        const card = event.target.closest("[data-vacation-id]");
        if (card && requestList.contains(card)) {
            writeScrollState(card.dataset.vacationId);
        }
    }, { capture: true, signal: signal });

    requestList.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") {
            return;
        }

        const card = event.target.closest("[data-vacation-id]");
        if (card && requestList.contains(card)) {
            writeScrollState(card.dataset.vacationId);
        }
    }, { capture: true, signal: signal });

    restoreScrollState();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initApplicationsPage, { once: true });
} else {
    initApplicationsPage();
}

document.addEventListener("app:navigation", initApplicationsPage);
