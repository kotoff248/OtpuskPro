const container = document.getElementById("container");
const registerBtn = document.getElementById("register");
const loginBtn = document.getElementById("login");
const authModeButtons = Array.from(document.querySelectorAll("[data-auth-mode]"));
const authLayoutQuery = window.matchMedia("(max-width: 900px)");
const reducedMotionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
let authLayoutTransitionTimer = null;

function clearKabinetSessionMemoryAfterLogout() {
    const params = new URLSearchParams(window.location.search);
    if (params.get("signed_out") !== "1") {
        return;
    }

    const exactKeys = [
        "applications:last-detail-href",
        "applications:last-list-href",
        "applications:list-scroll-state",
        "employees:last-detail-href",
        "employees:last-list-href",
        "employees:list-scroll-state",
        "notifications:last-list-href",
        "calendar:path",
        "calendar:last-url",
        "calendar:active-preferences-url",
        "calendar:board-scroll-state",
    ];
    const prefixes = ["profile-sections:", "profile-schedule-filters:", "calendar:preferences-draft:"];

    try {
        exactKeys.forEach(function (key) {
            sessionStorage.removeItem(key);
        });

        for (let index = sessionStorage.length - 1; index >= 0; index -= 1) {
            const key = sessionStorage.key(index);
            if (!key) {
                continue;
            }

            if (prefixes.some(function (prefix) {
                return key.indexOf(prefix) === 0;
            })) {
                sessionStorage.removeItem(key);
            }
        }
    } catch (error) {
    }

    params.delete("signed_out");
    const cleanQuery = params.toString();
    const cleanUrl = window.location.pathname + (cleanQuery ? "?" + cleanQuery : "") + window.location.hash;
    window.history.replaceState({}, document.title, cleanUrl);
}

clearKabinetSessionMemoryAfterLogout();

function setAuthMode(mode) {
    if (!container) {
        return;
    }

    const isManagementMode = mode === "management";
    container.classList.toggle("active", isManagementMode);
    authModeButtons.forEach(function (button) {
        button.setAttribute("aria-pressed", button.dataset.authMode === mode ? "true" : "false");
    });
}

if (container) {
    setAuthMode(container.classList.contains("active") ? "management" : "employee");
}

function playAuthLayoutTransition() {
    if (!container || reducedMotionQuery.matches) {
        return;
    }

    window.clearTimeout(authLayoutTransitionTimer);
    document.body.classList.remove("auth-layout-changing");
    void container.offsetWidth;
    document.body.classList.add("auth-layout-changing");

    authLayoutTransitionTimer = window.setTimeout(function () {
        document.body.classList.remove("auth-layout-changing");
    }, 620);
}

function setAuthLayoutMode(isMobile) {
    document.body.dataset.authLayout = isMobile ? "mobile" : "desktop";
}

if (container) {
    setAuthLayoutMode(authLayoutQuery.matches);

    const handleAuthLayoutChange = function (event) {
        setAuthLayoutMode(event.matches);
        playAuthLayoutTransition();
    };

    if (typeof authLayoutQuery.addEventListener === "function") {
        authLayoutQuery.addEventListener("change", handleAuthLayoutChange);
    } else if (typeof authLayoutQuery.addListener === "function") {
        authLayoutQuery.addListener(handleAuthLayoutChange);
    }
}

if (container && registerBtn && loginBtn) {
    registerBtn.addEventListener("click", function () {
        setAuthMode("management");
    });

    loginBtn.addEventListener("click", function () {
        setAuthMode("employee");
    });
}

authModeButtons.forEach(function (button) {
    button.addEventListener("click", function () {
        setAuthMode(button.dataset.authMode === "management" ? "management" : "employee");
    });
});
