FROM ubuntu:latest

WORKDIR /app

COPY requirements.txt commands.txt cookies.json  /app/
COPY bingai.py gpt_basic.py  my_dic.py  my_log.py  my_ocr.py  my_stt.py  my_trans.py  my_tts.py  tb.py /app/

RUN apt-get update && apt-get install -y software-properties-common && \
    add-apt-repository -y ppa:alex-p/tesseract-ocr5 && \
    apt-get update && \
    apt-get -y upgrade

RUN apt-get install -y \
    python3 \
    python3-pip \
    bsdmainutils \
    translate-shell \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-rus \
    tesseract-ocr-ukr \
    tesseract-ocr-osd \
    aspell \
    aspell-en \
    aspell-uk \
    aspell-ru \
    enchant-2 \
    locales && rm -rf /var/lib/apt/lists/* \
    && localedef -i en_US -c -f UTF-8 -A /usr/share/locale/locale.alias en_US.UTF-8


RUN pip install --no-cache-dir -r requirements.txt


ENV LANG=en_US.utf8
# передача токена через переменную окружения
ENV TOKEN=${TOKEN}
ENV OPENAI_KEY=${OPENAI_KEY}


CMD ["python3", "tb.py"]
