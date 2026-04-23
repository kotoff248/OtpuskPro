document.addEventListener("DOMContentLoaded", function () {
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const profilePages = Array.from(document.querySelectorAll("[data-profile-sections]"));

    if (prefersReducedMotion || !profilePages.length) {
        return;
    }

    function isInteractiveTarget(target) {
        return Boolean(target.closest("input, select, textarea, button, summary, [contenteditable='true'], [data-modal-open], [data-modal-close]"));
    }

    profilePages.forEach(function (page) {
        const pageMain = page.closest(".page-main");
        const mask = page.querySelector("[data-profile-mask]");
        const viewport = page.querySelector("[data-profile-viewport]");
        const sections = Array.from(page.querySelectorAll("[data-profile-section]"));
        const requestsScroll = page.querySelector("[data-profile-requests-scroll]");

        if (!pageMain || !mask || !viewport || sections.length < 2 || !requestsScroll) {
            return;
        }

        let activeIndex = 0;
        let transitionLock = false;
        let lockTimeoutId = null;
        let touchStartY = null;
        let requestsWheelGuard = false;
        let requestsWheelGuardTimeoutId = null;

        function setTransitionLock() {
            transitionLock = true;

            if (lockTimeoutId) {
                clearTimeout(lockTimeoutId);
            }

            lockTimeoutId = window.setTimeout(function () {
                transitionLock = false;
                lockTimeoutId = null;
            }, 460);
        }

        function clearRequestsWheelGuardTimeout() {
            if (requestsWheelGuardTimeoutId) {
                clearTimeout(requestsWheelGuardTimeoutId);
                requestsWheelGuardTimeoutId = null;
            }
        }

        function armRequestsWheelGuard() {
            requestsWheelGuard = true;
            clearRequestsWheelGuardTimeout();
        }

        function releaseRequestsWheelGuard() {
            requestsWheelGuard = false;
            clearRequestsWheelGuardTimeout();
        }

        function refreshRequestsWheelGuard() {
            clearRequestsWheelGuardTimeout();
            requestsWheelGuardTimeoutId = window.setTimeout(function () {
                requestsWheelGuard = false;
                requestsWheelGuardTimeoutId = null;
            }, 140);
        }

        function setActiveSection(index, immediate) {
            const nextIndex = Math.max(0, Math.min(index, sections.length - 1));
            activeIndex = nextIndex;

            if (immediate) {
                viewport.style.transition = "none";
            }

            page.dataset.activeSection = sections[nextIndex].dataset.profileSection || String(nextIndex);
            sections.forEach(function (section, sectionIndex) {
                section.classList.toggle("is-active", sectionIndex === nextIndex);
            });

            if (immediate) {
                requestAnimationFrame(function () {
                    viewport.style.transition = "";
                });
            }
        }

        function transitionTo(index) {
            if (transitionLock || index === activeIndex) {
                return;
            }

            if (index === 1) {
                requestsScroll.scrollTop = 0;
                armRequestsWheelGuard();
            } else {
                releaseRequestsWheelGuard();
            }

            setActiveSection(index, false);
            setTransitionLock();
        }

        function canScrollRequestsUp() {
            return requestsScroll.scrollTop > 0;
        }

        function hasScrollableRequests() {
            return requestsScroll.scrollHeight > requestsScroll.clientHeight + 1;
        }

        function scrollRequestsBy(delta) {
            requestsScroll.scrollBy({
                top: delta,
                left: 0,
                behavior: "auto",
            });
        }

        function handleOverviewWheel(event) {
            event.preventDefault();

            if (transitionLock || Math.abs(event.deltaY) < 28) {
                return;
            }

            if (event.deltaY > 0) {
                transitionTo(1);
            }
        }

        function handleRequestsWheel(event) {
            if (Math.abs(event.deltaY) < 2) {
                return;
            }

            if (requestsWheelGuard) {
                event.preventDefault();
                refreshRequestsWheelGuard();
                return;
            }

            if (event.deltaY < 0 && !canScrollRequestsUp()) {
                event.preventDefault();
                transitionTo(0);
                return;
            }

            if (!event.target.closest("[data-profile-requests-scroll]") && hasScrollableRequests()) {
                event.preventDefault();
                scrollRequestsBy(event.deltaY);
                return;
            }
        }

        function handleKeydown(event) {
            if (isInteractiveTarget(event.target)) {
                return;
            }

            const scrollStep = Math.max(requestsScroll.clientHeight * 0.8, 160);
            const isForwardKey = event.key === "ArrowDown" || event.key === "PageDown" || (event.key === " " && !event.shiftKey);
            const isBackwardKey = event.key === "ArrowUp" || event.key === "PageUp" || (event.key === " " && event.shiftKey);

            if (activeIndex === 0) {
                if (isForwardKey) {
                    event.preventDefault();
                    transitionTo(1);
                }
                return;
            }

            if (isBackwardKey) {
                event.preventDefault();

                if (canScrollRequestsUp()) {
                    scrollRequestsBy(-scrollStep);
                    return;
                }

                transitionTo(0);
                return;
            }

            if (isForwardKey) {
                event.preventDefault();
                scrollRequestsBy(scrollStep);
            }
        }

        page.addEventListener("wheel", function (event) {
            if (isInteractiveTarget(event.target)) {
                return;
            }

            if (activeIndex === 0) {
                handleOverviewWheel(event);
                return;
            }

            handleRequestsWheel(event);
        }, { passive: false });

        page.addEventListener("touchstart", function (event) {
            if (!event.touches.length || isInteractiveTarget(event.target)) {
                return;
            }

            touchStartY = event.touches[0].clientY;
        }, { passive: true });

        page.addEventListener("touchend", function (event) {
            if (touchStartY === null || !event.changedTouches.length || transitionLock) {
                touchStartY = null;
                return;
            }

            const deltaY = touchStartY - event.changedTouches[0].clientY;
            touchStartY = null;

            if (Math.abs(deltaY) < 52) {
                return;
            }

            if (activeIndex === 0 && deltaY > 0) {
                transitionTo(1);
                return;
            }

            if (activeIndex === 1 && deltaY < 0 && !canScrollRequestsUp()) {
                transitionTo(0);
            }
        }, { passive: true });

        document.addEventListener("keydown", handleKeydown);

        pageMain.classList.add("is-profile-sections");
        page.classList.add("is-enhanced");
        setActiveSection(0, true);
    });
});
