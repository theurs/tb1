#!/usr/bin/env python3
# pip install -U langchain
# pip install -U langchain-google-genai pillow
# pip install -U langchain-openai
# pip install -U langchain-groq
# pip install -U beautifulsoup4
# pip install -U langchain_community
# pip install -U faiss-cpu
# pip install -U langchain langchain-community langchainhub langchain-openai langchain-chroma bs4

import random



from langchain_core.prompts import ChatPromptTemplate
from langchain_groq import ChatGroq

from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    HarmBlockThreshold,
    HarmCategory,
)

from langchain_community.document_loaders import WebBaseLoader, TextLoader

from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings

import cfg


def gemini_get_llm() -> ChatGoogleGenerativeAI:
    api_key = random.choice(cfg.gemini_keys)
    # gemini-1.5-flash-latest
    # gemini-1.0-pro, gemini-1.0-pro-latest
    # gemini-1.5-pro-latest, gemini-pro
    # gemini-1.0-pro-vision-latest? gemini-pro-vision
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash-latest",
                                google_api_key=api_key,
                                safety_settings={
                                    HarmCategory.HARM_CATEGORY_UNSPECIFIED: HarmBlockThreshold.BLOCK_NONE,
                                    HarmCategory.HARM_CATEGORY_DEROGATORY: HarmBlockThreshold.BLOCK_NONE,
                                    HarmCategory.HARM_CATEGORY_TOXICITY: HarmBlockThreshold.BLOCK_NONE,
                                    HarmCategory.HARM_CATEGORY_VIOLENCE: HarmBlockThreshold.BLOCK_NONE,
                                    HarmCategory.HARM_CATEGORY_SEXUAL: HarmBlockThreshold.BLOCK_NONE,
                                    HarmCategory.HARM_CATEGORY_MEDICAL: HarmBlockThreshold.BLOCK_NONE,
                                    HarmCategory.HARM_CATEGORY_DANGEROUS: HarmBlockThreshold.BLOCK_NONE,
                                    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                                    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                                    },
                                )
    return llm


def gemini(query: str) -> str:
    if not hasattr(cfg, 'gemini_keys'):
        return ''
    llm = gemini_get_llm()
    result = llm.invoke(query)
    return result.content


def groq_get_llm() -> ChatGroq:
    api_key = random.choice(cfg.GROQ_API_KEY)
    llm = ChatGroq(temperature=0,
                    model_name="llama3-70b-8192",
                    api_key=api_key
                    )
    return llm


def groq_chat(query: str, system: str = "You are a helpful assistant.") -> str:
    if not hasattr(cfg, 'GROQ_API_KEY'):
        return ''

    chat = groq_get_llm()

    human = "{text}"
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])

    llm = prompt | chat
    result = llm.invoke({"text": query})

    return result.content


def ask_url(query: str = 'О чем текст, ответь ~100 слов на русском языке.',
         url: str = "http://lib.ru/POEZIQ/BAJRON/byron3_1.txt") -> str:
    # loader = WebBaseLoader(url)
    # docs = loader.load()

    # load text from file for testing
    loader = TextLoader('2.txt', autodetect_encoding=True)
    docs = loader.load()

    google_api_key = random.choice(cfg.gemini_keys)

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents(docs)
    embeddings = GoogleGenerativeAIEmbeddings(model="models/embedding-001", google_api_key = google_api_key)
    vectorstore = Chroma.from_documents(documents=splits, embedding=embeddings)

    # Retrieve and generate using the relevant snippets of the blog.
    retriever = vectorstore.as_retriever()
 

if __name__ == '__main__':
    # print(gemini('42'))
    # print(groq_chat('42', 'отвечай по-русски'))
    print(ask_url())
