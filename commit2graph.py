from datetime import datetime
from typing import Dict, Literal
import json
from os import path, chdir

from pydriller import Repository
from pydriller.domain.commit import ModificationType, Commit, Developer

from db import Neo4jDB

n4jdb = Neo4jDB()


def travese_commits(repo_path: str, knowledge: Dict[str, object], num_limit: int = -1):
    cnt = 0
    for commit in Repository(repo_path).traverse_commits():
        if cnt == num_limit:
            break
        cnt += 1
        if not commit.hash in knowledge:
            continue
        commit_knowledge = knowledge[commit.hash]
        print("handling", commit.hash, cnt)
        # create node
        commit_node = n4jdb.merge_node("Commit", get_commit_properties(commit))
        commit_element_id = commit_node["element_id"]
        # create parents
        for parent in commit.parents:
            parent_node = n4jdb.merge_node(
                "Commit",
                {"name": parent},
            )
            _ = n4jdb.create_relationship(
                parent_node["element_id"], commit_element_id, "PARENT_OF"
            )
            _ = n4jdb.create_relationship(
                commit_element_id, parent_node["element_id"], "CHILD_OF"
            )
        # create user
        date = commit.committer_date
        user_commit(
            commit_element_id, commit.author, commit.committer, commit.author_date, date
        )
        for file in commit.modified_files:
            try:
                match file.change_type:
                    case ModificationType.ADD:
                        fname = file.new_path
                        if not fname in commit_knowledge:
                            continue
                        file_change_node = n4jdb.merge_node(
                            "FileChange",
                            {
                                "file_name": fname,
                                "change_type": "ADD",
                                "modify_in": date,
                            },
                        )
                        _ = n4jdb.create_relationship(
                            commit_element_id,
                            file_change_node["element_id"],
                            "ADD_FILE",
                            {"date": date},
                        )
                        file_add(file_change_node, fname, commit_knowledge[fname])
                    case ModificationType.RENAME:
                        fname, ofname = file.new_path, file.old_path
                        ofile_change_node = n4jdb.match_nodes(
                            "FileChange", {"file_name": ofname}, limit=1
                        )[0]
                        file_change_node = n4jdb.copy_node_and_relations(
                            ofile_change_node["element_id"],
                            {
                                "file_name": fname,
                                "change_type": "RENAME",
                                "modify_in": date,
                            },
                        )
                        _ = n4jdb.create_relationship(
                            commit_element_id,
                            file_change_node["element_id"],
                            "RENAME_FILE",
                            {"date": date},
                        )
                    case ModificationType.DELETE:
                        fname = file.old_path
                        if not fname in commit_knowledge:
                            continue
                        file_change_node = n4jdb.merge_node(
                            "FileChange",
                            {
                                "file_name": fname,
                                "change_type": "DELETE",
                                "modify_in": date,
                            },
                        )
                        _ = n4jdb.create_relationship(
                            commit_element_id,
                            file_change_node["element_id"],
                            "DELETE_FILE",
                            {"date": date},
                        )
                        file_del(file_change_node, fname, commit_knowledge[fname])
                    case ModificationType.MODIFY:
                        fname = file.old_path
                        if not fname in commit_knowledge:
                            continue
                        file_change_node = n4jdb.merge_node(
                            "FileChange",
                            {
                                "file_name": fname,
                                "change_type": "MODIFY",
                                "modify_in": date,
                            },
                        )
                        _ = n4jdb.create_relationship(
                            commit_element_id,
                            file_change_node["element_id"],
                            "MODIFY_FILE",
                            {"date": date},
                        )
                        file_mod(file_change_node, fname, commit_knowledge[fname])

            except Exception as e:
                print(e)

        # if len(file.changed_methods) > 0:
        #     print(
        #         "{} modified {}, complexity: {}, and contains {} methods".format(
        #             author.name,
        #             file.filename,
        #             len(file.changed_methods),
        #         )
        #     )


def user_commit(
    commit_element_id: str,
    author: Developer,
    committer: Developer,
    author_date: datetime,
    committer_date: datetime,
):
    if author != committer:
        author_node = n4jdb.merge_node(
            ["User", "Author"],
            {"name": author.name, "email": author.email},
        )
        _ = n4jdb.create_relationship(
            author_node["element_id"],
            commit_element_id,
            "COMMIT",
            {"date": author_date},
        )
        committer_node = n4jdb.merge_node(
            ["User", "Committer"],
            {"name": committer.name, "email": committer.email},
        )
        _ = n4jdb.create_relationship(
            committer_node["element_id"],
            commit_element_id,
            "COMMIT",
            {"date": committer_date},
        )
    else:
        committer_node = n4jdb.merge_node(
            ["User", "Committer", "Author"],
            {"name": committer.name, "email": committer.email},
        )
        _ = n4jdb.create_relationship(
            committer_node["element_id"],
            commit_element_id,
            "COMMIT",
            {"date": committer_date},
        )


def file_add(fc_node, fname, feat_dict: dict[str, object]):
    if not isinstance(feat_dict, dict):
        return
    fcid = fc_node["element_id"]
    for feat, ident in feat_dict.items():
        if chk_no_in_str(feat):
            continue
        feat_node = n4jdb.merge_node(
            "Feature", {"name": feat, "ident": ident, "add_from": fname, "add_by": fcid}
        )
        _ = n4jdb.create_relationship(fcid, feat_node["element_id"], "ADD_FEAT")


def file_del(fc_node, fname, feat_dict: dict[str, object]):
    if not isinstance(feat_dict, dict):
        return
    fcid = fc_node["element_id"]
    for feat, ident in feat_dict.items():
        if chk_no_in_str(feat):
            continue
        feat_node = n4jdb.merge_node(
            "Feature", {"name": feat, "ident": ident, "delete_from": fname, "delete_by": fcid}
        )
        _ = n4jdb.create_relationship(fcid, feat_node["element_id"], "DELETE_FEAT")


def file_mod(fc_node, fname, feat_dict: dict[str, dict]):
    if "add" in feat_dict:
        file_add(fc_node, fname, feat_dict["add"])
    if "delete" in feat_dict:
        file_del(fc_node, fname, feat_dict["delete"])
    if "modify" in feat_dict:
        if not isinstance(feat_dict["modify"], dict):
            return
        fcid = fc_node["element_id"]
        for feat, ident in feat_dict["modify"].items():
            if chk_no_in_str(feat):
                continue
            feat_node = n4jdb.merge_node(
                "Feature",
                {"name": feat, "ident": ident, "modify_from": fname, "modify_by": fcid},
            )
            _ = n4jdb.create_relationship(fcid, feat_node["element_id"], "MODIFY_FEAT")


def chk_no_in_str(s: str):
    lowered = s[:min(8, len(s))].lower()
    if lowered.find("no") != -1 and lowered[0].isalpha():
        return True
    return False


def get_commit_properties(commit: Commit):
    return {
        "name": commit.hash,
        "author_name": commit.author.name,  # nested properties not supported
        "author_email": commit.author.email,
        "author_date": commit.author_date,
        "branches": list(commit.branches),
        "committer_name": commit.committer.name,
        "committer_email": commit.committer.email,
        "committer_date": commit.committer_date,
        "deletions": commit.deletions,
        "files": commit.files,
        "in_main_branch": commit.in_main_branch,
        "insertions": commit.insertions,
        "lines": commit.lines,
        "merge": commit.merge,
        "msg": commit.msg,
        "parents": commit.parents,
    }


def load_json(fname_no_ext: str):
    with open(fname_no_ext + ".json") as f:
        return json.load(f)


if __name__ == "__main__":
    REPO_NAME = "grep-ast"
    JSON_NAME = f"{REPO_NAME}_llama3-70b-8192_deepseek-v3_1744565333"
    WORK_DIR = path.dirname(__file__)
    chdir(WORK_DIR)
    REPO_PATH = path.join(WORK_DIR, path.pardir, "proj", REPO_NAME)
    data = load_json(JSON_NAME)
    travese_commits(REPO_PATH, knowledge=data)


# rename in 580b732e630c9eabb189fc63ac904a048b82902a 02d5167c4023dcc48c1c81499cbbcc1bf0615824 b1e7f9603f701bb97ae3a4a3fcbed47c887d074a