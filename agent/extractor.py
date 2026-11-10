import json
import re
from dataclasses import dataclass


@dataclass
class ExtractorOutput:
    result: str
    error: str


def extract_code(text: str) -> ExtractorOutput:
    """Call the proper function to extract code/tool_calls from text"""

    if "</tool_call>" in text:
        extracted = extract_hermes(text)
    elif "</invoke>" in text:
        extracted = extract_xml(text)
    elif "Action Input:" in text:
        extracted = extract_react(text)
    else:
        extracted = extract_python(text)

    if extracted.error:
        extracted.error += ("\ntool calling format handled:\n"
                               "1. python code blocks\n"
                               "2. Json/Hermes\n"
                               "3. XML\n"
                               "4. ReAct\n")

    return extracted


def extract_hermes(text: str) -> dict[str, str]:
    """Extract json/hermes tool calls format from text"""

    pattern = r"<tool_call>([\s\S]*?)</tool_call>"

    matches = re.findall(pattern, text)
    result: list[str] = []
    error: list[str] = []

    for tool in matches:
        try:
            dic = json.loads(tool)

            # default is empty            
            args: list[str] = []
            for k, v in dic["arguments"].items():
                args.append(f'{k}={repr(v)}')

            result.append(f"{dic['name']}({', '.join(args)})")

        except json.JSONDecodeError as e:
            error.append("Wrong Json format for the arguments.\n"
                          f"error: {e}")

    if not result:
        error.append("Error: Wrong Json/hermes format!\n"
                      'expected: <tool_call> {"name": "tool_name", "arguments": '
                      '{"arg": value, "arg2": value}} </tool_call>\n'
                      )
    return ExtractorOutput(result='\n'.join(result),
                           error='\n'.join(error))


def extract_python(text: str) -> ExtractorOutput:
    """Extract pure python code from text"""

    pattern = r"\`\`\`(?:python|py)([\s\S]*?)\`\`\`"

    matches = re.findall(pattern, text)
    error = ""

    if not matches:
        error = ("Error: No python code found in the given input!\n"
                 'Expected format: """python\n'
                 '#some code\n'
                 '"""')

    # return only last python code found
    try:
        tmp = matches[-1]
    except IndexError:
        tmp = ""

    return ExtractorOutput(result=tmp,
                           error=error)


def extract_xml(text: str) -> str:
    """Extract XML tool calls format from text"""

    function_name_pattern = r'<invoke name="([A-Za-z0-9_]*?)"'
    parameters_pattern = r'<parameter name="([A-Za-z0-9_]*?)">([\S\s]*?)<'

    # split every tool call to make it easier to link functions with their parameters
    tool_calls = text.split("</invoke>")
    result: list[str] = []
    error: list[str] = []

    for tool_call in tool_calls:
        function_name = re.findall(function_name_pattern, tool_call)
        parameters = re.findall(parameters_pattern, tool_call)

        if not function_name:
            continue

        params = []

        for name, value in parameters:
            params.append(f'{name}={repr(value)}')

        result.append(f"{function_name[0]}({', '.join(params)})")

    if not result:
        error.append("Error: Wrong XML format!\n"
                      'expected XML:\n<invoke name="tool_name">'
                      '<parameter name="arg1">value</parameter>'
                      '<parameter name="arg2">value</parameter>'
                      '</invoke>'
                      )
    return ExtractorOutput(result='\n'.join(result),
                           error='\n'.join(error))


def extract_react(text: str):
    """Extract ReAct tool calls format from text"""

    function_name_patern = r'Action:\s*([A-Za-z0-9_]*)'
    parameters_pattern = r'Action Input:\s*([\S\s]*?\})'

    function_name = re.findall(function_name_patern, text)
    parameter_lst = re.findall(parameters_pattern, text)

    result: list[str] = []
    error: list[str] = []

    for name, parameters in zip(function_name, parameter_lst):
        try:
            parameter_dict = json.loads(parameters)
            func_parameter = []

            for k, v in parameter_dict.items():
                func_parameter.append(f'{k}={repr(v)}')

            result.append(f"{name}({', '.join(func_parameter)})")
        except json.JSONDecodeError as e:
            error.append("Wrong Json format for the arguments.\n"
                          f"Error: {e}")

    if not result:
        error.append("Error: Wrong ReAct format!\n"
                      'expected ReAct:\nAction: tool_name\n'
                      'Action Input: {"arg1": value, "arg2": value}'
                      )
    return ExtractorOutput(result='\n'.join(result),
                           error='\n'.join(error))


################ Hermes test #####################

# print(extract_hermes(
#     '''
# I'll start by searching for the validation function.

# <tool_call>
# {"name": "search_code", "arguments": {"pattern": 10, "b": 2}}
# </tool_call>
# I'll start by searching for the validation function.

# <tool_call>
# {"name": "search_code", "arguments": {"pattern": "validate_email"}}
# </tool_call>
# I'll start by searching for the validation function.

# <tool_call>
# {"name": "search_code", "arguments": {}}
# </tool_call>

# '''
# ))


################ Python test #####################

# print(extract_python(
# """
# I need to find where email validation happens, then read that file.

# ```python
# matches = search_code("validate_email")
# print(matches)
# content = read_file(filepath="/testbed/models.py", start_line=1, end_line=50)
# print(content)
# ```
# or maybe use
# ```py
# blue = 1
# ```

# ```
# print("hello world")
# ```
# """
# ))


################ XML test #####################

# print(
#     extract_xml(
#         """<invoke name="search_code">
# <parameter name="pattern">validate_email</parameter>
# <parameter name="weee">12</parameter>
# </invoke>
# yeah that should work and then maybe
# <invoke name="search">
# <parameter name="pat">valid</parameter>
# <parameter name="woo">1</parameter>
# </invoke>
# <invoke name="be">
# </invoke>
# """
#     )
# )


################ ReAct test #####################

# print(extract_react("""Thought: I should look for the validation function.
# Action: search_code
# Action Input: {"pattern": "validate_email", "num": 123}
#                     Thought: I should look for the validation function.
# Action: search
# Action Input: {"pat": "valid", "nm": 13}
# Action: search
# Action Input: {}"""))
