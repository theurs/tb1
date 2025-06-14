# pip install plantweb


import cachetools.func
import html
import re

from plantweb.render import render


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
        if engine == 'ditaa':
            format = 'png'

        # PlantUML specific adjustment: replace older skinparam syntax with newer !option.
        # This ensures compatibility with newer PlantUML versions for handwritten style.
        if engine == 'plantuml':
            text = text.replace('skinparam handwritten true', '!option handwritten true')

        try:
            # Render the diagram using the specified engine and format.
            # 'cacheopts': {'use_cache': False} is set to prevent plantweb's internal caching,
            # as an external cache (cachetools.func.ttl_cache) is already applied to this function.
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
            return rendered_output[0]
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
    Supported engines are 'plantuml', 'dot', and 'ditaa'.
    Returns a list of dictionaries, where each dictionary contains the 'engine' and the 'code'.

    Args:
        text: The input string to search within.

    Returns:
        A list of dictionaries, e.g.,
        [
            {'engine': 'plantuml', 'code': 'some script on plantuml'},
            {'engine': 'dot', 'code': 'some script on dot'},
            {'engine': 'ditaa', 'code': 'some script on ditaa'},
        ]
    '''
    # Regular expression to find the code blocks.
    # It captures the engine name and the code content.
    # re.DOTALL allows the '.' to match newline characters.
    pattern = re.compile(r'<pre><code class="language-(plantuml|dot|ditaa)">(.*?)</code></pre>', re.DOTALL)

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
