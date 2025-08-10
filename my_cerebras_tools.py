# my_cerebras_tools.py

import inspect
from typing import Any, Callable, Dict, List, Tuple

import docstring_parser


# Maps Python types to JSON Schema type names.
PY_TO_JSON_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


# def get_tools_gpt_oss(
#     *functions: Callable[..., Any]
# ) -> Tuple[List[Dict[str, Any]], Dict[str, Callable[..., Any]]]:
#     """
#     Builds tool configurations from a list of Python functions.

#     This function uses runtime introspection to generate the necessary
#     JSON schema for each tool and a map of available tool functions,
#     compatible with the Cerebras API.

#     Args:
#         *functions: A sequence of callable Python functions passed as arguments.

#     Returns:
#         A tuple containing:
#         - A list of JSON schemas, one for each function.
#         - A dictionary mapping function names to the actual function objects.
#     """
#     tools_schema_list: List[Dict[str, Any]] = []
#     available_tools_map: Dict[str, Callable[..., Any]] = {}

#     for func in functions:
#         # Get the function's signature to inspect its parameters.
#         try:
#             signature = inspect.signature(func)
#         except (ValueError, TypeError):
#             # Skip functions that cannot be inspected (e.g., some built-ins).
#             continue

#         # Use the function's name for both the map key and the schema name.
#         func_name = func.__name__
#         available_tools_map[func_name] = func

#         # Use the function's docstring as its primary description.
#         # inspect.getdoc cleans up indentation.
#         description = inspect.getdoc(func) or "No description provided."

#         # Define containers for parameter properties and required parameter names.
#         param_properties: Dict[str, Dict[str, Any]] = {}
#         required_params: List[str] = []

#         for param in signature.parameters.values():
#             # A parameter is required if it does not have a default value.
#             if param.default is inspect.Parameter.empty:
#                 required_params.append(param.name)

#             # Map the Python type annotation to a JSON Schema type.
#             # Default to 'string' if the type is not in our map or not annotated.
#             param_type = PY_TO_JSON_TYPE_MAP.get(param.annotation, "string")
            
#             # Since we don't parse docstrings for params, the schema is simple.
#             param_properties[param.name] = {"type": param_type}

#         # Assemble the complete JSON schema for the function.
#         schema = {
#             "type": "function",
#             "function": {
#                 "name": func_name,
#                 "strict": False,
#                 "description": description,
#                 "parameters": {
#                     "type": "object",
#                     "properties": param_properties,
#                     "required": required_params,
#                 },
#             },
#         }
#         tools_schema_list.append(schema)

#     return tools_schema_list, available_tools_map


def get_tools_gpt_oss(
    *functions: Callable[..., Any]
) -> Tuple[List[Dict[str, Any]], Dict[str, Callable[..., Any]]]:
    """
    Builds tool configurations and adds a legacy 'strict' flag.

    This function reuses the core logic of `get_tools` and then patches
    the output by injecting 'strict: False' into each function schema.

    Args:
        *functions: A sequence of callable Python functions.

    Returns:
        A tuple containing:
        - A list of JSON schemas, each with the 'strict' flag.
        - A dictionary mapping function names to the function objects.
    """
    # 1. Get clean schemas from the main core.
    schemas, available_tools_map = get_tools(*functions)

    # 2. Inject the legacy 'strict' key into each one.
    for schema in schemas:
        schema["function"]["strict"] = False

    return schemas, available_tools_map


def get_tools(
    *functions: Callable[..., Any]
) -> Tuple[List[Dict[str, Any]], Dict[str, Callable[..., Any]]]:
    """
    Builds tool configurations from a list of Python functions.

    This function uses runtime introspection and a dedicated docstring parser
    to generate the necessary JSON schema for each tool and a map of
    available tool functions.

    Args:
        *functions: A sequence of callable Python functions passed as arguments.

    Returns:
        A tuple containing:
        - A list of JSON schemas, one for each function.
        - A dictionary mapping function names to the actual function objects.
    """
    tools_schema_list: List[Dict[str, Any]] = []
    available_tools_map: Dict[str, Callable[..., Any]] = {}

    for func in functions:
        try:
            signature = inspect.signature(func)
            docstring = inspect.getdoc(func) or ""
        except (ValueError, TypeError):
            continue

        func_name = func.__name__
        available_tools_map[func_name] = func

        # Use the dedicated library to parse the docstring professionally.
        parsed_docstring = docstring_parser.parse(docstring)

        # Combine short and long descriptions for a full picture.
        description_parts = [
            parsed_docstring.short_description,
            parsed_docstring.long_description
        ]
        description = "\n\n".join(filter(None, description_parts))

        # The library returns a clean list of parameters.
        param_docs: Dict[str, str] = {
            param.arg_name: param.description for param in parsed_docstring.params
        }

        param_properties: Dict[str, Dict[str, Any]] = {}
        required_params: List[str] = []

        for param in signature.parameters.values():
            if param.default is inspect.Parameter.empty:
                required_params.append(param.name)

            param_type = PY_TO_JSON_TYPE_MAP.get(param.annotation, "string")
            param_description = param_docs.get(param.name, "No description available.")

            param_properties[param.name] = {
                "type": param_type,
                "description": param_description,
            }

        schema = {
            "type": "function",
            "function": {
                "name": func_name,
                "description": description or "No description provided.",
                "parameters": {
                    "type": "object",
                    "properties": param_properties,
                    "required": required_params,
                },
            },
        }
        tools_schema_list.append(schema)

    return tools_schema_list, available_tools_map


if __name__ == "__main__":
    import my_skills_general
    import my_skills
    from pprint import pprint
    funcs = [
        my_skills.calc,
        my_skills.search_google_fast,
        my_skills.search_google_deep,
        my_skills.download_text_from_url,
        my_skills_general.get_time_in_timezone,
        my_skills.get_weather,
        my_skills.get_currency_rates,
        my_skills.tts,
        my_skills.speech_to_text,
        my_skills.edit_image,
        my_skills.translate_text,
        my_skills.translate_documents,
        my_skills.text_to_image,
        my_skills.text_to_qrcode,
        my_skills_general.save_to_txt,
        my_skills_general.save_to_excel,
        my_skills_general.save_to_docx,
        my_skills_general.save_to_pdf,
        my_skills_general.save_diagram_to_image,
        my_skills.save_chart_and_graphs_to_image,
        my_skills.save_html_to_image,
        my_skills.save_html_to_animation,
        my_skills.save_natal_chart_to_image,
        my_skills.send_tarot_cards,
        my_skills.query_user_file,
        my_skills.query_user_logs,
        my_skills_general.get_location_name,
        my_skills.help,
    ]
    schema, tools = get_tools(*funcs)
    pprint(schema, width=150)
    pprint(tools)
