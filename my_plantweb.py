# pip install plantweb


import cachetools.func
from plantweb.render import render


@cachetools.func.ttl_cache(maxsize=10, ttl=1*60)
def text_to_png(text: str, engine: str, format: str) -> bytes|str:
    '''
    Рендерит диаграмму из текста PlantUML, Graphviz, Ditaa
    Args:
        text: str текст в формате PlantUML, Graphviz, Ditaa
        engine: str 'plantuml', 'graphviz', 'ditaa'
        format: str 'png', 'svg'. ditta поддерживает только png
    '''
    output = ''
    try:
        try:
            output = render(
                text,
                engine=engine,
                format=format,
                cacheopts={
                    'use_cache': False
                }
            )
        except Exception as e:
            return str(e)

        if output:
            if len(output) > 1:
                if isinstance(output[0], bytes):
                    return output[0]

    except Exception as e:
        return str(e)

    # print(output)
    return 'FAILED ' + str(output)


if __name__ == '__main__':
    CONTENT1 = """
digraph finite_state_machine {
    rankdir=LR;
    size="8,5"
    node [shape = doublecircle]; LR_0 LR_3 LR_4 LR_8;
    node [shape = circle];
    LR_0 -> LR_2 [ label = "SS(B)" ];
    LR_0 -> LR_1 [ label = "SS(S)" ];
    LR_1 -> LR_3 [ label = "S($end)" ];
    LR_2 -> LR_6 [ label = "SS(b)" ];
    LR_2 -> LR_5 [ label = "SS(a)" ];
    LR_2 -> LR_4 [ label = "S(A)" ];
    LR_5 -> LR_7 [ label = "S(b)" ];
    LR_5 -> LR_5 [ label = "S(a)" ];
    LR_6 -> LR_6 [ label = "S(b)" ];
    LR_6 -> LR_5 [ label = "S(a)" ];
    LR_7 -> LR_8 [ label = "S(b)" ];
    LR_7 -> LR_5 [ label = "S(a)" ];
    LR_8 -> LR_6 [ label = "S(b)" ];
    LR_8 -> LR_5 [ label = "S(a)" ];
}"""

    CONTENT2 = """
@startditaa
+------------------------+
| [User]                 |
|                        |
|  +------------------+  |
|  | Web Browser      |  |
|  | {s}              |  |
|  +------------------+  |
|          |             |
|          | HTTP        |
|          v             |
|  +------------------+  |
|  | Application Server |
|  | {d}              |  |
|  +------------------+  |
|          |             |
|          | SQL         |
|          v             |
|  +------------------+  |
|  | Database          |
|  | {database}       |  |
|  +------------------+  |
+------------------------+
   :Internet:
   (Connection)
@enduml
"""

    CONTENT3 = """
@startuml
Alice -> Bob: Authentication Request
Bob --> Alice: Authentication Response

Alice -> "Web Server": Request for data
"Web Server" -> Database: Query data
Database --> "Web Server": Data response
"Web Server" --> Alice: Data display

@enduml
"""

    data = text_to_png(
        text=CONTENT1,
        engine='graphviz',
        format='png'
    )
    data2 = text_to_png(
        text=CONTENT2,
        engine='ditaa',
        format='png'
    )
    data3 = text_to_png(
        text=CONTENT3,
        engine='plantuml',
        format='png'
    )

    if data and isinstance(data, bytes):
        with open(r'c:\users\user\Downloads\test.png', 'wb') as f:
            f.write(data)
    elif isinstance(data, str):
        print(data)

    if data2 and isinstance(data2, bytes):
        with open(r'c:\users\user\Downloads\test2.png', 'wb') as f:
            f.write(data2)
    elif isinstance(data2, str):
        print(data2)

    if data3 and isinstance(data3, bytes):
        with open(r'c:\users\user\Downloads\test3.png', 'wb') as f:
            f.write(data3)
    elif isinstance(data3, str):
        print(data3)
