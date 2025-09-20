def split_thoughts(text: str) -> tuple[str, str]:
    """
    Splits the thoughts of the LLM model and the answer from the text.
    Responses from thinking LLM models consist of 2 parts: thoughts and answers.
    Thoughts are located at the beginning of the response and are highlighted with <think>...</think> tags.
    This function handles leading whitespace before the tags.

    Splits the model's thoughts and the answer, returns a tuple ('thoughts', 'answer').
    """
    start_tag: str = '<think>'
    end_tag: str = '</think>'

    # Trim leading whitespace to reliably check for the start tag
    trimmed_text: str = text.lstrip()

    if trimmed_text.startswith(start_tag):
        end_pos: int = trimmed_text.find(end_tag)
        if end_pos > -1:
            # Both tags are present at the beginning
            thoughts: str = trimmed_text[len(start_tag):end_pos].strip()
            answer: str = trimmed_text[end_pos + len(end_tag):].lstrip()
            return (thoughts, answer)
        else:
            # Only the opening tag is present at the beginning
            answer: str = trimmed_text[len(start_tag):].lstrip()
            return ('', answer)
    else:
        # Fallback for cases where only a closing tag exists (legacy behavior)
        end_pos: int = text.find(end_tag)
        if end_pos != -1:
            thoughts: str = text[:end_pos].strip()
            answer: str = text[end_pos + len(end_tag):].lstrip()
            return (thoughts, answer)
        else:
            # No tags found in expected positions
            return ('', text.strip())


def test_split_thoughts():
    assert split_thoughts(' <think>Мысли</think>Ответ') == ('Мысли', 'Ответ')
    assert split_thoughts('МыслиОтвет') == ('', 'МыслиОтвет')
    assert split_thoughts('<think>Мысли') == ('', 'Мысли')
    assert split_thoughts('Мысли</think>') == ('Мысли','')
    assert split_thoughts('Мысли</think>Ответ') == ('Мысли', 'Ответ')
    assert split_thoughts('Мысли') == ('', 'Мысли')
    assert split_thoughts('<think>Мысли</think>') == ('Мысли', '')
    assert split_thoughts('<think>Мысли</think>Ответ') == ('Мысли', 'Ответ')
    assert split_thoughts('Мысли</think>Ответ') == ('Мысли', 'Ответ')
    assert split_thoughts('Мысли</think>') == ('Мысли', '')


def reconstruct_html_answer_with_thoughts(thoughts: str, answer: str) -> str:
    '''
    Thoughts should be displayed in a collapsible block <blockquote expandable>...</blockquote>
    If there are no thoughts, the block is not needed.
    '''
    if thoughts.strip():
        return f'<blockquote expandable>\n{thoughts}\n</blockquote>\n{answer}'
    return answer


def text_to_mem_dict(downloaded_file) -> dict:
    '''
    Читает текстовый файл с записями типа таких
𝐔𝐒𝐄𝐑: 1+1=

𝐁𝐎𝐓: 2

    и создает словарь {user:bot, user:bot, ...}
    все линии до первого 𝐔𝐒𝐄𝐑 надо пропустить
    запросы и ответы могут быть многострочными

    '''
    if isinstance(downloaded_file, bytes):
        downloaded_file = downloaded_file.decode('utf-8', errors='replace')

    lines = downloaded_file.split('\n')
    mem_dict = {}
    current_user = None
    current_bot = None
    started = False

    for line in lines:
        if line.startswith('𝐔𝐒𝐄𝐑:'):
            started = True
            if current_user is not None:
                mem_dict[current_user.strip()] = current_bot.strip() if current_bot is not None else ""
            current_user = line[len('𝐔𝐒𝐄𝐑:'):]
            current_bot = None
        elif line.startswith('𝐁𝐎𝐓:'):
            if started:
              current_bot = line[len('𝐁𝐎𝐓:'):]
        elif started:
            if current_user is not None and current_bot is None:
                current_user += '\n' + line
            elif current_user is not None and current_bot is not None:
                current_bot += '\n' + line

    if current_user is not None:
        mem_dict[current_user.strip()] = current_bot.strip() if current_bot is not None else ""

    return mem_dict


def extract_and_replace_tool_code(text: str) -> str:
    """
    Searches for a specific code block in the text and extracts its content.
    If the content starts with '/google' or '/calc', the function returns only the content.
    Otherwise, it returns the original text.

    Args:
        text: The input string to search within.

    Returns:
        The extracted content or the original text.
    """
    start_delimiter = "```tool_code"
    end_delimiter = "```"
    start_index = text.find(start_delimiter)
    end_index = text.find(end_delimiter, start_index + len(start_delimiter))

    if start_index != -1 and end_index != -1:
        # Extract the content of the code block
        extracted_content = text[start_index + len(start_delimiter):end_index].strip()

        # Check if the content starts with '/google' or '/calc'
        if extracted_content.startswith("/google") or extracted_content.startswith("/calc"):
            return extracted_content
        else:
            return text
    else:
        return text


def detect_forbidden_prompt(text: str) -> bool:
    '''
    Определяет есть ли в тексте признаки запрещенных промптов.
    '''
    # Randi prompt
    count_word_randi = text.lower().count('randi ')
    has_word_void = 'VOID you' in text

    if has_word_void:
        return True
    if count_word_randi > 4:
        return True

    return False


if __name__ == '__main__':
    test_split_thoughts()

    test_text = """
какой-то текст
и еще текст
𝐔𝐒𝐄𝐑: 1+1=

𝐁𝐎𝐓: 2

𝐔𝐒𝐄𝐑: a
b
c

𝐁𝐎𝐓:
d
e
"""
    result = text_to_mem_dict(test_text)
    print(result)
