# pip install plantweb


import cachetools.func
import html
import re

from plantweb.render import render

import my_log
import my_mermaid


def extract_png_from_output(raw_output_bytes: bytes) -> bytes | str:
    """
    Extracts PNG image data from a byte string that may contain leading
    textual warnings or other non-image data.

    PNG image data is identified by its standard magic number: b'\\x89PNG\\r\\n\\x1a\\n'.
    This function searches for this sequence and returns all bytes from that
    point onwards, assuming it represents the complete PNG file.

    Args:
        raw_output_bytes (bytes): The raw byte string output, potentially
                                  containing warnings followed by PNG data.

    Returns:
        bytes | str: A byte string containing only the PNG image data if the
                      magic number is found, otherwise a string indicating that no PNG data was found.
    """
    # Standard PNG magic number
    png_magic_number = b'\x89PNG\r\n\x1a\n'

    # Find the starting index of the PNG magic number in the raw output
    png_start_index = raw_output_bytes.find(png_magic_number)

    if png_start_index == 0:
        # If the magic number is found at the very beginning, return all bytes
        return raw_output_bytes
    elif png_start_index != -1:
        #save warning to logs
        warning_str = raw_output_bytes[:png_start_index].decode('utf-8')
        my_log.log2(f'my_plantweb.extract_png_from_output: Warning: {warning_str}')
        # If the magic number is found, return the slice of bytes from that point
        return raw_output_bytes[png_start_index:]
    else:
        # If the magic number is not found, it means valid PNG data
        # (or at least its start) was not present in the given bytes.
        return 'No PNG data found'


@cachetools.func.ttl_cache(maxsize=10, ttl=1*60)
def text_to_png(text: str, engine: str, format: str) -> bytes | str:
    """
    Renders a diagram from text using PlantUML, Graphviz, or Ditaa engines.

    Args:
        text: The diagram definition text in PlantUML, Graphviz (DOT), or Ditaa format.
        engine: The diagram rendering engine to use: 'plantuml', 'graphviz', or 'ditaa'.
                'dot' will be automatically mapped to 'graphviz'.
        format: The desired output format: 'png' or 'svg'. Note that Ditaa only supports 'png'.
                If 'ditaa' engine is selected, the format will be automatically set to 'png'.

    Returns:
        bytes: The rendered diagram as a byte string (e.g., PNG or SVG bytes) if successful.
        str: An error message string if rendering fails or the output is not as expected.
    """
    try:
        # Standardize the engine name for consistency with plantweb.render
        if engine == 'dot':
            engine = 'graphviz'

        # Ditaa only supports PNG format, so enforce it if Ditaa engine is selected.
        if engine in ('ditaa', 'mermaid'):
            format = 'png'

        # PlantUML specific adjustment: replace older skinparam syntax with newer !option.
        # This ensures compatibility with newer PlantUML versions for handwritten style.
        if engine == 'plantuml':
            text = text.replace('skinparam handwritten true', '!option handwritten true')

        try:
            # Render the diagram using the specified engine and format.
            # 'cacheopts': {'use_cache': False} is set to prevent plantweb's internal caching,
            # as an external cache (cachetools.func.ttl_cache) is already applied to this function.
            if engine == 'mermaid':
                rendered_output = my_mermaid.generate_mermaid_png_bytes(text)
                return rendered_output
            else:
                rendered_output = render(
                    text,
                    engine=engine,
                    format=format,
                    cacheopts={'use_cache': False}
                )
        except Exception as e:
            # Catch exceptions that occur specifically during the diagram rendering process
            # and return the error message as a string.
            return f"Rendering failed: {e}"

        # The 'render' function typically returns a list where the first element is the
        # rendered content (bytes for PNG/SVG) and subsequent elements might be metadata.
        # Check if the output is valid (not empty, and the first element is bytes).
        if rendered_output and isinstance(rendered_output[0], bytes):
            return extract_png_from_output(rendered_output[0])
        else:
            # If the output from 'render' is not in the expected byte format or is empty,
            # return a descriptive failure message.
            return f"FAILED: Unexpected output format from renderer. Output: {rendered_output}"

    except Exception as e:
        # Catch any broader, unexpected exceptions that might occur outside the
        # specific rendering call but within the function's execution.
        return f"An unexpected error occurred: {e}"


def find_code_snippets(text: str) -> list[dict]:
    '''
    Searches for HTML code snippets in the text, specifically for diagram code blocks.
    The expected format is <pre><code class="language-[engine]">...</code></pre>
    Supported engines are 'mermaid', 'plantuml', 'dot', and 'ditaa'.
    Returns a list of dictionaries, where each dictionary contains the 'engine' and the 'code'.

    Args:
        text: The input string to search within.

    Returns:
        A list of dictionaries, e.g.,
        [
            {'engine': 'mermaid', 'code': 'some script on mermaid'},
            {'engine': 'plantuml', 'code': 'some script on plantuml'},
            {'engine': 'dot', 'code': 'some script on dot'},
            {'engine': 'ditaa', 'code': 'some script on ditaa'},
        ]
    '''
    # Regular expression to find the code blocks.
    # It captures the engine name and the code content.
    # re.DOTALL allows the '.' to match newline characters.
    pattern = re.compile(r'<pre><code class="language-(plantuml|dot|ditaa|mermaid)">(.*?)</code></pre>', re.DOTALL)

    # Find all matches in the input text.
    matches = pattern.findall(text)

    snippets = []
    for match in matches:
        engine = match[0] # The first captured group is the engine name.
        code = match[1].strip() # The second captured group is the code content, strip whitespace.
        snippets.append({'engine': engine, 'code': html.unescape(code)})

    return snippets


if __name__ == '__main__':
    pass
