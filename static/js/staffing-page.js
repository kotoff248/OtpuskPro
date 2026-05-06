function initStaffingPage() {
    const previousController = window.__staffingPageController;
    if (previousController) {
        previousController.abort();
    }

    const root = document.querySelector(".staffing-page");
    if (!root) {
        return;
    }

    const controller = new AbortController();
    const signal = controller.signal;
    window.__staffingPageController = controller;

    root.querySelectorAll("[data-staffing-workload-year-select]").forEach(function (select) {
        const form = select.closest("[data-staffing-workload-year-form]");
        if (!form) {
            return;
        }

        select.addEventListener("change", function () {
            if (typeof form.requestSubmit === "function") {
                form.requestSubmit();
                return;
            }
            form.submit();
        }, { signal: signal });
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initStaffingPage, { once: true });
} else {
    initStaffingPage();
}

document.addEventListener("app:navigation", initStaffingPage);
