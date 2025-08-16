
    Home
    Gemini API
    Models

Was this helpful?
Document understanding

Gemini models can process documents in PDF format, using native vision to understand entire document contexts. This goes beyond simple text extraction, allowing Gemini to:

    Analyze and interpret content, including text, images, diagrams, charts, and tables, even in long documents up to 1000 pages.
    Extract information into structured output formats.
    Summarize and answer questions based on both the visual and textual elements in a document.
    Transcribe document content (e.g. to HTML), preserving layouts and formatting, for use in downstream applications.

Passing inline PDF data

You can pass inline PDF data in the request to generateContent. For PDF payloads under 20MB, you can choose between uploading base64 encoded documents or directly uploading locally stored files.

The following example shows you how to fetch a PDF from a URL and convert it to bytes for processing:
Python
JavaScript
Go
REST

from google import genai
from google.genai import types
import httpx

client = genai.Client()

doc_url = "https://discovery.ucl.ac.uk/id/eprint/10089234/1/343019_3_art_0_py4t4l_convrt.pdf"

# Retrieve and encode the PDF byte
doc_data = httpx.get(doc_url).content

prompt = "Summarize this document"
response = client.models.generate_content(
  model="gemini-2.5-flash",
  contents=[
      types.Part.from_bytes(
        data=doc_data,
        mime_type='application/pdf',
      ),
      prompt])
print(response.text)

You can also read a PDF from a local file for processing:
Python
JavaScript
Go

from google import genai
from google.genai import types
import pathlib

client = genai.Client()

# Retrieve and encode the PDF byte
filepath = pathlib.Path('file.pdf')

prompt = "Summarize this document"
response = client.models.generate_content(
  model="gemini-2.5-flash",
  contents=[
      types.Part.from_bytes(
        data=filepath.read_bytes(),
        mime_type='application/pdf',
      ),
      prompt])
print(response.text)

Uploading PDFs using the File API

You can use the File API to upload larger documents. Always use the File API when the total request size (including the files, text prompt, system instructions, etc.) is larger than 20MB.
Note: The File API lets you store up to 50MB of PDF files. Files are stored for 48 hours. You can access them in that period with your API key, but you can't download them from the API. The File API is available at no cost in all regions where the Gemini API is available.

Call media.upload to upload a file using the File API. The following code uploads a document file and then uses the file in a call to models.generateContent.
Large PDFs from URLs

Use the File API to simplify uploading and processing large PDF files from URLs:
Python
JavaScript
Go
REST

from google import genai
from google.genai import types
import io
import httpx

client = genai.Client()

long_context_pdf_path = "https://www.nasa.gov/wp-content/uploads/static/history/alsj/a17/A17_FlightPlan.pdf"

# Retrieve and upload the PDF using the File API
doc_io = io.BytesIO(httpx.get(long_context_pdf_path).content)

sample_doc = client.files.upload(
  # You can pass a path or a file-like object here
  file=doc_io,
  config=dict(
    mime_type='application/pdf')
)

prompt = "Summarize this document"

response = client.models.generate_content(
  model="gemini-2.5-flash",
  contents=[sample_doc, prompt])
print(response.text)

Large PDFs stored locally
Python
JavaScript
Go
REST

from google import genai
from google.genai import types
import pathlib
import httpx

client = genai.Client()

# Retrieve and encode the PDF byte
file_path = pathlib.Path('large_file.pdf')

# Upload the PDF using the File API
sample_file = client.files.upload(
  file=file_path,
)

prompt="Summarize this document"

response = client.models.generate_content(
  model="gemini-2.5-flash",
  contents=[sample_file, "Summarize this document"])
print(response.text)

You can verify the API successfully stored the uploaded file and get its metadata by calling files.get. Only the name (and by extension, the uri) are unique.
Python
REST

from google import genai
import pathlib

client = genai.Client()

fpath = pathlib.Path('example.txt')
fpath.write_text('hello')

file = client.files.upload(file='example.txt')

file_info = client.files.get(name=file.name)
print(file_info.model_dump_json(indent=4))

Passing multiple PDFs

The Gemini API is capable of processing multiple PDF documents (up to 1000 pages) in a single request, as long as the combined size of the documents and the text prompt stays within the model's context window.
Python
JavaScript
Go
REST

from google import genai
import io
import httpx

client = genai.Client()

doc_url_1 = "https://arxiv.org/pdf/2312.11805"
doc_url_2 = "https://arxiv.org/pdf/2403.05530"

# Retrieve and upload both PDFs using the File API
doc_data_1 = io.BytesIO(httpx.get(doc_url_1).content)
doc_data_2 = io.BytesIO(httpx.get(doc_url_2).content)

sample_pdf_1 = client.files.upload(
  file=doc_data_1,
  config=dict(mime_type='application/pdf')
)
sample_pdf_2 = client.files.upload(
  file=doc_data_2,
  config=dict(mime_type='application/pdf')
)

prompt = "What is the difference between each of the main benchmarks between these two papers? Output these in a table."

response = client.models.generate_content(
  model="gemini-2.5-flash",
  contents=[sample_pdf_1, sample_pdf_2, prompt])
print(response.text)

Technical details

Gemini supports a maximum of 1,000 document pages. Each document page is equivalent to 258 tokens.

While there are no specific limits to the number of pixels in a document besides the model's context window, larger pages are scaled down to a maximum resolution of 3072x3072 while preserving their original aspect ratio, while smaller pages are scaled up to 768x768 pixels. There is no cost reduction for pages at lower sizes, other than bandwidth, or performance improvement for pages at higher resolution.
Document types

Technically, you can pass other MIME types for document understanding, like TXT, Markdown, HTML, XML, etc. However, document vision only meaningfully understands PDFs. Other types will be extracted as pure text, and the model won't be able to interpret what we see in the rendering of those files. Any file-type specifics like charts, diagrams, HTML tags, Markdown formatting, etc., will be lost.
Best practices

For best results:

    Rotate pages to the correct orientation before uploading.
    Avoid blurry pages.
    If using a single page, place the text prompt after the page.
