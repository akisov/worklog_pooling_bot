import requests
from datetime import datetime, timedelta
import isodate
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import re
import aiohttp
import asyncio
import time

# Функция для правильного склонения слова "час"
def format_hours(hours):
    """Возвращает правильное склонение слова 'час' в зависимости от числового значения"""
    hours_int = int(hours)
    remainder = hours_int % 10
    
    if hours_int % 100 in [11, 12, 13, 14]:
        return f"{hours:.2f} часов"
    elif remainder == 1:
        return f"{hours:.2f} час"
    elif remainder in [2, 3, 4]:
        return f"{hours:.2f} часа"
    else:
        return f"{hours:.2f} часов"

# Параметры запроса
url = 'https://api.tracker.yandex.net/v2/worklog'
url_user_info = 'https://api.tracker.yandex.net/v2/users/8000000000000066'  # Пример URL для получения информации о пользователе
headers = {
    'Host': 'api.tracker.yandex.net',
    'X-Org-ID': '7405124',
    'Authorization': 'Bearer y0_AgAEA7qkjmsWAAuVvAAAAAEBS9CYAABNuI3VZT1OwpTWBHpgfk-2pWeYTQ',
    'Cookie': 'uid=/gcAAGfRiGV8QgDfBdNFAg=='
}

# Кеш для хранения данных
worklog_cache = {}  # Формат: {login: {'data': [...], 'timestamp': time.time(), 'month_data': [...], 'recent_data': [...]}}
user_info_cache = {}  # Формат: {login: {'data': {...}, 'timestamp': time.time()}}
CACHE_EXPIRY = 3600  # Время жизни кеша в секундах (1 час)

def is_cache_valid(login, cache_type='worklog'):
    """Проверяет, актуален ли кеш для данного пользователя"""
    cache = worklog_cache if cache_type == 'worklog' else user_info_cache
    if login not in cache:
        return False
    
    # Проверяем, не истек ли срок действия кеша
    current_time = time.time()
    if current_time - cache[login]['timestamp'] > CACHE_EXPIRY:
        return False
    
    return True

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
    # Используем 2025 год и текущий месяц
    today = datetime.now()
    year_for_request = 2025  # Фиксированный год 2025
    current_month = today.month
    current_day = today.day
    
    # Формируем даты для запроса: с 1 числа текущего месяца до завтрашнего дня
    start_of_month = f"{year_for_request}-{current_month:02d}-01"  # Начало месяца
    tomorrow = today + timedelta(days=1)
    end_of_month = f"{year_for_request}-{current_month:02d}-{tomorrow.day:02d}"  # Завтрашний день, но в 2025 году
    
    # Определяем дату, с которой начинаются "последние 2 дня"
    two_days_ago = today - timedelta(days=2)
    two_days_ago_str = f"{year_for_request}-{two_days_ago.month:02d}-{two_days_ago.day:02d}"
    
    print(f"Запрос данных для {login} с {start_of_month} по {end_of_month} (год: {year_for_request}, месяц: {current_month})")

    # Проверяем наличие кеша и его актуальность
    all_worklogs = []
    need_full_update = not is_cache_valid(login)
    
    if need_full_update:
        print(f"Кеш для {login} отсутствует или устарел, запрашиваем все данные")
        # Если кеш отсутствует или устарел, запрашиваем все данные
        all_worklogs = fetch_all_worklogs(login, start_of_month, end_of_month)
        
        # Разделяем данные на "старые" (до последних 2 дней) и "новые" (последние 2 дня)
        month_data = [log for log in all_worklogs if log['createdAt'][:10] < two_days_ago_str]
        recent_data = [log for log in all_worklogs if log['createdAt'][:10] >= two_days_ago_str]
        
        # Обновляем кеш
        worklog_cache[login] = {
            'data': all_worklogs,
            'month_data': month_data,
            'recent_data': recent_data,
            'timestamp': time.time()
        }
    else:
        print(f"Используем кеш для {login}, обновляем только данные за последние 2 дня")
        # Если кеш актуален, запрашиваем только данные за последние 2 дня
        recent_data = fetch_all_worklogs(login, two_days_ago_str, end_of_month)
        
        # Объединяем "старые" данные из кеша с новыми данными за последние 2 дня
        all_worklogs = worklog_cache[login]['month_data'] + recent_data
        
        # Обновляем кеш
        worklog_cache[login]['data'] = all_worklogs
        worklog_cache[login]['recent_data'] = recent_data
        worklog_cache[login]['timestamp'] = time.time()
    
    print(f"Всего получено {len(all_worklogs)} записей для {login}")
    
    # Отладочная информация
    for log in all_worklogs:
        created_at = log['createdAt'][:10]  # Извлечение даты в формате YYYY-MM-DD
        print(f"Запись: {log['issue']['key']}, Дата: {created_at}, Длительность: {log['duration']}")
    
    total_duration = 0
    print(f"Год запроса: {year_for_request}, текущий месяц: {current_month}")
    
    for log in all_worklogs:
        duration = log['duration']
        created_at = log['createdAt'][:10]  # Формат YYYY-MM-DD
        log_date = datetime.strptime(created_at, "%Y-%m-%d")
        
        # Учитываем все записи, которые возвращает API
        if duration.startswith('P1D'):
            match = re.search(r'T(\d+)H', duration)
            extra_hours = int(match.group(1)) if match else 0
            duration_hours = 8 + extra_hours
        else:
            duration_hours = isodate.parse_duration(duration).total_seconds() / 3600
        total_duration += duration_hours
        print(f"Учтено: {log['issue']['key']}, Дата: {created_at}, Длительность: {duration_hours} часов")

    # Словарь сокращенных дней и их рабочих часов
    reduced_days = {
        '2025-03-07': 7  # 7 марта - сокращенный день (7 часов)
    }

    # Пересчитываем общее количество рабочих часов с учетом сокращенных дней
    start_date_obj = datetime.strptime(start_of_month, "%Y-%m-%d")
    end_date_obj = datetime.strptime(end_of_month, "%Y-%m-%d")
    total_working_hours = 0
    current_date = start_date_obj
    while current_date <= end_date_obj:
        if current_date.weekday() < 5:  # Понедельник-пятница
            date_str = current_date.strftime('%Y-%m-%d')
            if date_str in reduced_days:
                total_working_hours += reduced_days[date_str]
            else:
                total_working_hours += 8
        current_date += timedelta(days=1)

    # Устанавливаем коэффициент в зависимости от пользователя
    if login == 'r.egorov':
        coefficient = 0.7
    elif login == 's.doronin':
        coefficient = 0.6
    else:
        coefficient = 0.85

    # Рассчитываем норму выработки
    production_norm = total_working_hours * coefficient
    
    # Рассчитываем процент выработки по норме
    production_rate = (total_duration / production_norm) * 100

    # Детализация по задачам
    daily_durations = {}
    for log in all_worklogs:
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

        # Проверяем, есть ли информация о типе задачи в кеше
        issue_type_display = get_issue_type(issue_key)

        if created_at not in daily_durations:
            daily_durations[created_at] = {}
        if issue_key not in daily_durations[created_at]:
            daily_durations[created_at][issue_key] = {'hours': 0, 'type': issue_type_display}
        daily_durations[created_at][issue_key]['hours'] += duration_hours

    details = ""
    for date, issues in daily_durations.items():
        details += f"\nДата: {date}\n"
        for issue_key, data in issues.items():
            details += f"  Задача: {issue_key}, Тип: {data['type']}, Время: {format_hours(data['hours'])}\n"

    print(f"Обработка данных для {login}:")
    print(f"Общее время: {total_duration} часов")
    print(f"Рабочие дни: {total_working_hours} часов")
    print(f"Норма выработки: {production_norm} часов")
    print(f"Выработка по норме: {production_rate}%")

    return f"⏰ Суммарное время: {format_hours(total_duration)}\n📊 Выработка по норме: {production_rate:.2f}%\n{details}"

def fetch_all_worklogs(login, start_date, end_date):
    """Получает все записи о работе для указанного пользователя за указанный период"""
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
    
    # Создаем список интервалов по 3 дня, где дата начала нового периода совпадает с датой окончания предыдущего
    intervals = []
    current_start = start_date_obj
    
    while current_start < end_date_obj:
        # Определяем конец текущего интервала (через 3 дня или до конца периода)
        current_end = min(current_start + timedelta(days=3), end_date_obj)
        intervals.append((current_start, current_end))
        # Новый интервал начинается с даты окончания предыдущего
        current_start = current_end
    
    # Собираем данные за все интервалы
    all_worklogs = []
    
    for start_interval, end_interval in intervals:
        start_str = start_interval.strftime("%Y-%m-%d")
        end_str = end_interval.strftime("%Y-%m-%d")
        
        print(f"Запрос данных для интервала: {start_str} - {end_str}")
        
        # Используем список кортежей для параметров
        params = [
            ('createdBy', login),
            ('createdAt', f'from:{start_str}'),
            ('createdAt', f'to:{end_str}')
        ]

        # Используем GET-запрос
        response = requests.get(url, headers=headers, params=params)

        if response.status_code == 200:
            worklogs = response.json()
            print(f"Получено {len(worklogs)} записей для интервала {start_str} - {end_str}")
            all_worklogs.extend(worklogs)
        else:
            print(f"Ошибка при запросе интервала {start_str} - {end_str}: {response.status_code} - {response.text}")
    
    return all_worklogs

# Кеш для типов задач
issue_type_cache = {}

def get_issue_type(issue_key):
    """Получает тип задачи с использованием кеширования"""
    if issue_key in issue_type_cache:
        return issue_type_cache[issue_key]
    
    # Если тип задачи не найден в кеше, запрашиваем его
    issue_url = f"https://api.tracker.yandex.net/v2/issues/{issue_key}"
    issue_response = requests.get(issue_url, headers=headers)
    if issue_response.status_code == 200:
        issue_data = issue_response.json()
        issue_type_display = issue_data['type'].get('display', 'Неизвестно')
        # Сохраняем в кеш
        issue_type_cache[issue_key] = issue_type_display
        return issue_type_display
    else:
        return 'Неизвестно'

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
    # Проверяем наличие кеша и его актуальность
    if is_cache_valid(login, 'user_info'):
        print(f"Используем кешированную информацию о пользователе {login}")
        return user_info_cache[login]['data']
    
    # Если кеш отсутствует или устарел, запрашиваем данные
    url_user_info = f'https://api.tracker.yandex.net/v2/users/{login}'
    async with session.get(url_user_info, headers=headers) as response:
        if response.status == 200:
            user_info = await response.json()
            # Обновляем кеш
            user_info_cache[login] = {
                'data': user_info,
                'timestamp': time.time()
            }
            return user_info
        else:
            print(f"Ошибка при получении информации о пользователе {login}: {response.status} - {await response.text()}")
            return None

async def fetch_worklog_info(session, login):
    # Используем 2025 год и текущий месяц
    today = datetime.now()
    year_for_request = 2025  # Фиксированный год 2025
    current_month = today.month
    current_day = today.day
    
    # Формируем даты для запроса: с 1 числа текущего месяца до завтрашнего дня
    start_of_month = f"{year_for_request}-{current_month:02d}-01"  # Начало месяца
    tomorrow = today + timedelta(days=1)
    end_of_month = f"{year_for_request}-{current_month:02d}-{tomorrow.day:02d}"  # Завтрашний день, но в 2025 году
    
    # Определяем дату, с которой начинаются "последние 2 дня"
    two_days_ago = today - timedelta(days=2)
    two_days_ago_str = f"{year_for_request}-{two_days_ago.month:02d}-{two_days_ago.day:02d}"
    
    print(f"Запрос данных для {login} с {start_of_month} по {end_of_month} (год: {year_for_request}, месяц: {current_month})")

    # Проверяем наличие кеша и его актуальность
    all_worklogs = []
    need_full_update = not is_cache_valid(login)
    
    if need_full_update:
        print(f"Кеш для {login} отсутствует или устарел, запрашиваем все данные")
        # Если кеш отсутствует или устарел, запрашиваем все данные
        all_worklogs = await fetch_all_worklogs_async(session, login, start_of_month, end_of_month)
        
        # Разделяем данные на "старые" (до последних 2 дней) и "новые" (последние 2 дня)
        month_data = [log for log in all_worklogs if log['createdAt'][:10] < two_days_ago_str]
        recent_data = [log for log in all_worklogs if log['createdAt'][:10] >= two_days_ago_str]
        
        # Обновляем кеш
        worklog_cache[login] = {
            'data': all_worklogs,
            'month_data': month_data,
            'recent_data': recent_data,
            'timestamp': time.time()
        }
    else:
        print(f"Используем кеш для {login}, обновляем только данные за последние 2 дня")
        # Если кеш актуален, запрашиваем только данные за последние 2 дня
        recent_data = await fetch_all_worklogs_async(session, login, two_days_ago_str, end_of_month)
        
        # Объединяем "старые" данные из кеша с новыми данными за последние 2 дня
        all_worklogs = worklog_cache[login]['month_data'] + recent_data
        
        # Обновляем кеш
        worklog_cache[login]['data'] = all_worklogs
        worklog_cache[login]['recent_data'] = recent_data
        worklog_cache[login]['timestamp'] = time.time()
    
    print(f"Всего получено {len(all_worklogs)} записей для {login}")
    return all_worklogs

async def fetch_all_worklogs_async(session, login, start_date, end_date):
    """Асинхронно получает все записи о работе для указанного пользователя за указанный период"""
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d")
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d")
    
    # Создаем список интервалов по 3 дня, где дата начала нового периода совпадает с датой окончания предыдущего
    intervals = []
    current_start = start_date_obj
    
    while current_start < end_date_obj:
        # Определяем конец текущего интервала (через 3 дня или до конца периода)
        current_end = min(current_start + timedelta(days=3), end_date_obj)
        intervals.append((current_start, current_end))
        # Новый интервал начинается с даты окончания предыдущего
        current_start = current_end
    
    # Собираем данные за все интервалы
    all_worklogs = []
    
    for start_interval, end_interval in intervals:
        start_str = start_interval.strftime("%Y-%m-%d")
        end_str = end_interval.strftime("%Y-%m-%d")
        
        print(f"Асинхронный запрос данных для интервала: {start_str} - {end_str}")
        
        # Используем список кортежей для параметров
        params = [
            ('createdBy', login),
            ('createdAt', f'from:{start_str}'),
            ('createdAt', f'to:{end_str}')
        ]

        # Используем GET-запрос
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                worklogs = await response.json()
                print(f"Получено {len(worklogs)} записей для интервала {start_str} - {end_str}")
                all_worklogs.extend(worklogs)
            else:
                print(f"Ошибка при запросе интервала {start_str} - {end_str}: {response.status} - {await response.text()}")
    
    return all_worklogs

async def get_summary_info_async(session, login):
    user_info = await fetch_user_info(session, login)
    if user_info:
        first_name = user_info.get('firstName', 'Неизвестно')
        last_name = user_info.get('lastName', 'Неизвестно')
        full_name = f"{first_name} {last_name}"
        position = user_info.get('position', 'Неизвестно')
        login = user_info.get('login', 'Неизвестно')
        worklogs = await fetch_worklog_info(session, login)
        if worklogs and len(worklogs) > 0:
            total_duration = 0
            today = datetime.now()
            year_for_request = 2025  # Фиксированный год 2025
            current_month = today.month
            current_day = today.day
            print(f"Год запроса: {year_for_request}, месяц: {current_month}")
            
            for log in worklogs:
                duration = log['duration']
                created_at = log['createdAt'][:10]  # Формат YYYY-MM-DD
                log_date = datetime.strptime(created_at, "%Y-%m-%d")
                
                # Учитываем все записи, которые возвращает API
                if duration.startswith('P1D'):
                    match = re.search(r'T(\d+)H', duration)
                    extra_hours = int(match.group(1)) if match else 0
                    duration_hours = 8 + extra_hours
                else:
                    duration_hours = isodate.parse_duration(duration).total_seconds() / 3600
                total_duration += duration_hours

            # Используем даты из запроса для расчета рабочих часов
            start_of_month = f"{year_for_request}-{current_month:02d}-01"  # Начало месяца
            tomorrow = today + timedelta(days=1)
            end_of_month = f"{year_for_request}-{current_month:02d}-{tomorrow.day:02d}"  # Завтрашний день, но в 2025 году
            start_date_obj = datetime.strptime(start_of_month, "%Y-%m-%d")
            end_date_obj = datetime.strptime(end_of_month, "%Y-%m-%d")
            
            reduced_days = {
                '2025-03-07': 7  # 7 марта - сокращенный день (7 часов)
            }  # Словарь сокращенных дней
            total_working_hours = 0
            current_date = start_date_obj
            while current_date <= end_date_obj:
                if current_date.weekday() < 5:  # Понедельник-пятница
                    date_str = current_date.strftime('%Y-%m-%d')
                    if date_str in reduced_days:
                        total_working_hours += reduced_days[date_str]
                    else:
                        total_working_hours += 8
                current_date += timedelta(days=1)

            if login == 'r.egorov':
                coefficient = 0.7
            elif login == 's.doronin':
                coefficient = 0.6
            else:
                coefficient = 0.85

            # Рассчитываем норму выработки
            production_norm = total_working_hours * coefficient
            
            # Рассчитываем процент выработки по норме
            production_rate = (total_duration / production_norm) * 100
            print(f"Обработка данных для {login}:")
            print(f"Общее время: {total_duration} часов")
            print(f"Рабочие дни: {total_working_hours} часов")
            print(f"Норма выработки: {production_norm} часов")
            print(f"Выработка по норме: {production_rate}%")
            return f"👤 ФИО: {full_name}\n💼 Должность: {position}\n🔑 Логин: {login}\n⏰ Суммарное время: {format_hours(total_duration)}\n📊 Выработка по норме: {production_rate:.2f}%"
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
        # Проверяем, что summary_info содержит нужные данные
        if "📊 Выработка по норме:" in summary_info:
            production_rate_start = summary_info.find('📊 Выработка по норме:')
            production_rate_end = summary_info.find('%', production_rate_start)
            production_rate = float(summary_info[production_rate_start + 21:production_rate_end])
            name = names.get(login, login)
            if production_rate < 70:
                name += ' ❗'
        else:
            name = names.get(login, login) + ' ⚠️'  # Добавляем предупреждение, если данные не получены
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
        # Получаем текущий текст сообщения
        current_text = query.message.text if query.message.text else ""
        
        # Проверяем, изменилось ли содержимое сообщения
        if current_text != summary_info:
            await query.edit_message_text(text=summary_info, reply_markup=reply_markup)
        else:
            # Если содержимое не изменилось, просто отвечаем на запрос
            await query.answer("Информация не изменилась")

def get_all_team_summary():
    # Список логинов всех сотрудников
    logins = ['v.podlinov', 'i.nadenenko', 'v.samriakova', 's.doronin', 'g.maksimov', 'r.egorov', 'r.turalieva', 'a.goldobin', 'o.perevezentseva']
    all_summary = "Сводная информация по всей команде:\n"
    for login in logins:
        summary_info = get_summary_info(login)
        # Проверяем, что summary_info содержит нужные данные
        if "📊 Выработка по норме:" in summary_info:
            production_rate_start = summary_info.find('📊 Выработка по норме:')
            production_rate_end = summary_info.find('%', production_rate_start)
            production_rate = float(summary_info[production_rate_start + 21:production_rate_end])
            if production_rate < 70:
                # Добавляем восклицательный знак к имени
                summary_info = summary_info.replace('👤 ФИО:', '👤 ФИО: ❗')
            all_summary += f"\n{summary_info}\n"
        else:
            # Если данные не получены, добавляем сообщение об ошибке
            all_summary += f"\n👤 ФИО: {login} ⚠️ (Ошибка при получении данных)\n"
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
