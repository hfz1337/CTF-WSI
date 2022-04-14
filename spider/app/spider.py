#!/usr/bin/python3
import os
from typing import Tuple
import requests
from requests.exceptions import ConnectTimeout, ConnectionError
from pymongo import MongoClient, TEXT
from bs4 import BeautifulSoup

# Load environment variables
USER_AGENT = os.getenv("USER_AGENT")
CTFTIME_URL = os.getenv("CTFTIME_URL")
TIMEOUT = int(os.getenv("TIMEOUT"))
MONGODB_URI = os.getenv("MONGODB_URI")
DATABASE = os.getenv("DATABASE")
COLLECTION = os.getenv("COLLECTION")

PROGRESS_BAR_WIDTH = 100


class Logger:
    @staticmethod
    def success(string: str) -> None:
        print(f"\33[92m[+] {string}\33[0m")

    @staticmethod
    def info(string: str) -> None:
        print(f"\33[34m[*] {string}\33[0m")

    @staticmethod
    def error(string: str) -> None:
        print(f"\33[31m[-] {string}\33[0m")


def draw_progress_bar(current: int, last: int, width: int = PROGRESS_BAR_WIDTH) -> None:
    """Draw progress bar.

    Args:
        current: Current iteration.
        last: Maximum number of iterations.
        width: Width of the progress bar.
    """
    current = min(current, last)
    ratio = current / last
    print(
        f"{ratio*100:6.2f}% [{'='*int(ratio*(width-1))+'>':{width}}] {current}/{last}"
    )


def get_latest_writeup_id() -> int:
    """Scrape the latest write-up ID off the CTFtime home page.

    Returns:
        The latest write-up ID.
    """
    response = requests.get(url=CTFTIME_URL, headers={"User-Agent": USER_AGENT})
    if response.status_code != 200:
        return None

    return int(
        BeautifulSoup(response.content, "html.parser")
        .select_one(".page-header+ .table-striped tr:nth-child(2) td:nth-child(4) a")[
            "href"
        ]
        .split("/")[-1]
    )


def get_content_length(url: str) -> int:
    """Return the size of a page.

    Args:
        url: The URL to get the content length for.

    Returns:
        The content length of the URL.
    """
    try:
        response = requests.head(url=url, headers={"User-Agent": USER_AGENT})
        if "Content-Length" not in response:
            return None
        return response.headers["Content-Length"]
    except:
        return 0


def scrape_blog_writeup(url: str) -> str:
    """Scrape write-up from the blog page.

    Args:
        url: The URL to the blog post for the write-up.

    Returns:
        The write-up content.
    """
    # Remove what comes after the #
    url = url.split("#")[0]

    # Check page size before proceeding (this is done to avoid downloading huge
    # files like rockyou.txt when linked from a write-up).
    content_length = get_content_length(url)

    if content_length == 0 or content_length > 2 ** 21:
        # Page is empty or bigger than 2MB
        return ""

    # Are we dealing with a Github link? If so, then we download the raw markdown page
    # directly.
    if "gist.github.com" in url:
        url = f"{url.strip('/')}/raw"
    elif "github.com" in url:
        # Get direct link to the README.md file
        if not url.endswith(".md"):
            # Retrieve the filename, it's not always README.md in uppercase.
            response = requests.get(url=url, headers={"User-Agent": USER_AGENT})
            parser = BeautifulSoup(response.content, "html.parser")
            filename = parser.select_one("#readme .Link--primary")
            # Some people don't set a readme file, so we search for the first markdown
            # file we find in the repo.
            if filename:
                filename = filename.text
            else:
                for element in parser.select(".js-navigation-open.Link--primary"):
                    if element.text.endswith(".md"):
                        filename = element.text
                        break
            url = f"{url.replace('tree', 'blob').strip('/')}/{filename}"
        # Get direct link to the raw content
        url = url.replace("github.com", "raw.githubusercontent.com").replace(
            "/blob", "/"
        )

    try:
        response = requests.get(
            url=url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, verify=False
        )
        if response.status_code == 200:
            # Remove all Base64 embeded stuff
            parser = BeautifulSoup(response.content, "html.parser")
            for element in parser.findAll():
                if "src" in element.attrs and element["src"].startswith("data"):
                    element.decompose()
            content = parser.text.strip()
        else:
            content = ""
    except ConnectTimeout:
        Logger.error(f"{url} timed out.")
        content = ""
    except ConnectionError:
        Logger.error(f"{url} dead link.")
        content = ""

    return content


def scrape_writeup_info(writeup_id: int) -> Tuple[dict, int]:
    """Scrape write-up information off the CTFtime website.

    Args:
        writeup_id: The unique ID of the write-up.

    Returns:
        A tuple containing the dictionary representation of the write-up
        and the HTTP response code.
    """
    response = requests.get(
        url=f"{CTFTIME_URL}/writeup/{writeup_id}", headers={"User-Agent": USER_AGENT}
    )
    # The write-up was deleted.
    if response.status_code == 404:
        return {
            "id": writeup_id,
            "ctf": "",
            "name": "",
            "tags": "",
            "author": "",
            "team": "",
            "rating": "",
            "ctftime": f"{CTFTIME_URL}/writeup/{writeup_id}",
            "url": "",
            "ctftime_content": "",
            "blog_content": "",
        }, 404
    # Maybe CTFtime will block us one day?
    if response.status_code != 200:
        return None, response.status_code

    parser = BeautifulSoup(response.content, "html.parser")

    ctf_name = parser.select_one(".breadcrumb li:nth-child(3) a").text.strip()
    challenge_name = parser.select_one(".divider+ li a").text.strip()
    author = parser.select_one("h2+ a").text.strip()
    team = (element := parser.select_one(".page-header a+ a")) and element.text.strip()

    # If the team is not present, then author is the team itself
    team, author = team or author, team and author or ""

    # Tags if any
    tags = " ".join([element.text for element in parser.select(".label-info")])

    # If the rating was not present, it means that this write-up didn't receive
    # any rating. So it would make sense to set it to "not rated", but no, we need
    # it as a float to maybe sort write-ups from best to worst when searching.
    rating = (
        float(rating)
        if (rating := parser.select_one("#user_rating").text.strip())
        else 0.0
    )

    # URL to the write-up on the author's blog, not always available
    blog_url = (
        element[-1]["href"]
        if (element := parser.select(".well a")) and "href" in element[-1].attrs
        else ""
    )

    # Get rid of anchor elements to parse the description correctly
    for anchor in parser.findAll("a"):
        anchor.replaceWithChildren()
    # Replace br tags with a linebreak
    for line_break in parser.findAll("br"):
        line_break.replaceWith("\n")

    # Write-up content from the CTFtime page, not always available
    ctftime_writeup_content = (
        element.text.strip()
        if (element := parser.select_one("#id_description"))
        else ""
    )

    # If there's a URL to the original write-up, we scrape it
    try:
        blog_writeup_content = scrape_blog_writeup(blog_url) if blog_url else ""
    except Exception:
        Logger.error(f"{blog_url} crawling failed.")
        blog_writeup_content = ""
        blog_url = ""

    return {
        "id": writeup_id,
        "ctf": ctf_name,
        "name": challenge_name,
        "tags": tags,
        "author": author,
        "team": team,
        "rating": rating,
        "ctftime": f"{CTFTIME_URL}/writeup/{writeup_id}",
        "url": blog_url,
        "ctftime_content": ctftime_writeup_content,
        "blog_content": blog_writeup_content,
    }, 200


if __name__ == "__main__":
    mongo = MongoClient(MONGODB_URI)
    # Create text index if this is our first time setting the database
    if DATABASE not in mongo.list_database_names():
        Logger.info("Creating index...")
        mongo[DATABASE][COLLECTION].create_index(
            [
                ("name", TEXT),
                ("tags", TEXT),
                ("ctftime_content", TEXT),
                ("blog_content", TEXT),
            ],
            default_language="english",
        )
        Logger.success("Index created.")
    else:
        Logger.success("Index already created.")

    # Get the latest write-up ID from CTFtime
    latest_writeup_id = get_latest_writeup_id()

    # Get writeup IDs we already crawled
    crawled = [
        writeup["id"]
        for writeup in mongo[DATABASE][COLLECTION].find(
            projection={"id": True, "_id": False}
        )
    ]
    missing = [
        writeup_id
        for writeup_id in range(1, latest_writeup_id + 1)
        if writeup_id not in crawled
    ]
    missing_len = len(missing)

    if missing_len == 0:
        Logger.success("We're up to date, nothing to crawl.")
    else:
        Logger.info(f"Crawling {missing_len} write-up...")

    for idx, writeup_id in enumerate(missing):
        writeup_ctftime_url = f"{CTFTIME_URL}/writeup/{writeup_id}"
        # Display progress bar
        draw_progress_bar(idx, missing_len)
        Logger.info(f"Attempting to crawl {writeup_ctftime_url}...")

        writeup, code = scrape_writeup_info(writeup_id)
        if code == 200:
            mongo[DATABASE][COLLECTION].insert_one(writeup)
            Logger.success(f"{writeup_ctftime_url} crawled successfully.")
        elif code == 404:
            # Insert it into the database so we don't crawl it again unnecessarily.
            mongo[DATABASE][COLLECTION].insert_one(writeup)
            Logger.info(f"{writeup_ctftime_url} not found.")
        else:
            Logger.error(f"{writeup_ctftime_url} crawling failed.")
