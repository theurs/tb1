# pip install diskcache zstandard


import functools
# import io
# import lzma
# import random
import re
import time
import threading
from pathlib import Path

import diskcache
import numpy as np
import pandas as pd
from google import genai
from google.genai import types
# import zstandard as zstd

# import cfg
import my_db
import my_log
import my_gemini_general


# # Заголовки для определения алгоритма
# ZSTD_HEADER = b'ZSTD'
# LZMA_HEADER = b'LZMA'
# NONE_HEADER = b'NONE'


EMBEDDING_MODEL_ID = MODEL_ID = "gemini-embedding-001"


cache_dir = Path("./db/cache-gemini-embedding")
cache_dir.mkdir(exist_ok=True) # Создаем папку, если ее нет
# Создаем объект кеша
# Теперь 'cache.memoize' можно использовать как декоратор
cache = diskcache.Cache(str(cache_dir))


def rate_limiter(max_calls, max_tokens, time_window=60):
    """
    Потокобезопасный декоратор для управления лимитами API.

    Отслеживает количество вызовов и "потраченных" токенов за определенный
    промежуток времени. Если лимит скоро будет превышен, декоратор
    автоматически заставляет поток подождать.
    """
    def decorator(func):
        # Переменные состояния, общие для всех потоков
        calls = []
        tokens_in_window = 0
        lock = threading.Lock()  # Один замок для защиты общих переменных

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal tokens_in_window

            # Приблизительная оценка токенов делается один раз до входа в цикл
            estimated_tokens = len(kwargs.get('text', '')) + len(kwargs.get('title', ''))

            # "Зал ожидания": поток будет крутиться здесь, пока не получит разрешение
            while True:
                # Захватываем замок, чтобы безопасно проверить и изменить состояние
                with lock:
                    current_time = time.time()

                    # 1. Очищаем историю от старых вызовов
                    calls[:] = [c for c in calls if c > current_time - time_window]
                    if not calls:
                        # Если вызовов не осталось, мы в новом окне, сбрасываем токены
                        tokens_in_window = 0

                    # 2. Проверяем, есть ли свободный "слот"
                    if len(calls) < max_calls and (tokens_in_window + estimated_tokens) <= max_tokens:
                        # Ура, лимит не превышен!
                        # Обновляем состояние прямо внутри замка...
                        calls.append(current_time)
                        tokens_in_window += estimated_tokens
                        # ... и выходим из цикла ожидания
                        break

                    # Если мы здесь, лимит превышен. Вычисляем время ожидания.
                    time_to_wait = calls[0] - (current_time - time_window) + 0.1

                # 3. Ждем вне замка, чтобы не блокировать другие потоки
                # print(f"Rate limit reached. Thread waiting for {time_to_wait:.2f}s...")
                my_log.log_gemini(f"Rate limit reached. Thread waiting for {time_to_wait:.2f}s...")
                time.sleep(time_to_wait)
                # После ожидания цикл начнется снова, и поток опять попробует получить слот

            # 4. Если мы вышли из цикла, значит, разрешение получено. Выполняем функцию.
            return func(*args, **kwargs)

        return wrapper
    return decorator


# Создаем экземпляр нашего декоратора с нужными лимитами
# API Gemini для эмбеддингов - 1500 запросов в минуту (QPM)
# и 30 000 токенов в минуту.
# Возьмем с запасом, например 100 QPM. Лимит по токенам важнее.
limiter = rate_limiter(max_calls=100, max_tokens=30000)


@cache.memoize()
@limiter
def embed_fn(title, text):
    """
    Вычисляет эмбеддинг для текста, с 5 попытками в случае ошибки сети.
    """
    # print(f"!!! CACHE MISS: Calling Gemini API for title: '{title[:30]}...'")

    retries = 5
    delay = 5  # начальная задержка в секундах, всего получится 5+10+20+40 = 75

    for attempt in range(retries):
        try:
            client = genai.Client(api_key=my_gemini_general.get_next_key())
            response = client.models.embed_content(
                model=EMBEDDING_MODEL_ID,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type="retrieval_document",
                    title=title
                )
            )
            return response.embeddings[0].values

        # Ловим конкретные ошибки API или общие ошибки сети
        except Exception as e:
            if attempt < retries - 1:
                my_log.log_gemini(f"my_gemini_embedding:emded_fn: API call failed (attempt {attempt + 1}/{retries}): {e}. Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2  # Увеличиваем задержку
            else:
                my_log.log_gemini(f"my_gemini_embedding:emded_fn: API call failed after {retries} attempts. Giving up.")
                # Если все попытки провалены, пробрасываем последнюю ошибку
                raise e


def split_text_into_chunks(text: str, max_length_chars: int = 3000, overlap_chars: int = 400) -> list[str]:
    """
    Разбивает текст на осмысленные фрагменты (чанки), идеально подходящие для
    обработки языковыми моделями.

    Эта функция — настоящий швейцарский нож для подготовки текста:
    1.  **Рекурсивное разбиение**: Сначала пытается делить по параграфам,
        затем по предложениям, и так далее, чтобы сохранить структуру текста.
    2.  **Перекрытие (Overlap)**: Каждый следующий чанк включает в себя
        небольшой "хвост" от предыдущего. Это гарантирует, что контекст
        не потеряется на границах фрагментов.
    3.  **Безопасность**: Работает с количеством символов, а не токенов,
        поэтому `max_length_chars` выбрано с запасом (3000 символов — это
        примерно 700-1500 токенов), чтобы точно не превысить лимиты API.

    Args:
        text (str): Входной текст для разбиения.
        max_length_chars (int): Максимальная длина чанка в символах.
                                Должна быть больше, чем `overlap_chars`.
        overlap_chars (int): Количество символов для перекрытия между чанками.

    Returns:
        list[str]: Список текстовых фрагментов, готовых к дальнейшей обработке.
    """
    if not isinstance(text, str) or not text.strip():
        return []

    if max_length_chars <= overlap_chars:
        raise ValueError(
            "max_length_chars должен быть больше, чем overlap_chars, "
            "иначе возникнет бесконечная рекурсия."
        )

    # Приоритетный список разделителей: от крупных к мелким.
    separators = ["\n\n", "\n", ". ", "? ", "! ", " "]

    # --- Шаг 1: Рекурсивно разбиваем текст на базовые чанки ---
    # Начинаем с всего текста как одного большого чанка
    text_chunks_to_process = [text]

    for separator in separators:
        next_text_chunks_to_process = []
        for chunk in text_chunks_to_process:
            if len(chunk) <= max_length_chars:
                # Этот чанк уже достаточно мал, его больше не трогаем
                next_text_chunks_to_process.append(chunk)
            else:
                # Чанк слишком большой, разбиваем его текущим сепаратором
                # и отправляем на следующую итерацию для дальнейшего деления
                parts = chunk.split(separator)
                current_merged_chunk = ""
                for part in parts:
                    if len(current_merged_chunk) + len(part) + len(separator) > max_length_chars:
                        if current_merged_chunk:
                           next_text_chunks_to_process.append(current_merged_chunk)
                        current_merged_chunk = part
                    else:
                        if current_merged_chunk:
                           current_merged_chunk += separator + part
                        else:
                           current_merged_chunk = part
                if current_merged_chunk:
                    next_text_chunks_to_process.append(current_merged_chunk)

        text_chunks_to_process = next_text_chunks_to_process

    final_chunks = text_chunks_to_process # Все чанки, которые <= max_length_chars

    # --- Шаг 2: Применяем перекрытие (overlap) ---
    if overlap_chars > 0 and len(final_chunks) > 1:
        overlapped_chunks = [final_chunks[0]] # Первый чанк без изменений
        for i in range(1, len(final_chunks)):
            prev_chunk_end = final_chunks[i-1][-overlap_chars:]
            current_chunk = final_chunks[i]

            # Добавляем хвост предыдущего чанка к текущему
            overlapped_chunks.append(prev_chunk_end + current_chunk)
        return overlapped_chunks
    else:
        return final_chunks


def create_knowledge_base(raw_documents: list[dict]) -> pd.DataFrame:
    """
    Создает и обрабатывает базу знаний из списка "сырых" документов.
    Разбивает большие документы на чанки и генерирует их эмбеддинги.
    Если фрагменты закешированы то выполняется так быстро что нет смысла сохранять на диск и восстанавливать.

    Args:
        raw_documents (list[dict]): Список словарей, где каждый словарь
                                    представляет исходный документ
                                    (например, `{"title": "...", "content": "..."}`).

    Returns:
        pd.DataFrame: DataFrame, содержащий обработанные чанки,
                      их оригинальные заголовки (с номером части, если разбито)
                      и соответствующие эмбеддинги.
    """
    processed_documents_data = []
    for doc in raw_documents:
        # Разбиваем контент на чанки
        content_chunks = split_text_into_chunks(doc["content"])

        if len(content_chunks) == 1:
            # Если документ не был разбит, добавляем его как есть
            processed_documents_data.append({
                "Title": doc["title"],
                "Text": content_chunks[0] # Используем content_chunks[0], так как он мог быть очищен/обработан
            })
        else:
            # Если документ был разбит на несколько чанков, создаем записи для каждой части
            for i, chunk_text in enumerate(content_chunks):
                chunk_title = f"{doc['title']} - Part {i + 1}"
                processed_documents_data.append({
                    "Title": chunk_title,
                    "Text": chunk_text
                })

    # Создаем DataFrame из обработанных чанков
    df = pd.DataFrame(processed_documents_data)

    # Вычисляем эмбеддинги для каждого чанка
    df['Embeddings'] = df.apply(lambda row: embed_fn(row['Title'], row['Text']), axis=1)

    return df


# def serialize_dataframe(df: pd.DataFrame, compression: str = 'zstd', level: int = 6) -> bytes:
#     """
#     Сериализует Pandas DataFrame в байты, добавляя заголовок для
#     идентификации метода сжатия.

#     Args:
#         df (pd.DataFrame): DataFrame для сериализации.
#         compression (str): Метод обработки: 'zstd' (по умолчанию), 
#                            'lzma' или 'none' (без сжатия).
#         level (int): Уровень сжатия для 'zstd'. По умолчанию 6.
#     """
#     buffer = io.BytesIO()
#     df.to_pickle(buffer)
#     uncompressed_bytes = buffer.getvalue()

#     if compression == 'zstd':
#         compressed_bytes = zstd.compress(uncompressed_bytes, level=level)
#         final_bytes = ZSTD_HEADER + compressed_bytes
#     elif compression == 'lzma':
#         compressed_bytes = lzma.compress(uncompressed_bytes)
#         final_bytes = LZMA_HEADER + compressed_bytes
#     elif compression == 'none':
#         final_bytes = NONE_HEADER + uncompressed_bytes
#     else:
#         raise ValueError(f"Неизвестный метод: {compression}. Доступны 'zstd', 'lzma', 'none'.")

#     print(f"Метод обработки: {compression}")
#     print(f"Исходный размер (pickle): {len(uncompressed_bytes)} байт")
#     print(f"Итоговый размер (с заголовком): {len(final_bytes)} байт")
#     return final_bytes


# def deserialize_dataframe(data_bytes: bytes) -> pd.DataFrame:
#     """
#     Десериализует байты обратно в Pandas DataFrame, используя заголовок
#     для определения правильного метода распаковки.
#     """
#     header = data_bytes[:4]
#     payload = data_bytes[4:]

#     if header == ZSTD_HEADER:
#         decompressed_bytes = zstd.decompress(payload)
#     elif header == LZMA_HEADER:
#         decompressed_bytes = lzma.decompress(payload)
#     elif header == NONE_HEADER:
#         decompressed_bytes = payload  # Сжатия не было, используем "полезную нагрузку" как есть
#     else:
#         raise ValueError("Не удалось определить формат данных: неизвестный или поврежденный заголовок.")

#     buffer = io.BytesIO(decompressed_bytes)
#     df = pd.read_pickle(buffer)
#     return df


def find_best_passages(
    query: str,
    dataframe: pd.DataFrame,
    target_size_chars: int = 20000
) -> str:
    """
    Находит наиболее релевантные фрагменты текста, чтобы собрать из них
    единый контекст, СТРОГО не превышающий заданный размер,
    и форматирует результат в виде XML-подобной строки.

    Args:
        query (str): Запрос пользователя.
        dataframe (pd.DataFrame): DataFrame с данными.
        target_size_chars (int): Максимальный размер итоговой строки в символах.

    Returns:
        str: Строка в XML-формате.
    """
    if dataframe.empty:
        return ""

    # 1. Получаем эмбеддинг для запроса
    client = genai.Client(api_key=my_gemini_general.get_next_key())
    query_embedding_response = client.models.embed_content(
        model=EMBEDDING_MODEL_ID,
        contents=query,
        config=types.EmbedContentConfig(task_type="retrieval_query")
    )
    query_embedding = query_embedding_response.embeddings[0].values

    # 2. Считаем и сортируем все фрагменты по релевантности
    dot_products = np.dot(np.stack(dataframe['Embeddings'].values), query_embedding)
    all_passages = []
    for i, row in dataframe.iterrows():
        all_passages.append({
            'title': row['Title'],
            'text': row['Text'],
            'relevance': dot_products[i]
        })
    all_passages.sort(key=lambda x: x['relevance'], reverse=True)

    # 3. Итеративно набираем фрагменты, строго контролируя общий размер
    candidate_passages = []
    current_total_size = 0

    # Экранируем запрос один раз
    safe_query = query.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    for passage in all_passages:
        # Сначала — логически сортируем ТЕКУЩИЙ набор кандидатов
        temp_candidates = candidate_passages + [passage]
        title_pattern = re.compile(r"^(.*?)(?: - Part (\d+))?$")
        for p in temp_candidates:
            if 'original_title' not in p: # Парсим только новые
                match = title_pattern.match(p['title'])
                if match:
                    p['original_title'] = match.group(1).strip()
                    p['part_number'] = int(match.group(2)) if match.group(2) else 1
                else:
                    p['original_title'] = p['title']
                    p['part_number'] = 1
        temp_candidates.sort(key=lambda x: (x['original_title'], x['part_number']))

        # Теперь "рендерим" потенциальную итоговую строку и считаем её длину
        # Это самый точный способ узнать будущий размер

        # Заголовок и метаданные
        temp_text_len = sum(len(p['text']) for p in temp_candidates)
        meta_line = f"<meta>Найдено {len(temp_candidates)} фрагментов, общая длина {temp_text_len} символов.</meta>"

        # Собираем все части в список
        output_parts = ["<fragments>"]
        output_parts.append(f"<query>{safe_query}</query>")
        output_parts.append(meta_line)

        for i, p in enumerate(temp_candidates, 1):
            safe_title = p['title'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            safe_text = p['text'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            output_parts.append(f"<fragment_source_{i}>{safe_title}</fragment_source_{i}>")
            output_parts.append(f"<fragment_text_{i}>\n{safe_text}\n</fragment_text_{i}>")

        output_parts.append("</fragments>")

        # Считаем длину, как если бы мы соединили все части через \n
        provisional_size = len("\n".join(output_parts))

        # Главная проверка: если вылезли за лимит, не добавляем последний фрагмент и выходим
        if provisional_size > target_size_chars:
            break

        # Если всё хорошо, фиксируем добавление фрагмента
        candidate_passages.append(passage)
        current_total_size = provisional_size

    # 4. Финальная сборка результата из утвержденных кандидатов
    # (повторяем рендеринг, но уже с финальным списком)
    candidate_passages.sort(key=lambda x: (x['original_title'], x['part_number']))
    final_text_len = sum(len(p['text']) for p in candidate_passages)

    output_parts = ["<fragments>"]
    output_parts.append(f"<query>{safe_query}</query>")
    output_parts.append(f"<meta>Найдено {len(candidate_passages)} фрагментов, общая длина {final_text_len} символов. Итоговый размер: {current_total_size} из {target_size_chars}.</meta>")

    for i, p in enumerate(candidate_passages, 1):
        safe_title = p['title'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        safe_text = p['text'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        output_parts.append(f"<fragment_source_{i}>{safe_title}</fragment_source_{i}>")
        output_parts.append(f"<fragment_text_{i}>\n{safe_text}\n</fragment_text_{i}>")
        
    output_parts.append("</fragments>")
    
    return "\n".join(output_parts)


if __name__ == "__main__":
    my_db.init(backup=False)
    my_gemini_general.load_users_keys()

    DOCUMENT1 = {
        "title": "Operating the Climate Control System",
        "content": "Your Googlecar has a climate control system that allows you to adjust the temperature and airflow in the car. To operate the climate control system, use the buttons and knobs located on the center console.  Temperature: The temperature knob controls the temperature inside the car. Turn the knob clockwise to increase the temperature or counterclockwise to decrease the temperature. Airflow: The airflow knob controls the amount of airflow inside the car. Turn the knob clockwise to increase the airflow or counterclockwise to decrease the airflow. Fan speed: The fan speed knob controls the speed of the fan. Turn the knob clockwise to increase the fan speed or counterclockwise to decrease the fan speed. Mode: The mode button allows you to select the desired mode. The available modes are: Auto: The car will automatically adjust the temperature and airflow to maintain a comfortable level. Cool: The car will blow cool air into the car. Heat: The car will blow warm air into the car. Defrost: The car will blow warm air onto the windshield to defrost it."}
    DOCUMENT2 = {
        "title": "Touchscreen",
        "content": "Your Googlecar has a large touchscreen display that provides access to a variety of features, including navigation, entertainment, and climate control. To use the touchscreen display, simply touch the desired icon.  For example, you can touch the \"Navigation\" icon to get directions to your destination or touch the \"Music\" icon to play your favorite songs."}
    # Добавим очень длинный документ для теста разбиения
    LONG_DOCUMENT = {
        "title": "Advanced Driving Features",
        "content": """
        Ваш Googlecar оснащен множеством передовых функций помощи водителю,
        которые делают поездки более безопасными и комфортными.
        К ним относятся адаптивный круиз-контроль, система удержания в полосе,
        автоматическое экстренное торможение и помощь при парковке.

        Адаптивный круиз-контроль (АПКК) автоматически поддерживает заданную
        скорость и безопасное расстояние до впереди идущего автомобиля. Вы можете
        настроить желаемое расстояние с помощью кнопок на рулевом колесе.
        Система использует радарные датчики для отслеживания движения транспорта.
        Если автомобиль впереди замедляется, ваш Googlecar также сбросит скорость,
        а затем автоматически ускорится до заданной скорости, когда дорога станет свободной.

        Система удержания в полосе (СУП) помогает удерживать автомобиль
        в центре полосы движения. Она использует камеру, установленную на
        лобовом стекле, для распознавания дорожной разметки. Если автомобиль
        начинает отклоняться от полосы без включения сигнала поворота, СУП
        аккуратно корректирует рулевое управление, возвращая автомобиль на место.
        Эту функцию можно временно отключить или настроить ее чувствительность
        через меню настроек на центральном дисплее.

        Автоматическое экстренное торможение (АЭТ) предназначено для предотвращения
        или снижения тяжести столкновений. Система постоянно сканирует пространство
        перед автомобилем на наличие препятствий. В случае обнаружения потенциальной
        опасности столкновения, система сначала выдает звуковое и визуальное
        предупреждение. Если водитель не реагирует, АЭТ автоматически применяет
        тормоза для минимизации последствий.

        Помощь при парковке — еще одна удобная функция. Она позволяет автомобилю
        самостоятельно парковаться параллельно или перпендикулярно. Водитель
        контролирует только педали газа и тормоза, а система берет на себя рулевое
        управление. Это особенно полезно в тесных городских условиях или для
        начинающих водителей. Активация функции происходит через выбор соответствующего
        режима на центральном экране при движении на низкой скорости.
        Обязательно убедитесь, что вокруг автомобиля достаточно места.
        """
    }
    DOCUMENT3 = {
        "title": "Shifting Gears",
        "content": "Your Googlecar has an automatic transmission. To shift gears, simply move the shift lever to the desired position.  Park: This position is used when you are parked. The wheels are locked and the car cannot move. Reverse: This position is used to back up. Neutral: This position is used when you are stopped at a light or in traffic. The car is not in gear and will not move unless you press the gas pedal. Drive: This position is used to drive forward. Low: This position is used for driving in snow or other slippery conditions."}

    with open(r'C:\Users\user\Downloads\samples for ai\Алиса в изумрудном городе (большая книга).txt', 'r', encoding='utf-8') as f:
        LONG_DOCUMENT2 = {'title': 'Алиса в изумрудном городе (большая книга)', 'content': f.read()}

    # выполняется очень быстро если закеширован, нет смысла сохранять?
    df = create_knowledge_base([DOCUMENT1, DOCUMENT2, LONG_DOCUMENT, DOCUMENT3, LONG_DOCUMENT2])

    # # проверка сериализации
    # serialized_df = serialize_dataframe(df)
    # deserialized_df = deserialize_dataframe(serialized_df)
    # assert df.equals(deserialized_df)

    client = genai.Client(api_key=my_gemini_general.get_next_key())

    query = "Кто такой Данаан?"

    best_passages = find_best_passages(query, df)
    with open(r'C:\Users\user\Downloads\best_passages.txt', 'w', encoding='utf-8') as f:
        f.write(best_passages)


    my_db.close()
