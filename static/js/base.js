document.addEventListener("DOMContentLoaded", function () {
    function hasTextSelection() {
        const selection = window.getSelection ? window.getSelection().toString().trim() : "";
        return Boolean(selection);
    }

    function requestDatePicker(input) {
        if (!input || input.disabled || typeof input.showPicker !== "function") {
            return;
        }

        try {
            input.showPicker();
        } catch (error) {
        }
    }

    function syncDateInputState(input) {
        if (!input || input.type !== "date") {
            return;
        }

        input.classList.toggle("is-empty", !input.value);
    }

    function resolveModal(target) {
        if (!target) {
            return null;
        }

        if (typeof target === "string") {
            return document.getElementById(target);
        }

        return target;
    }

    function setModalState(target, isOpen) {
        const modal = resolveModal(target);
        if (!modal) {
            return;
        }

        const wasOpen = modal.classList.contains("is-open");
        modal.classList.toggle("is-open", isOpen);
        modal.setAttribute("aria-hidden", isOpen ? "false" : "true");

        if (wasOpen === isOpen) {
            return;
        }

        modal.dispatchEvent(new CustomEvent(isOpen ? "app-modal:open" : "app-modal:close", {
            bubbles: true,
            detail: { modalId: modal.id },
        }));
    }

    function closeAllModals() {
        document.querySelectorAll(".app-modal.is-open").forEach(function (modal) {
            setModalState(modal, false);
        });
    }

    window.appModal = {
        open: function (target) {
            setModalState(target, true);
        },
        close: function (target) {
            setModalState(target, false);
        },
    };

    document.querySelectorAll("[data-date-field] input[type='date']").forEach(function (input) {
        const field = input.closest("[data-date-field]");

        syncDateInputState(input);

        if (field) {
            field.addEventListener("click", function (event) {
                if (event.target.closest("button, select, textarea")) {
                    return;
                }
                requestDatePicker(input);
            });
        }

        input.addEventListener("focus", function () {
            requestDatePicker(input);
        });

        input.addEventListener("change", function () {
            syncDateInputState(input);
        });

        input.addEventListener("input", function () {
            syncDateInputState(input);
        });
    });

    document.addEventListener("click", function (event) {
        const openButton = event.target.closest("[data-modal-open]");
        if (openButton) {
            setModalState(openButton.dataset.modalOpen, true);
            return;
        }

        const closeButton = event.target.closest("[data-modal-close]");
        if (closeButton) {
            setModalState(closeButton.closest(".app-modal"), false);
            return;
        }

        const clickableRow = event.target.closest("[data-href]");
        if (!clickableRow) {
            return;
        }

        if (
            hasTextSelection()
            || event.target.closest("a, button, input, select, textarea, label, form")
        ) {
            return;
        }

        const href = clickableRow.dataset.href;
        if (href) {
            window.location.href = href;
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            closeAllModals();
        }

        if (event.key !== "Enter" && event.key !== " ") {
            return;
        }

        const clickableRow = event.target.closest("[data-href]");
        if (!clickableRow) {
            return;
        }

        event.preventDefault();
        const href = clickableRow.dataset.href;
        if (href) {
            window.location.href = href;
        }
    });
});
