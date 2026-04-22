from apps.leave.models import VacationRequest


def pending_requests_count(request):
    return {
        "pending_requests_count": VacationRequest.objects.filter(status=VacationRequest.STATUS_PENDING).count()
    }

