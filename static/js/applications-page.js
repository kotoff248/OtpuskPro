document.addEventListener("DOMContentLoaded", function () {
    const line = document.getElementById("lineCustom");
    const buttons = Array.from(document.querySelectorAll("#applications-status-form button[name='status']"));
    const tableBody = document.getElementById("vacationsTableBody");
    const departmentSelect = document.getElementById("department");

    if (!line || !buttons.length || !tableBody || !departmentSelect) {
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
        if (departmentSelect.value !== "all") {
            url.searchParams.set("department", departmentSelect.value);
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
                tableBody.innerHTML = "";

                if (!data.vacations.length) {
                    renderEmptyState();
                    updateUrl(currentStatus, departmentSelect.value);
                    return;
                }

                data.vacations.forEach(function (vacation) {
                    const row = document.createElement("tr");
                    row.className = "vacation-row is-clickable";
                    row.dataset.href = "/applications/" + vacation.id + "/";
                    row.tabIndex = 0;
                    row.setAttribute("role", "link");
                    row.appendChild(createCell(vacation.employee_name));
                    row.appendChild(createCell(vacation.start_date_formatted));
                    row.appendChild(createCell(vacation.end_date_formatted));
                    row.appendChild(createCell(vacation.vacation_type_label));
                    row.appendChild(createStatusCell(vacation));
                    tableBody.appendChild(row);
                });

                updateUrl(currentStatus, departmentSelect.value);
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
            fetchApplications();
        });
    });

    departmentSelect.addEventListener("change", fetchApplications);
});
