import requests
from datetime import datetime, timedelta
import isodate

# Параметры запроса
url = 'https://api.tracker.yandex.net/v2/worklog'
headers = {
    'Host': 'api.tracker.yandex.net',
    'X-Org-ID': '7405124',
    'Authorization': 'Bearer y0_AgAEA7qkjmsWAAuVvAAAAAEBS9CYAABNuI3VZT1OwpTWBHpgfk-2pWeYTQ',
    'Cookie': 'uid=/gcAAGfRiGV8QgDfBdNFAg=='
}

# Вычисление начала текущего месяца
start_of_month = datetime.now().replace(day=1).strftime("%Y-%m-%d")
end_of_today = datetime.now().strftime("%Y-%m-%d")

params = {
    'createdBy': '8000000000000066',
    'createdAt': f'from:{start_of_month},to:{end_of_today}'
}

# Выполнение запроса
response = requests.get(url, headers=headers, params=params)

# Проверка успешности запроса
if response.status_code == 200:
    worklogs = response.json()
    total_duration = sum(isodate.parse_duration(log['duration']).total_seconds() / 3600 for log in worklogs)  # Перевод из секунд в часы
    print(f"Суммарное время: {total_duration:.2f} часов")

    daily_durations = {}
    for log in worklogs:
        issue_key = log['issue']['key']
        created_at = log['createdAt'][:10]  # Извлечение даты в формате YYYY-MM-DD
        duration_hours = isodate.parse_duration(log['duration']).total_seconds() / 3600
        if created_at not in daily_durations:
            daily_durations[created_at] = {}
        if issue_key not in daily_durations[created_at]:
            daily_durations[created_at][issue_key] = 0
        daily_durations[created_at][issue_key] += duration_hours

    for date, issues in daily_durations.items():
        print(f"Дата: {date}")
        for issue_key, hours in issues.items():
            print(f"  Задача: {issue_key}, Время: {hours:.2f} часов")

    # Расчет нормы выработки
    # Подсчет количества рабочих дней в текущем месяце
    today = datetime.now()
    first_day_of_month = today.replace(day=1)
    num_working_days = sum(1 for i in range((today - first_day_of_month).days + 1)
                           if (first_day_of_month + timedelta(days=i)).weekday() < 5)
    total_working_hours = num_working_days * 8  # 8-часовой рабочий день
    production_rate = total_duration / (total_working_hours * 0.85) * 100
    print(f"Норма выработки: {production_rate:.2f}%")
else:
    print(f"Ошибка: {response.status_code} - {response.text}")
