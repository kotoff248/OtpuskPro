function initNotificationsPage() {
    const existingController = window.__notificationsPageController;
    if (existingController) {
        existingController.abort();
    }

    const root = document.querySelector("[data-notifications-page]");
    if (!root) {
        return;
    }

    const controller = new AbortController();
    const signal = controller.signal;
    window.__notificationsPageController = controller;

    const filterForm = document.getElementById("notifications-filter-form");
    const buttons = filterForm ? Array.from(filterForm.querySelectorAll("button[name='filter']")) : [];
    const list = document.getElementById("notificationsList");

    if (!filterForm || !buttons.length || !list) {
        return;
    }

    let currentFilter = (buttons.find(function (button) {
        return button.classList.contains("active");
    }) || buttons[0]).value;
    let requestSequence = 0;
    const defaultFilter = "all";

    function rememberListHref() {
        if (
            window.KabinetNavigation
            && typeof window.KabinetNavigation.rememberSectionListHref === "function"
        ) {
            window.KabinetNavigation.rememberSectionListHref("notifications", window.location.href);
        }
    }

    function setActiveButton(value) {
        let activeButton = null;
        buttons.forEach(function (button) {
            const isActive = button.value === value;
            button.classList.toggle("active", isActive);
            if (isActive) {
                activeButton = button;
            }
        });
        if (window.KabinetSegmented && typeof window.KabinetSegmented.sync === "function") {
            window.KabinetSegmented.sync(filterForm, activeButton);
        }
    }

    function updateCounts(counts) {
        if (!counts) {
            return;
        }
        Object.keys(counts).forEach(function (key) {
            const node = filterForm.querySelector('[data-notification-count="' + key + '"]');
            if (node) {
                node.textContent = String(counts[key]);
            }
        });
    }

    function updateUrl(filterValue) {
        const params = new URLSearchParams(window.location.search);
        params.set("filter", filterValue);
        const query = params.toString();
        window.history.replaceState({}, "", query ? window.location.pathname + "?" + query : window.location.pathname);
        rememberListHref();
    }

    function resetListScroll() {
        list.scrollTop = 0;
    }

    function fetchNotifications() {
        const url = new URL(window.location.href);
        const requestId = ++requestSequence;
        url.searchParams.set("filter", currentFilter);

        fetch(url.toString(), {
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
            signal: signal,
        })
            .then(function (response) {
                return response.json();
            })
            .then(function (data) {
                if (requestId !== requestSequence) {
                    return;
                }
                list.innerHTML = data.notifications_html || "";
                updateCounts(data.counts);
                updateUrl(currentFilter);
                resetListScroll();
            })
            .catch(function (error) {
                if (error.name === "AbortError") {
                    return;
                }
                console.error("Error fetching notifications:", error);
            });
    }

    setActiveButton(currentFilter);
    rememberListHref();

    buttons.forEach(function (button) {
        button.addEventListener("click", function () {
            currentFilter = button.value;
            setActiveButton(currentFilter);
            fetchNotifications();
        }, { signal: signal });
    });

    document.addEventListener("app:section-sidebar-repeat", function (event) {
        if (!event.detail || event.detail.sectionKey !== "notifications") {
            return;
        }

        event.preventDefault();
        currentFilter = defaultFilter;
        setActiveButton(currentFilter);
        fetchNotifications();
    }, { signal: signal });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initNotificationsPage, { once: true });
} else {
    initNotificationsPage();
}

document.addEventListener("app:navigation", initNotificationsPage);
