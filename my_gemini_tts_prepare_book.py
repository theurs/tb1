# pip install -U nltk


import nltk
from nltk.tokenize import sent_tokenize


nltk.download('punkt_tab')

# Загрузка необходимых данных (выполнить один раз)
# nltk.download('punkt')
# nltk.download('stopwords') # Для русского языка, если понадобится

def chunk_text(text, max_len=2000):
    sentences = sent_tokenize(text, language='russian')
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_len: # +1 для пробела
            if current_chunk:
                current_chunk += " "
            current_chunk += sentence
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sentence
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

with open(r'C:\Users\user\Downloads\samples for ai\Алиса в изумрудном городе (большая книга).txt', 'r', encoding='utf-8') as f:
    long_russian_text = f.read()


text_chunks = chunk_text(long_russian_text, max_len=2000)



#save with serialization
import pickle
with open(r'C:\Users\user\Downloads\samples for ai\Алиса в изумрудном городе (большая книга).txt.chunks.pkl', 'wb') as f:
    pickle.dump(text_chunks, f)
