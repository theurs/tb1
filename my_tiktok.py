#!/usr/bin/env python3


import os
import subprocess

import utils


def is_valid_url(url: str) -> bool:
    """
    Check if the given URL is a valid TikTok link.

    Args:
          url (str): The URL to check.

    Returns:
          bool: True if the URL is a valid TikTok link, False otherwise.
    """
    if not url.startswith("https://www.tiktok.com/") or '/video/' not in url:
        return False
    return True


def download_video(url: str) -> str:
    """
    Download a video from the given URL.

    Parameters:
        url (str): The URL of the video to be downloaded.

    Returns:
        str: The file path of the downloaded video.
    """
    tmp = utils.get_tmp_fname()
    subprocess.run(['yt-dlp', '-o', tmp, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.rename(tmp, tmp + '.mp4')
    return tmp + '.mp4'


if __name__ == "__main__":
    url = "https://www.tiktok.com/@tamar.mtmobile/video/7281190102313864450?is_from_webapp=1&sender_device=pc"
    # print(is_tiktok_link(url))
    # print(download_video(url))