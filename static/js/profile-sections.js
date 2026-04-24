function initProfileSectionsPage() {
    const previousController = window.__profileSectionsPageController;
    if (previousController) {
        previousController.abort();
    }

    const root = document.querySelector("[data-profile-sections]");
    if (!root) {
        return;
    }

    const controller = new AbortController();
    const signal = controller.signal;
    window.__profileSectionsPageController = controller;

    const pageMain = document.querySelector(".page-main");
    const requestsScroll = root.querySelector("[data-profile-requests-scroll]");
    const sections = Array.from(root.querySelectorAll("[data-profile-section]"));
    let activeSection = root.dataset.activeSection === "requests" ? "requests" : "overview";
    let ignoreNextRequestsWheel = false;

    if (pageMain) {
        pageMain.classList.add("is-profile-sections");
    }

    root.classList.add("is-enhanced");

    function syncSectionState() {
        root.dataset.activeSection = activeSection;
        sections.forEach(function (section) {
            const isActive = section.dataset.profileSection === activeSection;
            section.classList.toggle("is-active", isActive);
            section.setAttribute("aria-hidden", isActive ? "false" : "true");
        });
    }

    function activateSection(sectionName, options) {
        const nextOptions = options || {};
        if (sectionName === activeSection && !nextOptions.force) {
            return;
        }

        activeSection = sectionName;
        if (sectionName === "requests" && requestsScroll && nextOptions.resetScroll) {
            requestsScroll.scrollTop = 0;
        }

        ignoreNextRequestsWheel = sectionName === "requests" && Boolean(nextOptions.ignoreInitialScroll);
        syncSectionState();
    }

    function isRequestsScrollAtTop() {
        return !requestsScroll || requestsScroll.scrollTop <= 1;
    }

    root.addEventListener("wheel", function (event) {
        if (activeSection === "overview") {
            if (event.deltaY > 12) {
                event.preventDefault();
                activateSection("requests", {
                    resetScroll: true,
                    ignoreInitialScroll: true,
                });
            }
            return;
        }

        if (activeSection !== "requests") {
            return;
        }

        if (ignoreNextRequestsWheel) {
            if (event.deltaY > 0) {
                event.preventDefault();
                ignoreNextRequestsWheel = false;
                return;
            }
            ignoreNextRequestsWheel = false;
        }

        if (event.deltaY < -12 && isRequestsScrollAtTop()) {
            event.preventDefault();
            activateSection("overview");
        }
    }, { passive: false, signal: signal });

    syncSectionState();
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initProfileSectionsPage, { once: true });
} else {
    initProfileSectionsPage();
}

document.addEventListener("app:navigation", initProfileSectionsPage);
