# Телеграм бот для доступа к chatGPT, Google Bard, Claude AI и др

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

При общении с Claude загруженные файлы отправляются прямо к нему и в дальнейшем он может отвечать по их содержанию. Отправленные в этом режиме ссылки будут переданы клауду как текстовые файлы с содержанием этих веб страниц (и видео субтитров).

Команды и запросы можно делать голосовыми сообщениями, если отправить голосовое сообщение которое начинается на кодовое слово то бот отработает его как текстовую команду.


![Доступные команды](commands.txt)

**Команды для администратора**

/alert - массовая рассылка сообщения от администратора во все чаты, маркдаун форматирование, отправляет сообщение без уведомления но всё равно не приятная штука похожая на спам

/init - инициализация бота, установка описаний на всех языках, не обязательно, можно и вручную сделать, выполняется долго, ничего не блокирует

/dump_translation - отправляет файл с авто-переводами выполнеными гуглом для ручной доработки, исправленный перевод надо просто отправить боту от имени администратора

/blockadd - добавить id '[chat_id] [thread_id]' в список заблокированных (игнорируемых) юзеров или чатов, учитывается только первая цифра, то есть весь канал со всеми темами внутри

/blockdel - удалить id из игнорируемых

/blocklist - список игнорируемых

/fixlang <lang> - исправить автоперевод сделанный с помощью гугла для указанного языка, будет использоваться чатгпт для этого

/leave <chat_id> - выйти из чата (можно вместо одного id вывалить кучу, все номера похожие на номер группы в тексте будут использованы)

/revoke <chat_id> - убрать чат из списка на автовыхода(бана) (можно вместо одного id вывалить кучу, все номера похожие на номер группы в тексте будут использованы)

/model - меняет модель для chatGPT, доступно всем но как работает неизвестно, зависит от того что есть на бекендах

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

/chatgpt - обращение к chatgpt из другого режима

/gemini - обращение к gemini из другого режима

/claude - обращение к claude из другого режима

/bard - обращение к bard из другого режима

/gigachat - обращение к gigachat из другого режима, его в меню нет тк он слишком дорогой

/copilot - обращение к copilot из другого режима

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

ChatGPT | Google Bard | Claude AI

Голосовое управление, озвучивание текстов, пересказ веб страниц и видеороликов на Youtube, распознавание текста с картинок и из PDF."""

# краткое описание бота, которое отображается на странице профиля бота и отправляется
# вместе со ссылкой, когда пользователи делятся ботом. До 120 символов.
bot_short_description = """Free chat bot

ChatGPT | Google Bard | Claude AI"""

# Имя бота (псевдоним), это не уникальное имя, можно назвать как угодно,
# это не имя бота на которое он отзывается. До 64 символов.
bot_name = "Бот"

# имя на которое отзывается бот по умолчанию
default_bot_name = 'бот'

# какой бот отвечает по умолчанию
# 'bard', 'claude', 'chatgpt', 'gemini', 'gemini15', 'gigachat', 'bing'
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


# 16k
max_hist_lines = 10
max_hist_bytes = 9000
max_hist_compressed=1500
max_hist_mem = 2500
# максимальный запрос от юзера к chatGPT. длинные сообщения телеграм бьет на части но
# бот склеивает их обратно и может получиться слишком много
CHATGPT_MAX_REQUEST = 7000

# 4k
#max_hist_lines = 10
#max_hist_bytes = 2000
#max_hist_compressed=700
#max_hist_mem=300

model = 'gpt-3.5-turbo-16k'
#model = 'gpt-3.5-turbo-8k'
#model = 'gpt-3.5-turbo'
#model = "sage"
#model = 'claude-instant'
#model = 'claude-instant-100k'
#model = 'claude-2-100k'


# язык для распознавания, в том виде в котором принимает tesseract
# 'eng', 'ukr', 'rus+eng+ukr'
# можно указывать несколько через + но чем больше чем хуже, может путать буквы из разных языков даже в одном слове
# пакет для tesseract с этими языками должен быть установлен 
# https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html
ocr_language = 'rus'


# ключи для клауда 'sessionKey=sk....' искать на сайте claude.ai через американский прокси
claudeai_keys = ['sessionKey=sk-xxxxxxxxxx',] или None
# прокси для клода не получилось сделать, так что надо использовать впн туннель, 
# перенаправить в него адреса которые резолвятся из nslookup claude.ai

# показывать ли рекламу группы Neural Networks Forum при рисовании,
# что бы люди туда уходили рисовать и отстали от моего бота
enable_image_adv = False

# кодовые слова которые можно использовать вместо команды /music
MUSIC_WORDS = ['муз', 'ytb']

# https://ai.google.dev/
# ключи для Gemini Pro
gemini_keys = ['xxx', 'yyy']
# прокси для gemini pro, если не указать то сначала попытается работать
# напрямую а если не получится то будет постоянно искать открытые прокси
# gemini_proxies = ['http://172.28.1.5:3128', 'socks5h://172.28.1.5:1080']

# максимальный размер для скачивания музыки с ютуба в секундах
# если есть локальный сервер то можно много, если нет то 20 минут
# больше 50мбайт телеграм не пропустит :(
MAX_YTB_SECS = 20*60

# прокси для рисования бингом (не работает пока, игнорируется)
# bing_proxy = ['socks5://172.28.1.4:1080', 'socks5://172.28.1.7:1080']
bing_proxy = []

# показывать ли кнопки для скачивания тикток ссылок,
# может быть полезно там где он заблокирован
TIKTOK_ENABLED = True

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
