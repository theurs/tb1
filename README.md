# Телеграм бот для доступа к Google Gemini, MS Bing etc

Тестовый образец https://t.me/kun4sun_bot

Чат бот отзывается на кодовое слово `бот`(можно сменить командой /name) `бот расскажи про биткоин`

Кодовое слово `гугл`(нельзя изменить) позволит получить более актуальную информацию, бот будет гуглить перед ответом `гугл, сколько людей на земле осталось`

В привате можно не писать кодовые слова для обращения к боту

Если он перестал отвечать то возможно надо почистить ему память командой `забудь` `бот забудь`

Кодовое слово `нарисуй` и дальше описание даст картинки сгенерированные по описанию. В чате надо добавлять к этому обращение `бот нарисуй на заборе неприличное слово`

В чате бот будет автоматически распознавать голосовые сообщения, включить это можно в настроках.

Если отправить текстовый файл или пдф то выдаст краткое содержание.

Если отправить картинку или .pdf с подписью `ocr` то вытащит текст из них.

Если отправить ссылку в приват то попытается прочитать текст из неё и выдать краткое содержание.

Если отправить картинку с другой подписью или без подписи то напишет описание того что изображено на картинке или ответит на вопрос из подписи, в чате надо начинать с знака ?

Если ссылка на тикток видео то предложит его скачать (это нужно для рф где он заблокирован)

Если отправить номер телефона то попробует узнать кто звонил

Если начать с точки то будет использована модель gpt-3.5-turbo-instruct, она дает ответы без дополнений которые обычно есть в диалогах, и почти без цензуры. Её ответы попадают в память к Gemini Pro как ее собственные и могут развязать ей язык.

Команды и запросы можно делать голосовыми сообщениями, если отправить голосовое сообщение которое начинается на кодовое слово то бот отработает его как текстовую команду.


![Доступные команды](commands.txt)

**Команды для администратора**

/alert - массовая рассылка сообщения от администратора во все чаты, маркдаун форматирование, отправляет сообщение без уведомления но всё равно не приятная штука похожая на спам

/init - инициализация бота, установка описаний на всех языках, не обязательно, можно и вручную сделать, выполняется долго, ничего не блокирует

/enable - включить бота в публичном чате (комнате)
/disable - выключить бота в публичном чате (комнате)

/blockadd - добавить id '[chat_id] [thread_id]' в список заблокированных (игнорируемых) юзеров или чатов, учитывается только первая цифра, то есть весь канал со всеми темами внутри

/blockdel - удалить id из игнорируемых

/blocklist - список игнорируемых

/leave <chat_id> - выйти из чата (можно вместо одного id вывалить кучу, все номера похожие на номер группы в тексте будут использованы)

/revoke <chat_id> - убрать чат из списка на автовыхода(бана) (можно вместо одного id вывалить кучу, все номера похожие на номер группы в тексте будут использованы)

/restart - перезапуск бота на случай зависания

/stats - статистика бота (сколько было активно за последнее время)
/stats2 - статистика бота

/style2 - изменить стиль бота для заданного чата (пример: /style2 [id] [topic id] новая роль)

/reset_gemini2 - очистить историю чата Gemini Pro в другом чате Usage: /reset_gemini2 <chat_id_full!>

/gemini_proxy - [DEBUG] показывает список прокси которые нашел бот для Gemini Pro

/bingcookie - (/cookie /k) добавить куки для бинга, можно несколько через пробел

/bingcookieclear (/kc) - удалить все куки для бинга

/disable_chat_mode from to - принудительно сменить всем режим чата, например у кого бард переключить на джемини

/trial - userid_as_integer amount_of_monthes_to_add

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
# [urs, port, addr] | None
# webhook = ["https://mydomain.com/bot", 33333, '0.0.0.0']
webhook = None

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
# 'gemini', 'gemini15'
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

# активированы ли триальные периоды, бот будет выпрашивать донаты после нескольких дней работы
# если израсхововано меньше сообщений то продолжит работать и после 7 дней
# после послания бот даст еще 20 сообщений и снова покажет табличку с донатами и так по кругу
# TRIALS = True
# TRIAL_DAYS = 7
# TRIAL_MESSAGES = 300

# id группы на которую юзеры должны подписаться что бы юзать бота
# бот должен быть в группе и возможно иметь какие то права что бы проверять есть ли в ней юзер
# subscribe_channel_id = -xxx
# subscribe_channel_mes = 'Подпишитесь на наш канал http://t.me/blabla'
# subscribe_channel_cache = 3600*24 # сутки


# список юзеров кому доступен chatGPT (он хоть и дешевый но не бесплатный)
# если список пуст то всем можно
# allow_chatGPT_users = [xxx,]

# сколько раз раз в минуту можно обращаться к боту до бана
DDOS_MAX_PER_MINUTE = 15
# на сколько секунд банить
DDOS_BAN_TIME = 60*20

# telegram bot token
token   = "xxx"

# openai tokens and addresses
# список  серверов для chatGPT [['address', 'token', True/False(распознавание голоса), True/False(рисование)], [], ...]
# можно использовать стороннии сервисы работающие так же как openai например https://vsegpt.ru/
openai_servers = [
    ['https://api.openai.com/v1', 'sk-xxx', False, False],
    ['https://api.vsegpt.ru:6070/v1/', 'sk-or-vv-xxx', False, False],
    ['https://yyy.com/xxx', 'key', False, False]
]

# proxy for access openai
# openai_proxy = 'socks5://172.28.1.4:1080'
# openai_proxy = 'http://172.28.1.4:3128'


# искать (__Secure-1PSIDCC, __Secure-1PSID, __Secure-1PSIDTS, NID) в куках с сайта https://gemini.google.com/
# [(__Secure-1PSIDCC, __Secure-1PSID, __Secure-1PSIDTS, NID), ...]
bard_tokens = [
    ('xxx',
     'yyy',
     'zzz',
     'aaa'),
]


# id телеграм группы куда скидываются все сгенерированные картинки
# группы надо создать, добавить туда бота и дать права на публикацию
pics_group = 0
pics_group_url = ''
# pics_group = xxx
# pics_group_url = 'https://t.me/xxx'
# id телеграм группы куда скидываются все скаченные ролики с ютуба
videos_group = 0
videos_group_url = ''
# videos_group = xxxx
# videos_group_url = 'https://t.me/xxx'


# размер буфера для поиска в гугле, чем больше тем лучше ищет и отвечает
# и тем больше токенов жрет
# для модели с 4к памяти
#max_request = 2800
#max_google_answer = 1000
# для модели с 16к памяти
max_request = 14000
max_google_answer = 2000


# насколько большие сообщения от юзера принимать
max_message_from_user = 90000


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
# ключи для Gemini Pro
gemini_keys = ['xxx', 'yyy']

# размер истории gemini, (40 = 20 запросов и 20 ответов). чем больше тем больше токенов и дольше
GEMINI_MAX_CHAT_LINES = 40

# прокси для gemini pro, если не указать то сначала попытается работать
# напрямую а если не получится то будет постоянно искать открытые прокси
# gemini_proxies = ['http://172.28.1.5:3128', 'socks5h://172.28.1.5:1080']

# прокси для рисования бингом (не работает пока, игнорируется)
# bing_proxy = ['socks5://172.28.1.4:1080', 'socks5://172.28.1.7:1080']
bing_proxy = []

# отлавливать ли номера телефонов для проверки по базе мошенников
# если боту написать номер то он попробует проверить его на сайтах для проверки телефонов
PHONE_CATCHER = True

# рисование ключами stable diffusion
# https://stablediffusionapi.com/dashboard/apikeys
# STABLE_DIFFUSION_API = ['xxx',
#                        'yyy',]

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

# !!постоплата!! можно сильно влететь
# gigachat api ['xxx1','xxx2',...]
# https://developers.sber.ru/studio/workspaces/
# Используйте ключи для подключения сервиса -> Сгенерировать новый Client Secret -> Авторизационные данные
# дают бесплатно 1млн токенов в год и далее 5млн за 1000р или 25млн за 4850р
# GIGACHAT_API = [
#     'xxx1', 'xxx2'
#     ]
# сколько сообщений помнить (запрос+ответ=2 сообщения)
# GIGACHAT_MAX_MESSAGES = 20
# сколько символов помнить (какие лимиты хз, сколько стоит тоже хз, токены и символы это разные вещи)
# GIGACHAT_MAX_SYMBOLS = 10000
# не принимать запросы больше чем, это ограничение для телеграм бота (какие лимиты - хз)
# GIGACHAT_MAX_QUERY = 4000

# whisper api servers for speech to text
# [(address, port), (adress2, port2),]
# MY_WHISPER_API = [
#    ('10.147.17.227','34671'),
#    ('10.147.17.26', '34671'),
#    ]

# рисование кандинским, бесплатное
# https://fusionbrain.ai/docs/ru/doc/api-dokumentaciya/
KANDINSKI_API = [
    ('api key', 'secret key')
]

# гпт4 и далли3. просто ссылка в меню на отдельного бота с гпт4-турбо и далли3
coze_bot = 'https://t.me/kun6sun_bot'

# image creation with https://platform.stability.ai/account/keys
STABILITY_API = [
    'sk-xxx', # acc1
    'sk-yyy', # accN
]


# https://yandex.cloud/ru/docs/iam/operations/iam-token/create#api_1
YND_OAUTH = ['xxx1','xxx2']


# https://openrouter.ai/
# openrouter_api = ['xxx','yyy',]

```

Что бы работало рисование бингом надо заменить куки, взять с сайта bing.com раздел чат, попасть туда можно только с ип приличных стран и с аккаунтом в микрософте. С помощью браузерного расширения cookie editor надо достать куки с именем _U и передать боту через команду /bingcookie xxx
Что бы работал Copilot (bing.com -> chat) надо сохранить оттуда куки, export в json сохранить под именем cookie*.json и регулярно проходить капчу.



7. Запустить ./tb.py

Можно собрать и запустить докер образ. Ну или нельзя Ж) давно не проверял.

В докер файл можно добавить свой файл cfg.py


```
docker build  -t tb1 .
или
docker build --no-cache -t tb1 .
или
docker build --no-cache -t tb1 . &> build.log

docker run -d --env TOKEN='xxx' --name tb1 --restart unless-stopped tb1
или
docker run --env TOKEN='xxx' --name tb1 --restart unless-stopped tb1
или
docker run -d --env TOKEN='xxx' --env OPENAI_KEY='yyy' -e TZ=Asia/Vladivostok --name tb1 --restart unless-stopped tb1
```


## Использование

Перед тем как приглашать бота на канал надо в настройке бота у @Botfather выбрать бота, затем зайти в `Bot Settings-Group Privacy-` и выключить. После того как бот зашел на канал надо включить опять. Это нужно для того что бы у бота был доступ к сообщениям на канале.

## Лицензия

Лицензия, под которой распространяется проект.
