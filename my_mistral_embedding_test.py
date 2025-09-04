#!/usr/bin/env python3


import base64
import concurrent.futures
import io
import importlib
import hashlib
import os
import pickle
import random
import re
import subprocess
import sys
import traceback
import threading
import time
from flask import Flask, request, jsonify
from decimal import Decimal, getcontext
from multiprocessing.pool import ThreadPool
from typing import Any, Dict, List, Optional, Union

import langcodes
import pendulum
import PIL
import telebot
from fuzzywuzzy import fuzz
from sqlitedict import SqliteDict

import cfg
import md2tgmd
import my_alert
import my_init
import my_genimg
import my_cerebras
import my_cerebras_tools
import my_cohere
import my_db
import my_ddg
import my_doc_translate
import my_github
import my_google
# import my_gemini_embedding
import my_gemini_general
import my_gemini3
import my_gemini_tts
import my_gemini_genimg
import my_gemini_google
import my_groq
import my_log
import my_md_tables_to_png
import my_mistral
import my_mistral_embedding
import my_nebius
import my_pdf
import my_psd
import my_openrouter
import my_openrouter_free
import my_pandoc
import my_plantweb
import my_skills
import my_skills_general
import my_skills_storage
import my_stat
import my_stt
import my_svg
import my_subscription
import my_sum
import my_tavily
import my_qrcode
import my_trans
import my_transcribe
import my_tts
import my_ytb
import my_zip
import utils
import utils_llm
from utils import async_run



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

    query = "Кто победил в дуэли Гермионы и Хмури"
    print(f"\nFinding best passages for query: '{query}'")

    best_passages = my_mistral_embedding.find_best_passages(query, df)

    print("\n--- Best Passages Found ---")
    print(best_passages)
    print("---------------------------\n")

    my_db.close()
