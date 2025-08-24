import os

source_folder = r"C:\Users\user\V\4 python\2 telegram bot tesseract\tb1\.venv\Lib\site-packages\beta9"
output_file = r"C:\Users\user\Downloads\all.py.txt"

with open(output_file, "w", encoding="utf-8") as outfile:
    for root, _, files in os.walk(source_folder):
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                outfile.write(f"<filepath>{filepath}</filepath>\n")

                try:
                    with open(filepath, "r", encoding="utf-8") as infile:
                        content = infile.read()
                        outfile.write(content)
                        outfile.write("\n")
                except Exception as e:
                    outfile.write(f"Ошибка чтения файла: {e}\n")
                outfile.write("\n")

print(f"Все .py файлы из '{source_folder}' были собраны в '{output_file}'")
