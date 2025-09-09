Web Search

Some models and systems on Groq have native support for access to real-time web content, allowing them to answer questions with up-to-date information beyond their knowledge cutoff. API responses automatically include citations with a complete list of all sources referenced from the search results.

The use of this tool with a supported model in GroqCloud is not a HIPAA Covered Cloud Service under Groq's Business Associate Addendum at this time. This tool is also not available currently for use with regional / sovereign endpoints.
Supported Models

Built-in web search is supported for the following models and systems:
Model ID	Model
groq/compound
Compound
groq/compound-mini
Compound Mini

For a comparison between the groq/compound and groq/compound-mini systems and more information regarding extra capabilities, see the Compound Systems page.
Quick Start

To use web search, change the model parameter to one of the supported models.

from groq import Groq
import json

client = Groq()

response = client.chat.completions.create(
    model="groq/compound",
    messages=[
        {
            "role": "user",
            "content": "What happened in AI last week? Provide a list of the most important model releases and updates."
        }
    ]
)

# Final output
print(response.choices[0].message.content)

# Reasoning + internal tool calls
print(response.choices[0].message.reasoning)

# Search results from the tool calls
if response.choices[0].message.executed_tools:
    print(json.dumps(response.choices[0].message.executed_tools[0].search_results, indent=2))

And that's it!

When the API is called, it will intelligently decide when to use search to best answer the user's query. These tool calls are performed on the server side, so no additional setup is required on your part to use built-in tools.
Final Output

This is the final response from the model, containing the synthesized answer based on web search results. The model combines information from multiple sources to provide a comprehensive response with automatic citations. Use this as the primary output for user-facing applications.

Reasoning and Internal Tool Calls

This shows the model's internal reasoning process and the search queries it executed to gather information. You can inspect this to understand how the model approached the problem and what search terms it used. This is useful for debugging and understanding the model's decision-making process.

Search Results

These are the raw search results that the model retrieved from the web, including titles, URLs, content snippets, and relevance scores. You can use this data to verify sources, implement custom citation systems, or provide users with direct links to the original content. Each result includes a relevance score from 0 to 1.

Search Settings

Customize web search behavior by using the search_settings parameter. This parameter allows you to exclude specific domains from search results or restrict searches to only include specific domains. These parameters are supported for both groq/compound and groq/compound-mini.
Parameter	Type	Description
exclude_domains	string[]	List of domains to exclude when performing web searches. Supports wildcards (e.g., "*.com")
include_domains	string[]	Restrict web searches to only search within these specified domains. Supports wildcards (e.g., "*.edu")
country	string	Boost search results from a specific country. This will prioritize content from the selected country in the search results.

Domain Filtering with Wildcards

Both include_domains and exclude_domains support wildcard patterns using the * character. This allows for flexible domain filtering:

    Use *.com to include/exclude all .com domains
    Use *.edu to include/exclude all educational institutions
    Use specific domains like example.com to include/exclude exact matches

You can combine both parameters to create precise search scopes. For example:

    Include only .com domains while excluding specific sites
    Restrict searches to specific country domains
    Filter out entire categories of websites

Search Settings Examples
shell

curl "https://api.groq.com/openai/v1/chat/completions" \
  -X POST \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${GROQ_API_KEY}" \
  -d '{
         "messages": [
           {
             "role": "user",
             "content": "Tell me about the history of Bonsai trees in America"
           }
         ],
         "model": "groq/compound-mini",
         "search_settings": {
           "exclude_domains": ["wikipedia.org"]
         }
       }'

Pricing

Please see the Pricing page for more information.

There are two types of web search: basic search and advanced search, and these are billed differently.
Basic Search

A more basic, less comprehensive version of search that provides essential web search capabilities. Basic search is supported on Compound version 2025-07-23. To use basic search, specify the version in your API request. See Compound System Versioning for details on how to set your Compound version.
Advanced Search

The default search experience that provides more comprehensive and intelligent search results. Advanced search is automatically used with Compound versions newer than 2025-07-23 and offers enhanced capabilities for better information retrieval and synthesis.
Provider Information

Web search functionality is powered by Tavily, a search API optimized for AI applications. Tavily provides real-time access to web content with intelligent ranking and citation capabilities specifically designed for language models.


Browser Search

Some models on Groq have built-in support for interactive browser search, providing a more comprehensive approach to accessing real-time web content than traditional web search. Unlike Web Search which performs a single search and retrieves text snippets from webpages, Browser Search mimics human browsing behavior by navigating websites interactively, providing more detailed results.

For latency sensitive use cases, we recommend using Web Search instead.

The use of this tool with a supported model in GroqCloud is not a HIPAA Covered Cloud Service under Groq's Business Associate Addendum at this time. This tool is also not available currently for use with regional / sovereign endpoints.
Supported Models

Built-in browser search is supported for the following models:
Model ID	Model
openai/gpt-oss-20b
OpenAI GPT-OSS 20B
openai/gpt-oss-120b
OpenAI GPT-OSS 120B

Note: Browser search is not compatible with structured outputs.
Quick Start

To use browser search, change the model parameter to one of the supported models.

from groq import Groq

client = Groq()

chat_completion = client.chat.completions.create(
    messages=[
        {
            "role": "user", 
            "content": "What happened in AI last week? Give me a concise, one paragraph summary of the most important events."
        }
    ],
    model="openai/gpt-oss-20b",
    temperature=1,
    max_completion_tokens=2048,
    top_p=1,
    stream=False,
    stop=None,
    tool_choice="required",
    tools=[
        {
            "type": "browser_search"
        }
    ]
)

print(chat_completion.choices[0].message.content)

When the API is called, it will use browser search to best answer the user's query. This tool call is performed on the server side, so no additional setup is required on your part to use this feature.
Final Output

This is the final response from the model, containing snippets from the web pages that were searched, and the final response at the end. The model combines information from multiple sources to provide a comprehensive response.

Pricing

Please see the Pricing page for more information.
Best Practices

When using browser search with reasoning models, consider setting reasoning_effort to low to optimize performance and token usage. Higher reasoning effort levels can result in extended browser sessions with more comprehensive web exploration, which may consume significantly more tokens than necessary for most queries. Using low reasoning effort provides a good balance between search quality and efficiency.
Provider Information

Browser search functionality is powered by Exa, a search engine designed for AI applications. Exa provides comprehensive web browsing capabilities that go beyond traditional search by allowing models to navigate and interact with web content in a more human-like manner.


Visit Website

Some models and systems on Groq have native support for visiting and analyzing specific websites, allowing them to access current web content and provide detailed analysis based on the actual page content. This tool enables models to retrieve and process content from any publicly accessible website.

The use of this tool with a supported model in GroqCloud is not a HIPAA Covered Cloud Service under Groq's Business Associate Addendum at this time. This tool is also not available currently for use with regional / sovereign endpoints.
Supported Models

Built-in website visiting is supported for the following models and systems (on versions later than 2025-07-23):
Model ID	Model
groq/compound
Compound
groq/compound-mini
Compound Mini

For a comparison between the groq/compound and groq/compound-mini systems and more information regarding extra capabilities, see the Compound Systems page.
Quick Start

To use website visiting, simply include a URL in your request to one of the supported models. The examples below show how to access all parts of the response: the final content, reasoning process, and tool execution details.

import json
from groq import Groq

client = Groq(
    default_headers={
        "Groq-Model-Version": "latest"
    }
)

chat_completion = client.chat.completions.create(
    messages=[
        {
            "role": "user",
            "content": "Summarize the key points of this page: https://groq.com/blog/inside-the-lpu-deconstructing-groq-speed",
        }
    ],
    model="groq/compound",
)

message = chat_completion.choices[0].message

# Print the final content
print(message.content)

# Print the reasoning process
print(message.reasoning)

# Print executed tools
if message.executed_tools:
    print(message.executed_tools[0])

These examples show how to access the complete response structure to understand the website visiting process.

When the API is called, it will automatically detect URLs in the user's message and visit the specified website to retrieve its content. The response includes three key components:

    Content: The final synthesized response from the model
    Reasoning: The internal decision-making process showing the website visit
    Executed Tools: Detailed information about the website that was visited

How It Works

When you include a URL in your request:

    URL Detection: The system automatically detects URLs in your message
    Website Visit: The tool fetches the content from the specified website
    Content Processing: The website content is processed and made available to the model
    Response Generation: The model uses both your query and the website content to generate a comprehensive response

Final Output

This is the final response from the model, containing the analysis based on the visited website content. The model can summarize, analyze, extract specific information, or answer questions about the website's content.

		
		
		
		
		
		

Reasoning and Internal Tool Calls

This shows the model's internal reasoning process and the website visit it executed to gather information. You can inspect this to understand how the model approached the problem and what URL it accessed. This is useful for debugging and understanding the model's decision-making process.

Tool Execution Details

This shows the details of the website visit operation, including the type of tool executed and the content that was retrieved from the website.

Usage Tips

    Single URL per Request: Only one website will be visited per request. If multiple URLs are provided, only the first one will be processed.
    Publicly Accessible Content: The tool can only visit publicly accessible websites that don't require authentication.
    Content Processing: The tool automatically extracts the main content while filtering out navigation, ads, and other non-essential elements.
    Real-time Access: Each request fetches fresh content from the website at the time of the request, rendering the full page to capture dynamic content.

Pricing

Please see the Pricing page for more information about costs.


Browser Automation

Some models and systems on Groq have native support for advanced browser automation, allowing them to launch and control up to 10 browsers simultaneously to gather comprehensive information from multiple sources. This powerful tool enables parallel web research, deeper analysis, and richer evidence collection.

The use of this tool with a supported model in GroqCloud is not a HIPAA Covered Cloud Service under Groq's Business Associate Addendum at this time. This tool is also not available currently for use with regional / sovereign endpoints.
Supported Models

Browser automation is supported for the following models and systems (on versions later than 2025-07-23):
Model ID	Model
groq/compound
Compound
groq/compound-mini
Compound Mini

For a comparison between the groq/compound and groq/compound-mini systems and more information regarding extra capabilities, see the Compound Systems page.
Quick Start

To use browser automation, you must enable both browser_automation and web_search tools in your request to one of the supported models. The examples below show how to access all parts of the response: the final content, reasoning process, and tool execution details.

import json
from groq import Groq

client = Groq(
    default_headers={
        "Groq-Model-Version": "latest"
    }
)

chat_completion = client.chat.completions.create(
    messages=[
        {
            "role": "user",
            "content": "What are the latest models on Groq and what are they good at?",
        }
    ],
    model="groq/compound-mini",
    compound_custom={
        "tools": {
            "enabled_tools": ["browser_automation", "web_search"]
        }
    }
)

message = chat_completion.choices[0].message

# Print the final content
print(message.content)

# Print the reasoning process
print(message.reasoning)

# Print executed tools
if message.executed_tools:
    print(message.executed_tools[0])

These examples show how to enable browser automation to get deeper search results through parallel browser control.

When the API is called with browser automation enabled, it will launch multiple browsers to gather comprehensive information. The response includes three key components:

    Content: The final synthesized response from the model based on all browser sessions
    Reasoning: The internal decision-making process showing browser automation steps
    Executed Tools: Detailed information about the browser automation sessions and web searches

How It Works

When you enable browser automation:

    Tool Activation: Both browser_automation and web_search tools are enabled in your request. Browser automation will not work without both tools enabled.
    Parallel Browser Launch: Up to 10 browsers are launched simultaneously to search different sources
    Deep Content Analysis: Each browser navigates and extracts relevant information from multiple pages
    Evidence Aggregation: Information from all browser sessions is combined and analyzed
    Response Generation: The model synthesizes findings from all sources into a comprehensive response

Final Output

This is the final response from the model, containing analysis based on information gathered from multiple browser automation sessions. The model can provide comprehensive insights, multi-source comparisons, and detailed analysis based on extensive web research.

		
		
		

	
	
	
	
	

Reasoning and Internal Tool Calls

This shows the model's internal reasoning process and the browser automation sessions it executed to gather information. You can inspect this to understand how the model approached the problem, which browsers it launched, and what sources it accessed. This is useful for debugging and understanding the model's research methodology.

Tool Execution Details

This shows the details of the browser automation operations, including the type of tools executed, browser sessions launched, and the content that was retrieved from multiple sources simultaneously.

JSON
JSON

{
  "index": 2,
  "type": "browser_automation",
  "arguments": "",
  "output": "Page content analyzed: Found matches for 'groq':
# 【0†match at L2】
[Groq Cloud](/)

[](/)

# 【1†match at L12】
Join 2M+ developers building on GroqCloud™

We deliver inference with unmatched speed and cost, so you can ship fast.

# 【2†match at L26】
that I have read the [Privacy Policy](https://groq.com/privacy-policy).

The Models

Found matches for 'models':
# 【0†match at L28】
The Models

[![OpenAI](/_next/static/media/openailogo.523c87a0.svg) OpenAI GPT-OSS (20B &

# 【1†match at L31】
120B) models now available for instant inference. These models have built-in
browser search and code execution capabilities. Learn about
GPT-OSS](/docs/models#featured-models)

# 【2†match at L151】
We're adding new models all the time and will let you know when a new one comes
online.
See full details on our [Models page.](/docs/models)",
  "search_results": {
      "results": []
  }
}

Pricing

Please see the Pricing page for more information about costs.
Provider Information

Browser automation functionality is powered by Anchor Browser, a browser automation platform built for AI agents.
Was this page helpful?
On this page

    Supported Models
    Quick Start
    How It Works
    Pricing


Code Execution

Some models and systems on Groq have native support for automatic code execution, allowing them to perform calculations, run code snippets, and solve computational problems in real-time.

Only Python is currently supported for code execution.

The use of this tool with a supported model in GroqCloud is not a HIPAA Covered Cloud Service under Groq's Business Associate Addendum at this time. This tool is also not available currently for use with regional / sovereign endpoints.
Supported Models

Built-in code execution is supported for the following models and systems:
Model ID	Model
openai/gpt-oss-20b
OpenAI GPT-OSS 20B
openai/gpt-oss-120b
OpenAI GPT-OSS 120B
groq/compound
Compound
groq/compound-mini
Compound Mini

For a comparison between the groq/compound and groq/compound-mini systems and more information regarding extra capabilities, see the Compound Systems page.
Quick Start (Compound)

To use code execution with Groq's Compound systems, change the model parameter to one of the supported models or systems.

import os
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

response = client.chat.completions.create(
    messages=[
        {
            "role": "user",
            "content": "Calculate the square root of 101 and show me the Python code you used",
        }
    ],
    model="groq/compound-mini",
)

# Final output
print(response.choices[0].message.content)

# Reasoning + internal tool calls
print(response.choices[0].message.reasoning)

# Code execution tool call
if response.choices[0].message.executed_tools:
    print(response.choices[0].message.executed_tools[0])

And that's it!

When the API is called, it will intelligently decide when to use code execution to best answer the user's query. Code execution is performed on the server side in a secure sandboxed environment, so no additional setup is required on your part.
Final Output

This is the final response from the model, containing the answer based on code execution results. The model combines computational results with explanatory text to provide a comprehensive response. Use this as the primary output for user-facing applications.

Reasoning and Internal Tool Calls

This shows the model's internal reasoning process and the Python code it executed to solve the problem. You can inspect this to understand how the model approached the computational task and what code it generated. This is useful for debugging and understanding the model's decision-making process.

Executed Tools Information

This contains the raw executed tools data, including the generated Python code, execution output, and metadata. You can use this to access the exact code that was run and its results programmatically.

Quick Start (GPT-OSS)

To use code execution with OpenAI's GPT-OSS models on Groq (20B & 120B), add the code_interpreter tool to your request.

from groq import Groq

client = Groq(api_key="your-api-key-here")

response = client.chat.completions.create(
    messages=[
        {
            "role": "user",
            "content": "Calculate the square root of 12345. Output only the final answer.",
        }
    ],
    model="openai/gpt-oss-20b",  # or "openai/gpt-oss-120b"
    tool_choice="required",
    tools=[
        {
            "type": "code_interpreter"
        }
    ],
)

# Final output
print(response.choices[0].message.content)

# Reasoning + internal tool calls
print(response.choices[0].message.reasoning)

# Code execution tool call
print(response.choices[0].message.executed_tools[0])

When the API is called, it will use code execution to best answer the user's query. Code execution is performed on the server side in a secure sandboxed environment, so no additional setup is required on your part.
Final Output

This is the final response from the model, containing the answer based on code execution results. The model combines computational results with explanatory text to provide a comprehensive response.

Reasoning and Internal Tool Calls

This shows the model's internal reasoning process and the Python code it executed to solve the problem. You can inspect this to understand how the model approached the computational task and what code it generated.

Executed Tools Information

This contains the raw executed tools data, including the generated Python code, execution output, and metadata. You can use this to access the exact code that was run and its results programmatically.

How It Works

When you make a request to a model or system that supports code execution, it:

    Analyzes your query to determine if code execution would be helpful (for compound systems or when tool choice is not set to required)
    Generates Python code to solve the problem or answer the question
    Executes the code in a secure sandboxed environment powered by E2B
    Returns the results along with the code that was executed

Use Cases (Compound)
Mathematical Calculations

Ask the model to perform complex calculations, and it will automatically execute Python code to compute the result.

import os
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

chat_completion = client.chat.completions.create(
    messages=[
        {
            "role": "user",
            "content": "Calculate the monthly payment for a $30,000 loan over 5 years at 6% annual interest rate using the standard loan payment formula. Use python code.",
        }
    ],
    model="groq/compound-mini",
)

print(chat_completion.choices[0].message.content)

Code Debugging and Testing

Provide code snippets to check for errors or understand their behavior. The model can execute the code to verify functionality.

import os
from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

chat_completion = client.chat.completions.create(
    messages=[
        {
            "role": "user",
            "content": "Will this Python code raise an error? `import numpy as np; a = np.array([1, 2]); b = np.array([3, 4, 5]); print(a + b)`",
        }
    ],
    model="groq/compound-mini",
)

print(chat_completion.choices[0].message.content)

Security and Limitations

    Code execution runs in a secure sandboxed environment with no access to external networks or sensitive data
    Only Python is currently supported for code execution
    The execution environment is ephemeral - each request runs in a fresh, isolated environment
    Code execution has reasonable timeout limits to prevent infinite loops
    No persistent storage between requests

Pricing

Please see the Pricing page for more information.
Provider Information

Code execution functionality is powered by E2B, a secure cloud environment for AI code execution. E2B provides isolated, ephemeral sandboxes that allow models to run code safely without access to external networks or sensitive data.

Wolfram‑Alpha Integration

Some models and systems on Groq have native support for Wolfram‑Alpha integration, allowing them to access Wolfram's computational knowledge engine for mathematical, scientific, and engineering computations. This tool enables models to solve complex problems that require precise calculation and access to structured knowledge.

The use of this tool with a supported model in GroqCloud is not a HIPAA Covered Cloud Service under Groq's Business Associate Addendum at this time. This tool is also not available currently for use with regional / sovereign endpoints.
Supported Models

Wolfram‑Alpha integration is supported for the following models and systems (on versions later than 2025-07-23):
Model ID	Model
groq/compound
Compound
groq/compound-mini
Compound Mini

For a comparison between the groq/compound and groq/compound-mini systems and more information regarding extra capabilities, see the Compound Systems page.
Quick Start

To use Wolfram‑Alpha integration, you must provide your own Wolfram‑Alpha API key in the wolfram_settings configuration. The examples below show how to access all parts of the response: the final content, reasoning process, and tool execution details.

import json
from groq import Groq

client = Groq(
    default_headers={
        "Groq-Model-Version": "latest"
    }
)

chat_completion = client.chat.completions.create(
    messages=[
        {
            "role": "user",
            "content": "What is 1293392*29393?",
        }
    ],
    model="groq/compound",
    compound_custom={
        "tools": {
            "enabled_tools": ["wolfram_alpha"],
            "wolfram_settings": {"authorization": "your_wolfram_alpha_api_key_here"}
        }
    }
)

message = chat_completion.choices[0].message

# Print the final content
print(message.content)

# Print the reasoning process
print(message.reasoning)

# Print executed tools
if message.executed_tools:
    print(message.executed_tools[0])

These examples show how to access the complete response structure to understand the Wolfram‑Alpha computation process.

When the API is called with a mathematical or scientific query, it will automatically use Wolfram‑Alpha to compute precise results. The response includes three key components:

    Content: The final synthesized response from the model with computational results
    Reasoning: The internal decision-making process showing the Wolfram‑Alpha query
    Executed Tools: Detailed information about the computation that was performed

How It Works

When you ask a computational question:

    Query Analysis: The system analyzes your question to determine if Wolfram‑Alpha computation is needed
    Wolfram‑Alpha Query: The tool sends a structured query to Wolfram‑Alpha's computational engine
    Result Processing: The computational results are processed and made available to the model
    Response Generation: The model uses both your query and the computational results to generate a comprehensive response

Final Output

This is the final response from the model, containing the computational results and analysis. The model can provide step-by-step solutions, explanations, and contextual information about the mathematical or scientific computation.

Reasoning and Internal Tool Calls

This shows the model's internal reasoning process and the Wolfram‑Alpha computation it executed to solve the problem. You can inspect this to understand how the model approached the problem and what specific query it sent to Wolfram‑Alpha.

Tool Execution Details

This shows the details of the Wolfram‑Alpha computation, including the type of tool executed, the query that was sent, and the computational results that were retrieved.

Usage Tips

    API Key Required: You must provide your own Wolfram‑Alpha API key in the wolfram_settings.authorization field to use this feature.
    Mathematical Queries: Best suited for mathematical computations, scientific calculations, unit conversions, and factual queries.
    Structured Data: Wolfram‑Alpha returns structured computational results that the model can interpret and explain.
    Complex Problems: Ideal for problems requiring precise computation that go beyond basic arithmetic.

Getting Your Wolfram‑Alpha API Key

To use this integration:

    Visit Wolfram‑Alpha API
    Sign up for an account and choose an appropriate plan
    Generate an API key from your account dashboard
    Use the API key in the wolfram_settings.authorization field in your requests

Pricing

Groq does not charge for the use of the Wolfram‑Alpha built-in tool. However, you will be charged separately by Wolfram Research for API usage according to your Wolfram‑Alpha API plan.
Provider Information

Wolfram Alpha functionality is powered by Wolfram Research, a computational knowledge engine.



Compound

While LLMs excel at generating text, Groq's Compound systems take the next step. Compound is an advanced AI system that is designed to solve problems by taking action and intelligently uses external tools, such as web search and code execution, alongside the powerful GPT-OSS 120B, Llama 4 Scout, and Llama 3.3 70B models. This allows it access to real-time information and interaction with external environments, providing more accurate, up-to-date, and capable responses than an LLM alone.

Groq's compound AI system should not be used by customers for processing protected health information as it is not a HIPAA Covered Cloud Service under Groq's Business Associate Addendum at this time. This system is also not available currently for use with regional / sovereign endpoints.
Available Compound Systems

There are two compound systems available:

    groq/compound: supports multiple tool calls per request. This system is great for use cases that require multiple web searches or code executions per request.
    groq/compound-mini: supports a single tool call per request. This system is great for use cases that require a single web search or code execution per request. groq/compound-mini has an average of 3x lower latency than groq/compound.

Both systems support the following tools:

    Web Search
    Visit Website
    Code Execution
    Browser Automation
    Wolfram Alpha


Custom user-provided tools are not supported at this time.
Quickstart

To use compound systems, change the model parameter to either groq/compound or groq/compound-mini:

from groq import Groq


client = Groq()


completion = client.chat.completions.create(

    messages=[

        {

            "role": "user",

            "content": "What is the current weather in Tokyo?",

        }

    ],

    # Change model to compound to use built-in tools

    # model: "llama-3.3-70b-versatile",

    model="groq/compound",

)


print(completion.choices[0].message.content)

# Print all tool calls

# print(completion.choices[0].message.executed_tools)

And that's it!

When the API is called, it will intelligently decide when to use search or code execution to best answer the user's query. These tool calls are performed on the server side, so no additional setup is required on your part to use built-in tools.

In the above example, the API will use its build in web search tool to find the current weather in Tokyo. If you didn't use compound systems, you might have needed to add your own custom tools to make API requests to a weather service, then perform multiple API calls to Groq to get a final result. Instead, with compound systems, you can get a final result with a single API call.
Executed Tools

To view the tools (search or code execution) used automatically by the compound system, check the executed_tools field in the response:

import os

from groq import Groq


client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


response = client.chat.completions.create(

    model="groq/compound",

    messages=[

        {"role": "user", "content": "What did Groq release last week?"}

    ]

)

# Log the tools that were used to generate the response

print(response.choices[0].message.executed_tools)

Model Usage Details

The usage_breakdown field in responses provides detailed information about all the underlying models used during the compound system's execution.
JSON

"usage_breakdown": {
  "models": [
    {
      "model": "llama-3.3-70b-versatile",
      "usage": {
        "queue_time": 0.017298032,
        "prompt_tokens": 226,
        "prompt_time": 0.023959775,
        "completion_tokens": 16,
        "completion_time": 0.061639794,
        "total_tokens": 242,
        "total_time": 0.085599569
      }
    },
    {
      "model": "openai/gpt-oss-120b",
      "usage": {
        "queue_time": 0.019125835,
        "prompt_tokens": 903,
        "prompt_time": 0.033082052,
        "completion_tokens": 873,
        "completion_time": 1.776467372,
        "total_tokens": 1776,
        "total_time": 1.809549424
      }
    }
  ]
}

System Versioning

Compound systems support versioning through the Groq-Model-Version header. In most cases, you won't need to change anything since you'll automatically be on the latest stable version. To view the latest changes to the compound systems, see the Compound Changelog.
Available Systems and Versions
System	Default Version
(no header)	Latest Version
(Groq-Model-Version: latest)
groq/compound	2025-07-23 (stable)	2025-08-16 (prerelease)
groq/compound-mini	2025-07-23 (stable)	2025-08-16 (prerelease)
Version Details

    Default (no header): Uses version 2025-07-23, the latest stable version that has been fully tested and deployed
    Latest (Groq-Model-Version: latest): Uses version 2025-08-16, the prerelease version with the newest features before they're rolled out to everyone


To use a specific version, pass the version in the Groq-Model-Version header:

curl -X POST "https://api.groq.com/openai/v1/chat/completions" \
  -H "Authorization: Bearer $GROQ_API_KEY" \
  -H "Content-Type: application/json" \
  -H "Groq-Model-Version: latest" \
  -d '{
    "model": "groq/compound",
    "messages": [{"role": "user", "content": "What is the weather today?"}]
  }'

What's Next?

Now that you understand the basics of compound systems, explore these topics:

    Systems - Learn about the two compound systems and when to use each one
    Built-in Tools - Learn about the built-in tools available in Groq's Compound systems
    Search Settings - Customize web search behavior with domain filtering
    Use Cases - Explore practical applications and detailed examples

Was this page helpful?



Systems

Groq offers two compound AI systems that intelligently use external tools to provide more accurate, up-to-date, and capable responses than traditional LLMs alone. Both systems support web search and code execution, but differ in their approach to tool usage.

    Compound (groq/compound) - Full-featured system with up to 10 tool calls per request
    Compound Mini (groq/compound-mini) - Streamlined system with up to 1 tool call and average 3x lower latency

Getting Started
Compound
Learn about the full-featured system with up to 10 tool calls per request
Compound Mini
Discover the fast, single-tool-call system with average 3x lower latency

Both systems use the same API interface - simply change the model parameter to groq/compound or groq/compound-mini to get started.
System Comparison
Feature	Compound	Compound Mini
Tool Calls per Request	Up to 10	Up to 1
Average Latency	Standard	3x Lower
Token Speed	~350 tps	~350 tps
Best For	Complex multi-step tasks	Quick single-step queries
Key Differences
Compound

    Multiple Tool Calls: Can perform up to 10 server-side tool calls before returning an answer
    Complex Workflows: Ideal for tasks requiring multiple searches, code executions, or iterative problem-solving
    Comprehensive Analysis: Can gather information from multiple sources and perform multi-step reasoning
    Use Cases: Research tasks, complex data analysis, multi-part coding challenges

Compound Mini

    Single Tool Call: Performs up to 1 server-side tool call before returning an answer
    Fast Response: Average 3x lower latency compared to Compound
    Direct Answers: Perfect for straightforward queries that need one piece of current information
    Use Cases: Quick fact-checking, single calculations, simple web searches

Available Tools

Both systems support the same set of tools:

    Web Search - Access real-time information from the web
    Code Execution - Execute Python code automatically
    Visit Website - Access and analyze specific website content
    Browser Automation - Interact with web pages through automated browser actions
    Wolfram Alpha - Access computational knowledge and mathematical calculations


For more information about tool capabilities, see the Built-in Tools page.
When to Choose Which System
Choose Compound When:

    You need comprehensive research across multiple sources
    Your task requires iterative problem-solving
    You're building complex analytical workflows
    You need multi-step code generation and testing

Choose Compound Mini When:

    You need quick answers to straightforward questions
    Latency is a critical factor for your application
    You're building real-time applications
    Your queries typically require only one tool call


Compound
groq/compound
Try it in Playground
TOKEN SPEED
~450 tps
Powered bygroq
INPUT
Text
OUTPUT
Text
CAPABILITIES
Web Search, Code Execution, Visit Website, Browser Automation, Wolfram Alpha, JSON Object Mode
Groq logoGroq

Groq's Compound system integrates OpenAI's GPT-OSS 120B and Llama 4 models with external tools like web search and code execution. This allows applications to access real-time data and interact with external environments, providing more accurate and current responses than standalone LLMs. Instead of managing separate tools and APIs, Compound systems offer a unified interface that handles tool integration and orchestration, letting you focus on application logic rather than infrastructure complexity.

Rate limits for groq/compound are determined by the rate limits of the individual models that comprise them.
PRICING
Underlying Model Pricing (per 1M tokens)
Pricing (GPT-OSS-120B)
Input
$0.15
Output
$0.75
Pricing (Llama 4 Scout)
Input
$0.11
Output
$0.34
Built-in Tool Pricing
Basic Web Search
$5 / 1000 requests
Advanced Web Search
$8 / 1000 requests
Visit Website
$1 / 1000 requests
Code Execution
$0.18 / hour
Browser Automation
$0.08 / hour
Wolfram Alpha
Based on your API key from Wolfram, not billed by Groq
Final pricing depends on which underlying models and tools are used for your specific query. See the Pricing page for more details or the Compound page for usage breakdowns.
LIMITS
CONTEXT WINDOW
131,072
MAX OUTPUT TOKENS
8,192
QUANTIZATION
This uses Groq's TruePoint Numerics, which reduces precision only in areas that don't affect accuracy, preserving quality while delivering significant speedup over traditional approaches. Learn more here
.
Key Technical Specifications
Model Architecture

Compound is powered by Llama 4 Scout and GPT-OSS 120B for intelligent reasoning and tool use.
Performance Metrics
Groq developed a new evaluation benchmark for measuring search capabilities called RealtimeEval. This benchmark is designed to evaluate tool-using systems on current events and live data. On the benchmark, Compound outperformed GPT-4o-search-preview and GPT-4o-mini-search-preview significantly.
Learn More About Agentic Tooling
Discover how to build powerful applications with real-time web search and code execution
Use Cases
Realtime Web Search

Automatically access up-to-date information from the web using the built-in web search tool.
Code Execution

Execute Python code automatically using the code execution tool powered by E2B.
Code Generation and Technical Tasks
Create AI tools for code generation, debugging, and technical problem-solving with high-quality multilingual support.
Best Practices

    Use system prompts to improve steerability and reduce false refusals. Compound is designed to be highly steerable with appropriate system prompts.
    Consider implementing system-level protections like Llama Guard for input filtering and response validation.
    Deploy with appropriate safeguards when working in specialized domains or with critical content.
    Compound should not be used by customers for processing protected health information. It is not a HIPAA Covered Cloud Service under Groq's Business Associate Addendum for customers at this time.

Quick Start

Experience the capabilities of groq/compound on Groq:
shell

pip install groq

Python

from groq import Groq

client = Groq()

completion = client.chat.completions.create(

    model="groq/compound",

    messages=[

        {

            "role": "user",

            "content": "Explain why fast inference is critical for reasoning models"

        }

    ]

)

print(completion.choices[0].message.content)


Compound Mini
groq/compound-mini
Try it in Playground
TOKEN SPEED
~450 tps
Powered bygroq
INPUT
Text
OUTPUT
Text
CAPABILITIES
Web Search, Code Execution, Visit Website, Browser Automation, Wolfram Alpha, JSON Object Mode
Groq logoGroq

Groq's Compound Mini system integrates OpenAI's GPT-OSS 120B and Llama 3.3 70B models with external tools like web search and code execution. This allows applications to access real-time data and interact with external environments, providing more accurate and current responses than standalone LLMs. Instead of managing separate tools and APIs, Compound systems offer a unified interface that handles tool integration and orchestration, letting you focus on application logic rather than infrastructure complexity.

Rate limits for groq/compound-mini are determined by the rate limits of the individual models that comprise them.
PRICING
Underlying Model Pricing (per 1M tokens)
Pricing (GPT-OSS-120B)
Input
$0.15
Output
$0.75
Pricing (Llama 3.3 70B)
Input
$0.59
Output
$0.79
Built-in Tool Pricing
Basic Web Search
$5 / 1000 requests
Advanced Web Search
$8 / 1000 requests
Visit Website
$1 / 1000 requests
Code Execution
$0.18 / hour
Browser Automation
$0.08 / hour
Wolfram Alpha
Based on your API key from Wolfram, not billed by Groq
Final pricing depends on which underlying models and tools are used for your specific query. See the Pricing page for more details or the Compound page for usage breakdowns.
LIMITS
CONTEXT WINDOW
131,072
MAX OUTPUT TOKENS
8,192
QUANTIZATION
This uses Groq's TruePoint Numerics, which reduces precision only in areas that don't affect accuracy, preserving quality while delivering significant speedup over traditional approaches. Learn more here
.
Key Technical Specifications
Model Architecture

Compound mini is powered by Llama 3.3 70B and GPT-OSS 120B for intelligent reasoning and tool use. Unlike groq/compound, it can only use one tool per request, but has an average of 3x lower latency.
Performance Metrics
Groq developed a new evaluation benchmark for measuring search capabilities called RealtimeEval. This benchmark is designed to evaluate tool-using systems on current events and live data. On the benchmark, Compound Mini outperformed GPT-4o-search-preview and GPT-4o-mini-search-preview significantly.
Learn More About Agentic Tooling
Discover how to build powerful applications with real-time web search and code execution
Use Cases
Realtime Web Search

Automatically access up-to-date information from the web using the built-in web search tool.
Code Execution

Execute Python code automatically using the code execution tool powered by E2B.
Code Generation and Technical Tasks
Create AI tools for code generation, debugging, and technical problem-solving with high-quality multilingual support.
Best Practices

    Use system prompts to improve steerability and reduce false refusals. Compound mini is designed to be highly steerable with appropriate system prompts.
    Consider implementing system-level protections like Llama Guard for input filtering and response validation.
    Deploy with appropriate safeguards when working in specialized domains or with critical content.
    Compound mini should not be used by customers for processing protected health information. It is not a HIPAA Covered Cloud Service under Groq's Business Associate Addendum for customers at this time.

Quick Start

Experience the capabilities of groq/compound-mini on Groq:
shell

pip install groq

Python

from groq import Groq

client = Groq()

completion = client.chat.completions.create(

    model="groq/compound-mini",

    messages=[

        {

            "role": "user",

            "content": "Explain why fast inference is critical for reasoning models"

        }

    ]

)

print(completion.choices[0].message.content)


Built-in Tools

Compound systems come equipped with a comprehensive set of built-in tools that can be intelligently called to answer user queries. These tools not only expand the capabilities of language models by providing access to real-time information, computational power, and interactive environments, but also eliminate the need to build and maintain the underlying infrastructure for these tools yourself.

Built-in tools with Compound systems are not HIPAA Covered Cloud Services under Groq's Business Associate Addendum at this time. These tools are also not available currently for use with regional / sovereign endpoints.
Default Tools

The tools enabled by default vary depending on your Compound system version:
Version	Web Search	Code Execution	Visit Website
Newer than 2025-07-23 (Latest)	✅	✅	✅
2025-07-23 (Default)	✅	✅	❌

All tools are automatically enabled by default. Compound systems intelligently decide when to use each tool based on the user's query.

For more information on how to set your Compound system version, see the Compound System Versioning page.
Available Tools

These are all the available built-in tools on Groq's Compound systems.
Tool	Description	Identifier
Web Search	Access real-time web content and up-to-date information with automatic citations	web_search
Visit Website	Fetch and analyze content from specific web pages	visit_website
Browser Automation	Interact with web pages through automated browser actions	browser_automation
Code Execution	Execute Python code automatically in secure sandboxed environments	code_interpreter
Wolfram Alpha	Access computational knowledge and mathematical calculations	wolfram_alpha

Jump to the Configuring Tools section to learn how to enable specific tools via their identifiers.
Configuring Tools

You can customize which tools are available to Compound systems using the compound_custom.tools.enabled_tools parameter. This allows you to restrict or specify exactly which tools should be available for a particular request.

For a list of available tool identifiers, see the Available Tools section.
Example: Enable Specific Tools

from groq import Groq

client = Groq()

response = client.chat.completions.create(
    model="groq/compound",
    messages=[
        {
            "role": "user",
            "content": "Search for recent AI developments and then visit the Groq website"
        }
    ],
    compound_custom={
        "tools": {
            "enabled_tools": ["web_search", "visit_website"]
        }
    }
)

Example: Code Execution Only

response = client.chat.completions.create(
    model="groq/compound",
    messages=[
        {
            "role": "user", 
            "content": "Calculate the square root of 12345"
        }
    ],
    compound_custom={
        "tools": {
            "enabled_tools": ["code_interpreter"]
        }
    }
)

Pricing

See the Pricing page for detailed information on costs for each tool.


Use Cases

Groq's compound systems excel at a wide range of use cases, particularly when real-time information is required.
Real-time Fact Checker and News Agent

Your application needs to answer questions or provide information that requires up-to-the-minute knowledge, such as:

    Latest news
    Current stock prices
    Recent events
    Weather updates

Building and maintaining your own web scraping or search API integration is complex and time-consuming.
Solution with Compound

Simply send the user's query to groq/compound. If the query requires current information beyond its training data, it will automatically trigger its built-in web search tool to fetch relevant, live data before formulating the answer.
Why It's Great

    Get access to real-time information instantly without writing any extra code for search integration
    Leverage Groq's speed for a real-time, responsive experience

Code Example

import os

from groq import Groq


# Ensure your GROQ_API_KEY is set as an environment variable

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


user_query = "What were the main highlights from the latest Apple keynote event?"

# Or: "What's the current weather in San Francisco?"

# Or: "Summarize the latest developments in fusion energy research this week."


chat_completion = client.chat.completions.create(

    messages=[

        {

            "role": "user",

            "content": user_query,

        }

    ],

    # The *only* change needed: Specify the compound model!

    model="groq/compound",

)


print(f"Query: {user_query}")

print(f"Compound Response:\n{chat_completion.choices[0].message.content}")


# You might also inspect chat_completion.choices[0].message.executed_tools

# if you want to see if/which tool was used, though it's not necessary.

Find the latest news and headlines
Natural Language Calculator and Code Extractor

You want users to perform calculations, run simple data manipulations, or execute small code snippets using natural language commands within your application, without building a dedicated parser or execution environment.
Solution with Compound

Frame the user's request as a task involving computation or code. groq/compound-mini can recognize these requests and use its secure code execution tool to compute the result.
Why It's Great

    Effortlessly add computational capabilities
    Users can ask things like:
        "What's 15% of $540?"
        "Calculate the standard deviation of [10, 12, 11, 15, 13]"
        "Run this python code: print('Hello from Compound!')"

Code Example

import os

from groq import Groq


client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


# Example 1: Calculation

computation_query = "Calculate the monthly payment for a $30,000 loan over 5 years at 6% annual interest."


# Example 2: Simple code execution

code_query = "What is the output of this Python code snippet: `data = {'a': 1, 'b': 2}; print(data.keys())`"


# Choose one query to run

selected_query = computation_query


chat_completion = client.chat.completions.create(

    messages=[

        {

            "role": "system",

            "content": "You are a helpful assistant capable of performing calculations and executing simple code when asked.",

        },

        {

            "role": "user",

            "content": selected_query,

        }

    ],

    # Use the compound model

    model="groq/compound-mini",

)


print(f"Query: {selected_query}")

print(f"Compound Mini Response:\n{chat_completion.choices[0].message.content}")

Perform precise and verified calculations
Code Debugging Assistant

Developers often need quick help understanding error messages or testing small code fixes. Searching documentation or running snippets requires switching contexts.
Solution with Compound

Users can paste an error message and ask for explanations or potential causes. Compound Mini might use web search to find recent discussions or documentation about that specific error. Alternatively, users can provide a code snippet and ask "What's wrong with this code?" or "Will this Python code run: ...?". It can use code execution to test simple, self-contained snippets.
Why It's Great

    Provides a unified interface for getting code help
    Potentially draws on live web data for new errors
    Executes code directly for validation
    Speeds up the debugging process

Note: groq/compound-mini uses one tool per turn, so it might search OR execute, not both simultaneously in one response.
Code Example

import os

from groq import Groq


client = Groq(api_key=os.environ.get("GROQ_API_KEY"))


# Example 1: Error Explanation (might trigger search)

debug_query_search = "I'm getting a 'Kubernetes CrashLoopBackOff' error on my pod. What are the common causes based on recent discussions?"


# Example 2: Code Check (might trigger code execution)

debug_query_exec = "Will this Python code raise an error? `import numpy as np; a = np.array([1,2]); b = np.array([3,4,5]); print(a+b)`"


# Choose one query to run

selected_query = debug_query_exec


chat_completion = client.chat.completions.create(

    messages=[

        {

            "role": "system",

            "content": "You are a helpful coding assistant. You can explain errors, potentially searching for recent information, or check simple code snippets by executing them.",

        },

        {

            "role": "user",

            "content": selected_query,

        }

    ],

    # Use the compound model

    model="groq/compound-mini",

)


print(f"Query: {selected_query}")

print(f"Compound Mini Response:\n{chat_completion.choices[0].message.content}")

Chart Generation

Need to quickly create data visualizations from natural language descriptions? Compound's code execution capabilities can help generate charts without writing visualization code directly.
Solution with Compound

Describe the chart you want in natural language, and Compound will generate and execute the appropriate Python visualization code. The model automatically parses your request, generates the visualization code using libraries like matplotlib or seaborn, and returns the chart.
Why It's Great

    Generate charts from simple natural language descriptions
    Supports common chart types (scatter, line, bar, etc.)
    Handles all visualization code generation and execution
    Customize data points, labels, colors, and layouts as needed

Usage and Results
shell

curl -X POST https://api.groq.com/openai/v1/chat/completions \
  -H "Authorization: Bearer $GROQ_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "groq/compound",
    "messages": [
      {
        "role": "user",
        "content": "Create a scatter plot showing the relationship between market cap and daily trading volume for the top 5 tech companies (AAPL, MSFT, GOOGL, AMZN, META). Use current market data."
      }
    ]
  }'

Results
Plot result

Generate K-means clustering



