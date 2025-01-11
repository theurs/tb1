#!/usr/bin/env python3
# https://github.com/NexusAILab/bing_image_creator/blob/main/bing_image_creator/generator.py


import aiohttp
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs


class BingImageCreator:
    def __init__(self, cookies=None):
        self.cookies = cookies

    async def _get_redirect_url(self, html_content):
        soup = BeautifulSoup(html_content, 'html.parser')
        og_url_tag = soup.find('meta', property='og:url')
        
        if og_url_tag and og_url_tag.get('content'):
            og_url = og_url_tag['content']
            parsed_url = urlparse(og_url)
            query_params = parse_qs(parsed_url.query)
            og_id = query_params.get('id', [None])[0]
            return og_id
        return None


    async def get_image_models(self):
        return ["dall-e-3"]


    async def generate_images(self, prompt: str, model: str = "dall-e-3"):
        try:
            for rt in [4, 3]:
                _U = self.cookies
                headers = {
                    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
                    'accept-language': 'en-US,en-IN;q=0.9,en-GB;q=0.8,en;q=0.7,hi;q=0.6',
                    'cache-control': 'max-age=0',
                    'content-type': 'application/x-www-form-urlencoded',
                    'cookie': f"_U={_U}",
                    'dnt': '1',
                    'ect': '4g',
                    'origin': 'https://www.bing.com',
                    'priority': 'u=0, i',
                    'referer': 'https://www.bing.com/images/create?',
                    'sec-ch-ua': '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
                    'sec-ch-ua-arch': '"x86"',
                    'sec-ch-ua-bitness': '"64"',
                    'sec-ch-ua-full-version': '"130.0.6723.60"',
                    'sec-ch-ua-full-version-list': '"Chromium";v="130.0.6723.60", "Google Chrome";v="130.0.6723.60", "Not?A_Brand";v="99.0.0.0"',
                    'sec-ch-ua-mobile': '?0',
                    'sec-ch-ua-model': '""',
                    'sec-ch-ua-platform': '"Windows"',
                    'sec-ch-ua-platform-version': '"10.0.0"',
                    'sec-fetch-dest': 'document',
                    'sec-fetch-mode': 'navigate',
                    'sec-fetch-site': 'same-origin',
                    'sec-fetch-user': '?1',
                    'upgrade-insecure-requests': '1',
                    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
                }

                params = {
                    'q': prompt,
                    'rt': f'{rt}',
                    'FORM': 'GENCRE',
                }

                data = {
                    'q': prompt,
                    'qs': 'ds',
                }

                async with aiohttp.ClientSession() as session:
                    response = await session.post(
                        'https://www.bing.com/images/create',
                        params=params,
                        headers=headers,
                        data=data
                    )
                    response_text = await response.text()
                    redirect_url = await self._get_redirect_url(response_text)
                    if redirect_url is None:
                        continue

                    referer = f"https://www.bing.com/images/create/{prompt.replace(' ', '-')}/{redirect_url}"
                    headers.update({
                        'referer': referer,
                    })

                    params = {
                        'FORM': 'GUH2CR',
                    }
                    url = f"https://www.bing.com/images/create/{prompt.replace(' ', '-')}/{redirect_url}"

                    for _ in range(12):
                        response = await session.get(
                            url,
                            params=params,
                            headers=headers,
                        )
                        response_text = await response.text()
                        soup = BeautifulSoup(response_text, 'html.parser')
                        main_link = soup.find('a', class_=['girr_set', 'seled'])
                        if main_link:
                            image_links = [img['src'] for img in main_link.find_all('img')]
                            if image_links:
                                clean_links = [link.split('?')[0] for link in image_links]
                                return list(clean_links)
                        await asyncio.sleep(5)
                    
                raise RuntimeError(f"Images not found for prompt: {prompt}. All attempts failed.")
        except Exception as e:
            error_message = str(e)
            # raise RuntimeError(f"Error generating Bing images for prompt '{prompt}': {error_message}")
            raise RuntimeError(f"Error generating Bing images for this prompt: {error_message}")


    def generate_images_sync(self, prompt: str, model: str = "dall-e-3"):
        """Synchronous version of generate_images"""
        return asyncio.run(self.generate_images(prompt, model))


    def get_image_models_sync(self):
        """Synchronous version of get_image_models"""
        return asyncio.run(self.get_image_models())
