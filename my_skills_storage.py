import threading


STORAGE_LOCK = threading.Lock()


# {id:[{type,filename,data},{}],}
STORAGE = {}


# какому юзеру можно запрашивать какие ид в функции запроса файла
# это должно защитить от взлома промпта и запросов к чужим файлам
# {user_id(str):user_id(str),}
STORAGE_ALLOWED_IDS = {}
