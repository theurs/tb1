# pip install plantuml


import cachetools
import plantuml


@cachetools.func.ttl_cache(maxsize=10, ttl=1*60)
def plantuml_to_png(text: str) -> bytes|str|None:
    try:
        p = plantuml.PlantUML(url='http://www.plantuml.com/plantuml/img/')

        r = p.processes(text)
        if r:
            return r
    except Exception as e:
        return str(e)
    return None


if __name__ == '__main__':
    r = plantuml_to_png('hello')
    if r and isinstance(r, bytes):
        with open(r'c:\Users\user\Downloads\out.png', 'wb') as f:
            f.write(r)
