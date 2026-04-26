from django import forms

from apps.leave.models import VacationRequest

from .services import validate_schedule_change_request, validate_vacation_request_for_employee


class VacationRequestCreateForm(forms.ModelForm):
    class Meta:
        model = VacationRequest
        fields = ["vacation_type", "start_date", "end_date", "reason"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "reason": forms.Textarea(attrs={"rows": 3}),
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


class ScheduleChangeRequestCreateForm(forms.Form):
    new_start_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    new_end_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    reason = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, schedule_item=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.schedule_item = schedule_item

    def clean(self):
        cleaned_data = super().clean()
        if self.errors:
            return cleaned_data

        new_start_date = cleaned_data.get("new_start_date")
        new_end_date = cleaned_data.get("new_end_date")
        if self.schedule_item and new_start_date and new_end_date:
            validate_schedule_change_request(self.schedule_item, new_start_date, new_end_date)
        return cleaned_data

