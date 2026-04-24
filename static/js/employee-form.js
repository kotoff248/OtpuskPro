function initEmployeeFormPage() {
    const existingController = window.__employeeFormPageController;
    if (existingController) {
        existingController.abort();
    }

    document.querySelectorAll(".employee-select__menu--floating").forEach(function (menu) {
        menu.remove();
    });

    const controller = new AbortController();
    const signal = controller.signal;
    window.__employeeFormPageController = controller;

    const employeeSelects = Array.from(document.querySelectorAll("[data-employee-select]"));
    const employeeForms = Array.from(document.querySelectorAll("[data-employee-form]"));

    if (!employeeSelects.length && !employeeForms.length) {
        return;
    }

    function isModalSelect(selectWrapper) {
        return selectWrapper.classList.contains("employee-select--modal");
    }

    function isFloatingSelect(selectWrapper) {
        return isModalSelect(selectWrapper) || selectWrapper.classList.contains("employee-select--floating");
    }

    function getSelectParts(selectWrapper) {
        return {
            nativeSelect: selectWrapper.querySelector("select"),
            trigger: selectWrapper.querySelector("[data-employee-select-trigger]"),
            valueNode: selectWrapper.querySelector("[data-employee-select-value]"),
            menu: selectWrapper.__floatingMenu || selectWrapper.querySelector("[data-employee-select-menu]"),
        };
    }

    function restoreFloatingMenu(selectWrapper) {
        const parts = getSelectParts(selectWrapper);
        const menu = parts.menu;
        if (!menu || !menu.classList.contains("employee-select__menu--floating")) {
            return;
        }

        menu.classList.remove("employee-select__menu--floating", "is-open", "is-above");
        menu.style.top = "";
        menu.style.left = "";
        menu.style.width = "";
        menu.style.maxHeight = "";

        if (menu.__portalPlaceholder && menu.__portalPlaceholder.parentNode) {
            menu.__portalPlaceholder.parentNode.insertBefore(menu, menu.__portalPlaceholder);
            menu.__portalPlaceholder.remove();
            menu.__portalPlaceholder = null;
            selectWrapper.__floatingMenu = null;
            return;
        }

        selectWrapper.appendChild(menu);
        selectWrapper.__floatingMenu = null;
    }

    function closeEmployeeSelect(selectWrapper) {
        const parts = getSelectParts(selectWrapper);
        selectWrapper.classList.remove("is-open");

        if (parts.trigger) {
            parts.trigger.setAttribute("aria-expanded", "false");
        }

        if (isFloatingSelect(selectWrapper)) {
            restoreFloatingMenu(selectWrapper);
        }
    }

    function closeEmployeeSelects(exceptSelect) {
        employeeSelects.forEach(function (selectWrapper) {
            if (exceptSelect && selectWrapper === exceptSelect) {
                return;
            }

            closeEmployeeSelect(selectWrapper);
        });
    }

    function syncEmployeeSelect(selectWrapper) {
        if (!selectWrapper) {
            return;
        }

        const parts = getSelectParts(selectWrapper);
        if (!parts.nativeSelect || !parts.trigger || !parts.valueNode) {
            return;
        }

        const selectedOption = parts.nativeSelect.options[parts.nativeSelect.selectedIndex];
        if (selectedOption) {
            parts.valueNode.textContent = selectedOption.textContent;
        }

        parts.trigger.disabled = parts.nativeSelect.disabled;
        parts.trigger.setAttribute("aria-expanded", selectWrapper.classList.contains("is-open") ? "true" : "false");
        selectWrapper.classList.toggle("is-disabled", parts.nativeSelect.disabled);

        if (parts.menu) {
            parts.menu.querySelectorAll("[data-employee-select-option]").forEach(function (optionButton) {
                const isSelected = optionButton.dataset.value === parts.nativeSelect.value;
                optionButton.classList.toggle("is-selected", isSelected);
                optionButton.setAttribute("aria-selected", isSelected ? "true" : "false");
            });
        }
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

    function positionFloatingMenu(selectWrapper) {
        const parts = getSelectParts(selectWrapper);
        if (!parts.trigger || !parts.menu || !parts.menu.classList.contains("employee-select__menu--floating")) {
            return;
        }

        const viewportGap = 12;
        const triggerRect = parts.trigger.getBoundingClientRect();
        const maxPreferredHeight = 240;

        parts.menu.style.width = Math.round(triggerRect.width) + "px";
        parts.menu.style.left = Math.max(viewportGap, Math.round(triggerRect.left)) + "px";
        parts.menu.style.top = "0px";
        parts.menu.style.maxHeight = maxPreferredHeight + "px";

        const naturalHeight = Math.min(parts.menu.scrollHeight, maxPreferredHeight);
        const spaceBelow = window.innerHeight - triggerRect.bottom - viewportGap;
        const spaceAbove = triggerRect.top - viewportGap;
        const shouldOpenAbove = spaceBelow < naturalHeight && spaceAbove > spaceBelow;
        const availableSpace = shouldOpenAbove ? spaceAbove : spaceBelow;
        const finalMaxHeight = Math.max(120, Math.min(maxPreferredHeight, availableSpace));
        const top = shouldOpenAbove
            ? Math.max(viewportGap, Math.round(triggerRect.top - finalMaxHeight - 8))
            : Math.round(triggerRect.bottom + 8);

        parts.menu.classList.toggle("is-above", shouldOpenAbove);
        parts.menu.style.top = top + "px";
        parts.menu.style.maxHeight = finalMaxHeight + "px";
    }

    function openEmployeeSelect(selectWrapper) {
        const parts = getSelectParts(selectWrapper);
        if (!parts.trigger || !parts.menu) {
            return;
        }

        closeEmployeeSelects(selectWrapper);
        selectWrapper.classList.add("is-open");
        parts.trigger.setAttribute("aria-expanded", "true");

        if (isFloatingSelect(selectWrapper) && !parts.menu.classList.contains("employee-select__menu--floating")) {
            const placeholder = document.createComment("employee-select-menu-anchor");
            parts.menu.__portalPlaceholder = placeholder;
            parts.menu.parentNode.insertBefore(placeholder, parts.menu);
            document.body.appendChild(parts.menu);
            parts.menu.classList.add("employee-select__menu--floating");
            selectWrapper.__floatingMenu = parts.menu;
        }

        if (isFloatingSelect(selectWrapper)) {
            parts.menu.classList.add("is-open");
            positionFloatingMenu(selectWrapper);
        }
    }

    function repositionOpenSelects() {
        employeeSelects.forEach(function (selectWrapper) {
            if (selectWrapper.classList.contains("is-open") && isFloatingSelect(selectWrapper)) {
                positionFloatingMenu(selectWrapper);
            }
        });
    }

    employeeSelects.forEach(function (selectWrapper) {
        const parts = getSelectParts(selectWrapper);
        if (!parts.trigger || !parts.nativeSelect || !parts.menu) {
            return;
        }

        syncEmployeeSelect(selectWrapper);

        parts.trigger.addEventListener("click", function (event) {
            event.stopPropagation();
            if (parts.trigger.disabled) {
                return;
            }

            if (selectWrapper.classList.contains("is-open")) {
                closeEmployeeSelect(selectWrapper);
                return;
            }

            openEmployeeSelect(selectWrapper);
        }, { signal: signal });

        parts.menu.querySelectorAll("[data-employee-select-option]").forEach(function (optionButton) {
            optionButton.addEventListener("click", function (event) {
                event.stopPropagation();

                if (parts.nativeSelect.value !== optionButton.dataset.value) {
                    parts.nativeSelect.value = optionButton.dataset.value;
                    parts.nativeSelect.dispatchEvent(new Event("change", { bubbles: true }));
                } else {
                    syncEmployeeSelect(selectWrapper);
                }

                closeEmployeeSelect(selectWrapper);
            }, { signal: signal });
        });

        parts.nativeSelect.addEventListener("change", function () {
            syncEmployeeSelect(selectWrapper);
            syncFormSubmitState(parts.nativeSelect.closest("[data-employee-form]"));
        }, { signal: signal });
    });

    employeeForms.forEach(function (form) {
        ["input", "change"].forEach(function (eventName) {
            form.addEventListener(eventName, function () {
                syncFormSubmitState(form);
            }, { signal: signal });
        });

        syncFormSubmitState(form);
    });

    document.addEventListener("click", function (event) {
        if (!event.target.closest("[data-employee-select]") && !event.target.closest(".employee-select__menu--floating")) {
            closeEmployeeSelects();
        }
    }, { signal: signal });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            closeEmployeeSelects();
        }
    }, { signal: signal });

    window.addEventListener("resize", repositionOpenSelects, { signal: signal });
    window.addEventListener("scroll", repositionOpenSelects, { capture: true, signal: signal });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initEmployeeFormPage, { once: true });
} else {
    initEmployeeFormPage();
}

document.addEventListener("app:navigation", initEmployeeFormPage);
