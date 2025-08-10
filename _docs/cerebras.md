

# Tool Use

<Tip>
  [**To get started with a free API key, click here.**](https://cloud.cerebras.ai?utm_source=inferencedocs)
</Tip>

The Cerebras Inference SDK supports tool use, enabling programmatic execution of specific tasks by sending requests with clearly defined operations. This guide will walk you through a detailed example of how to use tool use with the Cerebras Inference SDK.

<Steps>
  <Step title="Initial Setup">
    To begin, we need to import the necessary libraries and set up our Cerebras client.

    <Tip>
      If you haven't set up your Cerebras API key yet, please visit our [QuickStart guide](quickstart) for detailed instructions on how to obtain and configure your API key.
    </Tip>

    ```python
    import os
    import json
    import re
    from cerebras.cloud.sdk import Cerebras

    # Initialize Cerebras client
    client = Cerebras(
        api_key=os.environ.get("CEREBRAS_API_KEY"),
    )
    ```
  </Step>

  <Step title="Setting Up the Tool">
    Our first step is to define the tool that our AI will use. In this example, we're creating a simple calculator function that can perform basic arithmetic operations.

    ```python
    def calculate(expression):
        expression = re.sub(r'[^0-9+\-*/().]', '', expression)
        
        try:
            result = eval(expression)
            return str(result)
        except (SyntaxError, ZeroDivisionError, NameError, TypeError, OverflowError):
            return "Error: Invalid expression"
    ```
  </Step>

  <Step title="Defining the Tool Schema">
    Next, we define the tool schema. This schema acts as a blueprint for the AI, describing the tool's functionality, when to use it, and what parameters it expects. It helps the AI understand how to interact with our custom tool effectively.

    <Warning>
      Please ensure that `"strict": True` is set inside the `function` object in the tool schema.
    </Warning>

    ```python
    tools = [
        {
            "type": "function",
            "function": {
                "name": "calculate",
                "strict": True,
                "description": "A calculator tool that can perform basic arithmetic operations. Use this when you need to compute mathematical expressions or solve numerical problems.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "The mathematical expression to evaluate"
                        }
                    },
                    "required": ["expression"]
                }
            }
        }
    ]
    ```
  </Step>

  <Step title="Making the API Call">
    With our tool and its schema defined, we can now set up the conversation for our AI. We will prompt the LLM using natural language to conduct a simple calculation, and make the API call.

    This call sends our messages and tool schema to the LLM, allowing it to generate a response that may include tool use.

    <Warning>
      You must set `parallel_tool_calls=False` when using tool calling with `llama-4-scout-17b-16e-instruct`. The model doesn’t currently support parallel tool calling, but a future release will.
    </Warning>

    ```python
    messages = [
        {"role": "system", "content": "You are a helpful assistant with access to a calculator. Use the calculator tool to compute mathematical expressions when needed."},
        {"role": "user", "content": "What's the result of 15 multiplied by 7?"},
    ]

    response = client.chat.completions.create(
        model="llama-4-scout-17b-16e-instruct",
        messages=messages,
        tools=tools,
        parallel_tool_calls=False,
    )
    ```
  </Step>

  <Step title="Handling Tool Calls">
    Now that we've made the API call, we need to process the response and handle any tool calls the LLM might have made. Note that the LLM determines based on the prompt if it should rely on a tool to respond to the user. Therefore, we need to check for any tool calls and handle them appropriately.

    In the code below, we first check if there are any tool calls in the model's response. If a tool call is present, we proceed to execute it and ensure that the function is fulfilled correctly. The function call is logged to indicate that the model is requesting a tool call, and the result of the tool call is logged to clarify that this is not the model's final output but rather the result of fulfilling its request. The result is then passed back to the model so it can continue generating a final response.

    ```python
    choice = response.choices[0].message

    if choice.tool_calls:
        function_call = choice.tool_calls[0].function
        if function_call.name == "calculate":
            # Logging that the model is executing a function named "calculate".
            print(f"Model executing function '{function_call.name}' with arguments {function_call.arguments}")

            # Parse the arguments from JSON format and perform the requested calculation.
            arguments = json.loads(function_call.arguments)
            result = calculate(arguments["expression"])

            # Note: This is the result of executing the model's request (the tool call), not the model's own output.
            print(f"Calculation result sent to model: {result}")
           
           # Send the result back to the model to fulfill the request.
            messages.append({
                "role": "tool",
                "content": json.dumps(result),
                "tool_call_id": choice.tool_calls[0].id
            })
     
           # Request the final response from the model, now that it has the calculation result.
            final_response = client.chat.completions.create(
                model="llama-4-scout-17b-16e-instruct",
                messages=messages,
            )
            
            # Handle and display the model's final response.
            if final_response:
                print("Final model output:", final_response.choices[0].message.content)
            else:
                print("No final response received")
    else:
        # Handle cases where the model's response does not include expected tool calls.
        print("Unexpected response from the model")
    ```
  </Step>
</Steps>

<Warning>
  Tool calling is currently enabled via prompt engineering, but strict adherence to expected outputs is not yet guaranteed. The LLM autonomously determines whether to call a tool. An update is in progress to improve reliability in future versions.
</Warning>

In this case, the LLM determined that a tool call was appropriate to answer the users' question of what the result of 15 multiplied by 7 is. See the output below.

```
Model executing function 'calculate' with arguments {"expression": "15 * 7"}
Calculation result sent to model: 105
Final model output: 15 * 7 = 105
```

## Multi-turn Tool Use

Most real-world workflows require more than one tool invocation. Multi-turn tool calling lets a model call a tool, incorporate its output, and then, within the same conversation, decide whether it needs to call the tool (or another tool) again to finish the task.

It works as follows:

1. After every tool call you append the tool response to `messages`, then ask the model to continue.
2. The model itself decides when enough information has been gathered to produce a final answer.
3. Continue calling `client.chat.completions.create()` until you get a message without `tool_calls`.

The example below demonstrates multi-turn tool use as an extension of the calculator example above. Before continuing, make sure you’ve completed Steps 1–3 from the calculator setup section.

```python
messages = [
    {
        "role": "system",
        "content": (
            "You are a helpful assistant with a calculator tool. "
            "Use it whenever math is required."
        ),
    },
    {"role": "user", "content": "First, multiply 15 by 7. Then take that result, add 20, and divide the total by 2. What's the final number?"},
]

# Register every callable tool once
available_functions = {
    "calculate": calculate,
}

while True:
    resp = client.chat.completions.create(
        model="qwen-3-32b",
        messages=messages,
        tools=tools,
    )
    msg = resp.choices[0].message

    # If the assistant didn’t ask for a tool, we’re done
    if not msg.tool_calls:
        print("Assistant:", msg.content)
        break

    # Save the assistant turn exactly as returned
    messages.append(msg.model_dump())    

    # Run the requested tool
    call  = msg.tool_calls[0]
    fname = call.function.name

    if fname not in available_functions:
        raise ValueError(f"Unknown tool requested: {fname!r}")

    args_dict = json.loads(call.function.arguments)  # assumes JSON object
    output = available_functions[fname](**args_dict)

    # Feed the tool result back
    messages.append({
        "role": "tool",
        "tool_call_id": call.id,
        "content": json.dumps(output),
    })
```

### Current Limitations of Multi-turn Tool Use

Multi-turn tool use is currently not supported with the `llama-3.3-70b` model. This model will error if you include a non-empty `tool_calls` array on an assistant turn.

For `llama-3.3-70b`, make sure your assistant response explicitly clears its `tool_calls` like this:

```python
{
  "role": "assistant",
  "content": "Here's the current temperature in Paris: 18°C",
  "tool_calls": []
}
```

Then append your "role": "tool" message containing the function output:

```python
{
  "role": "tool",
  "tool_call_id": "abc123",
  "content": "Paris temperature is 18°C"
}
```

## Conclusion

Tool use is an important feature that extends the capabilities of LLMs by allowing them to access pre-defined tools. Here are some more resources to continue learning about tool use with the Cerebras Inference SDK.

* [API Reference](/api-reference/chat-completions)
* [AI Agent Bootcamp: Tool Use & Function Calling](/agent-bootcamp/section-2)
* [Using Structured Outputs](/capabilities/structured-outputs)



# Tool Use and Function Calling

## Introduction

As we explored in the [previous section](/agent-bootcamp/section-1), large language model (LLM) applications can be significantly improved using the various components of agentic workflows. The first of these components that we’ll explore is tool use, which enables LLMs to perform more complex tasks than just text processing. 

In the context of AI agents, a tool is any external resource or capability that augments the core functionality of the LLM. Most often, the types of tools you’ll encounter when building AI agents will be through a method called function calling, a subset of tool use that allows the LLM to invoke predefined functions with specific parameters that can perform calculations, retrieve data, or execute actions that the model itself cannot directly carry out. 

To illustrate the value of tool use and function calling, let's consider a financial analyst tasked with comparing the [moving averages](https://www.investopedia.com/terms/m/movingaverage.asp) of two companies' stock prices. 

Without function calling capabilities, an LLM would have limited value to an analyst, facing significant challenges in performing detailed analysis. LLMs lack access to real-time or historical stock price data, making it difficult to work with up-to-date information. While they can explain concepts like moving averages and guide users through calculations, they aren't reliable for precise mathematical operations. Additionally, due to their probabilistic nature, the results provided by an LLM for complex calculations can be inconsistent or inaccurate.

Tool choice and function calling address these limitations by allowing the LLM to:

* Request specific stock data for the companies in question.

* Invoke a dedicated function that accurately calculates the moving average.

* Consistently produce precise results based on the provided data and specified parameters.

By utilizing a tool that performs an exact calculation of the moving average, the LLM can provide more reliable answers to the analyst. Using this very example, let’s build an AI agent with tool use capabilities to better understand the concept. 

## Initial Setup

Before diving into building our tools, let’s begin by initializing the Cerebras Inference SDK. Note, if this is your first time using our SDK, please visit our [QuickStart guide](/quickstart) for details on installation and obtaining API keys. 

```Python
from cerebras.cloud.sdk import Cerebras

client = Cerebras(
    api_key=os.environ.get("CEREBRAS_API_KEY"),
)
```

For the sake of simplicity, in this section we will only build out a tool for calculating the moving average of stocks. We will handle the data loading step by simply using local JSON files. Note that in a production environment, this could have also been done by creating a tool that fetched real-time stock data from a financial API. 

```Python
import json

with open("company_a.json") as f:
    company_a_data = json.load(f)

with open("company_b.json") as f:
    company_b_data = json.load(f)

available_data = {
    "company_a": company_a_data,
    "company_b": company_b_data,
}
```

## Creating a Moving Average Calculator Tool

Now that we have initialized our client and have some data to work with, let’s build our first tool: a function that our LLM can call to calculate the moving average of a stock.

We’ll name our function `calculate_moving_average`. It computes the moving average of stock prices over a specified period. It first validates the input parameters and retrieves the relevant stock data. The function then iterates through the data, maintaining a sliding window of stock prices. For each day after the initial window, it calculates the average price within the window, rounds it to two decimal places, and stores the result along with the corresponding date. This process continues until it has processed the specified number of days, resulting in a list of moving averages.

```Python
def calculate_moving_average(
    data_reference: str, num_days: int, window_size: int
) -> list[dict[str, float]]:
    if data_reference not in available_data:
        raise ValueError(f"Invalid data reference. Available options: {list(available_data.keys())}")
    
    stock_data = available_data[data_reference]
    
    if num_days < window_size:
        raise ValueError("num_days must be greater than or equal to window_size")

    if len(stock_data) < num_days:
        raise ValueError("Insufficient data for the specified number of days")

    recent_data: list[dict[str, float]] = stock_data[-num_days:]
    moving_averages: list[dict[str, float]] = []
    price_window: list[float] = [
        float(item["closingPrice"]) for item in recent_data[:window_size]
    ]

    for i in range(window_size, num_days):
        current_data = recent_data[i]
        current_price = float(current_data["closingPrice"])

        price_window.append(current_price)
        price_window.pop(0)
        average = round(sum(price_window) / window_size, 2)

        moving_averages.append({"date": current_data["date"], "movingAverage": average})

    return moving_averages
```

## Tool Schema

In addition to our `calculate_moving_average` tool, we need to [create a schema](https://json-schema.org/docs) which provides context on when and how it can be used. You can think of the tool schema as a user manual for your AI agent. The more precise and informative your schema, the better equipped the AI becomes at determining when to utilize your tool and how to construct appropriate arguments. You can provide the schema to the Cerebras Inference API through the tools parameter, as described in the [Tool Use section](https://inference-docs.cerebras.ai/tool-use) of the API documentation.

The schema is composed of three components: the `name` of the tool, a `description` of the tool, and what `parameters` it accepts.

For our schema, we'll use Pydantic to ensure type safety and simplify input validation before passing them to the function. This approach reduces the risk of errors that can arise from manually writing JSON schemas and keeps parameter definitions closely aligned with their usage in the code.

```Python
from pydantic import BaseModel, Field
from typing import Literal

class CalculateMovingAverageArgs(BaseModel):
    data_reference: Literal["company_a", "company_b"] = Field(..., description="The key to access specific stock data in the stock_data dictionary.")
    num_days: int = Field(..., description="The number of recent days to consider for calculation.")
    window_size: int = Field(..., description="The size of the moving average window.")

tools = [
    {
        "type": "function",
        "function": {
            "name": "calculate_moving_average",
            "description": "Calculate the moving average of stock data for a specified number of recent days.",
            "parameters": CalculateMovingAverageArgs.model_json_schema(),
        },
    }
]
```

## Integrating Tools Into the Workflow

Now that we have defined our `calculate_moving_average` function and created the corresponding tool schema, we need to integrate these components into our AI agent's workflow. The next step is to set up the messaging structure and create a chat completion request using the Cerebras Inference SDK. This involves all of the standard components that comprise a chat completion request, including crafting an initial system message and the user's query. We'll then pass these messages along with our defined tools to the chat completion method. This setup allows the AI to understand the context, interpret the user's request, and determine when and how to utilize the `calculate_moving_average` function to provide accurate responses.

```Python
messages = [
    {"role": "system", "content": "You are a helpful financial analyst. Use the supplied tools to assist the user."},
    {"role": "user", "content": "What's the 10-day moving average for company A over the last 50 days?"},
]

response = llm.chat.completions.create(
    model="llama-3.3-70b",
    messages=messages,
    tools=tools,
)
```

Once the LLM receives the request, it makes a determination as to whether or not it can answer the query without additional data or computations. If so, it provides a text-based reply, just like it would with any other request. This is typically the case for general knowledge questions or queries that don't require the use of tools. In our code, we first check to see if the model responded in this way. If so, we print out the content.

```Python
content = response.choices[0].message.content
if content:
    print(content)
```

In cases where the LLM recognizes that answering the query requires specific data or calculations beyond its inherent capabilities, it opts for a function call.

We handle this by checking for a function call, similar to how we checked for a text response. When a function call is detected, the code extracts the function arguments, parses them, and executes the corresponding function.

```Python
function_call = response.choices[0].message.tool_calls[0].function
if function_call.name == "calculate_moving_average":
    arguments = json.loads(function_call.arguments)
    result = calculate_moving_average(**arguments)
```

## Conclusion

Tool use and function calling significantly enhance the capabilities of large language models, enabling them to perform complex tasks beyond their core text processing abilities. As demonstrated in our financial analysis example, integrating tools allows LLMs to perform precise calculations, and provide more reliable and accurate responses to user queries.

Our workflow in this example was a simple one, but it can be applied to most tool use scenarios.

1. Defining the tool function (in our case, calculate\_moving\_average) and create a corresponding tool schema that clearly outlines its purpose and parameters.

2. Make a chat completion request, including the defined tools alongside the user's query and any system messages.

3. Handle the LLM's response, which may be either a text-based reply or a function call.

4. If a function call is made, execute the specified function with the provided arguments and process the results.

We now know how tool use and function calling extend the capabilities of AI agents. In subsequent sections, we’ll explore how we can do even more with tool use, such as:

* Multistep tool use, where the LLM chains together multiple function calls to solve more complex problems.

* Parallel tool use, allowing the model to decide for itself which functions are appropriate for the given task for increased flexibility



# Chat Completions

<ParamField path="messages" type="object[]" required="true">
  A list of messages comprising the conversation so far.

  **Note**: System prompts must be passed to the `messages` parameter as a string. Support for other object types will be added in future releases.
</ParamField>

<ParamField path="model" type="string" required="true">
  Available options:

  * `llama-4-scout-17b-16e-instruct`
  * `llama3.1-8b`
  * `llama-3.3-70b`
  * `llama-4-maverick-17b-128e-instruct` (preview)
  * `qwen-3-32b`
  * `qwen-3-235b-a22b-instruct-2507` (preview)
  * `qwen-3-235b-a22b-thinking-2507` (preview)
  * `qwen-3-coder-480b` (preview)
  * `gpt-oss-120b` (preview)
  * `deepseek-r1-distill-llama-70b`	(to be deprecated August 12, 2025)

  <Note>
    `deepseek-r1-distill-llama-70b` are available in private preview. Please [contact us](https://cerebras.ai/contact) to request access.
  </Note>
</ParamField>

<ParamField path="max_completion_tokens" type="integer | null">
  The maximum number of **tokens** that can be generated in the completion. The total length of input tokens and generated tokens is limited by the model's context length.
</ParamField>

<ParamField path="response_format" type="object | null">
  Controls the format of the model response. The primary option is structured outputs with schema enforcement, which ensures the model returns valid JSON adhering to your defined schema structure.

  Setting to `{ "type": "json_schema", "json_schema": { "name": "schema_name", "strict": true, "schema": {...} } }` enforces schema compliance. The schema must follow standard JSON Schema format with the following properties:

  <Expandable title="json_schema properties">
    <ParamField path="response_format.json_schema.name" type="string">
      An optional name for your schema.
    </ParamField>

    <ParamField path="response_format.json_schema.strict" type="boolean">
      When set to `true`, enforces strict adherence to the schema. The model will only return fields defined in the schema and with the correct types. When `false`, behaves similar to JSON mode but uses the schema as a guide.
    </ParamField>

    <ParamField path="response_format.json_schema.schema" type="object">
      A valid JSON Schema object that defines the structure, types, and requirements for the response. Supports standard JSON Schema features including types (string, number, boolean, integer, object, array, enum, anyOf, null), nested structures (up to 5 layers), required fields, and additionalProperties (must be set to false).
    </ParamField>
  </Expandable>

  Note: Structured outputs with JSON schema is currently in beta. Visit our page on [Structured Outputs](/capabilities/structured-outputs) for more information.

  <Expandable title="JSON mode">
    Alternatively, setting to `{ "type": "json_object" }` enables simple JSON mode, which ensures that the response is either a valid JSON object or an error response without enforcing a specific schema structure.

    Note that enabling JSON mode does not guarantee the model will successfully generate valid JSON. The model may fail to generate valid JSON due to various reasons such as incorrect formatting, missing or mismatched brackets, or exceeding the length limit.

    In cases where the model fails to generate valid JSON, the error response will be a valid JSON object with a key failed\_generation containing the string representing the invalid JSON. This allows you to re-submit the request with additional prompting to correct the issue. The error response will have a `400` server error status code.

    Note that JSON mode is not compatible with streaming. `"stream"` must be set to `false`.

    Important: When using JSON mode, you need to explicitly instruct the model to generate JSON through a system or user message.
  </Expandable>
</ParamField>

<ParamField path="reasoning_effort" type="string | null">
  Controls the amount of reasoning the model performs. Available values:

  * `"low"` - Minimal reasoning, faster responses
  * `"medium"` - Moderate reasoning (default)
  * `"high"` - Extensive reasoning, more thorough analysis
  * `"none"` - No explicit reasoning effort specified (model-dependent default)

  The default value depends on the specific model being used. For example, `none` will be treated as `medium` for `gpt-oss-120b`.

  <Note>This flag is only available for [gpt-oss-120b\`](/models/openai-oss) model. </Note>
</ParamField>

<ParamField path="seed" type="integer | null">
  If specified, our system will make a best effort to sample deterministically, such that repeated requests with the same `seed` and parameters should return the same result. Determinism is not guaranteed.
</ParamField>

<ParamField path="stop" type="string | null">
  Up to 4 sequences where the API will stop generating further tokens. The returned text will not contain the stop sequence.
</ParamField>

<ParamField path="stream" type="boolean | null">
  If set, partial message deltas will be sent.
</ParamField>

<ParamField path="temperature" type="number | null">
  What sampling temperature to use, between 0 and 1.5. Higher values like 0.8 will make the output more random, while lower values like 0.2 will make it more focused and deterministic. We generally recommend altering this or top\_p but not both.
</ParamField>

<ParamField path="top_p" type="number | null">
  An alternative to sampling with temperature, called nucleus sampling, where the model considers the results of the tokens with top\_p probability mass. So, 0.1 means only the tokens comprising the top 10% probability mass are considered. We generally recommend altering this or temperature but not both.
</ParamField>

<ParamField path="tool_choice" type="string | object">
  Controls which (if any) tool is called by the model. `none` means the model will not call any tool and instead generates a message. `auto` means the model can pick between generating a message or calling one or more tools. required means the model must call one or more tools. Specifying a particular tool via `{"type": "function", "function": {"name": "my_function"}}` forces the model to call that tool.

  `none` is the default when no tools are present. `auto` is the default if tools are present.
</ParamField>

<ParamField path="tools" type="object | null">
  A list of tools the model may call. Currently, only functions are supported as a tool. Use this to provide a list of functions the model may generate JSON inputs for.

  Specifying tools consumes prompt tokens in the context. If too many are given, the model may perform poorly or you may hit context length limitations

  <Expandable title="properties">
    <ParamField path="tools.function.description" type="string">
      A description of what the function does, used by the model to choose when and how to call the function.
    </ParamField>

    <ParamField path="tools.function.name" type="string">
      The name of the function to be called. Must be a-z, A-Z, 0-9, or contain underscores and dashes, with a maximum length of 64.
    </ParamField>

    <ParamField path="tools.function.parameters" type="object">
      The parameters the functions accepts, described as a JSON Schema object. Omitting parameters defines a function with an empty parameter list.
    </ParamField>

    <ParamField path="tools.type" type="string">
      The type of the tool. Currently, only `function` is supported.
    </ParamField>
  </Expandable>
</ParamField>

<ParamField path="user" type="string | null">
  A unique identifier representing your end-user, which can help to monitor and detect abuse.
</ParamField>

<ParamField path="logprobs" type="bool">
  Whether to return log probabilities of the output tokens or not.

  Default: `False`
</ParamField>

<ParamField path="top_logprobs" type="integer | null">
  An integer between 0 and 20 specifying the number of most likely tokens to return at each token position, each with an associated log probability.
  `logprobs` must be set to true if this parameter is used.
</ParamField>

<RequestExample>
  ```python Python
  from cerebras.cloud.sdk import Cerebras
  import os 

  client = Cerebras(api_key=os.environ.get("CEREBRAS_API_KEY"),)

  chat_completion = client.chat.completions.create(
      model="llama3.1-8b",
      messages=[
          {"role": "user", "content": "Hello!",}
      ],
  )
  print(chat_completion)
  ```

  ```javascript Node.js
  import Cerebras from '@cerebras/cerebras_cloud_sdk';

  const client = new Cerebras({
    apiKey: process.env['CEREBRAS_API_KEY'],
  });

  async function main() {
    const completionCreateResponse = await client.chat.completions.create({
      messages: [{ role: 'user', content: 'Hello!' }],
      model: 'llama3.1-8b',
    });

    console.log(completionCreateResponse);
  }
  main();
  ```

  ```cli cURL
  curl --location 'https://api.cerebras.ai/v1/chat/completions' \
  --header 'Content-Type: application/json' \
  --header "Authorization: Bearer ${CEREBRAS_API_KEY}" \
  --data '{
    "model": "llama3.1-8b",
    "stream": false,
    "messages": [{"content": "Hello!", "role": "user"}],
    "temperature": 0,
    "max_completion_tokens": -1,
    "seed": 0,
    "top_p": 1
  }'
  ```
</RequestExample>

<ResponseExample>
  ```json Response
  {
    "id": "chatcmpl-292e278f-514e-4186-9010-91ce6a14168b",
    "choices": [
      {
        "finish_reason": "stop",
        "index": 0,
        "message": {
          "content": "Hello! How can I assist you today?",
          "reasoning": "The user is asking for a simple greeting to the world. This is a straightforward request that doesn't require complex analysis. I should provide a friendly, direct response.",
          "role": "assistant"
      
        }
      }
    ],
    "created": 1723733419,
    "model": "llama3.1-8b",
    "system_fingerprint": "fp_70185065a4",
    "object": "chat.completion",
    "usage": {
      "prompt_tokens": 12,
      "completion_tokens": 10,
      "total_tokens": 22
    },
    "time_info": {
      "queue_time": 0.000073161,
      "prompt_time": 0.0010744798888888889,
      "completion_time": 0.005658071111111111,
      "total_time": 0.022224903106689453,
      "created": 1723733419
    }
  }
  ```
</ResponseExample>



