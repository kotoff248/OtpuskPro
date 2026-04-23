document.addEventListener("DOMContentLoaded", function () {
    const employeeSelects = Array.from(document.querySelectorAll("[data-employee-select]"));
    const employeeForms = Array.from(document.querySelectorAll("[data-employee-form]"));

    if (!employeeSelects.length && !employeeForms.length) {
        return;
    }

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
        selectWrapper.classList.toggle("is-disabled", nativeSelect.disabled);

        selectWrapper.querySelectorAll("[data-employee-select-option]").forEach(function (optionButton) {
            const isSelected = optionButton.dataset.value === nativeSelect.value;
            optionButton.classList.toggle("is-selected", isSelected);
            optionButton.setAttribute("aria-selected", isSelected ? "true" : "false");
        });
    }

    function formHasBlocker(form) {
        return Boolean(form.querySelector("[data-form-blocker]"));
    }

    function syncFormSubmitState(form) {
        if (!form) {
            return;
        }

        const submitButton = form.querySelector("[data-employee-submit]");
        if (!submitButton) {
            return;
        }

        submitButton.disabled = formHasBlocker(form) || !form.checkValidity();
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
            syncFormSubmitState(nativeSelect.closest("[data-employee-form]"));
        });
    });

    employeeForms.forEach(function (form) {
        ["input", "change"].forEach(function (eventName) {
            form.addEventListener(eventName, function () {
                syncFormSubmitState(form);
            });
        });

        syncFormSubmitState(form);
    });

    document.addEventListener("click", function (event) {
        if (!event.target.closest("[data-employee-select]")) {
            closeEmployeeSelects();
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            closeEmployeeSelects();
        }
    });
});
