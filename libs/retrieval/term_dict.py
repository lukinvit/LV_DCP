"""Bidirectional tech term dictionary for ru↔en query expansion."""
from __future__ import annotations

import re

# Core tech terms: Russian → English mapping
# Only terms that appear in code identifiers and are unambiguous
_RU_TO_EN: dict[str, str] = {
    # connection
    "подключение": "connection",
    "подключения": "connection",
    "подключении": "connection",
    "соединение": "connection",
    "соединения": "connection",
    # client
    "клиент": "client",
    "клиента": "client",
    "клиентов": "client",
    # server
    "сервер": "server",
    "сервера": "server",
    "серверу": "server",
    "сервером": "server",
    "серверов": "server",
    # request / response
    "запрос": "request",
    "запроса": "request",
    "запросов": "request",
    "ответ": "response",
    "ответа": "response",
    # routing
    "маршрут": "route",
    "маршрута": "route",
    "маршрутизация": "routing",
    "обработчик": "handler",
    "обработчика": "handler",
    "middleware": "middleware",
    # data
    "данные": "data",
    "данных": "data",
    "данными": "data",
    # database
    "база": "database",
    "базы": "database",
    "базу": "database",
    # model / service / config
    "модель": "model",
    "модели": "model",
    "сервис": "service",
    "сервиса": "service",
    "конфигурация": "config",
    "конфигурации": "config",
    "настройки": "settings",
    "настроек": "settings",
    # user / auth
    "пользователь": "user",
    "пользователя": "user",
    "пользователей": "user",
    "авторизация": "auth",
    "авторизации": "auth",
    "аутентификация": "authentication",
    "аутентификации": "authentication",
    # token / session / cache
    "токен": "token",
    "токена": "token",
    "токенов": "token",
    "сессия": "session",
    "сессии": "session",
    "кэш": "cache",
    "кэша": "cache",
    # queue / task / worker
    "очередь": "queue",
    "очереди": "queue",
    "задача": "task",
    "задачи": "task",
    "задач": "task",
    "воркер": "worker",
    "воркера": "worker",
    # parser / parsing
    "парсер": "parser",
    "парсера": "parser",
    "парсинг": "parsing",
    "парсинга": "parsing",
    # collection / channel
    "сбор": "collection",
    "сбора": "collection",
    "канал": "channel",
    "канала": "channel",
    "каналов": "channel",
    "каналы": "channel",
    # bot / command
    "бот": "bot",
    "бота": "bot",
    "команда": "command",
    "команды": "command",
    # button / keyboard
    "кнопка": "button",
    "кнопки": "button",
    "клавиатура": "keyboard",
    "клавиатуры": "keyboard",
    # message / notification
    "сообщение": "message",
    "сообщения": "message",
    "сообщений": "message",
    "уведомление": "notification",
    "уведомления": "notification",
    # subscription / monitoring
    "подписка": "subscription",
    "подписки": "subscription",
    "мониторинг": "monitoring",
    "мониторинга": "monitoring",
    # metric / log
    "метрика": "metric",
    "метрики": "metric",
    "метрик": "metric",
    "лог": "log",
    "лога": "log",
    "логов": "log",
    "логирование": "logging",
    "логирования": "logging",
    # test / migration / schema
    "тест": "test",
    "теста": "test",
    "тестов": "test",
    "миграция": "migration",
    "миграции": "migration",
    "схема": "schema",
    "схемы": "schema",
    # index / search / filter / sort
    "индекс": "index",
    "индекса": "index",
    "поиск": "search",
    "поиска": "search",
    "фильтр": "filter",
    "фильтра": "filter",
    "сортировка": "sort",
    "сортировки": "sort",
    # page / template / component / interface
    "страница": "page",
    "страницы": "page",
    "шаблон": "template",
    "шаблона": "template",
    "компонент": "component",
    "компонента": "component",
    "интерфейс": "interface",
    "интерфейса": "interface",
    # error / exception
    "ошибка": "error",
    "ошибки": "error",
    "ошибок": "error",
    "исключение": "exception",
    "исключения": "exception",
    # send / receive / upload / download
    "отправка": "send",
    "отправки": "send",
    "получение": "receive",
    "получения": "receive",
    "загрузка": "upload",
    "загрузки": "upload",
    "скачивание": "download",
    "скачивания": "download",
    # file / directory / path
    "файл": "file",
    "файла": "file",
    "файлов": "file",
    "папка": "directory",
    "папки": "directory",
    "путь": "path",
    "пути": "path",
    # key / value
    "ключ": "key",
    "ключа": "key",
    "ключей": "key",
    "значение": "value",
    "значения": "value",
    # list / dict / function / class / method
    "список": "list",
    "списка": "list",
    "словарь": "dict",
    "словаря": "dict",
    "функция": "function",
    "функции": "function",
    "класс": "class",
    "класса": "class",
    "метод": "method",
    "метода": "method",
    # app / web
    "приложение": "app",
    "приложения": "app",
    "веб": "web",
    # telegram / scraping / pipeline
    "телеграм": "telegram",
    "телеграма": "telegram",
    "скрапинг": "scraping",
    "скрапинга": "scraping",
    "пайплайн": "pipeline",
    "пайплайна": "pipeline",
    # graph / node / relation / dependency
    "граф": "graph",
    "графа": "graph",
    "узел": "node",
    "узла": "node",
    "связь": "relation",
    "связи": "relation",
    "зависимость": "dependency",
    "зависимости": "dependency",
    # import / export
    "импорт": "import",
    "импорта": "import",
    "экспорт": "export",
    "экспорта": "export",
}

# Build reverse dict (en → ru)
_EN_TO_RU: dict[str, str] = {v: k for k, v in _RU_TO_EN.items()}

_CYRILLIC_RE = re.compile(r"[а-яёА-ЯЁ]")


def expand_query(query: str) -> str:
    """Expand query with cross-language tech terms.

    If query has Russian words, appends English equivalents.
    If query has English words, appends Russian equivalents.
    Returns expanded query for broader FTS matching.
    """
    words = query.lower().split()
    additions: list[str] = []

    for word in words:
        if _CYRILLIC_RE.search(word):
            # Russian word → add English equivalent
            en = _RU_TO_EN.get(word)
            if en and en not in words:
                additions.append(en)
        else:
            # English word → add Russian equivalent
            ru = _EN_TO_RU.get(word)
            if ru and ru not in words:
                additions.append(ru)

    if not additions:
        return query
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for a in additions:
        if a not in seen:
            seen.add(a)
            unique.append(a)
    return query + " " + " ".join(unique)
