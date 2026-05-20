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
        "schedule-planning:last-active-href",
        "schedule-planning:calendar-path",
        "schedule-planning:calendar-last-url",
    ];
    const prefixes = ["profile-sections:", "profile-schedule-filters:", "calendar:preferences-draft:", "planning-scroll:"];

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

const demoAccess = document.querySelector("[data-demo-access]");
const demoAccessToggle = demoAccess ? demoAccess.querySelector("[data-demo-access-toggle]") : null;
const demoAccessPanel = demoAccess ? demoAccess.querySelector("[data-demo-access-panel]") : null;
let demoCopyTimer = null;

function setDemoAccessOpen(isOpen) {
    if (!demoAccess || !demoAccessToggle || !demoAccessPanel) {
        return;
    }

    demoAccess.classList.toggle("is-open", isOpen);
    demoAccessToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
    demoAccessPanel.setAttribute("aria-hidden", isOpen ? "false" : "true");
    if (isOpen) {
        demoAccessPanel.removeAttribute("inert");
    } else {
        demoAccessPanel.setAttribute("inert", "");
    }
}

function copyTextFallback(value) {
    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    textarea.style.top = "0";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();

    try {
        if (document.execCommand("copy")) {
            return Promise.resolve();
        }
        return Promise.reject(new Error("Copy command was not accepted."));
    } catch (error) {
        return Promise.reject(error);
    } finally {
        textarea.remove();
    }
}

function copyDemoValue(value) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
        return navigator.clipboard.writeText(value).catch(function () {
            return copyTextFallback(value);
        });
    }
    return copyTextFallback(value);
}

function markDemoCopyButton(button, isSuccess) {
    const valueNode = button.querySelector(".auth-demo-access__copy-value");
    const iconNode = button.querySelector(".material-icons-sharp");
    const originalValue = button.dataset.copyOriginalValue || (valueNode ? valueNode.textContent : "");
    const originalIcon = button.dataset.copyOriginalIcon || (iconNode ? iconNode.textContent : "content_copy");

    button.dataset.copyOriginalValue = originalValue;
    button.dataset.copyOriginalIcon = originalIcon;
    button.classList.add("is-copied");
    button.classList.toggle("is-copy-error", !isSuccess);
    if (valueNode) {
        valueNode.textContent = isSuccess ? "Скопировано" : "Не удалось";
    }
    if (iconNode) {
        iconNode.textContent = isSuccess ? "check" : "priority_high";
    }

    window.clearTimeout(demoCopyTimer);
    demoCopyTimer = window.setTimeout(function () {
        button.classList.remove("is-copied");
        button.classList.remove("is-copy-error");
        if (valueNode) {
            valueNode.textContent = originalValue;
        }
        if (iconNode) {
            iconNode.textContent = originalIcon;
        }
    }, 1400);
}

if (demoAccess && demoAccessToggle && demoAccessPanel) {
    demoAccessToggle.addEventListener("click", function () {
        setDemoAccessOpen(!demoAccess.classList.contains("is-open"));
    });

    demoAccess.addEventListener("click", function (event) {
        if (!(event.target instanceof Element)) {
            return;
        }
        const copyButton = event.target.closest("[data-demo-copy]");
        if (!copyButton) {
            return;
        }
        const value = copyButton.dataset.demoCopy || "";
        if (!value) {
            return;
        }
        copyDemoValue(value).then(function () {
            markDemoCopyButton(copyButton, true);
        }).catch(function () {
            markDemoCopyButton(copyButton, false);
        });
    });

    document.addEventListener("click", function (event) {
        if (!demoAccess.classList.contains("is-open")) {
            return;
        }
        if (event.target instanceof Element && demoAccess.contains(event.target)) {
            return;
        }
        setDemoAccessOpen(false);
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && demoAccess.classList.contains("is-open")) {
            setDemoAccessOpen(false);
            demoAccessToggle.focus();
        }
    });
}
