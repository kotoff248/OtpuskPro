function initProfileSectionsPage() {
    const previousController = window.__profileSectionsPageController;
    if (previousController) {
        previousController.abort();
    }

    const pageMain = document.querySelector(".page-main");
    const root = document.querySelector("[data-profile-sections]");
    if (!root) {
        if (pageMain) {
            pageMain.classList.remove("is-profile-sections");
        }
        return;
    }

    const controller = new AbortController();
    const signal = controller.signal;
    window.__profileSectionsPageController = controller;

    const requestsScroll = root.querySelector("[data-profile-requests-scroll]");
    const overviewScrolls = Array.from(root.querySelectorAll("[data-profile-overview-scroll], [data-entitlement-scroll]"));
    const requestScrolls = Array.from(root.querySelectorAll("[data-profile-requests-scroll]"));
    const viewport = root.querySelector("[data-profile-viewport]");
    const sections = Array.from(root.querySelectorAll("[data-profile-section]"));
    const preserveRequestsScrollOnSectionSwitch = root.hasAttribute("data-applications-page");
    const shouldUseGenericScrollMemory = !root.hasAttribute("data-applications-page");
    const sectionStorageKey = "profile-sections:" + window.location.pathname;
    const storedState = readSectionState();
    let activeSection = getInitialActiveSection();
    let ignoreNextRequestsWheel = false;
    let hasRestoredStoredScroll = false;

    if (pageMain) {
        pageMain.classList.add("is-profile-sections");
    }

    if (viewport && activeSection === "requests") {
        viewport.style.transition = "none";
    }

    root.classList.add("is-enhanced");

    function readSectionState() {
        try {
            return JSON.parse(sessionStorage.getItem(sectionStorageKey) || "null");
        } catch (error) {
            return null;
        }
    }

    function writeSectionState() {
        const state = {
            activeSection: activeSection,
        };

        if (
            shouldUseGenericScrollMemory
            && requestsScroll
            && !hasRestoredStoredScroll
            && storedState
            && storedState.requestsTop !== undefined
        ) {
            state.requestsTop = Number(storedState.requestsTop) || 0;
        } else if (shouldUseGenericScrollMemory && requestsScroll) {
            state.requestsTop = requestsScroll.scrollTop;
        }

        try {
            sessionStorage.setItem(sectionStorageKey, JSON.stringify(state));
        } catch (error) {
        }
    }

    function getInitialActiveSection() {
        if (root.dataset.activeSection === "requests") {
            return "requests";
        }

        if (root.dataset.activeSection === "overview") {
            return "overview";
        }

        if (storedState && storedState.activeSection === "requests") {
            return "requests";
        }

        return "overview";
    }

    function restoreStoredScroll() {
        if (!shouldUseGenericScrollMemory || !requestsScroll || !storedState) {
            return;
        }

        requestAnimationFrame(function () {
            requestsScroll.scrollTop = Number(storedState.requestsTop) || 0;
            hasRestoredStoredScroll = true;
            writeSectionState();
        });
    }

    function syncSectionState() {
        root.dataset.activeSection = activeSection;
        sections.forEach(function (section) {
            const isActive = section.dataset.profileSection === activeSection;
            section.classList.toggle("is-active", isActive);
            section.setAttribute("aria-hidden", isActive ? "false" : "true");
        });
        writeSectionState();
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

    function getEventElement(event) {
        return event.target instanceof Element ? event.target : null;
    }

    function canScrollElementVertically(element, deltaY, deltaX) {
        if (!element || Math.abs(deltaY) <= Math.abs(deltaX || 0)) {
            return false;
        }

        const maxScrollTop = element.scrollHeight - element.clientHeight;
        if (maxScrollTop <= 1) {
            return false;
        }

        if (deltaY > 0) {
            return element.scrollTop < maxScrollTop - 1;
        }

        if (deltaY < 0) {
            return element.scrollTop > 1;
        }

        return false;
    }

    function findScrollableElement(event, scrollRoots) {
        const target = getEventElement(event);
        if (!target) {
            return null;
        }

        const scrollRoot = scrollRoots.find(function (candidate) {
            return candidate.contains(target);
        });
        if (!scrollRoot) {
            return null;
        }

        return canScrollElementVertically(scrollRoot, event.deltaY, event.deltaX) ? scrollRoot : null;
    }

    function eventStartedInside(event, scrollRoots) {
        const target = getEventElement(event);
        if (!target) {
            return false;
        }

        return scrollRoots.some(function (candidate) {
            return candidate.contains(target);
        });
    }

    function shouldLeaveWheelAlone(event) {
        const target = getEventElement(event);
        if (!target) {
            return false;
        }

        const floatingMenu = target.closest(".employee-select__menu--floating, [data-employee-select-menu]");
        if (floatingMenu && canScrollElementVertically(floatingMenu, event.deltaY, event.deltaX)) {
            return true;
        }

        return false;
    }

    document.addEventListener("wheel", function (event) {
        if (shouldLeaveWheelAlone(event)) {
            return;
        }

        if (activeSection === "overview") {
            if (findScrollableElement(event, overviewScrolls)) {
                return;
            }

            if (event.deltaY > 12) {
                event.preventDefault();
                activateSection("requests", {
                    resetScroll: !preserveRequestsScrollOnSectionSwitch,
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

        if (findScrollableElement(event, requestScrolls)) {
            return;
        }

        if (
            event.deltaY < -12
            && (!eventStartedInside(event, requestScrolls) || isRequestsScrollAtTop())
        ) {
            event.preventDefault();
            activateSection("overview");
        }
    }, { passive: false, signal: signal });

    if (shouldUseGenericScrollMemory && requestsScroll) {
        requestsScroll.addEventListener("scroll", function () {
            writeSectionState();
        }, { passive: true, signal: signal });
    }

    syncSectionState();
    restoreStoredScroll();

    if (viewport && viewport.style.transition === "none") {
        requestAnimationFrame(function () {
            requestAnimationFrame(function () {
                viewport.style.transition = "";
            });
        });
    }
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initProfileSectionsPage, { once: true });
} else {
    initProfileSectionsPage();
}

document.addEventListener("app:navigation", initProfileSectionsPage);
