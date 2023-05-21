FROM python:3.9-slim-buster

WORKDIR /app

COPY my_ocr.py my_log.py my_trans.py requirements.txt tb.py /app/


RUN echo "deb http://deb.debian.org/debian buster main contrib non-free" >> /etc/apt/sources.list \
    && echo "deb http://deb.debian.org/debian-security/ buster/updates main contrib non-free" >> /etc/apt/sources.list \
    && echo "deb http://deb.debian.org/debian buster-updates main contrib non-free" >> /etc/apt/sources.list

RUN apt-get update && apt-get install -y --no-install-recommends \
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
    enchant \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

# передача токена через переменную окружения
ENV TOKEN=${TOKEN}

CMD ["python", "tb.py"]
