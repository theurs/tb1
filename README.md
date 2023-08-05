# Телеграм бот для автопереводов и распознавания текста с скриншотов и голосовых сообщений

Чат бот отзывается на кодовое слово `бот`(можно сменить командой /name) `бот расскажи про биткоин`

Кодовое слово `гугл`(нельзя изменить) позволит получить более актуальную информацию, бот будет гуглить перед ответом `гугл, сколько людей на земле осталось`

Кодовое слово `бинг`(нельзя изменить) позволит получить более актуальную информацию, бот будет дооолго гуглить перед ответом `бинг курс биткоина`

В привате можно не писать кодовые слова для обращения к боту

Если он забился в угол и не хочет отвечать то возможно надо почистить ему память командой `бот забудь`

Кодовое слово `нарисуй` и дальше описание даст картинки сгенерированные по описанию. В чате надо добавлять к этому обращение `бот нарисуй на заборе неприличное слово`

В чате бот будет автоматически переводить иностранные тексты на русский и распознавать голосовые сообщения, отключить это можно кодовым словом `бот замолчи`, включить обратно `бот вернись`

Если отправить текстовый файл в приват или с подписью `прочитай` то попытается озвучить его как книгу, ожидает .txt utf8 язык пытается определить автоматически (русский если не получилось)

Если отправить картинку или .pdf с подписью `прочитай` то вытащит текст из них.

Если отправить ссылку в приват то попытается прочитать текст из неё и выдать краткое содержание.

Если отправить текстовый файл или пдф с подписью `что там` или `перескажи` то выдаст краткое содержание.

Команды и запросы можно делать голосовыми сообщениями, если отправить голосовое сообщение которое начинается на кодовое слово то бот отработает его как текстовую команду.


![Доступные команды](commands.txt)

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
4. Установите словари и прочее `sudo apt install aspell aspell-en aspell-ru aspell-uk enchant-2 ffmpeg chromium-browser chromium-chromedriver python3-venv sox`
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
   
5. Установите зависимости, выполнив команду:

   ```
   pip install -r requirements.txt
   python -m textblob.download_corpora
   ```

6. Создайте файл cfg.py и добавьте в него строку
```
# список админов, кому можно использовать команды /restart и вкл-выкл автоответы в чатах
admins = [xxx,]

# telegram bot token
token   = "xxx"

# openai tokens and addresses
# список  серверов для chatGPT [['address', 'token', True/False(распознавание голоса), True/False(рисование)], [], ...]
# * где можно попытаться получить халявный ключ - дискорд chimeraGPT https://discord.gg/RFFeutYK https://chimeragpt.adventblocks.cc/ru
# * https://openai-api.ckt1031.xyz/
# * https://api.waveai.link/
openai_servers = [
    ['https://xxx.com/v1', 'sk-xxx', False, False],
    ['https://yyy.com/v1', 'sk-yyy', False, False]
]

# токены для google bard
# искать __Secure-1PSID в куках с сайта https://bard.google.com/
# можно указать только 1
bard_tokens = ['xxx',
               'yyy']

# локальное разпознавание голоса, виспер лучше но требует много памяти и мощного процессора или видеокарту
#stt = 'whisper'
whisper_model = 'small' # ['tiny.en', 'tiny', 'base.en', 'base', 'small.en', 'small', 'medium.en', 'medium', 'large-v1', 'large-v2', 'large']
stt = 'vosk'

# id телеграм группы куда скидываются все сгенерированные картинки
#pics_group = 0
#pics_group_url = ''
pics_group = xxx
pics_group_url = 'https://t.me/xxx'


# размер буфера для поиска в гугле, чем больше тем лучше ищет и отвечает
# и тем больше токенов жрет
# для модели с 4к памяти
#max_request = 2800
#max_google_answer = 1000
# для модели с 16к памяти
max_request = 15000
max_google_answer = 2000


# насколько большие сообщения от юзера принимать
# если у gpt всего 4к памяти то 1500
#max_message_from_user = 1500
max_message_from_user = 4000


# 16k
max_hist_lines = 10
max_hist_bytes = 8000
max_hist_compressed=1500
max_hist_mem = 2500

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

# использовать прокси (пиратские сайты обычно лочат ваш ип, так что смотрите за этим)
all_proxy = ''
#all_proxy =   'http://172.28.1.4:3128'
#all_proxy = 'socks5://172.28.1.5:1080'


key_test = ''
openai_api_base_test = ''
model_test = 'gpt-3.5-turbo-16k'

# язык для распознавания, в том виде в котором принимает tesseract
# 'eng', 'ukr', 'rus+eng+ukr'
# можно указывать несколько через + но чем больше чем хуже, может путать буквы из разных языков даже в одном слове
# пакет для tesseract с этими языками должен быть установлен 
# https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html
ocr_language = 'rus'


# сокс прокси для команды ask. сервис perplexity.ai на случай если напрямую не работает
# perplexity_proxies = None
# работает только так, с обязательным именем паролем адресом и портом
perplexity_proxies = [
    'socks5://user1:passwd@1.2.3.4:1234',
    'socks5://user1:passwd@example.ru:54821',
    ...
    ]

# ключи для клауда 'sessionKey=sk....' искать на сайте claude.ai через американский прокси
claudeai_keys = ['sessionKey=sk-xxxxxxxxxx',]
# прокси для клода, американский. либо = None
claude_proxy = None
#claude_proxy = {
#    'http': "socks5://172.28.1.7:1080",
#    'https': "socks5://172.28.1.7:1080",
#}

```

Для работы распознавания голосовых сообщений надо установить vosk сервер.

`https://github.com/alphacep/vosk-server`

В докере.

`docker run -d -p 2700:2700 --name kaldi-ru --restart always -v /home/ubuntu/vosk/vosk-model-small-ru-0.22:/opt/vosk-model-en/model alphacep/kaldi-en:latest` тут путь заменить и модель скачать в эту папку

Eсли на сервере много оперативки то можно по другому

`docker run -d -p 2700:2700 --name kaldi-ru --restart always  alphacep/kaldi-ru:latest`

Надо несколько 4+ гигабайт на диске и несколько гигабайт оперативной памяти (не знаю сколько но много).

Что бы работал бинг аи надо сохранить свои куки с сайта bing.com раздел чат, попасть туда можно только с ип приличных стран и с аккаунтом в микрософте.
Сохранить куки можно с помощью браузерного расширения cookie editor. Формат json, имя cookies.json



7. Запустить ./tb.py

Можно собрать и запустить докер образ. Ну или нельзя Ж) давно не проверял.

В докер файл можно добавить свой файл cfg.py
Как в него засунуть vosk сервер я не знаю.


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
