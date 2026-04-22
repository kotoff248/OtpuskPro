from apps.employees.models import Departments


def update_context_with_departments(request, context):
    departments = Departments.objects.all()
    if request.method == "POST" and "department" in request.POST:
        request.session["selected_department"] = request.POST.get("department", "all")

    context.update(
        {
            "departments": departments,
            "selected_department": request.session.get("selected_department", "all"),
        }
    )
    return context

