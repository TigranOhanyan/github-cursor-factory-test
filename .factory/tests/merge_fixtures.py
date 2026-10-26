#!/usr/bin/env python3
"""Fixture checks for github/workflows/merge.yml.

Runs the workflow script against a fake gh, and runs the jq filters
against review and check fixtures. This file is for the factory
repository. A host does not copy it.
"""

import json
import os
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "github" / "workflows" / "merge.yml"
HEAD = "a" * 40
OLD = "b" * 40
REPO = "acme/host"


def extract_script():
    lines = []
    capture = False
    for line in WORKFLOW.read_text().splitlines():
        if line == "        run: |":
            capture = True
            lines = []
            continue
        if not capture:
            continue
        if line.startswith("          "):
            lines.append(line[10:])
        elif line == "":
            lines.append("")
        else:
            break
    if not lines or not lines[0].startswith("set -euo pipefail"):
        raise SystemExit("could not extract the merge script")
    return "\n".join(lines) + "\n"


def extract_filter(script, name):
    start = script.index(f"{name}=\"$(cat <<'EOF'\n") + len(f"{name}=\"$(cat <<'EOF'\n")
    end = script.index("\nEOF\n", start)
    return script[start:end]


SCRIPT = extract_script()
APPROVALS = extract_filter(SCRIPT, "approvals_filter")
CHECKS = extract_filter(SCRIPT, "checks_filter")


def jq(program, args):
    proc = subprocess.run(
        ["jq", "-n", *args, program],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"jq failed: {proc.stderr}")
    return json.loads(proc.stdout)


def review(login, state, commit, submitted, rid):
    user = None if login is None else {"login": login}
    return {
        "id": rid,
        "user": user,
        "state": state,
        "commit_id": commit,
        "submitted_at": submitted,
    }


def check_run(name, status, conclusion, app="github-actions", rid=5, cid=2, started="2026-01-01T00:00:00Z"):
    return {
        "id": cid,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "started_at": started,
        "details_url": f"https://github.com/o/r/actions/runs/{rid}/job/{cid}",
        "app": None if app is None else {"slug": app},
    }


def status(context, state, updated, sid):
    return {
        "id": sid,
        "context": context,
        "state": state,
        "updated_at": updated,
        "created_at": updated,
    }


OWN = check_run("Factory merge", "in_progress", None, rid=999, cid=1)
PLAN = check_run("plan", "completed", "success", rid=5, cid=2)
APPLY = check_run("apply", "completed", "skipped", rid=5, cid=3)
GREEN = [OWN, PLAN, APPLY]


def run_approvals(reviews, allow, head=HEAD):
    return jq(
        APPROVALS,
        [
            "--argjson",
            "reviews",
            json.dumps(reviews),
            "--argjson",
            "allow",
            json.dumps(allow),
            "--arg",
            "head",
            head,
        ],
    )


def run_checks(checks, statuses, names, run_id="999"):
    return jq(
        CHECKS,
        [
            "--argjson",
            "checks",
            json.dumps(checks),
            "--argjson",
            "statuses",
            json.dumps(statuses),
            "--argjson",
            "names",
            json.dumps(names),
            "--arg",
            "run_id",
            run_id,
            "--arg",
            "job_name",
            "Factory merge",
        ],
    )


def pr_body(number=7, draft=False, state="open", sha=HEAD, repo=REPO, merged=False, base="develop"):
    return {
        "number": int(number),
        "draft": draft,
        "state": state,
        "merged": merged,
        "head": {
            "sha": sha,
            "repo": None if repo is None else {"full_name": repo},
        },
        "base": {"ref": base},
    }


class Case:
    def __init__(self, name):
        self.name = name
        self.event_name = "pull_request"
        self.event = {"pull_request": {"number": 7}}
        self.env = {}
        self.prs = {"7": pr_body()}
        self.reviews = {
            "7": [
                review("gcf-reviewer-1[bot]", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1),
                review("gcf-reviewer-2[bot]", "APPROVED", HEAD, "2026-01-01T00:00:01Z", 2),
            ]
        }
        self.checks = {HEAD: list(GREEN)}
        self.statuses = {HEAD: []}
        self.pulls = []
        self.pr_list = []
        self.fail_pulls = []
        self.fail_reviews = []
        self.merge_fail = []
        self.already_merged = []
        self.expect_code = 0
        self.expect_merged = ["7"]
        self.expect_log = []
        self.forbid_log = []


def run_case(case):
    work = pathlib.Path(tempfile.mkdtemp(prefix=f"merge-{case.name}-"))
    try:
        fixtures = {
            "prs": case.prs,
            "reviews": case.reviews,
            "checks": case.checks,
            "statuses": case.statuses,
            "pulls": case.pulls,
            "pr_list": case.pr_list,
            "fail_pulls": case.fail_pulls,
            "fail_reviews": case.fail_reviews,
            "merge_fail": case.merge_fail,
            "already_merged": case.already_merged,
        }
        (work / "fixtures.json").write_text(json.dumps(fixtures))
        (work / "event.json").write_text(json.dumps(case.event))
        (work / "calls").write_text("")
        (work / "gets.json").write_text("{}")
        (work / "merged").write_text("")
        (work / "gh").write_text(MOCK)
        os.chmod(work / "gh", 0o755)
        (work / "script.sh").write_text(SCRIPT)
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{work}:{env['PATH']}",
                "MOCK_STATE": str(work),
                "GITHUB_EVENT_NAME": case.event_name,
                "GITHUB_EVENT_PATH": str(work / "event.json"),
                "GITHUB_REPOSITORY": REPO,
                "GITHUB_REF_NAME": "feature",
                "GITHUB_RUN_ID": "999",
                "GH_TOKEN": "fake",
                "GH_REPO": REPO,
                "FACTORY_REQUIRED_APPROVALS": "",
                "FACTORY_REVIEWER_LOGINS": "gcf-reviewer-1[bot], gcf-reviewer-2[bot]",
                "FACTORY_REQUIRED_CHECKS": "",
            }
        )
        env.update(case.env)
        proc = subprocess.run(
            ["bash", str(work / "script.sh")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        merged = [line for line in (work / "merged").read_text().splitlines() if line]
        calls = [json.loads(line) for line in (work / "calls").read_text().splitlines() if line]
        log = proc.stdout + proc.stderr
        problems = []
        if proc.returncode != case.expect_code:
            problems.append(f"exit {proc.returncode}, expected {case.expect_code}")
        if merged != case.expect_merged:
            problems.append(f"merged {merged}, expected {case.expect_merged}")
        for text in case.expect_log:
            if text not in log:
                problems.append(f"log missing {text!r}")
        for text in case.forbid_log:
            if text in log:
                problems.append(f"log unexpectedly contained {text!r}")
        return problems, log, calls
    finally:
        shutil.rmtree(work)


MOCK = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

state = Path(os.environ["MOCK_STATE"])
args = sys.argv[1:]
with (state / "calls").open("a") as fh:
    fh.write(json.dumps(args) + "\n")
fixtures = json.loads((state / "fixtures.json").read_text())

def endpoint_of(argv):
    for arg in argv:
        if not arg.startswith("-"):
            return arg
    return ""

def respond(payload):
    if "--jq" in args:
        expr = args[args.index("--jq") + 1]
        proc = __import__("subprocess").run(
            ["jq", "-r", expr],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
        )
        sys.stdout.write(proc.stdout)
        sys.exit(proc.returncode)
    print(json.dumps(payload))

if args[:2] == ["pr", "list"]:
    numbers = fixtures.get("pr_list", [])
    expr = args[args.index("--jq") + 1]
    proc = __import__("subprocess").run(
        ["jq", "-r", expr],
        input=json.dumps([{"number": n} for n in numbers]),
        text=True,
        capture_output=True,
    )
    sys.stdout.write(proc.stdout)
    sys.exit(proc.returncode)

if args[:2] == ["pr", "merge"]:
    number = args[2]
    with (state / "merged").open("a") as fh:
        if number in fixtures.get("merge_fail", []) or number in fixtures.get("already_merged", []):
            print("merge refused", file=sys.stderr)
            sys.exit(1)
        fh.write(number + "\n")
    print("merged")
    sys.exit(0)

if not args or args[0] != "api":
    print("unexpected gh " + " ".join(args), file=sys.stderr)
    sys.exit(1)

endpoint = endpoint_of(args[1:])
slurp = "--slurp" in args

def emit(page):
    respond([page] if slurp else page)

if "/check-runs" in endpoint:
    sha = endpoint.split("/commits/")[1].split("/")[0]
    runs = fixtures.get("checks", {}).get(sha, [])
    emit({"total_count": len(runs), "check_runs": runs})
    sys.exit(0)

if "/statuses" in endpoint:
    sha = endpoint.split("/commits/")[1].split("/")[0]
    emit(fixtures.get("statuses", {}).get(sha, []))
    sys.exit(0)

if endpoint.endswith("/reviews"):
    number = endpoint.split("/pulls/")[1].split("/")[0]
    if number in fixtures.get("fail_reviews", []):
        print("reviews failed", file=sys.stderr)
        sys.exit(1)
    emit(fixtures.get("reviews", {}).get(number, []))
    sys.exit(0)

if "pulls?" in endpoint or endpoint.endswith("/pulls"):
    emit(fixtures.get("pulls", []))
    sys.exit(0)

if "/pulls/" in endpoint:
    number = endpoint.rstrip("/").rsplit("/", 1)[-1]
    if number in fixtures.get("fail_pulls", []):
        print("pull failed", file=sys.stderr)
        sys.exit(1)
    gets = json.loads((state / "gets.json").read_text())
    gets[number] = gets.get(number, 0) + 1
    (state / "gets.json").write_text(json.dumps(gets))
    body = json.loads(json.dumps(fixtures["prs"][number]))
    if number in fixtures.get("already_merged", []) and gets[number] >= 2:
        body["merged"] = True
        body["state"] = "closed"
    respond(body)
    sys.exit(0)

print("unhandled " + endpoint, file=sys.stderr)
sys.exit(1)
'''


def test_jq():
    allow = ["gcf-reviewer-1[bot]", "gcf-reviewer-2[bot]"]
    failures = []

    def expect(name, reviews, count, counted, allow_list=None):
        got = run_approvals(reviews, allow if allow_list is None else allow_list)
        if got["count"] != count or got["counted"] != counted:
            failures.append(f"{name}: {got}")

    expect(
        "two approvals",
        [
            review("gcf-reviewer-1[bot]", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1),
            review("gcf-reviewer-2[bot]", "APPROVED", HEAD, "2026-01-01T00:00:01Z", 2),
        ],
        2,
        ["gcf-reviewer-1[bot]", "gcf-reviewer-2[bot]"],
    )
    expect(
        "later changes requested overrides",
        [
            review("gcf-reviewer-1[bot]", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1),
            review("gcf-reviewer-1[bot]", "CHANGES_REQUESTED", HEAD, "2026-01-02T00:00:00Z", 2),
        ],
        0,
        [],
    )
    expect(
        "comment does not override",
        [
            review("gcf-reviewer-1[bot]", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1),
            review("gcf-reviewer-1[bot]", "COMMENTED", HEAD, "2026-01-02T00:00:00Z", 2),
        ],
        1,
        ["gcf-reviewer-1[bot]"],
    )
    expect(
        "comment never counts",
        [review("gcf-reviewer-1[bot]", "COMMENTED", HEAD, "2026-01-01T00:00:00Z", 1)],
        0,
        [],
    )
    expect(
        "stale sha",
        [review("gcf-reviewer-1[bot]", "APPROVED", OLD, "2026-01-01T00:00:00Z", 1)],
        0,
        [],
    )
    expect(
        "dismissed",
        [
            review("gcf-reviewer-1[bot]", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1),
            review("gcf-reviewer-1[bot]", "DISMISSED", HEAD, "2026-01-02T00:00:00Z", 2),
        ],
        0,
        [],
    )
    expect(
        "first login counts",
        [review("gcf-reviewer-1[bot]", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1)],
        1,
        ["gcf-reviewer-1[bot]"],
    )
    expect(
        "person login counts",
        [review("octocat", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1)],
        1,
        ["octocat"],
        allow_list=["octocat"],
    )
    expect("outsider", [review("someone", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1)], 0, [])

    def expect_checks(name, checks, statuses, names, blocking_names, required):
        got = run_checks(checks, statuses, names)
        blocking = [item["name"] for item in got["blocking_checks"]]
        report = [(item["name"], item["reason"]) for item in got["required_report"]]
        if blocking != blocking_names or report != required:
            failures.append(f"{name}: blocking={blocking} required={report} full={got}")

    expect_checks("skipped is not blocking when not required", GREEN, [], [], [], [])
    expect_checks(
        "required success",
        GREEN,
        [],
        ["plan"],
        [],
        [],
    )
    expect_checks(
        "required missing",
        GREEN,
        [],
        ["deploy"],
        [],
        [("deploy", "missing")],
    )
    expect_checks(
        "required skipped is not success",
        [OWN, check_run("plan", "completed", "skipped", rid=5, cid=2)],
        [],
        ["plan"],
        [],
        [("plan", "not successful")],
    )
    expect_checks(
        "required failure",
        [OWN, check_run("plan", "completed", "failure", rid=5, cid=2)],
        [],
        ["plan"],
        ["plan"],
        [("plan", "not successful")],
    )
    expect_checks(
        "required status success",
        GREEN,
        [status("ci/circle", "success", "2026-01-01T00:00:00Z", 1)],
        ["ci/circle"],
        [],
        [],
    )
    expect_checks(
        "required status missing",
        GREEN,
        [],
        ["ci/circle"],
        [],
        [("ci/circle", "missing")],
    )
    expect_checks(
        "own check is not the required name",
        GREEN,
        [],
        ["Factory merge"],
        [],
        [("Factory merge", "missing")],
    )
    expect_checks("empty names keep today", GREEN, [], [], [], [])
    if failures:
        raise SystemExit("jq fixtures failed:\n" + "\n".join(failures))
    print(f"jq fixtures ok")


def cases():
    happy = Case("happy")
    happy.expect_log = ["Requiring 2, the number of listed logins.", "Finished."]
    yield happy

    one = Case("one-approval")
    one.reviews["7"] = [review("gcf-reviewer-1[bot]", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1)]
    one.expect_merged = []
    one.expect_log = ["does not meet the merge conditions"]
    yield one

    single = Case("default-is-login-count")
    single.env = {
        "FACTORY_REVIEWER_LOGINS": "octocat",
        "FACTORY_REQUIRED_APPROVALS": "",
    }
    single.reviews["7"] = [review("octocat", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1)]
    single.expect_log = ["Requiring 1, the number of listed logins."]
    yield single

    too_high = Case("required-higher-than-logins")
    too_high.env = {"FACTORY_REQUIRED_APPROVALS": "3"}
    too_high.expect_code = 1
    too_high.expect_merged = []
    too_high.expect_log = [
        "FACTORY_REQUIRED_APPROVALS is 3, but FACTORY_REVIEWER_LOGINS lists 2 login(s)."
    ]
    yield too_high

    bad = Case("required-not-integer")
    bad.env = {"FACTORY_REQUIRED_APPROVALS": "two"}
    bad.expect_code = 1
    bad.expect_merged = []
    bad.expect_log = ["must be a non-negative integer"]
    yield bad

    blank = Case("blank-required-is-unset")
    blank.env = {"FACTORY_REQUIRED_APPROVALS": "   "}
    blank.expect_log = ["FACTORY_REQUIRED_APPROVALS is unset."]
    yield blank

    commented = Case("comment-after-approval")
    commented.reviews["7"] = [
        review("gcf-reviewer-1[bot]", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1),
        review("gcf-reviewer-2[bot]", "APPROVED", HEAD, "2026-01-01T00:00:01Z", 2),
        review("gcf-reviewer-1[bot]", "COMMENTED", HEAD, "2026-01-03T00:00:00Z", 3),
    ]
    yield commented

    changes = Case("changes-requested")
    changes.reviews["7"] = [
        review("gcf-reviewer-1[bot]", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1),
        review("gcf-reviewer-2[bot]", "APPROVED", HEAD, "2026-01-01T00:00:01Z", 2),
        review("gcf-reviewer-2[bot]", "CHANGES_REQUESTED", HEAD, "2026-01-03T00:00:00Z", 4),
    ]
    changes.expect_merged = []
    yield changes

    stale = Case("stale-sha")
    stale.reviews["7"] = [
        review("gcf-reviewer-1[bot]", "APPROVED", OLD, "2026-01-01T00:00:00Z", 1),
        review("gcf-reviewer-2[bot]", "APPROVED", HEAD, "2026-01-01T00:00:01Z", 2),
    ]
    stale.expect_merged = []
    yield stale

    draft = Case("draft")
    draft.prs["7"] = pr_body(draft=True)
    draft.expect_merged = []
    draft.expect_log = ["is a draft"]
    yield draft

    fork = Case("fork")
    fork.prs["7"] = pr_body(repo="other/fork")
    fork.expect_merged = []
    fork.expect_log = ["another repository"]
    yield fork

    missing_required = Case("required-check-missing")
    missing_required.env = {"FACTORY_REQUIRED_CHECKS": "deploy"}
    missing_required.expect_merged = []
    missing_required.expect_log = ["required deploy: missing"]
    yield missing_required

    required_ok = Case("required-check-present")
    required_ok.env = {"FACTORY_REQUIRED_CHECKS": " plan , ci/circle "}
    required_ok.statuses[HEAD] = [status("ci/circle", "success", "2026-01-01T00:00:00Z", 1)]
    required_ok.expect_log = ["Required checks: [\"ci/circle\",\"plan\"]"]
    yield required_ok

    required_skip = Case("required-check-skipped")
    required_skip.env = {"FACTORY_REQUIRED_CHECKS": "apply"}
    required_skip.expect_merged = []
    required_skip.expect_log = ["required apply: not successful"]
    yield required_skip

    status_missing = Case("required-status-missing")
    status_missing.env = {"FACTORY_REQUIRED_CHECKS": "ci/circle"}
    status_missing.expect_merged = []
    status_missing.expect_log = ["required ci/circle: missing"]
    yield status_missing

    sweep = Case("schedule-sweep")
    sweep.event_name = "schedule"
    sweep.event = {"schedule": "*/10 * * * *"}
    sweep.prs = {
        "1": pr_body(number=1, base="develop"),
        "4": pr_body(number=4, base="release"),
    }
    sweep.reviews = {
        "1": [
            review("gcf-reviewer-1[bot]", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1),
            review("gcf-reviewer-2[bot]", "APPROVED", HEAD, "2026-01-01T00:00:01Z", 2),
        ],
        "4": [review("gcf-reviewer-1[bot]", "APPROVED", HEAD, "2026-01-01T00:00:00Z", 1)],
    }
    sweep.pulls = [
        pr_body(number=1, base="develop"),
        pr_body(number=2, draft=True, base="main"),
        pr_body(number=3, repo="other/fork", base="main"),
        pr_body(number=4, base="release"),
    ]
    sweep.expect_merged = ["1"]
    sweep.expect_log = ["Finished."]
    sweep.forbid_log = ["Pull request #2", "Pull request #3"]
    yield sweep

    keep_going = Case("api-error-does-not-stop-the-next")
    keep_going.event_name = "check_suite"
    keep_going.event = {"check_suite": {"pull_requests": [{"number": 7}, {"number": 8}]}}
    keep_going.prs["8"] = pr_body(number=8, base="release")
    keep_going.reviews["8"] = keep_going.reviews["7"]
    keep_going.fail_pulls = ["7"]
    keep_going.expect_code = 1
    keep_going.expect_merged = ["8"]
    keep_going.expect_log = ["Could not read pull request #7.", "Pull request #7 failed.", "Finished."]
    yield keep_going

    raced = Case("already-merged-is-success")
    raced.event_name = "check_suite"
    raced.event = {"check_suite": {"pull_requests": [{"number": 7}, {"number": 8}]}}
    raced.prs["8"] = pr_body(number=8)
    raced.reviews["8"] = raced.reviews["7"]
    raced.already_merged = ["7"]
    raced.expect_code = 0
    raced.expect_merged = ["8"]
    raced.expect_log = ["Pull request #7 is already merged.", "Finished."]
    yield raced

    refused = Case("refused-merge-continues")
    refused.event_name = "check_suite"
    refused.event = {"check_suite": {"pull_requests": [{"number": 7}, {"number": 8}]}}
    refused.prs["8"] = pr_body(number=8)
    refused.reviews["8"] = refused.reviews["7"]
    refused.merge_fail = ["7"]
    refused.expect_code = 1
    refused.expect_merged = ["8"]
    refused.expect_log = ["GitHub refused to merge pull request #7.", "Pull request #7 failed."]
    yield refused


def main():
    test_jq()
    failed = 0
    ran = 0
    for case in cases():
        ran += 1
        problems, log, _calls = run_case(case)
        if problems:
            failed += 1
            print(f"FAIL {case.name}: {'; '.join(problems)}")
            print(log)
        else:
            print(f"ok {case.name}")
    if failed:
        raise SystemExit(f"{failed} script fixture(s) failed")
    print(f"{ran} script fixtures ok")


if __name__ == "__main__":
    main()
