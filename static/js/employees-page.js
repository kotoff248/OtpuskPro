document.addEventListener("DOMContentLoaded", function () {
    const employeeSelects = Array.from(document.querySelectorAll("[data-employee-select]"));

    function closeEmployeeSelects(exceptSelect) {
        employeeSelects.forEach(function (selectWrapper) {
            if (exceptSelect && selectWrapper === exceptSelect) {
                return;
            }

            selectWrapper.classList.remove("is-open");
            const trigger = selectWrapper.querySelector("[data-employee-select-trigger]");
            if (trigger) {
                trigger.setAttribute("aria-expanded", "false");
            }
        });
    }

    function syncEmployeeSelect(selectWrapper) {
        if (!selectWrapper) {
            return;
        }

        const nativeSelect = selectWrapper.querySelector("select");
        const trigger = selectWrapper.querySelector("[data-employee-select-trigger]");
        const valueNode = selectWrapper.querySelector("[data-employee-select-value]");

        if (!nativeSelect || !trigger || !valueNode) {
            return;
        }

        const selectedOption = nativeSelect.options[nativeSelect.selectedIndex];
        if (selectedOption) {
            valueNode.textContent = selectedOption.textContent;
        }

        trigger.disabled = nativeSelect.disabled;
        trigger.setAttribute("aria-expanded", selectWrapper.classList.contains("is-open") ? "true" : "false");

        selectWrapper.querySelectorAll("[data-employee-select-option]").forEach(function (optionButton) {
            const isSelected = optionButton.dataset.value === nativeSelect.value;
            optionButton.classList.toggle("is-selected", isSelected);
            optionButton.setAttribute("aria-selected", isSelected ? "true" : "false");
        });
    }

    function syncCreateSubmitState() {
        const createForm = document.querySelector("[data-employee-create-form]");
        if (!createForm) {
            return;
        }

        const submitButton = createForm.querySelector("[data-employee-create-submit]");
        if (!submitButton) {
            return;
        }

        submitButton.disabled = !createForm.checkValidity();
    }

    employeeSelects.forEach(function (selectWrapper) {
        const trigger = selectWrapper.querySelector("[data-employee-select-trigger]");
        const nativeSelect = selectWrapper.querySelector("select");

        if (!trigger || !nativeSelect) {
            return;
        }

        syncEmployeeSelect(selectWrapper);

        trigger.addEventListener("click", function (event) {
            event.stopPropagation();
            if (trigger.disabled) {
                return;
            }

            const willOpen = !selectWrapper.classList.contains("is-open");
            closeEmployeeSelects(selectWrapper);
            selectWrapper.classList.toggle("is-open", willOpen);
            trigger.setAttribute("aria-expanded", willOpen ? "true" : "false");
        });

        selectWrapper.querySelectorAll("[data-employee-select-option]").forEach(function (optionButton) {
            optionButton.addEventListener("click", function (event) {
                event.stopPropagation();

                if (nativeSelect.value !== optionButton.dataset.value) {
                    nativeSelect.value = optionButton.dataset.value;
                    nativeSelect.dispatchEvent(new Event("change", { bubbles: true }));
                } else {
                    syncEmployeeSelect(selectWrapper);
                }

                closeEmployeeSelects();
            });
        });

        nativeSelect.addEventListener("change", function () {
            syncEmployeeSelect(selectWrapper);
            syncCreateSubmitState();
        });
    });

    document.addEventListener("click", function () {
        closeEmployeeSelects();
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            closeEmployeeSelects();
        }
    });

    const createForm = document.querySelector("[data-employee-create-form]");
    if (createForm) {
        ["input", "change"].forEach(function (eventName) {
            createForm.addEventListener(eventName, syncCreateSubmitState);
        });

        syncCreateSubmitState();
    }

    const line = document.getElementById("line");
    const buttons = Array.from(document.querySelectorAll("#employees-status-form button[name='status']"));
    const staffTableBody = document.getElementById("employees-table-body");
    const departmentSelect = document.getElementById("department");
    const employeesCountNode = document.getElementById("employees-count");
    const canOpenProfiles = Boolean(document.querySelector(".employee-row-clickable"));

    if (!line || !buttons.length || !staffTableBody) {
        return;
    }

    let currentStatus = (buttons.find(function (button) {
        return button.classList.contains("active");
    }) || buttons[0]).value;

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

    function renderEmptyState() {
        staffTableBody.innerHTML = "";
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 5;
        const empty = document.createElement("p");
        empty.className = "table-empty";
        empty.textContent = "Сотрудники по выбранным фильтрам не найдены.";
        cell.appendChild(empty);
        row.appendChild(cell);
        staffTableBody.appendChild(row);
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

    function fetchEmployees() {
        const departmentId = departmentSelect ? departmentSelect.value : "all";
        const url = new URL(window.location.href);
        url.searchParams.set("status", currentStatus);

        if (departmentId && departmentId !== "all") {
            url.searchParams.set("department", departmentId);
        } else {
            url.searchParams.delete("department");
        }

        fetch(url.toString(), {
            headers: {
                "X-Requested-With": "XMLHttpRequest"
            }
        })
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                staffTableBody.innerHTML = "";

                if (!data.employees.length) {
                    renderEmptyState();
                    if (employeesCountNode) {
                        employeesCountNode.textContent = "0";
                    }
                    updateUrl(currentStatus, departmentId);
                    return;
                }

                data.employees.forEach(function (employee) {
                    const row = document.createElement("tr");
                    if (canOpenProfiles) {
                        row.className = "employee-row employee-row-clickable is-clickable";
                        row.dataset.href = "/employee/" + employee.id + "/";
                        row.tabIndex = 0;
                        row.setAttribute("role", "link");
                    }

                    row.appendChild(createCell(employee.name));
                    row.appendChild(createCell(employee.position));
                    row.appendChild(createCell(employee.date_joined));
                    row.appendChild(createCell(employee.vacation_days));
                    row.appendChild(createCell(employee.is_working ? "Работает" : "В отпуске"));
                    staffTableBody.appendChild(row);
                });

                if (employeesCountNode) {
                    employeesCountNode.textContent = String(data.employees.length);
                }

                updateUrl(currentStatus, departmentId);
            })
            .catch(function (error) {
                console.error("Error fetching employees:", error);
            });
    }

    setActiveButton(currentStatus);

    window.addEventListener("resize", function () {
        const activeButton = buttons.find(function (button) {
            return button.classList.contains("active");
        });
        if (activeButton) {
            moveLine(activeButton);
        }
    });

    buttons.forEach(function (button) {
        button.addEventListener("click", function () {
            currentStatus = button.value;
            setActiveButton(currentStatus);
            fetchEmployees();
        });
    });

    if (departmentSelect) {
        departmentSelect.addEventListener("change", fetchEmployees);
    }
});
