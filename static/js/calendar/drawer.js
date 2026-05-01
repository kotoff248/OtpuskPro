(function () {
    "use strict";

    const Calendar = window.KabinetCalendar || {};
    window.KabinetCalendar = Calendar;

    Calendar.createDrawerController = function (context, dependencies) {
        const signal = context.signal;
        let focusHighlightTimeout = null;
        let currentUpcomingAnchor = null;

        function getBoardScrollElement() {
            return document.querySelector("[data-calendar-grid-body]") || document.querySelector(".calendar-board-scroll");
        }

        function clearEntryHighlights() {
            document.querySelectorAll(".is-calendar-entry-highlight").forEach(function (element) {
                element.classList.remove("is-calendar-entry-highlight");
            });
        }

        function dateToComparable(value) {
            return String(value || "");
        }

        function getMonthNumber(value) {
            const parts = String(value || "").split("-");
            return Number(parts[1]) || 0;
        }

        function escapeSelectorValue(value) {
            if (window.CSS && typeof CSS.escape === "function") {
                return CSS.escape(value);
            }

            return String(value).replace(/"/g, '\\"');
        }

        function focusAnchorInCalendar(anchor) {
            if (!anchor) {
                return;
            }

            const employeeId = String(anchor.employee_id || "");
            const startDate = dateToComparable(anchor.start_date);
            const endDate = dateToComparable(anchor.end_date);
            const row = document.querySelector('[data-employee-id="' + escapeSelectorValue(employeeId) + '"]');

            closeDetailModal();
            clearEntryHighlights();
            if (!row) {
                return;
            }

            row.classList.add("is-calendar-entry-highlight");
            const dateCells = Array.from(row.querySelectorAll("[data-calendar-date]"));
            if (dateCells.length) {
                dateCells.forEach(function (cell) {
                    const cellDate = dateToComparable(cell.dataset.calendarDate);
                    if (cellDate >= startDate && cellDate <= endDate) {
                        cell.classList.add("is-calendar-entry-highlight");
                    }
                });
            } else {
                const startMonth = getMonthNumber(startDate);
                const endMonth = getMonthNumber(endDate);
                row.querySelectorAll("[data-calendar-month]").forEach(function (cell) {
                    const month = Number(cell.dataset.calendarMonth || 0);
                    if (month >= startMonth && month <= endMonth) {
                        cell.classList.add("is-calendar-entry-highlight");
                    }
                });
            }

            if (getBoardScrollElement() && typeof row.scrollIntoView === "function") {
                row.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
            }

            if (focusHighlightTimeout) {
                window.clearTimeout(focusHighlightTimeout);
            }
            focusHighlightTimeout = window.setTimeout(clearEntryHighlights, 1900);
        }

        function focusEntryInCalendar(item) {
            if (!item || !item.anchor) {
                return;
            }

            focusAnchorInCalendar(item.anchor);
        }

        function updateIssueSummary(detail) {
            if (!context.detailIssue) {
                return;
            }

            const hasConflict = Boolean(detail.has_conflict);
            const hasHighRisk = Boolean(detail.has_high_risk);
            context.detailIssue.classList.toggle("calendar-drawer__issue--conflict", hasConflict);
            context.detailIssue.classList.toggle("calendar-drawer__issue--risk", !hasConflict && hasHighRisk);
            context.detailIssue.classList.toggle("calendar-drawer__issue--clear", !hasConflict && !hasHighRisk);

            const icon = context.detailIssue.querySelector(".calendar-drawer__issue-icon");
            if (icon) {
                icon.innerHTML = hasConflict
                    ? '<span class="calendar-drawer__issue-symbol" aria-hidden="true">⚔</span>'
                    : '<span class="material-icons-sharp" aria-hidden="true">' + (hasHighRisk ? "bolt" : "check_circle") + '</span>';
            }
            if (context.detailIssueLabel) {
                context.detailIssueLabel.textContent = detail.issue_label || "Проблем нет";
            }
            if (context.detailIssueDescription) {
                context.detailIssueDescription.textContent = detail.issue_description || "В выбранном периоде критичных проблем не найдено.";
            }
        }

        function appendRiskLine(container, item) {
            const risk = document.createElement("span");
            risk.className = "calendar-drawer__entry-risk";
            if (item.has_conflict) {
                risk.classList.add("calendar-drawer__entry-risk--conflict");
            } else if (item.has_high_risk) {
                risk.classList.add("calendar-drawer__entry-risk--high");
            }

            risk.textContent = "Риск: " + (item.risk_label || "Низкий")
                + (item.risk_score ? " · " + item.risk_score + "%" : "")
                + (item.conflict_summary ? " · " + item.conflict_summary : "");
            container.appendChild(risk);
        }

        function renderEntriesSafe(container, entries, emptyText) {
            if (!container) {
                return;
            }

            container.innerHTML = "";
            if (!entries.length) {
                const placeholder = document.createElement("p");
                placeholder.className = "calendar-detail-placeholder";
                placeholder.textContent = emptyText;
                container.appendChild(placeholder);
                return;
            }

            entries.forEach(function (item) {
                const article = document.createElement("article");
                article.className = "calendar-drawer__entry status-" + item.status;

                const main = document.createElement("div");
                main.className = "calendar-drawer__entry-main";
                const strong = document.createElement("strong");
                strong.textContent = item.period_label;
                const type = document.createElement("span");
                type.textContent = (item.source_label ? item.source_label + " • " : "") + item.vacation_type_label;
                main.appendChild(strong);
                main.appendChild(type);
                appendRiskLine(main, item);

                const side = document.createElement("div");
                side.className = "calendar-drawer__entry-side";
                const status = document.createElement("span");
                status.textContent = item.status_label;
                const days = document.createElement("strong");
                days.textContent = item.days + " д.";
                side.appendChild(status);
                side.appendChild(days);

                if (item.detail_url) {
                    const detailAction = document.createElement("a");
                    detailAction.className = "calendar-drawer__entry-action calendar-drawer__entry-action--link";
                    detailAction.href = item.detail_url;
                    detailAction.dataset.appLink = "";
                    detailAction.textContent = item.detail_label || "Открыть заявку";
                    side.appendChild(detailAction);
                }

                if (item.can_request_transfer && item.transfer_url) {
                    const action = document.createElement("button");
                    action.type = "button";
                    action.className = "calendar-drawer__entry-action";
                    action.dataset.transferOpen = "";
                    action.dataset.transferUrl = item.transfer_url;
                    action.dataset.transferTitle = item.transfer_title || item.period_label;
                    action.textContent = "Запросить перенос";
                    side.appendChild(action);
                }

                const focusAction = document.createElement("button");
                focusAction.type = "button";
                focusAction.className = "calendar-drawer__entry-action calendar-drawer__entry-action--ghost";
                focusAction.dataset.calendarFocusEntry = "";
                focusAction.textContent = "Показать в графике";
                focusAction.addEventListener("click", function () {
                    focusEntryInCalendar(item);
                }, { signal: signal });
                side.appendChild(focusAction);

                article.appendChild(main);
                article.appendChild(side);
                container.appendChild(article);
            });
        }

        function openDetailModal() {
            if (!context.detailModal) {
                return;
            }

            dependencies.closeVacationModal();
            dependencies.closeCustomSelects();
            window.appModal.open(context.detailModal);
        }

        function closeDetailModal() {
            if (!context.detailModal) {
                return;
            }

            window.appModal.close(context.detailModal);
        }

        function updateDetailCard(employeeId) {
            const detail = context.detailsData[String(employeeId)];
            if (!detail) {
                return;
            }

            context.rows.forEach(function (row) {
                row.classList.toggle("is-active", row.dataset.employeeId === String(employeeId));
            });

            context.detailName.textContent = detail.employee_name;
            context.detailMeta.textContent = [
                detail.position,
                detail.department,
                detail.production_group,
            ].filter(Boolean).join(" • ");
            if (context.detailProfileLink) {
                if (detail.profile_url) {
                    context.detailProfileLink.href = detail.profile_url;
                    context.detailProfileLink.classList.remove("is-hidden");
                } else {
                    context.detailProfileLink.href = "#";
                    context.detailProfileLink.classList.add("is-hidden");
                }
            }
            context.detailPeriod.textContent = detail.selected_period_label;
            context.detailSchedule.textContent = detail.selected_schedule_days + " д.";
            context.detailRequests.textContent = detail.selected_request_days + " д.";
            context.detailChanged.textContent = detail.selected_changed_days + " д.";
            context.detailUpcoming.textContent = detail.upcoming_label;
            context.detailUpcomingStatus.textContent = detail.upcoming_status || "";
            currentUpcomingAnchor = detail.upcoming_anchor || null;
            if (context.detailUpcomingAction) {
                context.detailUpcomingAction.classList.toggle("is-hidden", !currentUpcomingAnchor);
            }
            updateIssueSummary(detail);
            renderEntriesSafe(context.selectedList, detail.selected_entries || [], "В выбранном периоде отпусков нет.");
            renderEntriesSafe(context.yearList, detail.year_entries || [], "За этот год записей пока нет.");
            openDetailModal();
        }

        function bindRows() {
            context.rows = Array.from(document.querySelectorAll("[data-employee-id]"));
            context.rows.forEach(function (row) {
                row.addEventListener("click", function (event) {
                    if (event.target.closest("a, button")) {
                        return;
                    }
                    updateDetailCard(row.dataset.employeeId);
                }, { signal: signal });
                row.addEventListener("keydown", function (event) {
                    if (event.target.closest("a, button")) {
                        return;
                    }
                    if (event.key !== "Enter" && event.key !== " ") {
                        return;
                    }

                    event.preventDefault();
                    updateDetailCard(row.dataset.employeeId);
                }, { signal: signal });
            });
        }

        if (context.detailUpcomingAction) {
            context.detailUpcomingAction.addEventListener("click", function () {
                focusAnchorInCalendar(currentUpcomingAnchor);
            }, { signal: signal });
        }

        function updateDetailsData(nextDetailsData) {
            context.detailsData = nextDetailsData || {};
            if (context.detailsDataNode) {
                context.detailsDataNode.textContent = JSON.stringify(context.detailsData);
            }
        }

        return {
            bindRows: bindRows,
            updateDetailsData: updateDetailsData,
            closeDetailModal: closeDetailModal,
            closeCalendarDetailDrawer: closeDetailModal,
        };
    };
})();
