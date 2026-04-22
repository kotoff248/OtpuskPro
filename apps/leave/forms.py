from django import forms

from apps.leave.models import VacationRequest

from .services import validate_vacation_request_for_employee


class VacationRequestCreateForm(forms.ModelForm):
    class Meta:
        model = VacationRequest
        fields = ["vacation_type", "start_date", "end_date"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee

    def clean(self):
        cleaned_data = super().clean()
        if self.errors:
            return cleaned_data

        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        vacation_type = cleaned_data.get("vacation_type")
        if self.employee and start_date and end_date and vacation_type:
            validate_vacation_request_for_employee(
                employee=self.employee,
                start_date=start_date,
                end_date=end_date,
                vacation_type=vacation_type,
            )
        return cleaned_data

