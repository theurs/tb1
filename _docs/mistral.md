
Text and Chat Completions

The Mistral models allows you to chat with a model that has been fine-tuned to follow instructions and respond to natural language prompts. A prompt is the input that you provide to the Mistral model. It can come in various forms, such as asking a question, giving an instruction, or providing a few examples of the task you want the model to perform. Based on the prompt, the Mistral model generates a text output as a response.

The chat completion API accepts a list of chat messages as input and generates a response. This response is in the form of a new chat message with the role "assistant" as output, the "content" of each response can either be a string or a list of chunks with different kinds of chunk types for different features. Visit our API spec for more details.

    python
    typescript
    curl

No streaming

import os
from mistralai import Mistral

api_key = os.environ["MISTRAL_API_KEY"]
model = "mistral-large-latest"

client = Mistral(api_key=api_key)

chat_response = client.chat.complete(
    model = model,
    messages = [
        {
            "role": "user",
            "content": "What is the best French cheese?",
        },
    ]
)

print(chat_response.choices[0].message.content)

With streaming

import os
from mistralai import Mistral

api_key = os.environ["MISTRAL_API_KEY"]
model = "mistral-large-latest"

client = Mistral(api_key=api_key)

stream_response = client.chat.stream(
    model = model,
    messages = [
        {
            "role": "user",
            "content": "What is the best French cheese?",
        },
    ]
)

for chunk in stream_response:
    print(chunk.data.choices[0].delta.content)

With async and without streaming

import asyncio
import os

from mistralai import Mistral
from mistralai.models import UserMessage


async def main():
    api_key = os.environ["MISTRAL_API_KEY"]
    model = "mistral-large-latest"

    client = Mistral(api_key=api_key)

    chat_response = await client.chat.complete_async(
        model=model,
        messages=[UserMessage(content="What is the best French cheese?")],
    )

    print(chat_response.choices[0].message.content)


if __name__ == "__main__":
    asyncio.run(main())

With async and with streaming

import asyncio
import os

from mistralai import Mistral


async def main():
    api_key = os.environ["MISTRAL_API_KEY"]
    model = "mistral-large-latest"

    client = Mistral(api_key=api_key)

    response = await client.chat.stream_async(
        model=model,
        messages=[
             {
                  "role": "user",
                  "content": "Who is the best French painter? Answer in JSON.",
              },
        ],
    )
    async for chunk in response:
        if chunk.data.choices[0].delta.content is not None:
            print(chunk.data.choices[0].delta.content, end="")


if __name__ == "__main__":
    asyncio.run(main())

Chat messages

Chat messages (messages) are a collection of prompts or messages, with each message having a specific role assigned to it, such as "system," "user," "assistant," or "tool."

    A system message is an optional message that sets the behavior and context for an AI assistant in a conversation, such as modifying its personality or providing specific instructions. A system message can include task instructions, personality traits, contextual information, creativity constraints, and other relevant guidelines to help the AI better understand and respond to the user's input. See the API reference for explanations on how to set up a custom system prompt.
    A user message is a message sent from the perspective of the human in a conversation with an AI assistant. It typically provides a request, question, or comment that the AI assistant should respond to. User prompts allow the human to initiate and guide the conversation, and they can be used to request information, ask for help, provide feedback, or engage in other types of interaction with the AI.
    An assistant message is a message sent by the AI assistant back to the user. It is usually meant to reply to a previous user message by following its instructions, but you can also find it at the beginning of a conversation, for example to greet the user.
    A tool message only appears in the context of function calling, it is used at the final response formulation step when the model has to format the tool call's output for the user. To learn more about function calling, see the guide.

When to use user prompt vs. system message then user message?

    You can either combine your system message and user message into a single user message or separate them into two distinct messages.
    We recommend you experiment with both ways to determine which one works better for your specific use case.

Other useful features

The prefix flag enables prepending content to the assistant's response content. When used in a message, it allows the addition of an assistant's message at the end of the list, which will be prepended to the assistant's response. For more details on how it works see prefix.

The safe_prompt flag is used to force chat completion to be moderated against sensitive content (see Guardrailing).

A stop sequence allows forcing the model to stop generating after one or more chosen tokens or strings.


Vision

Vision capabilities enable models to analyze images and provide insights based on visual content in addition to text. This multimodal approach opens up new possibilities for applications that require both textual and visual understanding.

For more specific use cases regarding document parsing and data extraction we recommend taking a look at our Document AI stack here.
Models with Vision Capabilities:

    Pixtral 12B (pixtral-12b-latest)
    Pixtral Large 2411 (pixtral-large-latest)
    Mistral Medium 2505 (mistral-medium-latest)
    Mistral Small 2503 (mistral-small-latest)

Passing an Image URL

If the image is hosted online, you can simply provide the URL of the image in the request. This method is straightforward and does not require any encoding.

    python
    typescript
    curl

import os
from mistralai import Mistral

# Retrieve the API key from environment variables
api_key = os.environ["MISTRAL_API_KEY"]

# Specify model
model = "pixtral-12b-2409"

# Initialize the Mistral client
client = Mistral(api_key=api_key)

# Define the messages for the chat
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": "What's in this image?"
            },
            {
                "type": "image_url",
                "image_url": "https://tripfixers.com/wp-content/uploads/2019/11/eiffel-tower-with-snow.jpeg"
            }
        ]
    }
]

# Get the chat response
chat_response = client.chat.complete(
    model=model,
    messages=messages
)

# Print the content of the response
print(chat_response.choices[0].message.content)

Passing a Base64 Encoded Image

If you have an image or a set of images stored locally, you can pass them to the model in base64 encoded format. Base64 encoding is a common method for converting binary data into a text format that can be easily transmitted over the internet. This is particularly useful when you need to include images in API requests.

    python
    typescript
    curl

import base64
import requests
import os
from mistralai import Mistral

def encode_image(image_path):
    """Encode the image to base64."""
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except FileNotFoundError:
        print(f"Error: The file {image_path} was not found.")
        return None
    except Exception as e:  # Added general exception handling
        print(f"Error: {e}")
        return None

# Path to your image
image_path = "path_to_your_image.jpg"

# Getting the base64 string
base64_image = encode_image(image_path)

# Retrieve the API key from environment variables
api_key = os.environ["MISTRAL_API_KEY"]

# Specify model
model = "pixtral-12b-2409"

# Initialize the Mistral client
client = Mistral(api_key=api_key)

# Define the messages for the chat
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": "What's in this image?"
            },
            {
                "type": "image_url",
                "image_url": f"data:image/jpeg;base64,{base64_image}" 
            }
        ]
    }
]

# Get the chat response
chat_response = client.chat.complete(
    model=model,
    messages=messages
)

# Print the content of the response
print(chat_response.choices[0].message.content)

Use cases
Understand charts
Compare images
Transcribe receipts
OCR old documents
OCR with structured output
FAQ

    What is the price per image?

    The price is calculated using the same pricing as input tokens per image, with each image being tokenized.

    How many tokens correspond to an image and/or what is the maximum resolution?

    Depending on the model and resolution, an image will be tokenized differently. Below is a summary.
    Model	Max Resolution	≈ Formula	≈ N Max Tokens
    Mistral Small 3.2	1540x1540	≈ (ResolutionX * ResolutionY) / 784	≈ 3025
    Mistral Medium 3	1540x1540	≈ (ResolutionX * ResolutionY) / 784	≈ 3025
    Mistral Small 3.1	1540x1540	≈ (ResolutionX * ResolutionY) / 784	≈ 3025
    Pixtral Large	1024x1024	≈ (ResolutionX * ResolutionY) / 256	≈ 4096
    Pixtral 12B	1024x1024	≈ (ResolutionX * ResolutionY) / 256	≈ 4096

    If the resolution of the image sent is higher than the maximum resolution of the model, the image will be downscaled to its maximum resolution. An error will be sent if the resolution is higher than 10000x10000.

    Can I fine-tune the image capabilities?

    Yes, you can fine-tune pixtral-12b.

    Can I use them to generate images?

    No, they are designed to understand and analyze images, not to generate them.

    What types of image files are supported?

    We currently support the following image formats:
        PNG (.png)
        JPEG (.jpeg and .jpg)
        WEBP (.webp)
        Non-animated GIF with only one frame (.gif)

    Is there a limit to the size of the image?

    The current file size limit is 10Mb.

    What's the maximum number images per request?

    The maximum number images per request via API is 8.

    What is the rate limit?

    For information on rate limits, please visit https://console.mistral.ai/limits/.


Function calling
Open In Colab

Function calling allows Mistral models to connect to external tools. By integrating Mistral models with external tools such as user defined functions or APIs, users can easily build applications catering to specific use cases and practical problems. In this guide, for instance, we wrote two functions for tracking payment status and payment date. We can use these two tools to provide answers for payment-related queries.
Available models

Currently, function calling is available for the following models:

    Mistral Large
    Mistral Medium
    Mistral Small
    Devstral Small
    Codestral
    Ministral 8B
    Ministral 3B
    Pixtral 12B
    Pixtral Large
    Mistral Nemo

Four steps

At a glance, there are four steps with function calling:

    User: specify tools and query
    Model: Generate function arguments if applicable
    User: Execute function to obtain tool results
    Model: Generate final answer

functioncalling1

In this guide, we will walk through a simple example to demonstrate how function calling works with Mistral models in these four steps.

Before we get started, let’s assume we have a dataframe consisting of payment transactions. When users ask questions about this dataframe, they can use certain tools to answer questions about this data. This is just an example to emulate an external database that the LLM cannot directly access.

    python
    typescript

import pandas as pd

# Assuming we have the following data
data = {
    'transaction_id': ['T1001', 'T1002', 'T1003', 'T1004', 'T1005'],
    'customer_id': ['C001', 'C002', 'C003', 'C002', 'C001'],
    'payment_amount': [125.50, 89.99, 120.00, 54.30, 210.20],
    'payment_date': ['2021-10-05', '2021-10-06', '2021-10-07', '2021-10-05', '2021-10-08'],
    'payment_status': ['Paid', 'Unpaid', 'Paid', 'Paid', 'Pending']
}

# Create DataFrame
df = pd.DataFrame(data)

Step 1. User: specify tools and query
functioncalling2
Tools

Users can define all the necessary tools for their use cases.

    In many cases, we might have multiple tools at our disposal. For example, let’s consider we have two functions as our two tools: retrieve_payment_status and retrieve_payment_date to retrieve payment status and payment date given transaction ID.

    python
    typescript

def retrieve_payment_status(df: data, transaction_id: str) -> str:
    if transaction_id in df.transaction_id.values: 
        return json.dumps({'status': df[df.transaction_id == transaction_id].payment_status.item()})
    return json.dumps({'error': 'transaction id not found.'})

def retrieve_payment_date(df: data, transaction_id: str) -> str:
    if transaction_id in df.transaction_id.values: 
        return json.dumps({'date': df[df.transaction_id == transaction_id].payment_date.item()})
    return json.dumps({'error': 'transaction id not found.'})

    In order for Mistral models to understand the functions, we need to outline the function specifications with a JSON schema. Specifically, we need to describe the type, function name, function description, function parameters, and the required parameter for the function. Since we have two functions here, let’s list two function specifications in a list.

    python
    typescript

tools = [
    {
        "type": "function",
        "function": {
            "name": "retrieve_payment_status",
            "description": "Get payment status of a transaction",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {
                        "type": "string",
                        "description": "The transaction id.",
                    }
                },
                "required": ["transaction_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_payment_date",
            "description": "Get payment date of a transaction",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {
                        "type": "string",
                        "description": "The transaction id.",
                    }
                },
                "required": ["transaction_id"],
            },
        },
    }
]

Note: You can specify multiple parameters for each function in the properties object. In the following example, we choose to merge the retrieve_payment_status and retrieve_payment_date into retrieve_payment_info:

tools = [
    {
        "type": "function",
        "function": {
            "name": "retrieve_payment_info",
            "description": "Retrieves payment infos",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {
                        "type": "string",
                        "description": "The transaction id",
                    },
                    "info_type": {
                        "type": "string",
                        "description": "The info type ('status' or 'date')",
                    }
                },
                "required": ["transaction_id", "info_type"],
            },
        },
    }
]

    Then we organize the two functions into a dictionary where keys represent the function name, and values are the function with the df defined. This allows us to call each function based on its function name.

    python
    typescript

import functools

names_to_functions = {
    'retrieve_payment_status': functools.partial(retrieve_payment_status, df=df),
    'retrieve_payment_date': functools.partial(retrieve_payment_date, df=df)
}

User query

Suppose a user asks the following question: “What’s the status of my transaction?” A standalone LLM would not be able to answer this question, as it needs to query the business logic backend to access the necessary data. But what if we have an exact tool we can use to answer this question? We could potentially provide an answer!

    python
    typescript

messages = [{"role": "user", "content": "What's the status of my transaction T1001?"}]

Step 2. Model: Generate function arguments
functioncalling3

How do Mistral models know about these functions and know which function to use? We provide both the user query and the tools specifications to Mistral models. The goal in this step is not for the Mistral model to run the function directly. It’s to 1) determine the appropriate function to use , 2) identify if there is any essential information missing for a function, and 3) generate necessary arguments for the chosen function.
tool_choice

Users can use tool_choice to specify how tools are used:

    "auto": default mode. Model decides if it uses the tool or not.
    "any": forces tool use.
    "none": prevents tool use.

parallel_tool_calls

Users can use parallel_tool_calls to specify whether parallel tool calling is allowed.

    true: default mode. The model decides if it uses parallel tool calls or not.
    false: forces the model to use single tool calling.

    python
    typescript

import os
from mistralai import Mistral

api_key = os.environ["MISTRAL_API_KEY"]
model = "mistral-large-latest"

client = Mistral(api_key=api_key)
response = client.chat.complete(
    model = model,
    messages = messages,
    tools = tools,
    tool_choice = "any",
    parallel_tool_calls = False,
)
response

We get the response including tool_calls with the chosen function name retrieve_payment_status and the arguments for this function.

Output:

ChatCompletionResponse(id='7cbd8962041442459eb3636e1e3cbf10', object='chat.completion', model='mistral-large-latest', usage=Usage(prompt_tokens=94, completion_tokens=30, total_tokens=124), created=1721403550, choices=[Choices(index=0, finish_reason='tool_calls', message=AssistantMessage(content='', tool_calls=[ToolCall(function=FunctionCall(name='retrieve_payment_status', arguments='{"transaction_id": "T1001"}'), id='D681PevKs', type='function')], prefix=False, role='assistant'))])

Let’s add the response message to the messages list.

    python
    typescript

messages.append(response.choices[0].message)

Step 3. User: Execute function to obtain tool results
functioncalling4

How do we execute the function? Currently, it is the user’s responsibility to execute these functions and the function execution lies on the user side. In the future, we may introduce some helpful functions that can be executed server-side.

Let’s extract some useful function information from model response including function_name and function_params. It’s clear here that our Mistral model has chosen to use the function retrieve_payment_status with the parameter transaction_id set to T1001.

    python
    typescript

import json

tool_call = response.choices[0].message.tool_calls[0]
function_name = tool_call.function.name
function_params = json.loads(tool_call.function.arguments)
print("\nfunction_name: ", function_name, "\nfunction_params: ", function_params)

Output

function_name:  retrieve_payment_status 
function_params: {'transaction_id': 'T1001'}

Now we can execute the function and we get the function output '{"status": "Paid"}'.

    python
    typescript

function_result = names_to_functions[function_name](**function_params)
function_result

Output

'{"status": "Paid"}'

Step 4. Model: Generate final answer
functioncalling5

We can now provide the output from the tools to Mistral models, and in return, the Mistral model can produce a customised final response for the specific user.

    python
    typescript

messages.append({
    "role":"tool", 
    "name":function_name, 
    "content":function_result, 
    "tool_call_id":tool_call.id
})

response = client.chat.complete(
    model = model, 
    messages = messages
)
response.choices[0].message.content

Output:

The status of your transaction with ID T1001 is "Paid". Is there anything else I can assist you with?


Basics of Function Calling
View on GitHub
Open in Colab

Function calling allows Mistral models to connect to external tools. By integrating Mistral models with external tools such as user defined functions or APIs, users can easily build applications catering to specific use cases and practical problems. In this guide, for instance, we wrote two functions for tracking payment status and payment date. We can use these two tools to provide answers for payment-related queries.

At a glance, there are four steps with function calling:

    User: specify tools and query
    Model: Generate function arguments if applicable
    User: Execute function to obtain tool results
    Model: Generate final answer

In this guide, we will walk through a simple example to demonstrate how function calling works with Mistral models in these four steps.

Before we get started, let’s assume we have a dataframe consisting of payment transactions. When users ask questions about this dataframe, they can use certain tools to answer questions about this data. This is just an example to emulate an external database that the LLM cannot directly access.

!pip install pandas mistralai

import pandas as pd

# Assuming we have the following data
data = {
    'transaction_id': ['T1001', 'T1002', 'T1003', 'T1004', 'T1005'],
    'customer_id': ['C001', 'C002', 'C003', 'C002', 'C001'],
    'payment_amount': [125.50, 89.99, 120.00, 54.30, 210.20],
    'payment_date': ['2021-10-05', '2021-10-06', '2021-10-07', '2021-10-05', '2021-10-08'],
    'payment_status': ['Paid', 'Unpaid', 'Paid', 'Paid', 'Pending']
}

# Create DataFrame
df = pd.DataFrame(data)

Step 1. User: specify tools and query
Tools

Users can define all the necessary tools for their use cases.

    In many cases, we might have multiple tools at our disposal. For example, let’s consider we have two functions as our two tools: retrieve_payment_status and retrieve_payment_date to retrieve payment status and payment date given transaction ID.

def retrieve_payment_status(df: data, transaction_id: str) -> str:
    if transaction_id in df.transaction_id.values:
        return json.dumps({'status': df[df.transaction_id == transaction_id].payment_status.item()})
    return json.dumps({'error': 'transaction id not found.'})

def retrieve_payment_date(df: data, transaction_id: str) -> str:
    if transaction_id in df.transaction_id.values:
        return json.dumps({'date': df[df.transaction_id == transaction_id].payment_date.item()})
    return json.dumps({'error': 'transaction id not found.'})

    In order for Mistral models to understand the functions, we need to outline the function specifications with a JSON schema. Specifically, we need to describe the type, function name, function description, function parameters, and the required parameter for the function. Since we have two functions here, let’s list two function specifications in a list.

tools = [
    {
        "type": "function",
        "function": {
            "name": "retrieve_payment_status",
            "description": "Get payment status of a transaction",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {
                        "type": "string",
                        "description": "The transaction id.",
                    }
                },
                "required": ["transaction_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "retrieve_payment_date",
            "description": "Get payment date of a transaction",
            "parameters": {
                "type": "object",
                "properties": {
                    "transaction_id": {
                        "type": "string",
                        "description": "The transaction id.",
                    }
                },
                "required": ["transaction_id"],
            },
        },
    }
]

    Then we organize the two functions into a dictionary where keys represent the function name, and values are the function with the df defined. This allows us to call each function based on its function name.

import functools

names_to_functions = {
  'retrieve_payment_status': functools.partial(retrieve_payment_status, df=df),
  'retrieve_payment_date': functools.partial(retrieve_payment_date, df=df)
}

User query

Suppose a user asks the following question: “What’s the status of my transaction?” A standalone LLM would not be able to answer this question, as it needs to query the business logic backend to access the necessary data. But what if we have an exact tool we can use to answer this question? We could potentially provide an answer!

messages = [{"role": "user", "content": "What's the status of my transaction T1001?"}]

Step 2. Model: Generate function arguments

How do Mistral models know about these functions and know which function to use? We provide both the user query and the tools specifications to Mistral models. The goal in this step is not for the Mistral model to run the function directly. It’s to 1) determine the appropriate function to use , 2) identify if there is any essential information missing for a function, and 3) generate necessary arguments for the chosen function.

import os
from mistralai import Mistral

api_key = os.environ["MISTRAL_API_KEY"]
model = "mistral-large-latest"

client = Mistral(api_key=api_key)
response = client.chat.complete(
    model = model,
    messages = messages,
    tools = tools,
    tool_choice = "any",
)
response

ChatCompletionResponse(id='7cbd8962041442459eb3636e1e3cbf10', object='chat.completion', model='mistral-large-latest', usage=Usage(prompt_tokens=94, completion_tokens=30, total_tokens=124), created=1721403550, choices=[Choices(index=0, finish_reason='tool_calls', message=AssistantMessage(content='', tool_calls=[ToolCall(function=FunctionCall(name='retrieve_payment_status', arguments='{"transaction_id": "T1001"}'), id='D681PevKs', type='function')], prefix=False, role='assistant'))])

messages.append(response.choices[0].message)

messages

[{'role': 'user', 'content': "What's the status of my transaction T1001?"},
 AssistantMessage(content='', tool_calls=[ToolCall(function=FunctionCall(name='retrieve_payment_status', arguments='{"transaction_id": "T1001"}'), id='D681PevKs', type='function')], prefix=False, role='assistant')]

Step 3. User: Execute function to obtain tool results

How do we execute the function? Currently, it is the user’s responsibility to execute these functions and the function execution lies on the user side. In the future, we may introduce some helpful functions that can be executed server-side.

Let’s extract some useful function information from model response including function_name and function_params. It’s clear here that our Mistral model has chosen to use the function retrieve_payment_status with the parameter transaction_id set to T1001.

import json
tool_call = response.choices[0].message.tool_calls[0]
function_name = tool_call.function.name
function_params = json.loads(tool_call.function.arguments)
print("\nfunction_name: ", function_name, "\nfunction_params: ", function_params)


function_name:  retrieve_payment_status 
function_params:  {'transaction_id': 'T1001'}

function_result = names_to_functions[function_name](**function_params)
function_result

'{"status": "Paid"}'

messages.append({"role":"tool", "name":function_name, "content":function_result, "tool_call_id":tool_call.id})

messages

[{'role': 'user', 'content': "What's the status of my transaction T1001?"},
 AssistantMessage(content='', tool_calls=[ToolCall(function=FunctionCall(name='retrieve_payment_status', arguments='{"transaction_id": "T1001"}'), id='D681PevKs', type='function')], prefix=False, role='assistant'),
 {'role': 'tool',
  'name': 'retrieve_payment_status',
  'content': '{"status": "Paid"}',
  'tool_call_id': 'D681PevKs'}]

Step 4. Model: Generate final answer

We can now provide the output from the tools to Mistral models, and in return, the Mistral model can produce a customised final response for the specific user.

response = client.chat.complete(
    model = model,
    messages = messages
)
response.choices[0].message.content

'The payment for transaction T1001 has been successfully paid.'


