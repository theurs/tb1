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


if __name__ == '__main__':
    test_split_thoughts()