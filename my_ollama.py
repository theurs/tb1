#!/usr/bin/env python3
# pip install -U ollama

from ollama import Client

client = Client(host='http://10.147.17.227:11434')

def main():
    context = []
    while True:
        user_input = input("You: ")
        if user_input.lower() in ["exit", "quit"]:
            break

        context.append({'role': 'user', 'content': user_input})
        
        stream = client.chat(model='mistral', messages=context, stream=True)
        
        full_response = ""
        for chunk in stream:
            content = chunk['message']['content']
            print(content, end='', flush=True)
            full_response += content
        
        print() # New line after the stream is complete
        context.append({'role': 'assistant', 'content': full_response})

if __name__ == "__main__":
    main()
