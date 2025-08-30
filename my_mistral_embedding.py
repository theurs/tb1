# pip install diskcache mistralai

import functools
import re
import time
import threading
from pathlib import Path

import diskcache
import numpy as np
import pandas as pd
from mistralai import Mistral

import my_db
import my_log
import my_mistral


EMBEDDING_MODEL_ID = "mistral-embed"


cache_dir = Path("./db/cache-mistral-embedding")
cache_dir.mkdir(exist_ok=True, parents=True)
cache = diskcache.Cache(str(cache_dir))


def rate_limiter(max_calls: int, time_window: int = 60):
    """
    A thread-safe decorator to manage API rate limits.
    Tracks the number of calls over a sliding time window.
    If the limit is about to be exceeded, it makes the thread wait.
    Note: Mistral's specific token limits are not handled here, only call frequency.
    """
    def decorator(func):
        calls = []
        lock = threading.Lock()

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            while True:
                with lock:
                    current_time = time.time()
                    # Remove calls older than the time window
                    calls[:] = [c for c in calls if c > current_time - time_window]

                    if len(calls) < max_calls:
                        # Limit not exceeded, proceed
                        calls.append(current_time)
                        break

                    # Limit exceeded, calculate wait time
                    time_to_wait = calls[0] - (current_time - time_window) + 0.1

                my_log.log_mistral(f"Rate limit reached. Thread waiting for {time_to_wait:.2f}s...")
                time.sleep(time_to_wait)

            return func(*args, **kwargs)
        return wrapper
    return decorator


# Mistral API rate limits are not as publicly defined as Gemini's.
# Using a conservative value of 100 calls per minute as a safeguard.
# This might need adjustment based on the actual API behavior.
limiter = rate_limiter(max_calls=200)


@cache.memoize()
@limiter
def embed_fn(title: str, text: str) -> list[float]:
    """
    Computes an embedding for the text using the Mistral API,
    with 5 retry attempts in case of network errors.
    The title and text are concatenated as Mistral's API takes a single input string.
    """
    # Combine title and text for Mistral's embedding model
    combined_input = f"{title}\n\n{text}" if title else text

    retries = 5
    delay = 5  # Initial delay in seconds
    api_key = "" # Define api_key here to be accessible in the except block

    for attempt in range(retries):
        try:
            # Use my_mistral to get API key and initialize client
            api_key = my_mistral.get_next_key()
            if not api_key:
                raise ValueError("No Mistral API key available.")

            client = Mistral(api_key=api_key)

            response = client.embeddings.create(
                model=EMBEDDING_MODEL_ID,
                inputs=[combined_input]
            )
            # Return the embedding vector for the first input
            return response.data[0].embedding

        except Exception as e:
            if "Unauthorized" in str(e) and my_mistral:
                my_mistral.remove_key(api_key)
                my_log.log_mistral(f"my_mistral_embedding:embed_fn: Unauthorized key removed. Retrying immediately.")
                continue # Try next key immediately

            if attempt < retries - 1:
                my_log.log_mistral(f"my_mistral_embedding:embed_fn: API call failed (attempt {attempt + 1}/{retries}): {e}. Retrying in {delay}s...")
                time.sleep(delay)
                delay *= 2  # Exponential backoff
            else:
                my_log.log_mistral(f"my_mistral_embedding:embed_fn: API call failed after {retries} attempts. Giving up.")
                raise e # Re-raise the last exception if all retries fail
    return [] # Should not be reached if an exception is raised, but here for safety


def split_text_into_chunks(text: str, max_length_chars: int = 3000, overlap_chars: int = 400) -> list[str]:
    """
    Splits text into meaningful chunks, ideal for language model processing.
    This function is API-agnostic and remains unchanged from the original.
    """
    if not isinstance(text, str) or not text.strip():
        return []

    if max_length_chars <= overlap_chars:
        raise ValueError("max_length_chars must be greater than overlap_chars.")

    separators = ["\n\n", "\n", ". ", "? ", "! ", " "]

    # Start with the whole text as a single chunk
    final_chunks = [text]

    # Iteratively split chunks that are too long
    for separator in separators:
        chunks_to_process = final_chunks
        final_chunks = []
        for chunk in chunks_to_process:
            if len(chunk) <= max_length_chars:
                final_chunks.append(chunk)
            else:
                final_chunks.extend(chunk.split(separator))

    # Merge small chunks back together
    merged_chunks = []
    current_chunk = ""
    for chunk in final_chunks:
        if len(current_chunk) + len(chunk) + 1 <= max_length_chars:
            current_chunk += chunk + " "
        else:
            merged_chunks.append(current_chunk.strip())
            current_chunk = chunk + " "
    if current_chunk:
        merged_chunks.append(current_chunk.strip())

    # Apply overlap
    if overlap_chars > 0 and len(merged_chunks) > 1:
        overlapped_chunks = [merged_chunks[0]]
        for i in range(1, len(merged_chunks)):
            prev_chunk_end = merged_chunks[i-1][-overlap_chars:]
            current_chunk = merged_chunks[i]
            overlapped_chunks.append(prev_chunk_end + current_chunk)
        return overlapped_chunks

    return merged_chunks


def create_knowledge_base(raw_documents: list[dict]) -> pd.DataFrame:
    """
    Creates and processes a knowledge base from a list of raw documents.
    Splits large documents into chunks and generates their embeddings using Mistral.
    """
    processed_documents_data = []
    for doc in raw_documents:
        content_chunks = split_text_into_chunks(doc.get("content", ""))

        if len(content_chunks) == 1:
            processed_documents_data.append({
                "Title": doc.get("title", "Untitled"),
                "Text": content_chunks[0]
            })
        else:
            for i, chunk_text in enumerate(content_chunks):
                chunk_title = f"{doc.get('title', 'Untitled')} - Part {i + 1}"
                processed_documents_data.append({
                    "Title": chunk_title,
                    "Text": chunk_text
                })

    if not processed_documents_data:
        return pd.DataFrame(columns=["Title", "Text", "Embeddings"])

    df = pd.DataFrame(processed_documents_data)
    df['Embeddings'] = df.apply(lambda row: embed_fn(row['Title'], row['Text']), axis=1)

    return df


def find_best_passages(
    query: str,
    dataframe: pd.DataFrame,
    target_size_chars: int = 20000
) -> str:
    """
    Finds the most relevant text passages to form a single context,
    strictly not exceeding the specified size, and formats the result
    as an XML-like string.
    """
    if dataframe.empty or 'Embeddings' not in dataframe.columns:
        return ""

    # 1. Get the embedding for the query using our new embed_fn
    query_embedding = embed_fn(title="", text=query)

    if not query_embedding:
        my_log.log_mistral("Failed to get query embedding. Aborting find_best_passages.")
        return ""

    # 2. Calculate and sort all passages by relevance
    dot_products = np.dot(np.stack(dataframe['Embeddings'].values), query_embedding)
    all_passages = []
    for i, row in dataframe.iterrows():
        all_passages.append({
            'title': row['Title'],
            'text': row['Text'],
            'relevance': dot_products[i]
        })
    all_passages.sort(key=lambda x: x['relevance'], reverse=True)

    # 3. Iteratively build the context while controlling for size
    candidate_passages = []
    current_total_size = 0
    safe_query = query.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    for passage in all_passages:
        # Create a temporary list to calculate potential size
        temp_candidates = candidate_passages + [passage]

        # Sort logically by original title and part number
        title_pattern = re.compile(r"^(.*?)(?: - Part (\d+))?$")
        for p in temp_candidates:
            if 'original_title' not in p:
                match = title_pattern.match(p['title'])
                p['original_title'] = match.group(1).strip() if match else p['title']
                p['part_number'] = int(match.group(2)) if match and match.group(2) else 1
        temp_candidates.sort(key=lambda x: (x['original_title'], x['part_number']))

        # Render a provisional output to measure its exact size
        output_parts = ["<fragments>", f"<query>{safe_query}</query>"]
        for i, p in enumerate(temp_candidates, 1):
            safe_title = p['title'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            safe_text = p['text'].replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            output_parts.append(f"<fragment_source_{i}>{safe_title}</fragment_source_{i}>")
            output_parts.append(f"<fragment_text_{i}>\n{safe_text}\n</fragment_text_{i}>")
        output_parts.append("</fragments>")

        provisional_size = len("\n".join(output_parts))

        if provisional_size > target_size_chars:
            break # Adding this passage would exceed the limit

        # If it fits, add it to the final list
        candidate_passages.append(passage)
        current_total_size = provisional_size

    # 4. Final assembly of the result from the approved candidates
    candidate_passages.sort(key=lambda x: (x.get('original_title', x['title']), x.get('part_number', 1)))
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
    # Setup necessary modules
    my_db.init(backup=False)
    my_mistral.load_users_keys()

    # Example documents
    DOCUMENT1 = {
        "title": "Operating the Climate Control System",
        "content": "Your car has a climate control system that allows you to adjust the temperature and airflow. To operate it, use the buttons and knobs on the center console. Turn the temperature knob clockwise to increase heat."
    }
    DOCUMENT2 = {
        "title": "Touchscreen",
        "content": "Your car has a large touchscreen display for navigation, entertainment, and climate control. Touch the 'Navigation' icon for directions or 'Music' for songs."
    }
    with open(r'c:\Users\user\Downloads\samples for ai\myachev_Significant_Digits_-_znachaschie_tsifryi_106746.txt', 'r', encoding='utf-8') as f:
        data = f.read()
        DOCUMENT3 = {
            "title": "Photo",
            "content": data
        }

    documents = [DOCUMENT1, DOCUMENT2, DOCUMENT3]

    print("Creating knowledge base with Mistral embeddings...")
    # This will be fast if cached, otherwise it will call the Mistral API.
    df = my_mistral_embedding.create_knowledge_base(documents)
    print("Knowledge base created successfully.")
    print(df)

    query = "текст пергамента."
    print(f"\nFinding best passages for query: '{query}'")

    best_passages = my_mistral_embedding.find_best_passages(query, df)

    print("\n--- Best Passages Found ---")
    print(best_passages)
    print("---------------------------\n")

    my_db.close()
