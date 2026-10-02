"""Optional phone notifications through ntfy.sh (free, no account).
Install the ntfy app, subscribe to a hard-to-guess topic name, and set NTFY_TOPIC to it."""
import os

import requests

from . import config


def notify(title, message, click=None):
    if not config.NTFY_TOPIC:
        return
    if click is None and os.environ.get("GITHUB_RUN_ID"):
        click = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                 f"{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    headers = {"Title": title.encode("utf-8"), "Tags": "movie_camera"}
    if click:
        headers["Click"] = click
    try:
        requests.post(f"https://ntfy.sh/{config.NTFY_TOPIC}", data=message.encode("utf-8"),
                      headers=headers, timeout=15)
    except requests.RequestException:
        pass
