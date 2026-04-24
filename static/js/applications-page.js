function initApplicationsPage() {
    const existingController = window.__applicationsPageController;
    if (existingController) {
        existingController.abort();
    }

    const controller = new AbortController();
    const signal = controller.signal;
    window.__applicationsPageController = controller;

    const line = document.getElementById("lineCustom");
    const buttons = Array.from(document.querySelectorAll("#applications-status-form button[name='status']"));
    const tableBody = document.getElementById("vacationsTableBody");
    const tableScrollShell = document.querySelector(".staff_table_custom");
    const departmentSelect = document.getElementById("department");
    const scrollStorageKey = "applications:list-scroll-state";

    if (!line || !buttons.length || !tableBody) {
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
        if (!tableScrollShell) {
            return;
        }

        const state = getCurrentListState();
        state.scrollTop = tableScrollShell.scrollTop;
        if (selectedVacationId) {
            state.selectedVacationId = selectedVacationId;
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
        if (!tableScrollShell) {
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
            tableScrollShell.scrollTop = Number(savedState.scrollTop) || 0;

            if (!savedState.selectedVacationId) {
                return;
            }

            const selectedRow = tableBody.querySelector('[data-vacation-id="' + savedState.selectedVacationId + '"]');
            if (!selectedRow) {
                return;
            }

            const shellBounds = tableScrollShell.getBoundingClientRect();
            const rowBounds = selectedRow.getBoundingClientRect();
            if (rowBounds.top < shellBounds.top || rowBounds.bottom > shellBounds.bottom) {
                selectedRow.scrollIntoView({ block: "center", behavior: "auto" });
            }
        });
    }

    function moveLine(button) {
        const navRect = line.parentElement.getBoundingClientRect();
        const buttonRect = button.getBoundingClientRect();
        line.style.transform = "translateX(" + (buttonRect.left - navRect.left) + "px)";
        line.style.width = buttonRect.width + "px";
    }

    function setActiveButton(value) {
        buttons.forEach(function (button) {
            const isActive = button.value === value;
            button.classList.toggle("active", isActive);
            if (isActive) {
                moveLine(button);
            }
        });
    }

    function createCell(text) {
        const cell = document.createElement("td");
        cell.textContent = text;
        return cell;
    }

    function createStatusCell(vacation) {
        const cell = document.createElement("td");
        cell.className = "status-cell";

        const badge = document.createElement("span");
        badge.className = vacation.status_css_class;

        const icon = document.createElement("span");
        icon.className = "material-icons-sharp";
        icon.textContent = vacation.status_icon;

        badge.appendChild(icon);
        badge.appendChild(document.createTextNode(" " + vacation.status_label));
        cell.appendChild(badge);
        return cell;
    }

    function renderEmptyState() {
        tableBody.innerHTML = "";
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 5;
        const empty = document.createElement("p");
        empty.className = "table-empty";
        empty.textContent = "По выбранным фильтрам заявок не найдено.";
        cell.appendChild(empty);
        row.appendChild(cell);
        tableBody.appendChild(row);
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

    function fetchApplications() {
        const url = new URL(window.location.href);
        url.searchParams.set("status", currentStatus);
        const selectedDepartment = getDepartmentValue();
        if (selectedDepartment !== "all") {
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
                tableBody.innerHTML = "";

                if (!data.vacations.length) {
                    renderEmptyState();
                    updateUrl(currentStatus, selectedDepartment);
                    if (tableScrollShell) {
                        tableScrollShell.scrollTop = 0;
                    }
                    clearScrollState();
                    return;
                }

                data.vacations.forEach(function (vacation) {
                    const row = document.createElement("tr");
                    row.className = "vacation-row is-clickable";
                    row.dataset.href = "/applications/" + vacation.id + "/";
                    row.dataset.vacationId = vacation.id;
                    row.tabIndex = 0;
                    row.setAttribute("role", "link");
                    row.appendChild(createCell(vacation.employee_name));
                    row.appendChild(createCell(vacation.start_date_formatted));
                    row.appendChild(createCell(vacation.end_date_formatted));
                    row.appendChild(createCell(vacation.vacation_type_label));
                    row.appendChild(createStatusCell(vacation));
                    tableBody.appendChild(row);
                });

                updateUrl(currentStatus, selectedDepartment);
                if (tableScrollShell) {
                    tableScrollShell.scrollTop = 0;
                }
                clearScrollState();
            })
            .catch(function (error) {
                console.error("Error fetching applications:", error);
            });
    }

    setActiveButton(currentStatus);

    buttons.forEach(function (button) {
        button.addEventListener("click", function () {
            currentStatus = button.value;
            setActiveButton(currentStatus);
            clearScrollState();
            fetchApplications();
        }, { signal: signal });
    });

    if (departmentSelect) {
        departmentSelect.addEventListener("change", function () {
            clearScrollState();
            fetchApplications();
        }, { signal: signal });
    }

    if (tableScrollShell) {
        tableScrollShell.addEventListener("scroll", function () {
            writeScrollState();
        }, { passive: true, signal: signal });
    }

    tableBody.addEventListener("click", function (event) {
        const row = event.target.closest("[data-vacation-id]");
        if (row && tableBody.contains(row)) {
            writeScrollState(row.dataset.vacationId);
        }
    }, { capture: true, signal: signal });

    tableBody.addEventListener("keydown", function (event) {
        if (event.key !== "Enter" && event.key !== " ") {
            return;
        }

        const row = event.target.closest("[data-vacation-id]");
        if (row && tableBody.contains(row)) {
            writeScrollState(row.dataset.vacationId);
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
