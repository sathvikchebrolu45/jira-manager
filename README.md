# Jira Manager

A local toolkit for managing Jira tickets for the **MID1** project — with both a
Streamlit web dashboard and a CLI, plus Excel import/export helpers.

## Features

- **📝 Create Stories** — bulk-create Jira stories from the UI or an Excel sheet
- **📊 Jira Data Sync** — pull issues into a table / JSON / Excel export with
  flexible filters (date range, issue type, status, parent/epic)
- **🗑️ Delete Tickets** — preview and safely bulk-delete tickets by key
- **📈 Manager Dashboard** — manager-friendly overview: total epics/stories,
  open vs. closed counts, status & issue-type breakdowns, per-epic progress,
  and open workload by assignee
- **excel_jira.py** — standalone CLI for generating templates, bulk-creating
  stories from Excel, and syncing Jira data back to Excel
- **cli.py** — additional command-line Jira utilities

## Requirements

- Python 3.11+
- A Jira Cloud account with an [API token](https://id.atlassian.com/manage-profile/security/api-tokens)

## Setup

```bash
pip install -r requirements.txt
```

## Usage

### Web Dashboard (Streamlit)

```bash
streamlit run app.py
```

Enter your Jira email and API token in the sidebar, pick a board, and use the
tabs to create stories, sync data, delete tickets, or view the manager
dashboard.

### CLI (Excel ↔ Jira)

```bash
python excel_jira.py
```

Follow the interactive prompts to generate an Excel template, bulk-create
stories, or sync Jira data to Excel.

## Configuration

Project key, base URL, and board IDs are defined at the top of `app.py` and
`excel_jira.py`:

```python
JIRA_BASE_URL = "https://maersk-tools.atlassian.net"
JIRA_PROJECT  = "MID1"
```

Update these to point at your own Jira instance/project as needed.

## Notes

- Credentials are stored only in your browser session (Streamlit) or in
  `~/.jira_cli_creds` (CLI, `chmod 600`) — never committed to source control.
- Deletion actions are permanent; the dashboard always shows a preview and
  requires explicit confirmation before deleting tickets.
