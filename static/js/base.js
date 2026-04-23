document.addEventListener("DOMContentLoaded", function () {
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

        if (!thumb || !links.length || !activeLink) {
            return;
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

            thumb.style.transform = "translate3d(0, " + Math.round(metrics.top) + "px, 0)";
            thumb.style.height = Math.round(metrics.height) + "px";

            if (immediate) {
                requestAnimationFrame(function () {
                    thumb.style.transition = "";
                });
            }
        }

        function resetNavigationState() {
            nav.classList.remove("is-navigating", "is-pointer-down");
            links.forEach(function (link) {
                link.classList.remove("is-current-from", "is-current-to");
            });
            setTransitionState(false);

            if (navigationTimeoutId) {
                clearTimeout(navigationTimeoutId);
                navigationTimeoutId = null;
            }
        }

        function setPointerDownState(isPointerDown) {
            nav.classList.toggle("is-pointer-down", isPointerDown);
        }

        function getTargetPath(link) {
            const url = new URL(link.href, window.location.href);
            return url.pathname + url.search + url.hash;
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

                setPointerDownState(true);
                link.blur();
            });

            link.addEventListener("click", function (event) {
                if (!shouldAnimateNavigation(event, link)) {
                    setPointerDownState(false);
                    return;
                }

                event.preventDefault();
                link.blur();
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
                    window.location.href = link.href;
                }, 240);
            });
        });

        window.addEventListener("pointerup", function () {
            if (!nav.classList.contains("is-navigating")) {
                setPointerDownState(false);
            }
        });

        window.addEventListener("pointercancel", function () {
            if (!nav.classList.contains("is-navigating")) {
                setPointerDownState(false);
            }
        });

        resetNavigationState();
        positionThumbOnActive(true);
        nav.classList.add("is-ready");

        window.addEventListener("resize", function () {
            positionThumbOnActive(true);
        });

        window.addEventListener("pageshow", function () {
            resetNavigationState();
            positionThumbOnActive(true);
            nav.classList.add("is-ready");
        });
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
