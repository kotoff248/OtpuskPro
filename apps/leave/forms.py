from django import forms

from apps.leave.models import VacationRequest

from .services.preferences import get_paid_leave_available_from
from .services.validation import validate_schedule_change_request, validate_vacation_request_for_employee


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


class VacationPreferenceResponseForm(forms.Form):
    primary_start_date = forms.DateField(
        required=False,
        label="Дата начала основного отпуска",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    primary_end_date = forms.DateField(
        required=False,
        label="Дата окончания основного отпуска",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    backup_start_date = forms.DateField(
        required=False,
        label="Дата начала запасного отпуска",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    backup_end_date = forms.DateField(
        required=False,
        label="Дата окончания запасного отпуска",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    comment = forms.CharField(required=False, label="Комментарий", widget=forms.Textarea(attrs={"rows": 3}))
    no_preferences = forms.BooleanField(required=False, label="Нет пожеланий")

    def __init__(self, *args, employee=None, collection=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        self.collection = collection

    def _clean_period(self, cleaned_data, start_field, end_field, label):
        start_date = cleaned_data.get(start_field)
        end_date = cleaned_data.get(end_field)
        if not start_date or not end_date:
            raise forms.ValidationError(f"Укажите даты для блока «{label}».")
        if end_date < start_date:
            raise forms.ValidationError(f"В блоке «{label}» дата окончания не может быть раньше даты начала.")

        year = self.collection.year
        if start_date.year != year or end_date.year != year:
            raise forms.ValidationError(f"В блоке «{label}» даты должны быть в пределах {year} года.")

        available_from = get_paid_leave_available_from(self.employee)
        if start_date < available_from:
            raise forms.ValidationError(
                f"В блоке «{label}» оплачиваемый отпуск доступен с {available_from:%d.%m.%Y}."
            )

    def clean(self):
        cleaned_data = super().clean()
        if self.errors:
            return cleaned_data
        if cleaned_data.get("no_preferences"):
            return cleaned_data

        self._clean_period(
            cleaned_data,
            "primary_start_date",
            "primary_end_date",
            "Основной отпуск",
        )
        self._clean_period(
            cleaned_data,
            "backup_start_date",
            "backup_end_date",
            "Запасной отпуск",
        )
        return cleaned_data

