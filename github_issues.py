"""usage: python github_issues.py <REPO> <TOKEN>"""
import json
import requests
from sys import argv
from os import chdir, path, getenv


def get(url: str, token: str):
    """Github API limit is easier to reach without token"""
    response = requests.get(
        url=url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    response.raise_for_status()
    return response


# https://docs.github.com/en/rest/issues/issues?apiVersion=2022-11-28#list-repository-issues
def list_repo_issues(owner_repo: str, token: str):
    json_list = []
    index = 0
    base_url = (
        f"https://api.github.com/repos/{owner_repo}/issues?state=all&per_page=100&page="
    )
    while True:
        try:
            response = get(f"{base_url}{index}&sort=created", token)
        except requests.exceptions.RequestException as e:
            print(e)
        if response.status_code == 200:
            if len(response.json()) > 0:
                json_list.append(response.json())
                print("List 100 issues from page {}".format(index))
                index += 1
            else:
                print("List all issues successfully")
                break
        else:
            print("Stop listing issues at page {}: {}".format(index, response.text))
            break
    return json_list


# https://docs.github.com/en/rest/issues/issues?apiVersion=2022-11-28#get-an-issue
# "state" "title" "body" "comments" "user.login"
def get_an_issue(
    token: str,
    owner_repo: str | None = None,
    issue_number: str | None = None,
    issue_url: str | None = None,
):
    if not issue_url:
        issue_url = f"https://api.github.com/repos/{owner_repo}/issues/{issue_number}"
    try:
        response = get(issue_url, token)
        if response.status_code == 200 and len(response.json()) > 0:
            return response.json()
        else:
            print(f"error getting issue {issue_url}: {response.text}")
    except requests.exceptions.RequestException as e:
        print(e)
        raise e


# https://docs.github.com/en/rest/issues/issues?apiVersion=2022-11-28#list-repository-issues
def extract_issue_urls(file: str, failed_file: str):
    """extract todo issue_urls from `file`, return `None` if `failed_file` exists"""
    issue_urls = []
    with open(file, "r") as f:
        repo_issue_list = json.load(f)
        if not isinstance(repo_issue_list, list):
            raise TypeError(f"Invalid JSON format: {file}")
        for i, page in enumerate(repo_issue_list):
            if not isinstance(page, list):
                print(f"Invalid JSON format: page {i+1} @ {file}")
            issue_urls.extend([issue.get("url") for issue in page])
    return issue_urls


# https://docs.github.com/zh/rest/issues/comments?apiVersion=2022-11-28#list-issue-comments
# "body" "user.login"
def list_issue_comments(
    token: str,
    owner_repo: str | None = None,
    issue_number: str | None = None,
    comments_url: str | None = None,
):
    if not comments_url:
        comments_url = f"https://api.github.com/repos/{owner_repo}/issues/{issue_number}/comments?per_page=100"
    try:
        response = get(comments_url, token)
        if response.status_code == 200 and len(response.json()) > 0:
            return response.json()
        else:
            print(f"error getting comments {comments_url}: {response.text}")
    except requests.exceptions.RequestException as e:
        print(e)
        raise e


def save_to_json(file_name: str, json_data: list):
    l = len(json_data)
    print(f"saving {l} pages > {file_name}")
    if l > 0:
        with open(file_name, "w") as fp:
            json.dump(json_data, fp, indent=4)


def get_repo_issue_comments_from_json_file(file: str, failed_file: str, token: str):
    if not file:
        file = FNAME_BASE + ".json"
    failed_urls, issue_with_comments = [], []
    failed_data = None
    if path.exists(failed_file):
        with open(failed_file, "r") as fail:
            failed_data = json.load(fail)
    with open(file, "r") as f:
        data = json.load(f)
        failed_set = set()
        if isinstance(failed_data, list):
            failed_set.__init__(failed_data)
        if not isinstance(data, list):
            raise TypeError(f"Invalid JSON format: {file}")
        l = len(data)
        for i, page in enumerate(data):
            print(f"Getting issues from page {i+1} / {l}")
            if not isinstance(page, list):
                print(f"Invalid JSON format: page {i+1} @ {file}")
                continue
            for j, issue in enumerate(page):
                if not isinstance(issue, dict):
                    print(f"Invalid JSON format: {issue} @ line {j+1}, page {i+1} @ {file}")
                    continue
                try:
                    url = issue.get("url")
                    if not url in failed_set:
                        continue
                    issue_json = get_an_issue(token, issue_url=url)
                    cm = issue.get("comments")
                    if cm and int(cm) > 0:
                        issue_comments = list_issue_comments(
                            token,
                            comments_url=issue.get("comments_url"),
                        )
                        if issue_comments:
                            issue_json["comments"] = issue_comments
                    issue_with_comments.append(issue_json)
                except:
                    failed_urls.append(issue.get("url"))
    return issue_with_comments, failed_urls


def merge_issue_lists(a: list[dict], b: list[dict]):
    """sort by url descending"""
    merged = []
    i, j = 0, 0
    la, lb = len(a), len(b)
    while i < la and j < lb:
        if a[i].get("url") < b[j].get("url"):
            merged.append(b[j])
            j += 1
        else:
            merged.append(a[i])
            i += 1
    if i < la:
        merged.extend(a[i:])
    if j < lb:
        merged.extend(b[j:])
    return merged


if __name__ == "__main__":
    chdir(path.dirname(__file__))
    if len(argv) > 2:
        REPO, TOKEN = argv[1], argv[2]
    else:
        REPO = input("Please enter Github repo (e.g. octocat/Hello-World): \n").strip()
        github_api_key = getenv("github_api_key")
        if github_api_key:
            TOKEN = github_api_key
        else:
            TOKEN = input("Please enter Github token: \n").strip()
    FNAME_BASE = REPO.replace("/", "_", 1)
    JSON_FILE = FNAME_BASE + ".json"
    FAILED_FILE = FNAME_BASE + "_todo.json"
    MERGED_FILE = FNAME_BASE + "_issues_merged.json"

    # list repo issues
    if not path.exists(JSON_FILE):
        issue_list = list_repo_issues(REPO, TOKEN)
        save_to_json(JSON_FILE, issue_list)
    else:
        print(f"{JSON_FILE} alredy exists, skipping list_repo_issues()")


    if not path.exists(FAILED_FILE):
        issue_urls = extract_issue_urls(JSON_FILE, FAILED_FILE)
        save_to_json(FAILED_FILE, issue_urls)
    else:
        print(f"{FAILED_FILE} alredy exists, skipping extract_issue_urls()")

    # get issue comments
    repo_issue_comments, failed = get_repo_issue_comments_from_json_file(
        JSON_FILE, FAILED_FILE, TOKEN
    )
    save_to_json(FAILED_FILE, failed)
    if not path.exists(MERGED_FILE):
        # successfully get all issues with comments in one go
        save_to_json(MERGED_FILE, repo_issue_comments)
    else:
        with open(MERGED_FILE) as f:
            issues = json.load(f)
            # merge results from last time
            merged = merge_issue_lists(repo_issue_comments, issues)
            save_to_json(MERGED_FILE, merged)

