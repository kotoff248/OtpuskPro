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
    const deleteModal = document.getElementById("notification-delete-modal");
    const deleteForm = document.getElementById("notification-delete-form");
    const deleteIdInput = deleteForm ? deleteForm.querySelector("[data-notification-delete-id]") : null;
    const deleteTitleNode = deleteModal ? deleteModal.querySelector("[data-notification-delete-title]") : null;

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

    function updateSidebarUnreadCount(unreadCount) {
        if (typeof unreadCount !== "number") {
            return;
        }

        const link = document.querySelector('[data-sidebar-key="notifications"]');
        if (!link) {
            return;
        }

        let side = link.querySelector(".sidebar__link-side");
        let badge = side ? side.querySelector(".message-count") : null;
        if (unreadCount > 0) {
            if (!side) {
                side = document.createElement("span");
                side.className = "sidebar__link-side";
                link.appendChild(side);
            }
            if (!badge) {
                badge = document.createElement("span");
                badge.className = "message-count";
                side.appendChild(badge);
            }
            badge.textContent = String(unreadCount);
            return;
        }

        if (side) {
            side.remove();
        }
    }

    function getNotificationCardId(card) {
        return card ? card.getAttribute("data-notification-card") : "";
    }

    function getNotificationScrollAnchor(form) {
        const card = form ? form.closest("[data-notification-card]") : null;
        const previousCard = card ? card.previousElementSibling : null;
        const nextCard = card ? card.nextElementSibling : null;
        return {
            listScrollTop: list.scrollTop,
            windowScrollX: window.scrollX,
            windowScrollY: window.scrollY,
            cardId: getNotificationCardId(card),
            previousId: getNotificationCardId(previousCard),
            nextId: getNotificationCardId(nextCard),
            cardTop: card ? card.getBoundingClientRect().top : null,
        };
    }

    function findNotificationAnchorCard(anchor) {
        if (!anchor) {
            return null;
        }

        const ids = [anchor.cardId, anchor.nextId, anchor.previousId].filter(Boolean);
        for (let index = 0; index < ids.length; index += 1) {
            const card = list.querySelector('[data-notification-card="' + ids[index] + '"]');
            if (card) {
                return card;
            }
        }
        return null;
    }

    function restoreNotificationScroll(anchor) {
        if (!anchor) {
            return;
        }

        list.scrollTop = anchor.listScrollTop;
        window.scrollTo(anchor.windowScrollX, anchor.windowScrollY);

        const anchorCard = findNotificationAnchorCard(anchor);
        if (anchorCard && anchor.cardTop !== null) {
            const delta = anchorCard.getBoundingClientRect().top - anchor.cardTop;
            if (Math.abs(delta) > 0.5) {
                if (list.scrollHeight > list.clientHeight) {
                    list.scrollTop += delta;
                } else {
                    window.scrollBy(0, delta);
                }
            }
        }
    }

    function renderNotifications(data, options) {
        const shouldResetScroll = !options || options.resetScroll !== false;
        const anchor = options ? options.anchor : null;

        list.innerHTML = data.notifications_html || "";
        updateCounts(data.counts);
        updateSidebarUnreadCount(data.unread_count);
        updateUrl(data.filter || currentFilter);
        if (shouldResetScroll) {
            resetListScroll();
            return;
        }

        restoreNotificationScroll(anchor);
        window.requestAnimationFrame(function () {
            restoreNotificationScroll(anchor);
        });
    }

    function parseNotificationsHtml(html) {
        const template = document.createElement("template");
        template.innerHTML = html || "";
        return template.content;
    }

    function findUpdatedNotificationCard(data, cardId) {
        if (!cardId || !data || !data.notifications_html) {
            return null;
        }

        const fragment = parseNotificationsHtml(data.notifications_html);
        return fragment.querySelector('[data-notification-card="' + cardId + '"]');
    }

    function getActionCard(form, formData) {
        if (form && list.contains(form)) {
            return form.closest("[data-notification-card]");
        }

        const notificationId = formData ? formData.get("notification_id") : "";
        if (!notificationId) {
            return null;
        }

        return list.querySelector('[data-notification-card="' + notificationId + '"]');
    }

    function replaceNotificationCard(currentCard, updatedCard, actionValue) {
        if (!currentCard || !updatedCard) {
            return;
        }

        const cardHeight = currentCard.getBoundingClientRect().height;
        currentCard.style.minHeight = cardHeight + "px";
        currentCard.className = updatedCard.className;
        currentCard.innerHTML = updatedCard.innerHTML;
        animateInsertedCompanionAction(currentCard, actionValue);
        window.requestAnimationFrame(function () {
            currentCard.style.minHeight = "";
        });
    }

    function removeNotificationCard(card, data) {
        if (card) {
            card.remove();
        }

        if (!list.querySelector("[data-notification-card]")) {
            list.innerHTML = data && data.notifications_html ? data.notifications_html : "";
        }
    }

    function applyNotificationActionResult(form, formData, data, options) {
        updateCounts(data.counts);
        updateSidebarUnreadCount(data.unread_count);
        updateUrl(data.filter || currentFilter);

        const card = getActionCard(form, formData);
        const cardId = getNotificationCardId(card);
        const actionValue = formData.get("action");
        const updatedCard = findUpdatedNotificationCard(data, cardId);

        if (actionValue === "delete" || !updatedCard) {
            removeNotificationCard(card, data);
        } else {
            replaceNotificationCard(card, updatedCard, actionValue);
        }

        if (options && options.closeModal && deleteModal && window.appModal && typeof window.appModal.close === "function") {
            window.appModal.close(deleteModal);
        }
    }

    function updateUrl(filterValue) {
        const params = new URLSearchParams(window.location.search);
        params.set("filter", filterValue);
        const query = params.toString();
        window.history.replaceState({}, "", query ? window.location.pathname + "?" + query : window.location.pathname);
        rememberListHref();
    }

    function getCurrentPostAction() {
        const url = new URL(window.location.href);
        url.searchParams.set("filter", currentFilter);
        return url.pathname + "?" + url.searchParams.toString();
    }

    function openDeleteModal(trigger) {
        if (!trigger || !deleteModal || !deleteForm || !deleteIdInput) {
            return;
        }

        deleteIdInput.value = trigger.dataset.notificationId || "";
        deleteForm.action = getCurrentPostAction();

        if (deleteTitleNode) {
            const title = trigger.dataset.notificationTitle || "";
            deleteTitleNode.hidden = false;
            deleteTitleNode.textContent = title || "Выбранное уведомление";
        }

        if (window.appModal && typeof window.appModal.open === "function") {
            window.appModal.open(deleteModal);
        }
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
                renderNotifications(data, { resetScroll: true });
            })
            .catch(function (error) {
                if (error.name === "AbortError") {
                    return;
                }
                console.error("Error fetching notifications:", error);
            });
    }

    function getActionAnimationInfo(actionValue) {
        if (actionValue === "mark_read") {
            return {
                mode: "shrink",
                formClass: "is-transforming-to-unread",
                icon: "mark_email_unread",
                variantClass: "notification-action--unread",
            };
        }
        if (actionValue === "mark_done") {
            return {
                mode: "shrink",
                formClass: "is-transforming-to-undone",
                icon: "close",
                variantClass: "notification-action--undo-done",
            };
        }
        if (actionValue === "mark_unread") {
            return {
                mode: "expand",
                icon: "drafts",
                label: "Прочитано",
                variantClass: "notification-action--read",
            };
        }
        if (actionValue === "mark_active") {
            return {
                mode: "expand",
                icon: "check_circle",
                label: "Выполнено",
                variantClass: "notification-action--done",
            };
        }
        return null;
    }

    function getActionValue(form) {
        const input = form ? form.querySelector('input[name="action"]') : null;
        return input ? input.value : "";
    }

    function getCompactActionWidth() {
        const rootFontSize = parseFloat(window.getComputedStyle(document.documentElement).fontSize) || 16;
        return rootFontSize * 2.25;
    }

    function findActionForm(card, actionValues, excludedForm) {
        if (!card) {
            return null;
        }

        const values = Array.isArray(actionValues) ? actionValues : [actionValues];
        return Array.from(card.querySelectorAll("[data-notification-action-form]")).find(function (candidate) {
            return candidate !== excludedForm && values.includes(getActionValue(candidate));
        }) || null;
    }

    function getActionLabel(button) {
        return Array.from(button.children).find(function (child) {
            return !child.classList.contains("material-icons-sharp");
        });
    }

    function setActionLabel(button, labelText) {
        let label = getActionLabel(button);
        if (!label && labelText) {
            label = document.createElement("span");
            button.appendChild(label);
        }
        if (label) {
            label.textContent = labelText || "";
        }
    }

    function setActionVariant(button, variantClass) {
        [
            "notification-action--read",
            "notification-action--unread",
            "notification-action--done",
            "notification-action--undo-done",
        ].forEach(function (className) {
            button.classList.remove(className);
        });

        if (variantClass) {
            button.classList.add(variantClass);
        }
    }

    function measureExpandedActionWidth(button, info) {
        const clone = button.cloneNode(true);
        clone.classList.remove("notification-action--icon");
        setActionVariant(clone, info.variantClass);
        setActionLabel(clone, info.label);

        const icon = clone.querySelector(".material-icons-sharp");
        if (icon && info.icon) {
            icon.textContent = info.icon;
        }

        clone.style.position = "absolute";
        clone.style.visibility = "hidden";
        clone.style.pointerEvents = "none";
        clone.style.width = "auto";
        clone.style.minWidth = "0";
        clone.style.maxWidth = "none";
        clone.style.transition = "none";
        document.body.appendChild(clone);
        const width = clone.getBoundingClientRect().width;
        clone.remove();
        return width;
    }

    function collapseCompanionAction(form) {
        const button = form ? form.querySelector(".notification-action") : null;
        if (!button) {
            return;
        }

        const width = button.getBoundingClientRect().width;
        form.style.width = width + "px";
        form.style.minWidth = width + "px";
        button.style.width = width + "px";
        button.style.minWidth = width + "px";

        button.getBoundingClientRect();
        form.classList.add("is-companion-collapsing");
        window.requestAnimationFrame(function () {
            form.style.width = "0px";
            form.style.minWidth = "0px";
            button.style.width = "0px";
            button.style.minWidth = "0px";
        });
    }

    function collapseRelatedActions(form, actionValue) {
        if (actionValue !== "mark_done") {
            return;
        }

        const card = form.closest("[data-notification-card]");
        const readToggle = findActionForm(card, ["mark_read", "mark_unread"], form);
        collapseCompanionAction(readToggle);
    }

    function animateInsertedCompanionAction(card, actionValue) {
        if (actionValue !== "mark_active") {
            return;
        }

        const form = findActionForm(card, "mark_unread", null);
        const button = form ? form.querySelector(".notification-action") : null;
        if (!button) {
            return;
        }

        const targetWidth = getCompactActionWidth();
        form.style.width = "0px";
        form.style.minWidth = "0px";
        button.style.width = "0px";
        button.style.minWidth = "0px";
        form.classList.add("is-companion-entering");

        button.getBoundingClientRect();
        window.requestAnimationFrame(function () {
            form.classList.remove("is-companion-entering");
            form.style.width = targetWidth + "px";
            form.style.minWidth = targetWidth + "px";
            button.style.width = targetWidth + "px";
            button.style.minWidth = targetWidth + "px";

            window.setTimeout(function () {
                form.style.width = "";
                form.style.minWidth = "";
                button.style.width = "";
                button.style.minWidth = "";
            }, 260);
        });
    }

    function prepareActionButtonAnimation(form, formData) {
        const actionValue = formData.get("action");
        const info = getActionAnimationInfo(actionValue);
        const button = form.querySelector(".notification-action");
        if (!info || !button) {
            return 0;
        }

        const icon = button.querySelector(".material-icons-sharp");
        if (icon && info.icon) {
            icon.textContent = info.icon;
        }

        const startWidth = button.getBoundingClientRect().width;
        const targetWidth = info.mode === "expand" ? measureExpandedActionWidth(button, info) : getCompactActionWidth();

        form.style.width = startWidth + "px";
        form.style.minWidth = startWidth + "px";
        button.style.width = startWidth + "px";
        button.style.minWidth = startWidth + "px";

        if (info.mode === "expand") {
            button.classList.remove("notification-action--icon");
            setActionVariant(button, info.variantClass);
            setActionLabel(button, info.label);
            form.classList.add("is-transforming-to-full");
        } else {
            setActionVariant(button, info.variantClass);
            form.classList.add("is-transforming-to-icon");
        }
        if (info.formClass) {
            form.classList.add(info.formClass);
        }

        button.getBoundingClientRect();
        collapseRelatedActions(form, actionValue);
        window.requestAnimationFrame(function () {
            form.style.width = targetWidth + "px";
            form.style.minWidth = targetWidth + "px";
            button.style.width = targetWidth + "px";
            button.style.minWidth = targetWidth + "px";
        });

        return 300;
    }

    function waitForActionAnimation(delay) {
        return new Promise(function (resolve) {
            window.setTimeout(resolve, delay);
        });
    }

    function submitNotificationAction(form, options) {
        if (!form) {
            return;
        }

        const anchor = getNotificationScrollAnchor(form);
        const formData = new FormData(form);
        const animationDelay = prepareActionButtonAnimation(form, formData);
        const actionUrl = new URL(form.getAttribute("action") || getCurrentPostAction(), window.location.origin);
        actionUrl.searchParams.set("filter", currentFilter);

        form.classList.add("is-submitting");
        const request = fetch(actionUrl.toString(), {
            method: "POST",
            body: formData,
            headers: {
                "X-Requested-With": "XMLHttpRequest",
            },
            signal: signal,
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("Notification action failed: " + response.status);
                }
                return response.json();
            });

        Promise.all([request, waitForActionAnimation(animationDelay)])
            .then(function (results) {
                const data = results[0];
                applyNotificationActionResult(form, formData, data, options);
                restoreNotificationScroll(anchor);
            })
            .catch(function (error) {
                if (error.name === "AbortError") {
                    return;
                }
                console.error("Error updating notification:", error);
            })
            .finally(function () {
                form.classList.remove("is-submitting");
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

    list.addEventListener("click", function (event) {
        const trigger = event.target.closest("[data-notification-delete-open]");
        if (!trigger || !list.contains(trigger)) {
            return;
        }

        event.preventDefault();
        openDeleteModal(trigger);
    }, { signal: signal });

    list.addEventListener("submit", function (event) {
        const form = event.target.closest("[data-notification-action-form]");
        if (!form || !list.contains(form)) {
            return;
        }

        event.preventDefault();
        submitNotificationAction(form);
    }, { signal: signal });

    if (deleteForm) {
        deleteForm.addEventListener("submit", function (event) {
            event.preventDefault();
            submitNotificationAction(deleteForm, { closeModal: true });
        }, { signal: signal });
    }

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
