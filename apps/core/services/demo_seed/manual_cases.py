from apps.core.services.demo_urgent_closure_cases import ensure_demo_urgent_closure_cases


def create_manual_draft_cases(*, planning_year, employees):
    return ensure_demo_urgent_closure_cases(planning_year=planning_year, employees=employees)
