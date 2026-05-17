(function () {
    "use strict";

    const SEARCH_DEBOUNCE_MS = 320;
    const FILTER_NAVIGATION_DELAY_MS = 300;
    const SCROLL_STORAGE_PREFIX = "preferences-readiness:scroll:";

    function getNavigation() {
        return window.KabinetNavigation || {};
    }

    function normalizeSearch(value) {
        return (value || "").trim().replace(/\s+/g, " ");
    }

    function navigateTo(url, options) {
        const nextOptions = options || {};
        if (url === window.location.href) {
            return;
        }
        if (nextOptions.focusSearch) {
            window.__preferenceReadinessFocusSearch = true;
        }
        const navigation = getNavigation();
        if (navigation && typeof navigation.navigate === "function" && navigation.navigate(url, true)) {
            return;
        }
        window.location.href = url;
    }

    function readInputSelection(input) {
        if (!input) {
            return null;
        }
        try {
            if (typeof input.selectionStart === "number" && typeof input.selectionEnd === "number") {
                return {
                    start: input.selectionStart,
                    end: input.selectionEnd,
                };
            }
        } catch (error) {
        }
        return null;
    }

    function clampSelection(selection, value) {
        const length = (value || "").length;
        const start = Math.max(0, Math.min(length, selection && Number.isFinite(selection.start) ? selection.start : length));
        const end = Math.max(0, Math.min(length, selection && Number.isFinite(selection.end) ? selection.end : start));
        return {
            start: start,
            end: end,
        };
    }

    function buildUrl(form, status, query) {
        const url = new URL(form.action || window.location.href, window.location.href);
        url.searchParams.set("status", status || "all");
        if (query) {
            url.searchParams.set("q", query);
        } else {
            url.searchParams.delete("q");
        }
        return url.href;
    }

    function getScrollStorageKey() {
        return SCROLL_STORAGE_PREFIX + window.location.pathname + window.location.search;
    }

    function initReadinessPage() {
        const root = document.querySelector("[data-page='preference-readiness']");
        if (!root) {
            return;
        }
        if (root.dataset.preferenceReadinessInitialized === "true") {
            return;
        }
        const previousController = window.__preferenceReadinessController;
        if (previousController) {
            previousController.abort();
        }
        const controller = new AbortController();
        const signal = controller.signal;
        window.__preferenceReadinessController = controller;
        root.dataset.preferenceReadinessInitialized = "true";

        const navigation = getNavigation();
        if (typeof navigation.rememberActiveCalendarPreferenceHref === "function") {
            navigation.rememberActiveCalendarPreferenceHref(window.location.href);
        }
        if (typeof navigation.syncSectionBackLinks === "function") {
            navigation.syncSectionBackLinks(root);
        }

        const filterForm = root.querySelector("[data-preference-readiness-filter]");
        const searchForm = root.querySelector("[data-preference-readiness-search]");
        const toolbar = root.querySelector(".preference-readiness-toolbar");
        const searchInput = searchForm ? searchForm.querySelector("[data-preference-readiness-search-input]") : null;
        const searchToggle = searchForm ? searchForm.querySelector("[data-preference-readiness-search-toggle]") : null;
        const searchClear = searchForm ? searchForm.querySelector("[data-preference-readiness-search-clear]") : null;
        const statusInput = searchForm ? searchForm.querySelector('input[type="hidden"][name="status"]') : null;
        const scrollRoot = root.querySelector(".preference-readiness-panel__scroll");
        const buttons = filterForm ? Array.from(filterForm.querySelectorAll("button[name='status']")) : [];
        let currentStatus = statusInput ? statusInput.value || "all" : "all";
        let currentSearch = normalizeSearch(searchInput ? searchInput.value : "");
        let searchTimer = null;
        let filterNavigationTimer = 0;
        let scrollStateTimer = 0;

        function rememberSearchSelection() {
            if (!searchInput) {
                return;
            }
            const selection = readInputSelection(searchInput);
            window.__preferenceReadinessSearchSelection = {
                value: currentSearch,
                selection: clampSelection(selection, currentSearch),
            };
        }

        function getSearchFocusSelection(shouldRestoreSelection) {
            const saved = shouldRestoreSelection ? window.__preferenceReadinessSearchSelection : null;
            if (saved && searchInput && saved.value === searchInput.value) {
                return clampSelection(saved.selection, searchInput.value);
            }
            return {
                start: searchInput ? searchInput.value.length : 0,
                end: searchInput ? searchInput.value.length : 0,
            };
        }

        function placeSearchCaret(shouldRestoreSelection) {
            if (!searchInput) {
                return;
            }
            const selection = getSearchFocusSelection(shouldRestoreSelection);
            try {
                searchInput.setSelectionRange(selection.start, selection.end);
            } catch (error) {
            }
        }

        function syncSearchDock() {
            if (!toolbar || !filterForm || !searchForm) {
                return;
            }
            const toolbarRect = toolbar.getBoundingClientRect();
            const filterRect = filterForm.getBoundingClientRect();
            const searchRect = searchForm.getBoundingClientRect();
            const collapsedWidth = Math.max(42, Math.round(searchRect.height || 48));
            const gap = 12;
            const left = Math.max(0, Math.round(filterRect.right - toolbarRect.left + gap));
            const maxWidth = Math.max(collapsedWidth, Math.floor(toolbarRect.right - toolbarRect.left - left));

            toolbar.style.setProperty("--readiness-search-left", left + "px");
            toolbar.style.setProperty("--readiness-search-max-width", maxWidth + "px");
        }

        function writeScrollState() {
            if (!scrollRoot) {
                return;
            }
            try {
                sessionStorage.setItem(getScrollStorageKey(), JSON.stringify({
                    top: scrollRoot.scrollTop,
                    left: scrollRoot.scrollLeft,
                }));
            } catch (error) {
            }
        }

        function flushScrollState() {
            if (scrollStateTimer) {
                window.clearTimeout(scrollStateTimer);
                scrollStateTimer = 0;
            }
            writeScrollState();
        }

        function scheduleScrollStateWrite() {
            if (scrollStateTimer) {
                window.clearTimeout(scrollStateTimer);
            }
            scrollStateTimer = window.setTimeout(function () {
                scrollStateTimer = 0;
                writeScrollState();
            }, 140);
        }

        function restoreScrollState() {
            if (!scrollRoot) {
                return;
            }
            let state = null;
            try {
                state = JSON.parse(sessionStorage.getItem(getScrollStorageKey()) || "null");
            } catch (error) {
                state = null;
            }
            if (!state) {
                return;
            }
            const top = Number(state.top) || 0;
            const left = Number(state.left) || 0;
            const applyScroll = function () {
                scrollRoot.scrollTop = top;
                scrollRoot.scrollLeft = left;
            };
            window.requestAnimationFrame(function () {
                applyScroll();
                window.requestAnimationFrame(applyScroll);
            });
            window.setTimeout(applyScroll, 90);
            window.setTimeout(applyScroll, 240);
            window.setTimeout(function () {
                scrollRoot.scrollTop = Number(state.top) || 0;
                scrollRoot.scrollLeft = Number(state.left) || 0;
            }, 420);
        }

        function setSearchOpen(isOpen) {
            if (!searchForm) {
                return;
            }
            const shouldOpen = Boolean(isOpen || currentSearch);
            searchForm.classList.toggle("is-open", shouldOpen);
            if (searchToggle) {
                searchToggle.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
            }
        }

        function syncSearchControls() {
            if (!searchForm) {
                return;
            }
            const hasFocus = searchForm.contains(document.activeElement);
            setSearchOpen(hasFocus || Boolean(currentSearch));
            if (searchClear) {
                searchClear.hidden = !currentSearch;
            }
            if (statusInput) {
                statusInput.value = currentStatus;
            }
        }

        function focusSearchInput(options) {
            if (!searchInput) {
                return;
            }
            const shouldRestoreSelection = Boolean(options && options.restoreSelection);
            searchInput.focus({ preventScroll: true });
            placeSearchCaret(shouldRestoreSelection);
            window.requestAnimationFrame(function () {
                searchInput.focus({ preventScroll: true });
                placeSearchCaret(shouldRestoreSelection);
                window.requestAnimationFrame(function () {
                    searchInput.focus({ preventScroll: true });
                    placeSearchCaret(shouldRestoreSelection);
                });
            });
        }

        function submitSearch() {
            if (!searchForm) {
                return;
            }
            window.clearTimeout(searchTimer);
            clearFilterNavigation();
            rememberSearchSelection();
            navigateTo(buildUrl(searchForm, currentStatus, currentSearch), { focusSearch: true });
        }

        function scheduleSearch() {
            window.clearTimeout(searchTimer);
            clearFilterNavigation();
            searchTimer = window.setTimeout(submitSearch, SEARCH_DEBOUNCE_MS);
        }

        function clearFilterNavigation() {
            if (filterNavigationTimer) {
                window.clearTimeout(filterNavigationTimer);
                filterNavigationTimer = 0;
            }
        }

        function scheduleFilterNavigation(url) {
            clearFilterNavigation();
            filterNavigationTimer = window.setTimeout(function () {
                filterNavigationTimer = 0;
                navigateTo(url);
            }, FILTER_NAVIGATION_DELAY_MS);
        }

        if (filterForm && buttons.length) {
            buttons.forEach(function (button) {
                button.addEventListener("click", function () {
                    window.clearTimeout(searchTimer);
                    const nextStatus = button.value || "all";
                    currentStatus = nextStatus;
                    buttons.forEach(function (item) {
                        item.classList.toggle("active", item === button);
                    });
                    if (window.KabinetSegmented && typeof window.KabinetSegmented.sync === "function") {
                        window.KabinetSegmented.sync(filterForm, button);
                    }
                    syncSearchControls();
                    scheduleFilterNavigation(buildUrl(filterForm, nextStatus, currentSearch));
                }, { signal: signal });
            });
        }

        if (searchForm && searchInput) {
            searchForm.addEventListener("submit", function (event) {
                event.preventDefault();
                currentSearch = normalizeSearch(searchInput.value);
                searchInput.value = currentSearch;
                rememberSearchSelection();
                syncSearchControls();
                submitSearch();
            }, { signal: signal });

            searchInput.addEventListener("input", function () {
                currentSearch = normalizeSearch(searchInput.value);
                rememberSearchSelection();
                syncSearchControls();
                scheduleSearch();
            }, { signal: signal });

            searchForm.addEventListener("focusout", function () {
                window.setTimeout(syncSearchControls, 0);
            }, { signal: signal });
        }

        if (searchToggle && searchInput) {
            searchToggle.addEventListener("pointerdown", function (event) {
                event.preventDefault();
                setSearchOpen(true);
                focusSearchInput();
            }, { signal: signal });

            searchToggle.addEventListener("click", function () {
                setSearchOpen(true);
                focusSearchInput();
            }, { signal: signal });
        }

        if (searchClear && searchInput) {
            searchClear.addEventListener("click", function () {
                searchInput.value = "";
                currentSearch = "";
                syncSearchControls();
                submitSearch();
                focusSearchInput();
            }, { signal: signal });
        }

        if (scrollRoot) {
            scrollRoot.addEventListener("scroll", scheduleScrollStateWrite, { passive: true, signal: signal });
            restoreScrollState();
        }

        document.addEventListener("app:before-navigation", flushScrollState, { signal: signal });
        signal.addEventListener("abort", function () {
            window.clearTimeout(searchTimer);
            clearFilterNavigation();
            if (scrollStateTimer) {
                window.clearTimeout(scrollStateTimer);
            }
        }, { once: true });

        syncSearchDock();
        window.addEventListener("resize", syncSearchDock, { signal: signal });
        if ("ResizeObserver" in window && toolbar && filterForm) {
            const resizeObserver = new ResizeObserver(syncSearchDock);
            resizeObserver.observe(toolbar);
            resizeObserver.observe(filterForm);
            signal.addEventListener("abort", function () {
                resizeObserver.disconnect();
            }, { once: true });
        }

        if (filterForm && window.KabinetSegmented && typeof window.KabinetSegmented.sync === "function") {
            window.KabinetSegmented.sync(filterForm);
        }
        syncSearchControls();
        if (window.__preferenceReadinessFocusSearch) {
            window.__preferenceReadinessFocusSearch = false;
            setSearchOpen(true);
            focusSearchInput({ restoreSelection: true });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initReadinessPage, { once: true });
    } else {
        initReadinessPage();
    }

    document.addEventListener("app:navigation", initReadinessPage);
})();
