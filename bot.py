import requests
from datetime import datetime, timedelta
import isodate
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import re
import aiohttp
import asyncio

# Параметры запроса
url = 'https://api.tracker.yandex.net/v2/worklog'
url_user_info = 'https://api.tracker.yandex.net/v2/users/8000000000000066'  # Пример URL для получения информации о пользователе
headers = {
    'Host': 'api.tracker.yandex.net',
    'X-Org-ID': '7405124',
    'Authorization': 'Bearer y0_AgAEA7qkjmsWAAuVvAAAAAEBS9CYAABNuI3VZT1OwpTWBHpgfk-2pWeYTQ',
    'Cookie': 'uid=/gcAAGfRiGV8QgDfBdNFAg=='
}

def get_user_self_url(login):
    # Предполагаем, что есть API для получения self URL по логину
    url_user_info = f'https://api.tracker.yandex.net/v2/users/{login}'
    response = requests.get(url_user_info, headers=headers)
    if response.status_code == 200:
        user_info = response.json()
        self_url = user_info.get('self', None)
        print(f"Получен self URL для {login}: {self_url}")  # Логирование
        return self_url
    else:
        print(f"Ошибка при получении self URL для {login}: {response.status_code} - {response.text}")  # Логирование
        return None

def get_worklog_info(login):
    # Логика из main.py
    start_of_month = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    end_of_today = datetime.now().strftime("%Y-%m-%d")

    params = {
        'createdBy': login,
        'createdAt': f'from:{start_of_month},to:{end_of_today}'
    }

    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 200:
        worklogs = response.json()
        total_duration = 0
        for log in worklogs:
            duration = log['duration']
            if duration.startswith('P1D'):
                # Используем регулярное выражение для извлечения дополнительных часов
                match = re.search(r'T(\d+)H', duration)
                extra_hours = int(match.group(1)) if match else 0
                duration_hours = 8 + extra_hours  # Считаем P1D как 8 часов плюс дополнительные часы
            else:
                duration_hours = isodate.parse_duration(duration).total_seconds() / 3600
            total_duration += duration_hours

        today = datetime.now()
        first_day_of_month = today.replace(day=1)
        # Словарь сокращенных дней и их рабочих часов
        reduced_days = {
            '2023-03-07': 7,  # Пример сокращенного дня
            # Добавьте другие сокращенные дни здесь
        }

        # Пересчитываем общее количество рабочих часов с учетом сокращенных дней
        total_working_hours = 0
        for i in range((today - first_day_of_month).days + 1):
            current_day = first_day_of_month + timedelta(days=i)
            if current_day.weekday() < 5:  # Понедельник-пятница
                if current_day.strftime('%Y-%m-%d') in reduced_days:
                    total_working_hours += reduced_days[current_day.strftime('%Y-%m-%d')]
                else:
                    total_working_hours += 8

        # Устанавливаем коэффициент в зависимости от пользователя
        if login == 'r.egorov':
            coefficient = 0.7
        elif login == 's.doronin':
            coefficient = 0.6
        else:
            coefficient = 0.85

        production_rate = total_duration / (total_working_hours * coefficient) * 100

        # Детализация по задачам
        daily_durations = {}
        for log in worklogs:
            issue_key = log['issue']['key']
            created_at = log['createdAt'][:10]  # Извлечение даты в формате YYYY-MM-DD
            duration = log['duration']
            if duration.startswith('P1D'):
                # Используем регулярное выражение для извлечения дополнительных часов
                match = re.search(r'T(\d+)H', duration)
                extra_hours = int(match.group(1)) if match else 0
                duration_hours = 8 + extra_hours  # Считаем P1D как 8 часов плюс дополнительные часы
            else:
                duration_hours = isodate.parse_duration(duration).total_seconds() / 3600

            # Новый запрос для получения типа задачи
            issue_url = f"https://api.tracker.yandex.net/v2/issues/{issue_key}"
            issue_response = requests.get(issue_url, headers=headers)
            if issue_response.status_code == 200:
                issue_data = issue_response.json()
                issue_type_display = issue_data['type'].get('display', 'Неизвестно')
            else:
                issue_type_display = 'Неизвестно'

            if created_at not in daily_durations:
                daily_durations[created_at] = {}
            if issue_key not in daily_durations[created_at]:
                daily_durations[created_at][issue_key] = {'hours': 0, 'type': issue_type_display}
            daily_durations[created_at][issue_key]['hours'] += duration_hours

        details = ""
        for date, issues in daily_durations.items():
            details += f"\nДата: {date}\n"
            for issue_key, data in issues.items():
                details += f"  Задача: {issue_key}, Тип: {data['type']}, Время: {data['hours']:.2f} часов\n"

        print(f"Обработка данных для {login}:")
        print(f"Общее время: {total_duration} часов")
        print(f"Рабочие дни: {total_working_hours} часов")
        print(f"Норма выработки: {production_rate}%")

        return f"⏰ Суммарное время: {total_duration:.2f} часов\n📊 Норма выработки: {production_rate:.2f}%\n{details}"
    else:
        return f"Ошибка: {response.status_code} - {response.text}"

def get_summary_info(login):
    # Обновляем URL для получения информации о пользователе
    url_user_info = f'https://api.tracker.yandex.net/v2/users/{login}'
    response = requests.get(url_user_info, headers=headers)
    if response.status_code == 200:
        user_info = response.json()
        first_name = user_info.get('firstName', 'Неизвестно')
        last_name = user_info.get('lastName', 'Неизвестно')
        full_name = f"{first_name} {last_name}"
        position = user_info.get('position', 'Неизвестно')
        login = user_info.get('login', 'Неизвестно')
        worklog_info = get_worklog_info(login)
        # Извлекаем только сводную часть
        summary_end = worklog_info.find("\nДата:")
        summary_info = worklog_info[:summary_end]
        return f"👤 ФИО: {full_name}\n💼 Должность: {position}\n🔑 Логин: {login}\n{summary_info}"
    else:
        return f"Ошибка: {response.status_code} - {response.text}"

def get_worklog_details(login):
    worklog_info = get_worklog_info(login)
    details_start = worklog_info.find("\nДата:")
    return worklog_info[details_start:]

async def fetch_user_info(session, login):
    url_user_info = f'https://api.tracker.yandex.net/v2/users/{login}'
    async with session.get(url_user_info, headers=headers) as response:
        if response.status == 200:
            return await response.json()
        else:
            print(f"Ошибка при получении self URL для {login}: {response.status} - {await response.text()}")
            return None

async def fetch_worklog_info(session, login):
    start_of_month = datetime.now().replace(day=1).strftime("%Y-%m-%d")
    end_of_today = datetime.now().strftime("%Y-%m-%d")

    params = {
        'createdBy': login,
        'createdAt': f'from:{start_of_month},to:{end_of_today}'
    }

    async with session.get(url, headers=headers, params=params) as response:
        if response.status == 200:
            return await response.json()
        else:
            print(f"Ошибка: {response.status} - {await response.text()}")
            return None

async def get_summary_info_async(session, login):
    user_info = await fetch_user_info(session, login)
    if user_info:
        first_name = user_info.get('firstName', 'Неизвестно')
        last_name = user_info.get('lastName', 'Неизвестно')
        full_name = f"{first_name} {last_name}"
        position = user_info.get('position', 'Неизвестно')
        login = user_info.get('login', 'Неизвестно')
        worklogs = await fetch_worklog_info(session, login)
        if worklogs is not None:
            total_duration = 0
            for log in worklogs:
                duration = log['duration']
                if duration.startswith('P1D'):
                    match = re.search(r'T(\d+)H', duration)
                    extra_hours = int(match.group(1)) if match else 0
                    duration_hours = 8 + extra_hours
                else:
                    duration_hours = isodate.parse_duration(duration).total_seconds() / 3600
                total_duration += duration_hours

            today = datetime.now()
            first_day_of_month = today.replace(day=1)
            reduced_days = {'2023-03-07': 7}
            total_working_hours = 0
            for i in range((today - first_day_of_month).days + 1):
                current_day = first_day_of_month + timedelta(days=i)
                if current_day.weekday() < 5:
                    if current_day.strftime('%Y-%m-%d') in reduced_days:
                        total_working_hours += reduced_days[current_day.strftime('%Y-%m-%d')]
                    else:
                        total_working_hours += 8

            if login == 'r.egorov':
                coefficient = 0.7
            elif login == 's.doronin':
                coefficient = 0.6
            else:
                coefficient = 0.85

            production_rate = total_duration / (total_working_hours * coefficient) * 100
            print(f"Обработка данных для {login}:")
            print(f"Общее время: {total_duration} часов")
            print(f"Рабочие дни: {total_working_hours} часов")
            print(f"Норма выработки: {production_rate}%")
            return f"👤 ФИО: {full_name}\n💼 Должность: {position}\n🔑 Логин: {login}\n⏰ Суммарное время: {total_duration:.2f} часов\n📊 Норма выработки: {production_rate:.2f}%"
    return "Ошибка при получении данных"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = []
    logins = ['v.podlinov', 'i.nadenenko', 'v.samriakova', 's.doronin', 'g.maksimov', 'r.egorov', 'r.turalieva', 'a.goldobin', 'o.perevezentseva']
    names = {
        'v.podlinov': 'Владислав Подлинов',
        'i.nadenenko': 'Игорь Надененко',
        'v.samriakova': 'Валерия Самрякова',
        's.doronin': 'Сергей Доронин',
        'g.maksimov': 'Геннадий Максимов',
        'r.egorov': 'Роман Егоров',
        'r.turalieva': 'Раушан Туралиева',
        'a.goldobin': 'Александр Голдобин',
        'o.perevezentseva': 'Ольга Перевезенцева'
    }

    async with aiohttp.ClientSession() as session:
        tasks = [get_summary_info_async(session, login) for login in logins]
        summaries = await asyncio.gather(*tasks)

    for login, summary_info in zip(logins, summaries):
        production_rate_start = summary_info.find('📊 Норма выработки:')
        production_rate_end = summary_info.find('%', production_rate_start)
        production_rate = float(summary_info[production_rate_start + 18:production_rate_end])
        name = names.get(login, login)
        if production_rate < 70:
            name += ' ❗'
        keyboard.append([InlineKeyboardButton(name, callback_data=login)])
    keyboard.append([InlineKeyboardButton("Вся команда", callback_data='all_team')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    message = update.effective_message
    await message.reply_text("Выберите пользователя:", reply_markup=reply_markup)

async def user_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_login = query.data
    if user_login == 'all_team':
        summary_info = get_all_team_summary()
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=summary_info, reply_markup=reply_markup)
    elif user_login == 'back':
        await start(update, context)
    else:
        summary_info = get_summary_info(user_login)
        keyboard = [
            [InlineKeyboardButton("Подробно", callback_data=f'details_{user_login}')],
            [InlineKeyboardButton("🔙 Назад", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # Проверка на изменение содержимого сообщения
        if query.message.text != summary_info or query.message.reply_markup != reply_markup:
            await query.edit_message_text(text=summary_info, reply_markup=reply_markup)

def get_all_team_summary():
    # Список логинов всех сотрудников
    logins = ['v.podlinov', 'i.nadenenko', 'v.samriakova', 's.doronin', 'g.maksimov', 'r.egorov', 'r.turalieva', 'a.goldobin', 'o.perevezentseva']
    all_summary = "Сводная информация по всей команде:\n"
    for login in logins:
        summary_info = get_summary_info(login)
        # Проверяем норму выработки
        production_rate_start = summary_info.find('📊 Норма выработки:')
        production_rate_end = summary_info.find('%', production_rate_start)
        production_rate = float(summary_info[production_rate_start + 18:production_rate_end])
        if production_rate < 70:
            # Добавляем восклицательный знак к имени
            summary_info = summary_info.replace('👤 ФИО:', '👤 ФИО: ❗')
        all_summary += f"\n{summary_info}\n"
    return all_summary

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_login = query.data.split('_')[1]
    summary_info = get_summary_info(user_login)
    details = get_worklog_details(user_login)
    full_info = f"{summary_info}\n{details}"
    keyboard = [
        [InlineKeyboardButton("🔙 Назад", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text=full_info, reply_markup=reply_markup)

def main():
    application = ApplicationBuilder().token("7948134656:AAHf_oMEkccjH2Lc1cDH1CRED1hUCdcTt9M").build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(user_info, pattern='^(v.podlinov|i.nadenenko|v.samriakova|s.doronin|g.maksimov|r.egorov|r.turalieva|a.goldobin|o.perevezentseva|all_team|back)$'))
    application.add_handler(CallbackQueryHandler(button, pattern='^details_'))

    application.run_polling()

if __name__ == '__main__':
    main()
