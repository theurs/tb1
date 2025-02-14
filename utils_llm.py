def split_thoughts(text: str) -> tuple[str, str]:
    '''
    Splits the thoughts of the LLM model and the answer from the text.
    Responses from thinking LLM models consist of 2 parts: thoughts and answers.
    Thoughts are located at the beginning of the response and are highlighted with <think>...</think> tags.
    There are cases when there are no tags, then there are no thoughts, it is necessary to return ''.
    There are cases when there is only an opening tag, this means there are no thoughts, the tag must simply be cut out.
    There are cases when there is only a closing tag, this means that the opening tag is simply missing, there are thoughts.

    Splits the model's thoughts and the answer, returns a tuple ('thoughts', 'answer').
    '''
    start_tag: str = '<think>'
    end_tag: str = '</think>'
    start_pos: int = text.find(start_tag)
    end_pos: int = text.find(end_tag)

    # Check if the text starts with <think>
    starts_with_think: bool = start_pos == 0

    if starts_with_think:
        if end_pos != -1 and end_pos > start_pos:
            # Both tags are present, the opening tag is at the beginning
            thoughts: str = text[len(start_tag):end_pos].strip()
            answer: str = text[end_pos + len(end_tag):].lstrip()
            return (thoughts, answer)
        else:
            # Only the opening tag (or closing tag before opening)
            answer: str = text[len(start_tag):].lstrip()
            return ('', answer)
    else:
        if end_pos != -1:
            # Only the closing tag is present
            thoughts: str = text[:end_pos].strip()
            answer: str = text[end_pos + len(end_tag):].lstrip()
            return (thoughts, answer)
        else:
            # No tags or only the opening tag is not at the beginning
            return ('', text.strip())

def test_split_thoughts():
    assert split_thoughts('<think>Мысли</think>Ответ') == ('Мысли', 'Ответ')
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


if __name__ == '__main__':
    # test_split_thoughts()

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
