#!/usr/bin/env python3
import json
import os
import sys
from datetime import datetime, timedelta

import inquirer
import requests
from requests.auth import HTTPBasicAuth
from rich.console import Console
from rich.table import Table
from rich import print as rprint

console = Console()

JIRA_BASE_URL = "https://maersk-tools.atlassian.net"
JIRA_PROJECT  = "MID1"

BOARDS = {
    "WS4 - AI/ML":        41741,
    "MIDAS - Cloud Gov":  43666,
    "MIDAS - SMUS (K)":   47357,
    "WS1 - DBX":          40984,
    "WS2 - FEP Decking":  47952,
}

STORY_POINTS = {
    "0 – Not set":              0,
    "1 – Trivial (1-2 hrs)":    1,
    "2 – Small (half day)":     2,
    "3 – Medium (1 day)":       3,
    "5 – Large (2-3 days)":     5,
    "8 – Very Large (near sprint)": 8,
    "13 – Too big, split it":  13,
}

# ── Credentials ───────────────────────────────────────────────────────────────

def get_credentials():
    creds_file = os.path.expanduser("~/.jira_cli_creds")
    email, token = "", ""

    if os.path.exists(creds_file):
        with open(creds_file) as f:
            data = json.load(f)
            email = data.get("email", "")
            token = data.get("token", "")
        console.print(f"\n[green]✅ Using saved credentials for:[/green] {email}")
        use_saved = inquirer.prompt([
            inquirer.Confirm("use", message="Use saved credentials?", default=True)
        ])
        if not use_saved or not use_saved["use"]:
            email, token = "", ""

    if not email or not token:
        answers = inquirer.prompt([
            inquirer.Text("email", message="Jira Email"),
            inquirer.Password("token", message="Jira API Token (generate at https://id.atlassian.com/manage-profile/security/api-tokens)"),
        ])
        email  = answers["email"]
        token  = answers["token"]
        save   = inquirer.prompt([inquirer.Confirm("save", message="Remember credentials?", default=True)])
        if save and save["save"]:
            with open(creds_file, "w") as f:
                json.dump({"email": email, "token": token}, f)
            os.chmod(creds_file, 0o600)
            console.print("[green]✅ Credentials saved.[/green]")

    return email, token


def validate_credentials(email, token):
    resp = requests.get(
        f"{JIRA_BASE_URL}/rest/api/3/myself",
        auth=HTTPBasicAuth(email, token),
        headers={"Accept": "application/json"},
        timeout=10,
    )
    if resp.status_code == 200:
        name = resp.json().get("displayName", "")
        console.print(f"[green]✅ Authenticated as:[/green] {name}")
        return True
    console.print(f"[red]❌ Authentication failed ({resp.status_code}). Check your email/token.[/red]")
    return False


def get_auth(email, token):
    return HTTPBasicAuth(email, token)


# ── Story Points Field ─────────────────────────────────────────────────────────

def get_story_points_field(email, token):
    resp = requests.get(
        f"{JIRA_BASE_URL}/rest/api/3/field",
        auth=get_auth(email, token),
        headers={"Accept": "application/json"},
        timeout=10,
    )
    if resp.status_code != 200:
        return None
    for field in resp.json():
        name = field.get("name", "").lower()
        if "story point" in name or "story_point" in name:
            return field["id"]
    return None


# ── Board selector ─────────────────────────────────────────────────────────────

def select_board():
    answer = inquirer.prompt([
        inquirer.List("board", message="Select Board", choices=list(BOARDS.keys()))
    ])
    name = answer["board"]
    board_id = BOARDS[name]
    board_url = f"{JIRA_BASE_URL}/jira/software/c/projects/{JIRA_PROJECT}/boards/{board_id}"
    console.print(f"[cyan]📋 Board:[/cyan] {name} → {board_url}")
    return name, board_id


# ── CREATE STORIES ─────────────────────────────────────────────────────────────

def create_stories(email, token):
    console.rule("[bold blue]📝 Create Jira Stories[/bold blue]")
    select_board()

    num = int(inquirer.prompt([
        inquirer.Text("n", message="How many stories to create?", default="1",
                      validate=lambda _, x: x.isdigit() and int(x) >= 1)
    ])["n"])

    sp_field = get_story_points_field(email, token)
    created, failed = [], []

    for i in range(num):
        console.rule(f"Story {i+1}")
        ans = inquirer.prompt([
            inquirer.Text("summary",  message="Summary (title)"),
            inquirer.Text("parent",   message="Parent Issue (optional, e.g. MID1-1221)", default=""),
            inquirer.Text("desc",     message="Description"),
            inquirer.List("priority", message="Priority",
                          choices=["Medium", "Highest", "High", "Low", "Lowest"]),
            inquirer.List("sp",       message="Story Points — How much effort does this task require?",
                          choices=list(STORY_POINTS.keys())),
            inquirer.Text("assignee", message="Assignee Email (optional)", default=""),
        ])

        if not ans["summary"].strip():
            console.print(f"[yellow]⚠️ Story {i+1} has no summary — skipped.[/yellow]")
            continue

        payload = {
            "fields": {
                "project":     {"key": JIRA_PROJECT},
                "summary":     ans["summary"],
                "issuetype":   {"name": "Story"},
                "priority":    {"name": ans["priority"]},
                "description": {
                    "type": "doc", "version": 1,
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": ans["desc"] or " "}]}],
                },
            }
        }

        sp_val = STORY_POINTS[ans["sp"]]
        if sp_val and sp_field:
            payload["fields"][sp_field] = float(sp_val)

        if ans["parent"].strip():
            payload["fields"]["parent"] = {"key": ans["parent"].strip().upper()}

        if ans["assignee"].strip():
            r = requests.get(
                f"{JIRA_BASE_URL}/rest/api/3/user/search",
                params={"query": ans["assignee"]},
                auth=get_auth(email, token),
                headers={"Accept": "application/json"},
                timeout=10,
            )
            if r.status_code == 200 and r.json():
                payload["fields"]["assignee"] = {"accountId": r.json()[0]["accountId"]}

        resp = requests.post(
            f"{JIRA_BASE_URL}/rest/api/3/issue",
            auth=get_auth(email, token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )

        if resp.status_code == 201:
            data = resp.json()
            url  = f"{JIRA_BASE_URL}/browse/{data['key']}"
            created.append({"key": data["key"], "summary": ans["summary"], "url": url})
            console.print(f"[green]✅ Created:[/green] [{data['key']}]({url}) — {ans['summary']}")
        else:
            failed.append({"summary": ans["summary"], "error": resp.text})
            console.print(f"[red]❌ Failed:[/red] {resp.text}")

    if created:
        console.print(f"\n[green]✅ {len(created)} ticket(s) created successfully![/green]")
    if failed:
        console.print(f"[red]❌ {len(failed)} ticket(s) failed.[/red]")


# ── DATA SYNC ──────────────────────────────────────────────────────────────────

def data_sync(email, token):
    console.rule("[bold blue]📊 Jira Data Sync[/bold blue]")
    select_board()

    today = datetime.today().date()
    ans = inquirer.prompt([
        inquirer.Text("start",  message="From date (YYYY-MM-DD)",
                      default=str(today - timedelta(days=30))),
        inquirer.Text("end",    message="To date (YYYY-MM-DD)", default=str(today)),
        inquirer.Checkbox("types", message="Issue Types",
                          choices=["Story", "Bug", "Task", "Epic", "Sub-task"],
                          default=["Story", "Bug", "Task"]),
        inquirer.Checkbox("statuses", message="Statuses (space to select, leave empty for all)",
                          choices=["To Do", "In Progress", "In Review", "Done", "Blocked"],
                          default=[]),
        inquirer.Text("parent", message="Filter by Parent Issue (optional, e.g. MID1-1221)", default=""),
        inquirer.Text("max",    message="Max results", default="100"),
    ])

    type_clause   = " OR ".join([f'issuetype = "{t}"' for t in ans["types"]]) if ans["types"] else 'issuetype in standardIssueTypes()'
    status_clause = (" AND (" + " OR ".join([f'status = "{s}"' for s in ans["statuses"]]) + ")") if ans["statuses"] else ""
    parent_clause = f' AND parent = {ans["parent"].strip().upper()}' if ans["parent"].strip() else ""
    date_clause   = f' AND created >= "{ans["start"]}" AND created <= "{ans["end"]}"' if not ans["parent"].strip() else ""

    jql = f'project = {JIRA_PROJECT} AND ({type_clause}){date_clause}{status_clause}{parent_clause} ORDER BY created DESC'

    console.print(f"\n[dim]JQL: {jql}[/dim]")

    with console.status("Fetching data from Jira..."):
        resp = requests.post(
            f"{JIRA_BASE_URL}/rest/api/3/search/jql",
            auth=get_auth(email, token),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json={"jql": jql, "maxResults": int(ans["max"]),
                  "fields": ["summary", "status", "issuetype", "priority", "assignee", "reporter", "created", "updated", "labels", "components"]},
            timeout=30,
        )

    if resp.status_code != 200:
        console.print(f"[red]❌ Failed: {resp.status_code}\n{resp.text}[/red]")
        return

    raw    = resp.json()
    issues = []
    for issue in raw.get("issues", []):
        f = issue.get("fields", {})
        issues.append({
            "key":       issue["key"],
            "url":       f"{JIRA_BASE_URL}/browse/{issue['key']}",
            "summary":   f.get("summary"),
            "issuetype": f.get("issuetype", {}).get("name"),
            "status":    f.get("status", {}).get("name"),
            "priority":  f.get("priority", {}).get("name"),
            "assignee":  f.get("assignee", {}).get("displayName") if f.get("assignee") else None,
            "reporter":  f.get("reporter", {}).get("displayName") if f.get("reporter") else None,
            "labels":    f.get("labels", []),
            "created":   f.get("created"),
            "updated":   f.get("updated"),
        })

    console.print(f"\n[green]✅ Fetched {len(issues)} of {raw.get('total', 0)} total issues.[/green]")

    # Table view
    table = Table(show_header=True, header_style="bold cyan")
    for col in ["Key", "Summary", "Type", "Status", "Priority", "Assignee"]:
        table.add_column(col)
    for i in issues:
        table.add_row(
            i["key"], (i["summary"] or "")[:60],
            i["issuetype"] or "", i["status"] or "",
            i["priority"] or "", i["assignee"] or "—",
        )
    console.print(table)

    # Save JSON
    save = inquirer.prompt([inquirer.Confirm("save", message="Save results to JSON file?", default=True)])
    if save and save["save"]:
        filename = f"jira_{JIRA_PROJECT}_{ans['start']}_{ans['end']}.json"
        with open(filename, "w") as f:
            json.dump(issues, f, indent=2, ensure_ascii=False)
        console.print(f"[green]✅ Saved to:[/green] {filename}")


# ── DELETE TICKETS ─────────────────────────────────────────────────────────────

def delete_tickets(email, token):
    console.rule("[bold red]🗑️ Delete Jira Tickets[/bold red]")
    console.print("[yellow]⚠️  Deletion is permanent and cannot be undone.[/yellow]\n")

    ans = inquirer.prompt([
        inquirer.Text("keys", message="Enter ticket key(s) to delete (comma-separated, e.g. MID1-100,MID1-101)")
    ])
    keys = [k.strip().upper() for k in ans["keys"].split(",") if k.strip()]

    if not keys:
        console.print("[yellow]No keys entered. Returning to menu.[/yellow]")
        return

    # Preview
    console.print("\n[cyan]Fetching ticket details...[/cyan]")
    found, not_found = {}, []
    for key in keys:
        r = requests.get(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{key}",
            auth=get_auth(email, token),
            headers={"Accept": "application/json"},
            params={"fields": "summary,status,issuetype,assignee"},
            timeout=10,
        )
        if r.status_code == 200:
            f = r.json().get("fields", {})
            found[key] = {
                "summary":  f.get("summary", "—"),
                "type":     f.get("issuetype", {}).get("name", "—"),
                "status":   f.get("status", {}).get("name", "—"),
                "assignee": f.get("assignee", {}).get("displayName", "Unassigned") if f.get("assignee") else "Unassigned",
            }
        else:
            not_found.append(key)

    for k in not_found:
        console.print(f"[red]❌ {k} — not found or no access[/red]")

    if not found:
        return

    table = Table(show_header=True, header_style="bold red")
    for col in ["Key", "Summary", "Type", "Status", "Assignee"]:
        table.add_column(col)
    for k, v in found.items():
        table.add_row(k, v["summary"][:60], v["type"], v["status"], v["assignee"])
    console.print(table)

    confirm = inquirer.prompt([
        inquirer.Confirm("go", message=f"Permanently delete {len(found)} ticket(s)? This cannot be undone!", default=False)
    ])
    if not confirm or not confirm["go"]:
        console.print("[yellow]Deletion cancelled.[/yellow]")
        return

    deleted, errors = [], []
    for key in found:
        r = requests.delete(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{key}",
            auth=get_auth(email, token),
            timeout=10,
        )
        if r.status_code == 204:
            deleted.append(key)
            console.print(f"[green]✅ Deleted:[/green] {key}")
        else:
            errors.append({"key": key, "error": r.text})
            console.print(f"[red]❌ Failed to delete {key}:[/red] {r.text}")

    console.print(f"\n[green]✅ {len(deleted)} deleted.[/green]" if deleted else "")
    console.print(f"[red]❌ {len(errors)} failed.[/red]" if errors else "")


# ── MAIN MENU ──────────────────────────────────────────────────────────────────

def main():
    console.print("\n[bold cyan]🎯 Jira Manager CLI[/bold cyan]")
    console.print(f"[dim]Project: {JIRA_PROJECT} | {JIRA_BASE_URL}[/dim]\n")

    email, token = get_credentials()
    if not validate_credentials(email, token):
        sys.exit(1)

    while True:
        ans = inquirer.prompt([
            inquirer.List("action", message="What would you like to do?", choices=[
                "📝 Create Stories",
                "📊 Jira Data Sync",
                "🗑️  Delete Tickets",
                "🚪 Exit",
            ])
        ])

        choice = ans["action"]
        if "Create" in choice:
            create_stories(email, token)
        elif "Sync" in choice:
            data_sync(email, token)
        elif "Delete" in choice:
            delete_tickets(email, token)
        elif "Exit" in choice:
            console.print("[cyan]Bye! 👋[/cyan]")
            break


if __name__ == "__main__":
    main()
