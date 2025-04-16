import json
from os import path, chdir
from time import sleep, time
from typing import Dict, List, Any

from markdown_to_json import dictify

from api_agicto import request_llm


ISSUE_PROMPT = """You are tasked with analyzing a GitHub issue and its comments. Follow these steps strictly:

1. **Read & Categorize**:
   - Review the user provided GitHub issue title, body, labels and comments.
   - Directly categorize the issue as **bug-report**, **feature-request**, or **discussion**.
   - Only choose one category.

2. **For bug-report**:
   - **Features**: Identify and list all functional features (e.g., authentication, UI components) directly impacted by the bug.
   - **Reproduction**: Summarize the reproduction steps provided or inferred.
   - **Cause**: Deduce the root cause of the bug (e.g., code error, dependency conflict).

3. **For feature-request**:
   - **Features**: List every distinct feature or enhancement explicitly requested in the issue and comments.
   - Avoid vague descriptions; extract specific functionalities.

4. **For discussions**:
   - **Opinions**: Identify and list all differing opinions, questions, or proposals from participants.
   - Attribute opinions to commenters (e.g., "User A suggests...", "User B argues...").

**Response Format**:
- Be concise. Do not include explanations.
- Use clear headings and bullet points, e.g.

# bug-report\n
## features\n
bullet points\n
## reproduction\n
bullet points\n
## cause\n
bullet points\n
"""


def traverse_issue_comments(
    issue_comments_list: List[Dict],
    num_limit: int = -1,
    max_retries: int = 4,
    time_sleep: float = 1,
):
    n = len(issue_comments_list)
    ans = []
    for i, issue in enumerate(issue_comments_list):
        if i == num_limit:
            break

        # if "pull_request" in issue:
        #     ans.append(None)
        #     continue

        # prepare issue and comments
        issue_dict = {
            "title": issue["title"],
            "user": issue["user"]["login"],  # "html_url"
            "body": issue["body"],
        }
        if issue["comments"] == 0:
            issue_dict["comments"] = None
        else:
            issue_dict["comments"] = [
                {
                    "user": c["user"]["login"],  # "html_url"
                    "body": c["body"],
                }
                for c in issue["comments"]
            ]
        if issue["labels"]:
            issue_dict["labels"] = [l["name"] for l in issue["labels"]]
        print("handling", i, "/", n)
        for j in range(max_retries):
            resp_md, resp = None, None
            try:
                resp_md = chat_issue_comment(issue_dict)
                resp = process_resp_md(resp_md)
            except Exception as e:
                print(j, "/", max_retries)
                print(e)
                if resp_md:
                    print(resp_md)
                sleep(time_sleep * ((j + 1) ** 2))
            else:
                break

        ans.append(resp)
    return ans


def chat_issue_comment(issue_comment):
    messages = [
        {"role": "system", "content": ISSUE_PROMPT},
        {"role": "user", "content": f"issue:\n\n{issue_comment}"},
    ]
    resp = request_llm(messages, MODEL)
    return resp


def process_resp_md(resp: str):
    """try to format `resp` to JSON"""
    resp = resp.replace("`", "")
    if not resp:
        return None
    resp_dict = dictify(resp)
    if len(resp_dict) == 1 and "root" in resp_dict:  # parse failed
        raise json.JSONDecodeError("JSON parse error", resp_dict)
    return resp_dict


def save_to_json(file_name_no_ext: str, json_data: list | dict):
    l = len(json_data)
    print(f"saving {l} elements > {file_name_no_ext}.json")
    if l > 0:
        with open(file_name_no_ext + ".json", "w") as fp:
            json.dump(json_data, fp, indent=4)


def test_traverse_issue_comments(issue_comments: List[Dict]):
    for i, issue in enumerate(issue_comments):
        issue_dict = {
            "title": issue["title"],
            "user": issue["user"]["login"],  # "html_url"
            "body": issue["body"],
        }
        if issue["comments"] == 0:
            issue_dict["comments"] = None
        else:
            issue_dict["comments"] = [
                {
                    "user": c["user"]["login"],  # "html_url"
                    "body": c["body"],
                }
                for c in issue["comments"]
            ]
        if issue["labels"]:
            issue_dict["labels"] = [l["name"] for l in issue["labels"]]
        print(issue_dict)


# "Doubao-pro-32k" "Doubao-lite-32k" "gpt-4o-mini" "gpt-4o" "deepseek-v3" "ERNIE-Speed-128K" "llama3-70b-8192" "gemma2-9b-it" "deepseek-chat"

MODEL = "Doubao-lite-32k"
if __name__ == "__main__":
    REPO_NAME = "Aider-AI/grep-ast"
    BASE_FNAME = REPO_NAME.replace("/", "_")
    JSON_NAME = path.join("issues", f"{BASE_FNAME}_issues_merged.json")
    WORK_DIR = path.dirname(__file__)
    chdir(WORK_DIR)
    with open(JSON_NAME, "r") as f:
        issue_comments = json.load(f)
    ans = traverse_issue_comments(issue_comments)

    save_to_json(
        path.join("issues_chatted", f"{BASE_FNAME}_{MODEL}_{int(time())}"), ans
    )
