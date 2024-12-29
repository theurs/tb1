import json
import requests
from typing import List, Dict, Any


BASE_URL = "http://127.0.0.1:58796/bing"


def send_image_generation_request(prompt: str) -> List[str]:
    """
    Sends a POST request to the image generation API with the given prompt.

    :param prompt: The prompt for image generation.
    :return: A list of image URLs returned by the API.
    :raises requests.RequestException: If there's an error with the request.
    :raises json.JSONDecodeError: If the response is not a valid JSON.
    """
    url: str = BASE_URL
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    data: Dict[str, str] = {"prompt": prompt}

    try:
        # Send the POST request
        response: requests.Response = requests.post(url, headers=headers, json=data)
        
        # Raise an exception for bad status codes
        response.raise_for_status()
        
        # Parse the JSON response
        json_response: Dict[str, Any] = response.json()
        
        # Extract the list of URLs
        image_urls: List[str] = json_response.get("urls", [])
        
        return image_urls

    except requests.RequestException as e:
        print(f"An error occurred while sending the request: {e}")
        raise
    except json.JSONDecodeError as e:
        print(f"An error occurred while parsing the response: {e}")
        raise


def gen_images(prompt: str) -> List[str]:
    return send_image_generation_request(prompt)


if __name__ == "__main__":
    # Example prompt in Russian
    prompt: str = "Нарисуй закат на море с яркими оранжевыми и розовыми оттенками на небе,\nа на переднем плане пусть будет одинокая лодка, покачивающаяся на волнах."
    
    try:
        # Send the request and get the URLs
        urls: List[str] = send_image_generation_request(prompt)
        
        # Print the URLs
        for url in urls:
            print(url)
    
    except Exception as e:
        print(f"An error occurred: {e}")
