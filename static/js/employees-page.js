function initEmployeesPage() {
    const existingController = window.__employeesPageController;
    if (existingController) {
        existingController.abort();
    }

    const controller = new AbortController();
    const signal = controller.signal;
    window.__employeesPageController = controller;

    const buttons = Array.from(document.querySelectorAll("#employees-status-form button[name='status']"));
    const employeesList = document.getElementById("employees-table-body");
    const employeesScrollShell = document.querySelector(".employee-cards-shell");
    const departmentSelect = document.getElementById("department");
    const employeesCountNode = document.getElementById("employees-count");
    const canOpenProfiles = Boolean(document.querySelector(".employee-row-clickable"));
    const segmentedControl = document.getElementById("employees-status-form");
    const scrollStorageKey = "employees:list-scroll-state";

    if (!segmentedControl || !buttons.length || !employeesList) {
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

    function writeScrollState(selectedEmployeeId) {
        if (!employeesScrollShell) {
            return;
        }

        const state = getCurrentListState();
        state.scrollTop = employeesScrollShell.scrollTop;
        if (selectedEmployeeId) {
            state.selectedEmployeeId = selectedEmployeeId;
        }

        try {
            sessionStorage.setItem(scrollStorageKey, JSON.stringify(state));
        } catch (error) {
            return;
        }
    }

    function clearScrollState() {
        try {
            sessionStorage.removeItem(scrollStorageKey);
        } catch (error) {
            return;
        }
    }

    function restoreScrollState() {
        if (!employeesScrollShell) {
            return;
        }

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
            employeesScrollShell.scrollTop = Number(savedState.scrollTop) || 0;

            if (!savedState.selectedEmployeeId) {
                return;
            }

            const selectedCard = employeesList.querySelector('[data-employee-id="' + savedState.selectedEmployeeId + '"]');
            if (!selectedCard) {
                return;
            }

            const shellBounds = employeesScrollShell.getBoundingClientRect();
            const cardBounds = selectedCard.getBoundingClientRect();
            if (cardBounds.top < shellBounds.top || cardBounds.bottom > shellBounds.bottom) {
                selectedCard.scrollIntoView({ block: "center", behavior: "auto" });
            }
        });
    }

    function getStatusKey(statusValue) {
        if (statusValue === "True") {
            return "working";
        }
        if (statusValue === "False") {
            return "vacation";
        }
        return "all";
    }

    function syncActiveHoverState() {
        const activeButton = buttons.find(function (button) {
            return button.classList.contains("active");
        });

        if (!activeButton) {
            segmentedControl.classList.remove("is-active-hover");
            return;
        }

        const isHovered = activeButton.matches(":hover");
        segmentedControl.classList.toggle("is-active-hover", isHovered);
    }

    function setActiveButton(value) {
        segmentedControl.dataset.activeStatus = getStatusKey(value);
        buttons.forEach(function (button) {
            const isActive = button.value === value;
            button.classList.toggle("active", isActive);
        });
        syncActiveHoverState();
    }

    function renderEmptyState() {
        employeesList.innerHTML = "";
        const empty = document.createElement("div");
        empty.className = "employee-cards-empty";
        empty.innerHTML = '<p class="table-empty">Сотрудники по выбранным фильтрам не найдены.</p>';
        employeesList.appendChild(empty);
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

    function createCell(label, value, extraClass) {
        const cell = document.createElement("div");
        cell.className = "employee-card__cell" + (extraClass ? " " + extraClass : "");

        const labelNode = document.createElement("span");
        labelNode.className = "employee-card__label";
        labelNode.textContent = label;

        const valueNode = document.createElement("span");
        valueNode.className = "employee-card__value";
        valueNode.textContent = value;

        cell.appendChild(labelNode);
        cell.appendChild(valueNode);
        return cell;
    }

    function createEmployeeCard(employee) {
        const article = document.createElement("article");
        article.className = "employee-card";

        if (canOpenProfiles) {
            article.classList.add("employee-row", "employee-row-clickable", "is-clickable");
            article.dataset.href = employee.profile_url;
            article.dataset.employeeId = employee.id;
            article.tabIndex = 0;
            article.setAttribute("role", "link");
        }

        const primary = document.createElement("div");
        primary.className = "employee-card__primary";
        primary.innerHTML = '<span class="employee-card__label">Сотрудник</span>';

        const nameNode = document.createElement("strong");
        nameNode.className = "employee-card__value employee-card__value--name";
        nameNode.textContent = employee.name;
        primary.appendChild(nameNode);

        const meta = document.createElement("div");
        meta.className = "employee-card__meta";
        meta.appendChild(createCell("Должность", employee.position));
        meta.appendChild(createCell("Отдел", employee.department_name || "Не указан"));
        meta.appendChild(createCell("Дата начала работы", employee.date_joined));
        meta.appendChild(createCell("Доступно к заявке", employee.available_days + " д.", "employee-card__cell--available"));

        const status = document.createElement("div");
        status.className = "employee-card__status";
        status.innerHTML = '<span class="employee-card__label">Статус</span>';

        const badge = document.createElement("span");
        badge.className = "employee-status-badge " + (employee.is_working ? "employee-status-badge--working" : "employee-status-badge--vacation");
        badge.textContent = employee.status_label;
        status.appendChild(badge);

        article.appendChild(primary);
        article.appendChild(meta);
        article.appendChild(status);
        return article;
    }

    function fetchEmployees() {
        const departmentId = getDepartmentValue();
        const url = new URL(window.location.href);
        url.searchParams.set("status", currentStatus);

        if (departmentId && departmentId !== "all") {
            url.searchParams.set("department", departmentId);
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
                employeesList.innerHTML = "";

                if (!data.employees.length) {
                    renderEmptyState();
                    if (employeesCountNode) {
                        employeesCountNode.textContent = "0";
                    }
                    updateUrl(currentStatus, departmentId);
                    return;
                }

                data.employees.forEach(function (employee) {
                    employeesList.appendChild(createEmployeeCard(employee));
                });

                if (employeesCountNode) {
                    employeesCountNode.textContent = String(data.employees.length);
                }

                updateUrl(currentStatus, departmentId);
                if (employeesScrollShell) {
                    employeesScrollShell.scrollTop = 0;
                }
                clearScrollState();
            })
            .catch(function (error) {
                console.error("Error fetching employees:", error);
            });
    }

    setActiveButton(currentStatus);

    buttons.forEach(function (button) {
        button.addEventListener("mouseenter", function () {
            syncActiveHoverState();
        }, { signal: signal });

        button.addEventListener("mouseleave", function () {
            syncActiveHoverState();
        }, { signal: signal });

        button.addEventListener("focus", function () {
            syncActiveHoverState();
        }, { signal: signal });

        button.addEventListener("blur", function () {
            syncActiveHoverState();
        }, { signal: signal });

        button.addEventListener("click", function () {
            currentStatus = button.value;
            setActiveButton(currentStatus);
            clearScrollState();
            fetchEmployees();
        }, { signal: signal });
    });

    if (departmentSelect) {
        departmentSelect.addEventListener("change", function () {
            clearScrollState();
            fetchEmployees();
        }, { signal: signal });
    }

    if (employeesScrollShell) {
        employeesScrollShell.addEventListener("scroll", function () {
            writeScrollState();
        }, { passive: true, signal: signal });
    }

    employeesList.addEventListener("click", function (event) {
        const card = event.target.closest("[data-employee-id]");
        if (card && employeesList.contains(card)) {
            writeScrollState(card.dataset.employeeId);
        }
    }, { capture: true, signal: signal });

    employeesList.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") {
            return;
        }

        const card = event.target.closest("[data-employee-id]");
        if (card && employeesList.contains(card)) {
            writeScrollState(card.dataset.employeeId);
        }
    }, { capture: true, signal: signal });

    restoreScrollState();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initEmployeesPage, { once: true });
} else {
    initEmployeesPage();
}

document.addEventListener("app:navigation", initEmployeesPage);
