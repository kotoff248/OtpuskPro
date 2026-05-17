(function () {
    "use strict";

    if (window.__scheduleStatusTooltipInitialized) {
        return;
    }
    window.__scheduleStatusTooltipInitialized = true;

    let tooltip = null;
    let activeTarget = null;

    function ensureTooltip() {
        if (tooltip) {
            return tooltip;
        }

        tooltip = document.createElement("div");
        tooltip.className = "schedule-status-tooltip";
        tooltip.setAttribute("role", "tooltip");
        tooltip.innerHTML = [
            '<strong class="schedule-status-tooltip__title"></strong>',
            '<span class="schedule-status-tooltip__text"></span>',
        ].join("");
        document.body.appendChild(tooltip);
        return tooltip;
    }

    function getTarget(element) {
        return element instanceof Element
            ? element.closest("[data-schedule-status-tooltip]")
            : null;
    }

    function clearVariantClasses(node) {
        Array.from(node.classList).forEach(function (className) {
            if (className.indexOf("schedule-status-tooltip--") === 0) {
                node.classList.remove(className);
            }
        });
    }

    function placeTooltip(node, target) {
        const targetRect = target.getBoundingClientRect();
        const tooltipRect = node.getBoundingClientRect();
        const gap = 10;
        let left = targetRect.left + (targetRect.width / 2) - (tooltipRect.width / 2);
        let top = targetRect.bottom + gap;

        left = Math.max(12, Math.min(left, window.innerWidth - tooltipRect.width - 12));
        if (top + tooltipRect.height + 12 > window.innerHeight) {
            top = targetRect.top - tooltipRect.height - gap;
        }
        top = Math.max(12, top);

        node.style.left = left + "px";
        node.style.top = top + "px";
    }

    function showTooltip(target) {
        if (!target || !target.dataset.tooltipText) {
            return;
        }

        activeTarget = target;
        const node = ensureTooltip();
        const title = node.querySelector(".schedule-status-tooltip__title");
        const text = node.querySelector(".schedule-status-tooltip__text");
        if (title) {
            title.textContent = target.dataset.tooltipTitle || "";
        }
        if (text) {
            text.textContent = target.dataset.tooltipText || "";
        }

        clearVariantClasses(node);
        node.classList.add("schedule-status-tooltip--" + (target.dataset.scheduleStatusVariant || "empty"));
        node.classList.add("is-visible");
        placeTooltip(node, target);
    }

    function hideTooltip() {
        activeTarget = null;
        if (tooltip) {
            tooltip.classList.remove("is-visible");
        }
    }

    document.addEventListener("pointerover", function (event) {
        const target = getTarget(event.target);
        if (!target || target === activeTarget) {
            return;
        }
        showTooltip(target);
    });

    document.addEventListener("pointerout", function (event) {
        const target = getTarget(event.target);
        if (!target || (event.relatedTarget instanceof Node && target.contains(event.relatedTarget))) {
            return;
        }
        hideTooltip();
    });

    document.addEventListener("focusin", function (event) {
        const target = getTarget(event.target);
        if (target) {
            showTooltip(target);
        }
    });

    document.addEventListener("focusout", function (event) {
        const target = getTarget(event.target);
        if (target) {
            hideTooltip();
        }
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
            hideTooltip();
        }
    });

    window.addEventListener("scroll", hideTooltip, true);
    window.addEventListener("resize", hideTooltip);
})();
