import json
from os import path, chdir
from time import sleep, time

from pydriller import Repository
from pydriller.domain.commit import ModificationType, ModifiedFile
from grep_ast import filename_to_lang
from markdown_to_json import dictify

# from static_analysis.dump import dump
from api_agicto import request_llm


K = 4096
LANG_NOT_SUPPORTED = {"xml"}

PREFILL_RESP = [
    {"role": "assisstant", "content": "{"},
    {"role": "user", "content": "continue"},
]

ROLE_PROMPT = "act as a software engineer, "

MD_RESTRICT = """**response format**:
- Use clear, technical language
- Avoid markdown
- Structure respond as:
"""

FEAT_MD = "## <feature / component name>\n...\nbrief explanation\n...\n"

FEAT_MODFILE_MD = f"""# add\n
{FEAT_MD}
# delete\n
{FEAT_MD}
# modify\n
{FEAT_MD}"""

SYS_PROMPT_MD_ADD = f"""{ROLE_PROMPT}read user code, then identify added software features (e.g. 'This addition enables X functionality')

{MD_RESTRICT}
{FEAT_MD}"""

SYS_PROMPT_MD_DEL = f"""{ROLE_PROMPT}read user code, then identify deleted software features (e.g. 'This deletion removes support for Y')

{MD_RESTRICT}
{FEAT_MD}"""

SYS_PROMPT_MD_DIFF = f"""{ROLE_PROMPT}analyzing a `git diff` to identify and explain changes related to software feature add, delete, or modify.
**Instructions**
1. Parse the provided `git diff`
2. Categorize changes into:
   - **add**: New features, endpoints, functions, UI components, or dependencies
   - **delete**: Removed features, deprecated code, or retired functionality
   - **modify**: Changes to existing logic, behavior, APIs, or configurations
3. For each category, clearly:
   - Describe the technical nature of the change
   - Specify which classes / functions / components are impacted
   - Explain the implications (e.g., "This addition enables X functionality," "This deletion removes support for Y," "This modification optimizes Z")
4. Summarize overall impact of these changes on software (e.g., user experience, performance, security)

{MD_RESTRICT}
{FEAT_MODFILE_MD}"""

COMMIT_FEAT_MD = (
    "## ident\n\n - short, precise ident\n\n## impact_files\n\n- file_a\n\n"
)

COMMIT_MD = f"""# add\n
{COMMIT_FEAT_MD}
# delete\n
{COMMIT_FEAT_MD}
# modify\n
{COMMIT_FEAT_MD}
# summary\n
- high-level impact
- ..."""

USER_PROMPT_MD_COMMIT = f"""{ROLE_PROMPT}review a Git commit. Use commit message and prior analysis of individual file changes (provided in the user chat history), synthesize a concise summary of **feature-level additions, deletions, and modifications** introduced in this commit.
1. Review the chat history containing per-file analyses
2. Read **commit message**
3. Categorize changes into:
   - **add**: New user-facing features, APIs, UI components, or dependencies
   - **delete**: Removal of features, endpoints, or deprecated logic
   - **modify**: Functional changes to existing behavior, configurations, or critical logic
4. For each category:
   - Explicitly name the **feature/component** (e.g., "User Auth API," "Dashboard UI")
   - Note the **technical intent** (e.g., "enables X," "deprecates Y," "optimizes Z")
   - Reference impacted files/components (e.g., "via `api/auth.py`")
5. Conclude with a **Summary** explaining the overall impact (e.g., user experience, performance, security)

{MD_RESTRICT}
{COMMIT_MD}"""


def travese_commits(
    repo_path: str,
    num_limit: int = -1,
    max_retries: int = 4,
    time_sleep: float = 2,
    single: str = None,
):
    cnt = 0
    ans = {}
    for commit in Repository(repo_path, single=single).traverse_commits():
        if cnt == num_limit:
            break
        cnt += 1
        mod_files_resp = {}
        print("handling", commit.hash, cnt)
        for file in commit.modified_files:
            lang = filename_to_lang(file.filename)
            if not lang or lang in LANG_NOT_SUPPORTED:  # unsupported file type
                continue
            hsitory_req_resp = []
            resp, resp_md = None, None
            for i in range(max_retries):
                try:
                    fname, resp_md = chat_mod_file(file, lang)
                    resp = process_resp_md(resp_md)
                except Exception as e:
                    print(file.filename, i, "/", max_retries)
                    print(e)
                    if resp_md:
                        print(resp_md)
                    sleep(time_sleep * ((i + 1) ** 2))
                else:
                    break
            mod_files_resp[fname] = resp
            hsitory_req_resp.extend(
                [
                    {"role": "user", "content": f"file:\n{fname}"},
                    {"role": "assisstant", "content": resp_md},
                ]
            )
        summary, summary_md = None, None
        for i in range(max(1, max_retries >> 1)):
            try:
                summary_md = chat_commit(hsitory_req_resp, commit.msg)
                summary = process_resp_md(summary_md)
            except Exception as e:
                print(cnt, i, "/", max_retries)
                print(e)
                if summary_md:
                    print(summary_md)
                sleep(time_sleep)
            else:
                break

        mod_files_resp["summary"] = summary
        ans[commit.hash] = mod_files_resp

        # if len(file.changed_methods) > 0:
        #     print(
        #         "{} modified {}, complexity: {}, and contains {} methods".format(
        #             commit.author.name,
        #             file.filename,
        #             len(file.changed_methods),
        #         )
        #     )
    return ans


def chat_mod_file(file: ModifiedFile, lang: str):
    match file.change_type:
        case ModificationType.ADD:
            fname = file.new_path
            if (
                not file.source_code or file.source_code.strip(" \n\r") == ""
            ):  # new empty file
                resp_md = f"# add\n\nempty file: {fname}"
                return fname, resp_md
            resp_md = chat_file_add(fname, file.source_code, lang)
        case ModificationType.RENAME:
            fname = file.new_path
            resp_md = f"# rename\n\n## old_path\n\n{file.old_path}\n## new_path\n\n{file.new_path}"
        case ModificationType.DELETE:
            fname = file.old_path
            if (
                not file.source_code_before
                or file.source_code_before.strip(" \n\r") == ""
            ):  # delete empty file
                resp_md = f"# delete\n\nempty file: {fname}"
                return fname, resp_md
            resp_md = chat_file_del(fname, file.source_code_before, lang)
        case ModificationType.MODIFY:
            fname = file.old_path
            resp_md = chat_file_mod(fname, file.diff, lang)
    return fname, resp_md


def get_sys_message(content: str):
    return {"role": "system", "content": content}


def process_resp_md(resp: str):
    """try to format `resp` to JSON"""
    resp = resp.replace("`", "")
    if not resp:
        return None
    resp_dict = dictify(resp)
    if len(resp_dict) == 1 and "root" in resp_dict:  # parse failed
        raise json.JSONDecodeError("JSON parse error", resp_dict)
    return resp_dict


def chat_file_mod(fname, diff, lang):
    messages = [
        get_sys_message(SYS_PROMPT_MD_DIFF),
        {"role": "user", "content": f"language: {lang}\n{fname}\ndiff:\n\n{diff}"},
    ]
    # messages.extend(PREFILL_RESP)
    resp = request_llm(messages, MODEL)
    return resp


def chat_file_add(fname, source_code, lang):
    messages = [
        get_sys_message(SYS_PROMPT_MD_ADD),
        {"role": "user", "content": f"{lang} code:\n{fname}\n\n{source_code}"},
    ]
    # messages.extend(PREFILL_RESP)
    resp = request_llm(messages, MODEL)
    return resp


def chat_file_del(fname, source_code, lang):
    messages = [
        get_sys_message(SYS_PROMPT_MD_DEL),
        {"role": "user", "content": f"{lang} code:\n{fname}\n\n{source_code}"},
    ]
    # messages.extend(PREFILL_RESP)
    resp = request_llm(messages, MODEL)
    return resp


def chat_commit(hsitory_req_resp: list[str], msg: str):
    hsitory_req_resp.append(
        {
            "role": "user",
            "content": f"{USER_PROMPT_MD_COMMIT}\n\n\ncommit_message:\n\n{msg}",
        }
    )
    # hsitory_req_resp.extend(PREFILL_RESP)
    resp = request_llm(hsitory_req_resp, STRONG_MODEL)
    return resp


def test_travese_commits(repo_path: str, num_limit: int = -1):
    cnt = 0
    repo = Repository(repo_path)
    for commit in repo.traverse_commits():
        if cnt == num_limit:
            break
        cnt += 1
        for file in commit.modified_files:
            print(file.diff)


def process_resp_json_str(resp: str):
    """try to format `resp` to JSON"""
    resp = resp.replace("```json", "")
    resp = resp.replace("```", "")
    if not resp:
        return None
    while True:
        try:
            return json.loads(resp)
        except:
            resp = resp[resp.find("{") : resp.rfind("}") + 1]
            return json.loads(resp)


def save_to_json(file_name_no_ext: str, json_data: list | dict):
    l = len(json_data)
    print(f"saving {l} elements > {file_name_no_ext}.json")
    if l > 0:
        with open(file_name_no_ext + ".json", "w") as fp:
            json.dump(json_data, fp, indent=4)


# "Doubao-pro-32k" "Doubao-lite-32k" "gpt-4o-mini" "gpt-4o" "deepseek-v3" "ERNIE-Speed-128K" "llama3-70b-8192" "gemma2-9b-it" "deepseek-chat"
MODEL = "Doubao-pro-32k"
STRONG_MODEL = "deepseek-v3"
if __name__ == "__main__":
    REPO_NAME = "aspnetcore-realworld-example-app"  # "cakephp-realworld-example-app"
    WORK_DIR = path.dirname(__file__)
    chdir(WORK_DIR)
    # REPO_PATH = path.join(WORK_DIR, path.pardir, "proj", REPO_NAME)
    REPO_PATH = path.join("path_to_repo", REPO_NAME)
    ans = travese_commits(REPO_PATH, max_retries=8)
    save_to_json(
        "_".join(
            [
                REPO_NAME,
                MODEL,
                STRONG_MODEL if MODEL != STRONG_MODEL else "",
                str(int(time())),
            ]
        ),
        ans,
    )


# PS_CODE = "ps: comments and doc strings are helpful to understand code; DO NOT explain, answer directly; "
JSON_RESTRICT = """**response format**:
- Use clear, technical language
- Avoid markdown
- Response MUST BE JSON, structure as:
"""

FEAT_JSON = {"<feature / component name>": "brief explanation"}


FEAT_MODFILE_JSON = {
    "add": FEAT_JSON,
    "delete": FEAT_JSON,
    "modify": FEAT_JSON,
    "summary": "1-2 sentences on the collective impact",
}

SYS_PROMPT_JSON_ADD = f"""{ROLE_PROMPT}read user code, then identify added software features (e.g. 'This addition enables X functionality')

{JSON_RESTRICT}
{FEAT_JSON}"""

SYS_PROMPT_JSON_DEL = f"""{ROLE_PROMPT}read user code, then identify deleted software features (e.g. 'This deletion removes support for Y')

{JSON_RESTRICT}
{FEAT_JSON}"""


SYS_PROMPT_JSON_DIFF = f"""{ROLE_PROMPT}analyzing a `git diff` to identify and explain changes related to software feature add, delete, or modify.
**Instructions**
1. Parse the provided `git diff`
2. Categorize changes into:
   - **add**: New features, endpoints, functions, UI components, or dependencies
   - **delete**: Removed features, deprecated code, or retired functionality
   - **modify**: Changes to existing logic, behavior, APIs, or configurations
3. For each category, clearly:
   - Describe the technical nature of the change
   - Specify which classes / functions / components are impacted
   - Explain the implications (e.g., "This addition enables X functionality," "This deletion removes support for Y," "This modification optimizes Z")
4. Summarize overall impact of these changes on software (e.g., user experience, performance, security)

{JSON_RESTRICT}
{FEAT_MODFILE_JSON}"""

COMMIT_FEAT_JSON = {"ident": " ", "impact_files": []}

COMMIT_JSON = {
    "add": COMMIT_FEAT_JSON,
    "delete": COMMIT_FEAT_JSON,
    "modify": COMMIT_FEAT_JSON,
    "summary": "1-2 sentences on high-level impact",
}

USER_PROMPT_JSON_COMMIT = f"""{ROLE_PROMPT}review a Git commit. Use commit message prior analysis of individual file changes (provided in the chat history), synthesize a concise summary of **feature-level additions, deletions, and modifications** introduced in this commit.
1. Review the chat history containing per-file `git diff` analyses
2. Read commit message
3. Categorize changes into:
   - **Additions**: New user-facing features, APIs, UI components, or dependencies
   - **Deletions**: Removal of features, endpoints, or deprecated logic
   - **Modifications**: Functional changes to existing behavior, configurations, or critical logic
4. For each category:
   - Explicitly name the **feature/component** (e.g., "User Auth API," "Dashboard UI")
   - Note the **technical intent** (e.g., "enables X," "deprecates Y," "optimizes Z")
   - Reference impacted files/components (e.g., "via `api/auth.py`")
5. Exclude trivial changes (e.g., formatting, logging) unless they directly affect functionality
6. Conclude with a **Summary** explaining the commit’s overall impact (e.g., user experience, performance, security)

{JSON_RESTRICT}
{COMMIT_JSON}"""
