from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('main', '0012_employees_user_sync'),
    ]

    operations = [
        migrations.CreateModel(
            name='VacationRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_date', models.DateField(verbose_name='Дата начала')),
                ('end_date', models.DateField(verbose_name='Дата окончания')),
                (
                    'vacation_type',
                    models.CharField(
                        choices=[('paid', 'Оплачиваемый'), ('unpaid', 'Неоплачиваемый'), ('study', 'Учебный')],
                        default='paid',
                        max_length=50,
                        verbose_name='Тип отпуска',
                    ),
                ),
                (
                    'status',
                    models.CharField(
                        choices=[('pending', 'В ожидании'), ('approved', 'Одобрено'), ('rejected', 'Отклонено')],
                        default='pending',
                        max_length=20,
                        verbose_name='Статус',
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')),
                (
                    'employee',
                    models.ForeignKey(on_delete=models.deletion.CASCADE, to='main.employees', verbose_name='Сотрудник'),
                ),
            ],
            options={
                'verbose_name': 'Заявка на отпуск',
                'verbose_name_plural': 'Заявки на отпуск',
                'ordering': ['-created_at'],
            },
        ),
        migrations.DeleteModel(name='Vacation'),
        migrations.DeleteModel(name='PreHolidays'),
        migrations.DeleteModel(name='СanceledHolidays'),
    ]
