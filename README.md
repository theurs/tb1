# Телеграм бот для доступа к Google Gemini, MS Bing etc

Тестовый образец https://t.me/kun4sun_bot

Чат бот отзывается на кодовое слово `бот`(можно сменить командой /name) `бот расскажи про биткоин`

Кодовое слово `гугл`(нельзя изменить) позволит получить более актуальную информацию, бот будет гуглить перед ответом `гугл, сколько людей на земле осталось`

В привате можно не писать кодовые слова для обращения к боту

Если он перестал отвечать то возможно надо почистить ему память командой `забудь` `бот забудь`

Кодовое слово `нарисуй` и дальше описание даст картинки сгенерированные по описанию. В чате надо добавлять к этому обращение `бот нарисуй на заборе неприличное слово`

В чате бот будет автоматически распознавать голосовые сообщения, включить это можно в настройках.

Если отправить текстовый файл или пдф то выдаст краткое содержание.

Если отправить картинку с подписью `ocr` то вытащит текст из них.

Если отправить ссылку в приват то попытается прочитать текст из неё и выдать краткое содержание.

Если отправить картинку с другой подписью или без подписи то напишет описание того что изображено на картинке или ответит на вопрос из подписи, в чате надо начинать с знака ?

Если отправить номер телефона то попробует узнать кто звонил (только русские номера)

Команды и запросы можно делать голосовыми сообщениями, если отправить голосовое сообщение которое начинается на кодовое слово то бот отработает его как текстовую команду.

![Доступные команды](commands.txt)

## Уникальные фичи бота

* Может работать на бесплатных ключах от пользователей, gemini, groq, huggingface, deepl, и на платных openrouter - любая модель, ключи от бинга мог бы брать но с ними мороки много и вроде не надо, своих хватает.

* В этого бота можно кидать тексты больше 4к символов. Телеграмм их режет на части а бот склеивает обратно и отвечает на них как на цельные сообщения большого размера.

* Может выдавать ответы любого размера, режет их на части так что бы не сломалось маркдаун форматирование. Или отправляет как файл если в ответе очень много символов (больше 40т).


## Команды

### Команды для юзера

/openrouter - выбрать openrouter.ai поставщик разнообразных платных ИИ
/gemma (gemma2 9b) /haiku /gpt (4o mini ddg) /llama (llama 3 70b) /flash (gemini1.5flash) /pro (gemini1.5pro) - обращение напрямую к этим моделям без изменения настроек

### Команды для администратора

/addkey - добавить ключ для джемини другому юзеру /addkey <uid> <key>

/alert - массовая рассылка сообщения от администратора во все чаты, маркдаун форматирование, отправляет сообщение без уведомления но всё равно не приятная штука похожая на спам

/msg - userid_as_int text to send from admin to user'

/init - инициализация бота, установка описаний на всех языках, не обязательно, можно и вручную сделать, выполняется долго, ничего не блокирует

/enable - включить бота в публичном чате (комнате)
/disable - выключить бота в публичном чате (комнате)

/blockadd - добавить id '[chat_id] [thread_id]' в список заблокированных (игнорируемых) юзеров или чатов, учитывается только первая цифра, то есть весь канал со всеми темами внутри

/blockdel - удалить id из игнорируемых

/blocklist - список игнорируемых

/blockadd2 /blockdel2 /blocklist2 - блокировка юзеров в бинге, их запросы на рисование будут принудительно изменятся на nsfw

/blockadd3 /blockdel3 /blocklist3 - блокировка юзеров полная, их запросы не попадают даже в логи

/leave <chat_id> - выйти из чата (можно вместо одного id вывалить кучу, все номера похожие на номер группы в тексте будут использованы)

/ping простейшее эхо, для проверки телебота, не использует никаких ресурсов кроме самых необходимых для ответа

/reload <имя модуля> - перезагружает модуль на ходу, можно вносить изменения в бота и перезагружать модули не перезапуская всего бота

/revoke <chat_id> - убрать чат из списка на автовыхода(бана) (можно вместо одного id вывалить кучу, все номера похожие на номер группы в тексте будут использованы)

/restart - перезапуск бота на случай зависания

/stats - статистика бота (сколько было активно за последнее время)

/style2 - изменить стиль бота для заданного чата (пример: /style2 [id] [topic id] новая роль)

/reset_gemini2 - очистить историю чата Gemini Pro в другом чате Usage: /reset_gemini2 <chat_id_full!>

========================================

/tgui - исправление переводов, ищет среди переводов совпадение и пытается исправить перевод

тут перевод указан вручную

/tgui клавиши Близнецы добавлены|||ключи для Gemini добавлены

а тут будет автоперевод с помощью ии

/tgui клавиши Близнецы добавлены

========================================

/bingcookie - (/cookie /k) добавить куки для бинга, можно несколько через пробел

/bingcookieclear (/kc) - удалить все куки для бинга

/disable_chat_mode from to - принудительно сменить всем режим чата, например у кого бард переключить на джемини

/cmd /shell - выполнить команду в шеле, команды записаны в cfg.SYSTEM_CMDS, обращение к ним идет по их номерам, /cmd 2 - выполнит вторую команду из списка


![Скриншоты](pics/README.md)


## Установка

Для установки проекта выполните следующие шаги:

1. Установите Python 3.8+.
2. Установите утилиту trans `sudo apt-get install translate-shell`
3. Установите утилиту tesseract. В убунте 22.04.х (и дебиане 11) в репах очень старая версия тессеракта, надо подключать репозиторий с новыми версиями или ставить из бекпортов
    ```
    sudo apt-get update && \
    sudo apt-get install -y software-properties-common && \
    sudo add-apt-repository -y ppa:alex-p/tesseract-ocr5 && \
    sudo apt-get update && \
    sudo apt install tesseract-ocr tesseract-ocr-eng \
    tesseract-ocr-rus tesseract-ocr-ukr tesseract-ocr-osd
    ```
4. Установите словари и прочее `sudo apt install aspell aspell-en aspell-ru aspell-uk catdoc enchant-2 ffmpeg pandoc python3-venv sox`
   yt-dlp надо установить отдельно, т.к. в репах нет актуальной свежей версии, а она нужна для скачивания тиктоков и музыки с ютуба

5. Клонируйте репозиторий с помощью команды:

   ```
   git clone https://github.com/theurs/tb1.git
   
   python -m venv .tb1
   source ~/.tb1/bin/activate
   
   ```
   
4. Перейдите в директорию проекта:

   ```
   cd tb1
   ```
   
5. Создайте файл cfg.py и добавьте в него строку
```
# Quick'n'dirty SSL certificate generation:
#
# openssl genrsa -out webhook_pkey.pem 2048
# openssl req -new -x509 -days 3650 -key webhook_pkey.pem -out webhook_cert.pem
#
# When asked for "Common Name (e.g. server FQDN or YOUR name)" you should reply
# with the same value in you put in WEBHOOK_HOST
# WEBHOOK_DOMAIN = 'bot777.hostname.com'
# WEBHOOK_PORT = xxxx  # 443, 80, 88 or 8443 (port need to be 'open')
# WEBHOOK_SSL_CERT = './webhook_cert.pem'  # Path to the ssl certificate
# WEBHOOK_SSL_PRIV = './webhook_pkey.pem'  # Path to the ssl private key


# не журналировать id чатов из этого списка
DO_NOT_LOG = [xxx, yyy,]

# описание бота, которое отображается в чате с ботом, если чат пуст. До 512 символов.
bot_description = """Free chat bot

Голосовое управление, озвучивание текстов, пересказ веб страниц и видеороликов на Youtube, распознавание текста с картинок и из PDF."""

# краткое описание бота, которое отображается на странице профиля бота и отправляется
# вместе со ссылкой, когда пользователи делятся ботом. До 120 символов.
bot_short_description = """Free chat bot"""

# Имя бота (псевдоним), это не уникальное имя, можно назвать как угодно,
# это не имя бота на которое он отзывается. До 64 символов.
bot_name = "Бот"

# имя на которое отзывается бот по умолчанию
default_bot_name = 'бот'

# какой бот отвечает по умолчанию
# 'gemini', 'gemini15', 'llama370', 'openrouter', 'gpt4o', 'gpt4omini', 'gemma2-9b', 'haiku', 'gpt35', 'llama370', 'gpt-4o-mini-ddg'
chat_mode_default = 'gemini15'

# default locale, язык на который переводятся все сообщения
DEFAULT_LANGUAGE = 'ru'

# список админов, кому можно использовать команды /restart и вкл-выкл автоответы в чатах
admins = [xxx,]

# группа для логов, вместо(вместе с :) сохранения в текстовые файлы
# сообщения будут копироваться в эту группу, группа должна быть закрытой,
# у бота должны быть права на управление темами (тредами)
# LOGS_GROUP = -1234567890

# -1 - do not log to files
# 0 - log users to log2/ only
# 1 - log users to log/ and log2/
# LOG_MODE = 1

# id группы на которую юзеры должны подписаться что бы юзать бота
# бот должен быть в группе и возможно иметь какие то права что бы проверять есть ли в ней юзер
# subscribe_channel_id = -xxx
# subscribe_channel_mes = 'Подпишитесь на наш канал http://t.me/blabla'
# subscribe_channel_cache = 3600*24 # сутки

# сколько раз раз в минуту можно обращаться к боту до бана
DDOS_MAX_PER_MINUTE = 10
# на сколько секунд банить
DDOS_BAN_TIME = 60*10

# telegram bot token
token   = "xxx"


# id телеграм группы куда скидываются все сгенерированные картинки
# группы надо создать, добавить туда бота и дать права на публикацию
pics_group = 0
pics_group_url = ''
# pics_group = xxx
# pics_group_url = 'https://t.me/xxx'

# размер буфера для поиска в гугле, чем больше тем лучше ищет и отвечает
# и тем больше токенов жрет
# для модели с 4к памяти
#max_request = 2800
#max_google_answer = 1000
# для модели с 16к памяти
max_request = 14000
max_google_answer = 2000


# насколько большие сообщения от юзера принимать
max_message_from_user = 40000


# язык для распознавания, в том виде в котором принимает tesseract
# 'eng', 'ukr', 'rus+eng+ukr'
# можно указывать несколько через + но чем больше чем хуже, может путать буквы из разных языков даже в одном слове
# пакет для tesseract с этими языками должен быть установлен 
# https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html
ocr_language = 'rus'


# показывать ли рекламу группы Neural Networks Forum при рисовании,
# что бы люди туда уходили рисовать и отстали от моего бота
enable_image_adv = False

# https://ai.google.dev/
# ключи для Gemini
gemini_keys = ['xxx', 'yyy']

# размер истории gemini. чем больше тем больше токенов и дольше
# GEMINI_MAX_CHAT_LINES = 40

# прокси для gemini, если не указать то сначала попытается работать
# напрямую а если не получится то будет постоянно искать открытые прокси
# gemini_proxies = ['http://172.28.1.5:3128', 'socks5h://172.28.1.5:1080']

# прокси для рисования бингом (не работает пока, игнорируется)
# bing_proxy = ['socks5://172.28.1.4:1080', 'socks5://172.28.1.7:1080']
# bing_proxy = []

# отлавливать ли номера телефонов для проверки по базе мошенников
# если боту написать номер то он попробует проверить его на сайтах для проверки телефонов
PHONE_CATCHER = True


# huggin_face_models_urls = [
#     #"https://api-inference.huggingface.co/models/thibaud/sdxl_dpo_turbo",
#     #"https://api-inference.huggingface.co/models/thibaud/sdxl_dpo_turbo",

#     "https://api-inference.huggingface.co/models/stablediffusionapi/juggernaut-xl-v8",
#     "https://api-inference.huggingface.co/models/stablediffusionapi/juggernaut-xl-v8",

#     "https://api-inference.huggingface.co/models/openskyml/dalle-3-xl",
#     "https://api-inference.huggingface.co/models/openskyml/dalle-3-xl",
#     "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0",
#     #"https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2-1",
#     "https://api-inference.huggingface.co/models/cagliostrolab/animagine-xl-3.0",
#     ]


# рисование кандинским, бесплатное
# https://fusionbrain.ai/docs/ru/doc/api-dokumentaciya/
KANDINSKI_API = [
    ('api key', 'secret key'),
]

# https://yandex.cloud/ru/docs/iam/operations/iam-token/create#api_1
YND_OAUTH = ['xxx', 'yyy']


# https://console.groq.com/keys
GROQ_API_KEY = [
    'gsk_xxx',
    'gsk_yyy',
    ]
# GROQ_PROXIES = ['socks5://172.28.1.8:1080',]


# ключ от опенроутера openrouter.ai
OPEN_ROUTER_KEY = 'xxx'


# translate api https://www.deepl.com
# DEEPL_KEYS = ['xxx', 'yyy']


# shell команды которые бот может выполнять /shell
#SYSTEM_CMDS = [
#    'sudo systemctl restart wg-quick@wg1.service',
#    'python /home/ubuntu/bin/d.py',
#    'dir c:\\'
#]


# for youtube subtitles downloads
#YT_SUBS_PROXY = [
#    'socks5://user:pass@host:port',
#]


# proxy for DuckDuckGo Chat
#DDG_PROXY = [
#    'socks5://user:pass@host:port',
#]


# https://www.assemblyai.com/ speech-to-text free 100hours. slow in free account?
ASSEMBLYAI_KEYS = [
    'key1',
    'key2',
]


# курсы валют
# https://openexchangerates.org/api
# OPENEXCHANGER_KEY = 'xxx'


# https://www.cryptocompare.com/
# CRYPTOCOMPARE_KEY = 'xxx'

# for gpt 4o mini
# GPT4OMINI_URL = 'https://openrouter.ai/api/v1/chat/completions'
# GPT4OMINI_KEY = 'xxx'


# DEBUG = False
```

Что бы работало рисование бингом надо заменить куки, взять с сайта bing.com раздел чат, попасть туда можно только с ип приличных стран и с аккаунтом в микрософте. С помощью браузерного расширения cookie editor надо достать куки с именем _U и передать боту через команду /bingcookie xxx
Что бы работал Copilot (bing.com -> chat) надо сохранить оттуда куки, export в json сохранить под именем cookie*.json и регулярно проходить капчу.



7. Запустить ./tb.py



## Использование

Перед тем как приглашать бота на канал надо в настройке бота у @Botfather выбрать бота, затем зайти в `Bot Settings-Group Privacy-` и выключить. После того как бот зашел на канал надо включить опять. Это нужно для того что бы у бота был доступ к сообщениям на канале.

## Лицензия

Лицензия, под которой распространяется проект.
