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

            const riskDetails = detail.risk_details || {};
            const status = riskDetails.status || (detail.has_conflict ? "conflict" : (detail.has_high_risk ? "risk" : "clear"));
            const hasConflict = status === "conflict" || Boolean(detail.has_conflict);
            const hasHighRisk = status === "risk" || Boolean(detail.has_high_risk);
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
                context.detailIssueLabel.textContent = riskDetails.label || detail.issue_label || "Проблем нет";
            }
            if (context.detailIssueDescription) {
                context.detailIssueDescription.textContent = riskDetails.summary || detail.issue_description || "В выбранном периоде критичных проблем не найдено.";
            }
            renderRiskReasons(riskDetails.problems || riskDetails.reasons || []);
        }

        function renderRiskReasons(problems) {
            if (!context.detailIssueReasons) {
                return;
            }

            const safeProblems = Array.isArray(problems) ? problems : [];
            context.detailIssueReasons.innerHTML = "";
            context.detailIssueReasons.classList.toggle("is-empty", !safeProblems.length);

            safeProblems.forEach(function (problem) {
                const item = document.createElement("article");
                item.className = "calendar-drawer__issue-problem calendar-drawer__issue-problem--" + (problem.kind || "risk");

                const head = document.createElement("div");
                head.className = "calendar-drawer__issue-problem-head";
                if (problem.period_label) {
                    const period = document.createElement("span");
                    period.className = "calendar-drawer__issue-period";
                    period.textContent = problem.period_label;
                    head.appendChild(period);
                }
                const title = document.createElement("strong");
                title.textContent = problem.title || "Риск состава";
                head.appendChild(title);

                const text = document.createElement("p");
                text.textContent = problem.text || problem.summary || "";

                const meta = document.createElement("div");
                meta.className = "calendar-drawer__issue-problem-meta";
                [problem.impact_label, problem.substitution_label].forEach(function (label) {
                    if (!label) {
                        return;
                    }
                    const chip = document.createElement("span");
                    chip.textContent = label;
                    meta.appendChild(chip);
                });

                item.appendChild(head);
                item.appendChild(text);
                if (meta.childElementCount) {
                    item.appendChild(meta);
                }
                if (Array.isArray(problem.affected_names) && problem.affected_names.length) {
                    const affected = document.createElement("div");
                    affected.className = "calendar-drawer__issue-affected";
                    const affectedLabel = document.createElement("span");
                    affectedLabel.textContent = "Отсутствуют:";
                    const affectedNames = document.createElement("strong");
                    affectedNames.textContent = problem.affected_names.join(", ")
                        + (problem.extra_affected_count ? " + еще " + problem.extra_affected_count : "");
                    affected.appendChild(affectedLabel);
                    affected.appendChild(affectedNames);
                    item.appendChild(affected);
                }
                context.detailIssueReasons.appendChild(item);
            });
        }

        function updateProfileLink(detail) {
            if (!context.detailProfileLink) {
                return;
            }

            const link = context.detailProfileLink;
            const roleVariant = detail.role_variant || "employee";
            const roleLabel = detail.role_label || "";
            const employeeName = detail.employee_name || "сотрудника";

            Array.from(link.classList).forEach(function (className) {
                if (className.indexOf("calendar-drawer__profile-link--") === 0) {
                    link.classList.remove(className);
                }
            });
            link.classList.add("calendar-drawer__profile-link--" + roleVariant);

            if (detail.profile_url) {
                link.href = detail.profile_url;
                link.classList.remove("is-hidden");
            } else {
                link.href = "#";
                link.classList.add("is-hidden");
            }

            link.title = "Открыть профиль сотрудника " + employeeName;
            link.setAttribute(
                "aria-label",
                "Открыть профиль сотрудника " + employeeName + (roleLabel ? ". " + roleLabel : "")
            );
            link.innerHTML = "";

            const icon = document.createElement("span");
            icon.className = detail.role_icon_type === "symbol"
                ? "calendar-drawer__profile-symbol"
                : "material-icons-sharp";
            icon.setAttribute("aria-hidden", "true");
            icon.textContent = detail.role_icon || "person";
            link.appendChild(icon);
        }

        function renderManagementBadges(badges) {
            if (!context.detailManagementBadges) {
                return;
            }

            const safeBadges = Array.isArray(badges) ? badges : [];
            context.detailManagementBadges.innerHTML = "";
            context.detailManagementBadges.classList.toggle("is-empty", !safeBadges.length);

            safeBadges.forEach(function (badge) {
                const item = document.createElement("span");
                item.className = "calendar-drawer__employee-badge calendar-drawer__employee-badge--" + (badge.variant || "employee");

                const icon = document.createElement("span");
                icon.className = badge.icon_type === "symbol"
                    ? "calendar-drawer__employee-badge-symbol"
                    : "material-icons-sharp";
                icon.setAttribute("aria-hidden", "true");
                icon.textContent = badge.icon || "verified_user";

                const label = document.createElement("span");
                label.textContent = badge.label || "";

                item.appendChild(icon);
                item.appendChild(label);
                context.detailManagementBadges.appendChild(item);
            });
        }

        function appendRiskLine(container, item) {
            const risk = document.createElement("span");
            risk.className = "calendar-drawer__entry-risk";
            if (item.has_conflict) {
                risk.classList.add("calendar-drawer__entry-risk--conflict");
            } else if (item.has_high_risk) {
                risk.classList.add("calendar-drawer__entry-risk--high");
            }

            const reason = item.risk_short_reason || item.conflict_summary || "";
            if (item.has_conflict) {
                risk.textContent = "Конфликт состава";
            } else {
                risk.textContent = "Риск: " + (item.risk_label || "Низкий")
                    + (item.risk_score ? " · " + item.risk_score + "%" : "")
                    + (reason ? " · " + reason : "");
            }
            container.appendChild(risk);
        }

        function renderEntriesSafe(container, entries, emptyText) {
            if (!container) {
                return;
            }

            const safeEntries = Array.isArray(entries) ? entries : [];
            container.innerHTML = "";
            if (!safeEntries.length) {
                const placeholder = document.createElement("p");
                placeholder.className = "calendar-detail-placeholder";
                placeholder.textContent = emptyText;
                container.appendChild(placeholder);
                return;
            }

            safeEntries.forEach(function (item) {
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
                if (item.anchor) {
                    focusAction.dataset.employeeId = item.anchor.employee_id;
                    focusAction.dataset.startDate = item.anchor.start_date;
                    focusAction.dataset.endDate = item.anchor.end_date;
                }
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
            if (context.detailPosition) {
                context.detailPosition.textContent = detail.position || "Должность не указана";
            }
            if (context.detailDepartment) {
                context.detailDepartment.textContent = detail.department || "Не указан";
            }
            if (context.detailGroup) {
                context.detailGroup.textContent = detail.production_group || "Не указана";
            }
            updateProfileLink(detail);
            renderManagementBadges(detail.employee_management_badges);
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

            const primaryEntries = Array.isArray(detail.primary_entries) ? detail.primary_entries : (detail.selected_entries || []);
            const secondaryEntries = Array.isArray(detail.secondary_entries) ? detail.secondary_entries : (detail.year_entries || []);
            const hasSecondary = !detail.is_year_view && secondaryEntries.length > 0;
            if (context.primaryTitle) {
                context.primaryTitle.textContent = detail.primary_entries_title || (detail.is_year_view ? "Записи за год" : "Отпуска в выбранном месяце");
            }
            if (context.secondaryTitle) {
                context.secondaryTitle.textContent = detail.secondary_entries_title || "Остальные записи за год";
            }
            if (context.secondarySection) {
                context.secondarySection.classList.toggle("is-hidden", !hasSecondary);
            }
            if (context.detailContentGrid) {
                context.detailContentGrid.classList.toggle("calendar-drawer__content-grid--single", !hasSecondary);
            }

            renderEntriesSafe(
                context.primaryList || context.selectedList,
                primaryEntries,
                detail.primary_entries_empty || (detail.is_year_view ? "За этот год записей пока нет." : "В выбранном месяце отпусков нет.")
            );
            renderEntriesSafe(
                context.secondaryList || context.yearList,
                secondaryEntries,
                detail.secondary_entries_empty || "Других записей за год нет."
            );
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
