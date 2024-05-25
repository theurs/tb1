#!/usr/bin/env python3
# pip install -U spacy
## python -m spacy download ru_core_news_sm
## python -m spacy download ru_core_news_md
# python -m spacy download ru_core_news_lg

import time

import spacy


def search_relevant_chunks(text, query, nlp, similarity_threshold=0.5, chunk_size=5):
    """
    Поиск релевантных кусков текста с использованием spaCy.

    Args:
        text (str): Текст для поиска.
        query (str): Запрос для поиска.
        nlp (spacy.Language): Загруженная модель spaCy.
        similarity_threshold (float): Порог сходства для отбора релевантных кусков.
        chunk_size (int): Количество предложений в каждом куске текста.

    Returns:
        list: Список релевантных кусков текста.
    """
    start_time = time.time()
    doc = nlp(text)
    print(f"Обработан текст размером {len(text)} за {time.time() - start_time} секунд")

    query_doc = nlp(query)
    relevant_chunks = []

    start_time = time.time()
    sentences = list(doc.sents)
    for i in range(0, len(sentences), chunk_size):
        chunk = sentences[i:i + chunk_size]
        chunk_text = " ".join([sent.text for sent in chunk])
        chunk_doc = nlp(chunk_text)
        similarity = chunk_doc.similarity(query_doc)

        if similarity > similarity_threshold:
            relevant_chunks.append((chunk_text, similarity))

    print(f"Найдено {len(relevant_chunks)} релевантных кусков за {time.time() - start_time} секунд")

    # оставить только 10 самых близких кусков
    relevant_chunks = sorted(relevant_chunks, key=lambda x: x[1], reverse=True)[:10]

    return [x[0] for x in relevant_chunks]


if __name__ == "__main__":

    text = open("1.txt", encoding="windows-1251").read()
    query = "кто соблазнял героя, принцесса или кто то там был такой"
    nlp = spacy.load("ru_core_news_md")

    relevant_chunks = search_relevant_chunks(text, query, nlp)

    for chunk in relevant_chunks:
        print(f"---\n{chunk}\n---")
