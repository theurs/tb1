#!/usr/bin/env python3
# pip install -U telegramify-markdown


import re
from typing import List, Match, Optional, Tuple

import textwrap
import telegramify_markdown
from telegramify_markdown import customize


customize.markdown_symbol.head_level_1 = "📌"  # If you want, Customizing the head level 1 symbol
customize.markdown_symbol.link = "🔗"  # If you want, Customizing the link symbol
# customize.strict_markdown = True  # If you want to use __underline__ as underline, set it to False, or it will be converted to bold as telegram does.
customize.cite_expandable = True  # If you want to enable expandable citation, set it to True.
customize.latex_escape = True  # If you want to escape LaTeX symbols, set it to True.

customize.strict_markdown = False


def sub_sp_symbols(text: str) -> str:
    # Словарь подстрочных символов
    subscript_map = {
        '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄', '5': '₅',
        '6': '₆', '7': '₇', '8': '₈', '9': '₉',
        '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
        'a': 'ₐ',
        # 'b': '♭', 
        'c': '꜀',
        # 'd': 'ᑯ',
        'e': 'ₑ',
        # 'f': '⨍',
        'g': '₉',
        'h': 'ₕ',
        'i': 'ᵢ',
        'j': 'ⱼ',
        'k': 'ₖ',
        'l': 'ₗ',
        'm': 'ₘ',
        'n': 'ₙ',
        'o': 'ₒ',
        'p': 'ₚ',
        # 'q': '૧',
        'r': 'ᵣ',
        's': 'ₛ',
        't': 'ₜ',
        'u': 'ᵤ',
        'v': 'ᵥ',
        # 'w': 'w',
        'x': 'ₓ',
        'y': 'ᵧ',
        'z': '₂'
    }

    # Словарь надстрочных символов
    superscript_map = {
        '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴', '5': '⁵',
        '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
        '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
        'a': 'ᵃ',
        'b': 'ᵇ',
        'c': 'ᶜ',
        'd': 'ᵈ',
        'e': 'ᵉ',
        'f': 'ᶠ',
        'g': 'ᵍ',
        'h': 'ʰ',
        'i': 'ⁱ',
        'j': 'ʲ',
        'k': 'ᵏ',
        'l': 'ˡ',
        'm': 'ᵐ',
        'n': 'ⁿ',
        'o': 'ᵒ',
        'p': 'ᵖ',
        'q': '𐞥', 
        'r': 'ʳ',
        's': 'ˢ',
        't': 'ᵗ',
        'u': 'ᵘ',
        'v': 'ᵛ',
        'w': 'ʷ',
        'x': 'ˣ',
        'y': 'ʸ',
        'z': 'ᶻ'
    }

    # замена тегов <sub> <sup> на подстрочные и надстрочные символы
    text = re.sub(r'<sup\\>(.*?)</sup\\>', lambda m: ''.join(superscript_map.get(c, c) for c in m.group(1)), text)
    text = re.sub(r'<sub\\>(.*?)</sub\\>', lambda m: ''.join(subscript_map.get(c, c) for c in m.group(1)), text)

    return text


def process_block(match: Match[str]) -> str:
    """
    Process a single code block match by removing common indentation.
    
    Args:
        match: Regular expression match object containing the code block
        
    Returns:
        Processed code block with normalized indentation and triple backticks
    """
    indent: str = match.group(1)  # Leading whitespace
    lang: str = match.group(2)    # Language identifier
    code: str = match.group(3)    # Code content
    
    # Split into lines and remove trailing whitespace
    lines: list[str] = code.rstrip().split('\n')
    
    # Find the minimum indent of non-empty lines
    min_indent: int = min(
        len(line) - len(line.lstrip())
        for line in lines
        if line.strip()
    )
    
    # Remove the common indentation from each line
    normalized_lines: list[str] = [
        line[min_indent:] if line.strip() else ''
        for line in lines
    ]
    
    # Join lines back together
    normalized_code: str = '\n'.join(normalized_lines)
    
    # Construct the final block with triple backticks
    return f"{indent}```{lang}\n{normalized_code}\n{indent}```"


def convert_code_blocks(text: str) -> str:
    """
    Convert single-backtick code blocks to triple-backtick blocks in markdown text,
    removing common indentation from the code content.
    
    Args:
        text: Input markdown text containing code blocks
        
    Returns:
        Text with converted code blocks using triple backticks and normalized indentation
    """
    pattern: str = r'([ \t]*)`(\w*)\n(.*?)\n\1`'
    return re.sub(
        pattern,
        process_block,
        text,
        flags=re.DOTALL | re.MULTILINE
    )


def md2md(text: str) -> str:
    text = textwrap.dedent(text)
    # text = convert_code_blocks(text)

    converted = telegramify_markdown.markdownify(
        text,
        max_line_length=None,  # If you want to change the max line length for links, images, set it to the desired value.
        normalize_whitespace=False
    )
    # converted = sub_sp_symbols(converted)
    return converted


def chunk_markdown(text: str, max_chunk_size: int = 3000) -> List[str]:
    """
    Split markdown text into chunks of specified maximum size while preserving code blocks.
    
    Args:
        text: Input markdown text
        max_chunk_size: Maximum allowed size of each chunk
        
    Returns:
        List of markdown text chunks
    """
    chunks: List[str] = []
    current_chunk: List[str] = []
    current_size: int = 0
    in_code_block: bool = False
    code_block_header: Optional[str] = None
    pending_code_block_end: bool = False

    # Split text into lines while preserving empty lines
    lines: List[str] = text.splitlines(keepends=True)

    def add_chunk() -> None:
        """Helper function to add accumulated lines as a new chunk."""
        nonlocal current_size
        if current_chunk:
            chunks.append(''.join(current_chunk))
            current_chunk.clear()
            current_size = 0

    def is_code_block_start(line: str) -> Tuple[bool, Optional[str]]:
        """
        Check if line is a code block start and extract its header.

        Returns:
            Tuple of (is_start: bool, header: Optional[str])
        """
        stripped = line.lstrip()
        if stripped.startswith('```'):
            return True, line.rstrip()
        return False, None

    def is_code_block_end(line: str) -> bool:
        """Check if line is a code block end."""
        return line.lstrip().startswith('```') and not line.lstrip()[3:].strip()

    for i, line in enumerate(lines):
        line_size = len(line)
        # next_line = lines[i + 1] if i + 1 < len(lines) else None

        # Handle code block boundaries
        if not in_code_block:
            is_start, header = is_code_block_start(line)
            if is_start:
                in_code_block = True
                code_block_header = header
                pending_code_block_end = False
        else:
            if is_code_block_end(line):
                in_code_block = False
                code_block_header = None
                pending_code_block_end = False

        # Start new chunk if current would exceed max size
        if current_size + line_size > max_chunk_size and current_chunk:
            if in_code_block and not pending_code_block_end:
                current_chunk.append('```\n')  # Close code block in current chunk
                pending_code_block_end = True
            add_chunk()
            if in_code_block and code_block_header:
                current_chunk.append(f'{code_block_header}\n')  # Reopen code block in new chunk
                pending_code_block_end = False
            current_size = line_size
        else:
            current_size += line_size

        # Skip adding closing tag if it's already pending
        if pending_code_block_end and is_code_block_end(line):
            continue

        current_chunk.append(line)

    # Add final chunk
    add_chunk()

    return chunks


if __name__ == '__main__':
    pass
    # Use `r` to avoid escaping the backslash.
    markdown_text = r""" 
1. **Отсутствует **`begin`** после заголовка программы:**
    `pascal
    program Program1;

    {... объявления переменных и процедур ...}

    {* Здесь должен быть begin *}

    end.  // <- Строка 24
    `

   **Решение:** Добавьте `begin` перед строкой 24 (или там, где должен начинаться основной блок кода программы).


"""

    r = chunk_markdown(md2md(markdown_text))
    print(r)
