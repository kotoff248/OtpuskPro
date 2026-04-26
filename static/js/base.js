document.addEventListener("DOMContentLoaded", function () {
    const CORE_STYLE_MATCHERS = ["css/reset.css", "css/main.css"];
    const CORE_SCRIPT_MATCHERS = ["js/base.js"];

    function assetMatches(url, matchers) {
        return matchers.some(function (matcher) {
            return url.indexOf(matcher) !== -1;
        });
    }

    function dispatchNavigationEvent(pathname) {
        document.dispatchEvent(new CustomEvent("app:navigation", {
            detail: { pathname: pathname || window.location.pathname },
        }));
    }

    function ensureDocumentStyles(nextDocument) {
        const nextStyles = Array.from(nextDocument.querySelectorAll("link[rel='stylesheet'][href]"));

        nextStyles.forEach(function (styleNode) {
            const href = styleNode.href;
            if (!href || assetMatches(href, CORE_STYLE_MATCHERS)) {
                return;
            }

            if (!document.querySelector("link[rel='stylesheet'][href='" + href + "']")) {
                const clone = styleNode.cloneNode(true);
                document.head.appendChild(clone);
            }
        });
    }

    async function ensureDocumentScripts(nextDocument) {
        const nextScripts = Array.from(nextDocument.querySelectorAll("script[src]"));

        const pendingScripts = nextScripts
            .map(function (scriptNode) {
                return scriptNode.src;
            })
            .filter(function (src) {
                return src && !assetMatches(src, CORE_SCRIPT_MATCHERS) && !document.querySelector("script[src='" + src + "']");
            })
            .map(function (src) {
                return new Promise(function (resolve, reject) {
                    const script = document.createElement("script");
                    script.src = src;
                    script.defer = true;
                    script.onload = resolve;
                    script.onerror = reject;
                    document.body.appendChild(script);
                });
            });

        if (pendingScripts.length) {
            await Promise.all(pendingScripts);
        }
    }

    function replaceAppContainer(nextDocument) {
        const currentContainer = document.querySelector("[data-app-container]");
        const nextContainer = nextDocument.querySelector("[data-app-container]");

        if (!currentContainer || !nextContainer) {
            return false;
        }

        currentContainer.replaceWith(nextContainer);
        if (window.__sidebarPanelHovered) {
            const nextSidebar = nextContainer.querySelector("[data-sidebar-nav]");
            if (nextSidebar) {
                nextSidebar.classList.add("is-panel-hovered");
                const nextActiveLink = nextSidebar.querySelector("[data-sidebar-link].active, [data-sidebar-link][aria-current='page']");
                if (
                    nextActiveLink
                    && getPathFromHref(nextActiveLink.href) === window.__sidebarActiveHoverPath
                    && isStoredPointerOverElement(nextActiveLink)
                ) {
                    nextSidebar.classList.add("is-active-hover", "is-restored-active-hover");
                }
            }
        }
        document.title = nextDocument.title;
        if (nextDocument.body) {
            const nextBodyClass = nextDocument.body.getAttribute("class");
            if (nextBodyClass) {
                document.body.setAttribute("class", nextBodyClass);
            } else {
                document.body.removeAttribute("class");
            }
        }
        return true;
    }

    function getPathFromHref(href) {
        try {
            const url = new URL(href, window.location.href);
            return url.pathname + url.search + url.hash;
        } catch (error) {
            return "";
        }
    }

    function rememberSidebarPointerPosition(event) {
        if (!event || typeof event.clientX !== "number" || typeof event.clientY !== "number") {
            return;
        }

        window.__sidebarPointerPosition = {
            x: event.clientX,
            y: event.clientY,
        };
    }

    function isStoredPointerOverElement(element) {
        const pointerPosition = window.__sidebarPointerPosition;
        if (!element || !pointerPosition) {
            return false;
        }

        const x = Number(pointerPosition.x);
        const y = Number(pointerPosition.y);
        if (!Number.isFinite(x) || !Number.isFinite(y)) {
            return false;
        }

        const hitElement = document.elementFromPoint(x, y);
        if (hitElement) {
            return element.contains(hitElement);
        }

        const rect = element.getBoundingClientRect();
        return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
    }

    function applyRememberedCalendarHref(link) {
        if (!link || !link.href) {
            return;
        }

        try {
            const rememberedPath = sessionStorage.getItem("calendar:path");
            const rememberedUrl = sessionStorage.getItem("calendar:last-url");
            if (!rememberedPath || !rememberedUrl) {
                return;
            }

            const linkUrl = new URL(link.href, window.location.href);
            const restoredUrl = new URL(rememberedUrl, window.location.href);

            if (
                linkUrl.origin === window.location.origin
                && restoredUrl.origin === window.location.origin
                && linkUrl.pathname === rememberedPath
                && restoredUrl.pathname === rememberedPath
            ) {
                link.href = restoredUrl.href;
            }
        } catch (error) {
        }
    }

    function canNavigateWithFetch(targetUrl) {
        try {
            const url = new URL(targetUrl, window.location.href);
            const currentPath = window.location.pathname + window.location.search + window.location.hash;
            const targetPath = url.pathname + url.search + url.hash;

            return url.origin === window.location.origin && targetPath !== currentPath;
        } catch (error) {
            return false;
        }
    }

    async function navigateWithFetch(targetUrl, pushState) {
        try {
            const response = await fetch(targetUrl);

            if (!response.ok) {
                throw new Error("Navigation failed");
            }

            const html = await response.text();
            const parser = new DOMParser();
            const nextDocument = parser.parseFromString(html, "text/html");

            ensureDocumentStyles(nextDocument);

            if (!replaceAppContainer(nextDocument)) {
                throw new Error("Navigation shell mismatch");
            }

            if (pushState) {
                window.history.pushState({}, "", targetUrl);
            }

            window.scrollTo({ top: 0, left: 0, behavior: "auto" });
            await ensureDocumentScripts(nextDocument);
            initSidebarNavigation();
            dispatchNavigationEvent(new URL(targetUrl, window.location.href).pathname);
        } catch (error) {
            window.location.href = targetUrl;
        }
    }

    function initSidebarNavigation() {
        const nav = document.querySelector("[data-sidebar-nav]");
        if (!nav) {
            return;
        }

        const thumb = nav.querySelector(".sidebar__thumb");
        const links = Array.from(nav.querySelectorAll("[data-sidebar-link]"));
        const activeLink = nav.querySelector("[data-sidebar-link].active, [data-sidebar-link][aria-current='page']");
        const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        let transitionTimeoutId = null;
        let navigationTimeoutId = null;
        let navigationController = window.__sidebarNavigationController;

        if (navigationController) {
            navigationController.abort();
        }

        navigationController = new AbortController();
        window.__sidebarNavigationController = navigationController;
        const signal = navigationController.signal;

        if (!thumb || !links.length || !activeLink) {
            return;
        }

        function setPanelHoverState(isHovered) {
            window.__sidebarPanelHovered = Boolean(isHovered);
            nav.classList.toggle("is-panel-hovered", window.__sidebarPanelHovered);
            if (!window.__sidebarPanelHovered) {
                window.__sidebarActiveHoverPath = "";
                nav.classList.remove("is-restored-active-hover");
            }
        }

        function syncActiveHoverState() {
            const currentActive = nav.querySelector("[data-sidebar-link].active, [data-sidebar-link][aria-current='page']") || activeLink;
            const activeIsHovered = Boolean(
                window.__sidebarPanelHovered
                && currentActive
                && (currentActive.matches(":hover") || isStoredPointerOverElement(currentActive))
            );
            const shouldRestoreActiveHover = (
                window.__sidebarPanelHovered
                && currentActive
                && getPathFromHref(currentActive.href) === window.__sidebarActiveHoverPath
                && isStoredPointerOverElement(currentActive)
            );
            const isActiveHover = activeIsHovered || shouldRestoreActiveHover;
            nav.classList.toggle("is-active-hover", isActiveHover);
            if (!isActiveHover) {
                nav.classList.remove("is-restored-active-hover");
            }
        }

        function getLinkMetrics(link) {
            const navRect = nav.getBoundingClientRect();
            const linkRect = link.getBoundingClientRect();

            return {
                top: linkRect.top - navRect.top,
                height: linkRect.height,
            };
        }

        function setTransitionState(isTransitioning) {
            nav.classList.toggle("is-transitioning", isTransitioning);

            if (transitionTimeoutId) {
                clearTimeout(transitionTimeoutId);
                transitionTimeoutId = null;
            }

            if (isTransitioning) {
                transitionTimeoutId = window.setTimeout(function () {
                    nav.classList.remove("is-transitioning");
                    transitionTimeoutId = null;
                }, 360);
            }
        }

        function applyThumb(metrics, immediate) {
            if (immediate) {
                thumb.style.transition = "none";
            }

            thumb.style.setProperty("--sidebar-thumb-top", Math.round(metrics.top) + "px");
            thumb.style.height = Math.round(metrics.height) + "px";

            if (immediate) {
                requestAnimationFrame(function () {
                    thumb.style.transition = "";
                });
            }
        }

        function resetNavigationState() {
            nav.classList.remove("is-navigating", "is-pointer-down", "is-active-hover");
            links.forEach(function (link) {
                link.classList.remove("is-current-from", "is-current-to");
            });
            setTransitionState(false);
            syncActiveHoverState();

            if (navigationTimeoutId) {
                clearTimeout(navigationTimeoutId);
                navigationTimeoutId = null;
            }
        }

        function setPointerDownState(isPointerDown) {
            nav.classList.toggle("is-pointer-down", isPointerDown);
        }

        function getTargetPath(link) {
            return getPathFromHref(link.href);
        }

        function getCurrentPath() {
            return window.location.pathname + window.location.search + window.location.hash;
        }

        function shouldAnimateNavigation(event, link) {
            if (
                prefersReducedMotion
                || !link
                || !link.href
                || event.defaultPrevented
                || event.button !== 0
                || event.detail === 0
                || event.metaKey
                || event.ctrlKey
                || event.shiftKey
                || event.altKey
                || (link.target && link.target !== "_self")
                || link.hasAttribute("download")
            ) {
                return false;
            }

            try {
                const url = new URL(link.href, window.location.href);
                if (url.origin !== window.location.origin) {
                    return false;
                }

                return getTargetPath(link) !== getCurrentPath();
            } catch (error) {
                return false;
            }
        }

        function positionThumbOnActive(immediate) {
            const currentActive = nav.querySelector("[data-sidebar-link].active, [data-sidebar-link][aria-current='page']") || activeLink;
            applyThumb(getLinkMetrics(currentActive), immediate);
        }

        links.forEach(function (link) {
            if (!link.href) {
                return;
            }

            link.addEventListener("pointerdown", function (event) {
                if (
                    prefersReducedMotion
                    || event.button !== 0
                    || event.metaKey
                    || event.ctrlKey
                    || event.shiftKey
                    || event.altKey
                    || (link.target && link.target !== "_self")
                    || link.hasAttribute("download")
                ) {
                    return;
                }

                nav.classList.remove("is-restored-active-hover");
                rememberSidebarPointerPosition(event);
                setPointerDownState(true);
                window.__sidebarActiveHoverPath = getTargetPath(link);
                syncActiveHoverState();
                link.blur();
            });

            link.addEventListener("mouseenter", function (event) {
                rememberSidebarPointerPosition(event);
                if (getTargetPath(link) !== window.__sidebarActiveHoverPath) {
                    nav.classList.remove("is-restored-active-hover");
                }
                syncActiveHoverState();
            }, { signal: signal });

            link.addEventListener("mouseleave", function (event) {
                rememberSidebarPointerPosition(event);
                nav.classList.remove("is-restored-active-hover");
                syncActiveHoverState();
            }, { signal: signal });

            link.addEventListener("click", function (event) {
                applyRememberedCalendarHref(link);

                if (!shouldAnimateNavigation(event, link)) {
                    setPointerDownState(false);
                    syncActiveHoverState();
                    return;
                }

                event.preventDefault();
                window.__sidebarActiveHoverPath = getTargetPath(link);
                link.blur();
                nav.classList.remove("is-restored-active-hover");
                resetNavigationState();
                nav.classList.add("is-ready", "is-navigating");

                const currentActive = nav.querySelector("[data-sidebar-link].active, [data-sidebar-link][aria-current='page']") || activeLink;
                if (currentActive) {
                    currentActive.classList.add("is-current-from");
                }
                link.classList.add("is-current-to");

                requestAnimationFrame(function () {
                    setTransitionState(true);
                    applyThumb(getLinkMetrics(link), false);
                });

                navigationTimeoutId = window.setTimeout(function () {
                    navigateWithFetch(link.href, true);
                }, 240);
            }, { signal: signal });
        });

        setPanelHoverState(Boolean(window.__sidebarPanelHovered || nav.matches(":hover")));

        nav.addEventListener("pointerenter", function () {
            setPanelHoverState(true);
        }, { signal: signal });

        nav.addEventListener("pointermove", function (event) {
            rememberSidebarPointerPosition(event);
            syncActiveHoverState();
        }, { passive: true, signal: signal });

        nav.addEventListener("pointerleave", function (event) {
            rememberSidebarPointerPosition(event);
            setPanelHoverState(false);
            syncActiveHoverState();
        }, { signal: signal });

        window.addEventListener("pointerup", function () {
            if (!nav.classList.contains("is-navigating")) {
                setPointerDownState(false);
            }
        }, { signal: signal });

        window.addEventListener("pointercancel", function () {
            if (!nav.classList.contains("is-navigating")) {
                setPointerDownState(false);
            }
        }, { signal: signal });

        resetNavigationState();
        positionThumbOnActive(true);
        syncActiveHoverState();
        nav.classList.add("is-ready");

        window.addEventListener("resize", function () {
            positionThumbOnActive(true);
            syncActiveHoverState();
        }, { signal: signal });

        window.addEventListener("pageshow", function () {
            resetNavigationState();
            positionThumbOnActive(true);
            nav.classList.add("is-ready");
        }, { signal: signal });

        window.addEventListener("popstate", function () {
            navigateWithFetch(window.location.href, false);
        }, { signal: signal });
    }

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

    initSidebarNavigation();

    function initDateFields() {
        document.querySelectorAll("[data-date-field] input[type='date']").forEach(function (input) {
            if (input.dataset.dateFieldBound === "true") {
                syncDateInputState(input);
                return;
            }

            const field = input.closest("[data-date-field]");
            input.dataset.dateFieldBound = "true";
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
    }

    initDateFields();
    document.addEventListener("app:navigation", initDateFields);

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
        if (!href) {
            return;
        }

        if (canNavigateWithFetch(href)) {
            event.preventDefault();
            navigateWithFetch(href, true);
        } else {
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
        if (!href) {
            return;
        }

        if (canNavigateWithFetch(href)) {
            navigateWithFetch(href, true);
        } else {
            window.location.href = href;
        }
    });
});
