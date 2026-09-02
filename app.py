import streamlit as st
import requests
import json
import re
import pandas as pd
from datetime import datetime, timedelta
from requests.auth import HTTPBasicAuth

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Jira Manager",
    page_icon="🎯",
    layout="wide",
)

# ── Manager Dashboard styling (KPI cards, badges, progress bars) ─────────────
st.markdown("""
<style>
.kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 1.5rem;
}
.kpi-card {
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
    border: 1px solid rgba(128,128,128,0.25);
    padding: 1rem;
    text-align: center;
}
.kpi-label {
    font-size: 12px;
    opacity: 0.7;
    margin-bottom: 8px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
.kpi-value { font-size: 32px; font-weight: 700; }
.kpi-stale { border-left: 4px solid #f59e0b; }
.kpi-blocked { border-left: 4px solid #ef4444; }
.kpi-open { border-left: 4px solid #3b82f6; }
.kpi-closed { border-left: 4px solid #10b981; }
.badge {
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 4px;
    font-weight: 600;
    display: inline-block;
    margin-right: 6px;
}
.badge-stale { background: #fef3c7; color: #92400e; }
.badge-blocked { background: #fee2e2; color: #7f1d1d; }
.epics-overview { margin-top: 0.5rem; }
.epic-row {
    border-bottom: 1px solid rgba(128,128,128,0.25);
    padding: 16px 4px;
}
.epic-row:last-child { border-bottom: none; }
.epic-row.stale-left-border { border-left: 3px solid #f59e0b; padding-left: 12px; }
.epic-row.blocked-left-border { border-left: 3px solid #ef4444; padding-left: 12px; }
.epic-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; }
.epic-title { font-weight: 600; font-size: 15px; margin-bottom: 4px; }
.epic-title a:hover { text-decoration: underline !important; }
.epic-badges { margin-top: 6px; margin-bottom: 4px; }
.epic-meta { font-size: 13px; opacity: 0.65; margin-top: 4px; }
.epic-completion { text-align: right; min-width: 90px; }
.epic-percentage { font-size: 18px; font-weight: 700; }
.epic-done { font-size: 12px; opacity: 0.65; margin-top: 3px; }
.progress-bar {
    width: 100%;
    height: 8px;
    background: rgba(128,128,128,0.25);
    border-radius: 4px;
    overflow: hidden;
    margin-top: 10px;
}
.progress-fill { height: 100%; border-radius: 4px; }
.progress-fill-done { background: #10b981; }
.progress-fill-in-progress { background: #f59e0b; }
.progress-fill-pending { background: #3b82f6; }
.empty-state { text-align: center; padding: 2rem; opacity: 0.6; }
</style>
""", unsafe_allow_html=True)

JIRA_BASE_URL = "https://maersk-tools.atlassian.net"
JIRA_PROJECT  = "MID1"

BOARDS = {
    "WS4 - AI/ML":           41741,
    "MIDAS - Cloud Gov":     43666,
    "MIDAS - SMUS (K)":      47357,
    "WS1 - DBX":             40984,
    "WS2 - FEP Decking":     47952,
}

# ── Sidebar – credentials ─────────────────────────────────────────────────────
st.sidebar.title("🔐 Jira Credentials")
st.sidebar.markdown(
    "Don't have a token? "
    "[Generate one here](https://id.atlassian.com/manage-profile/security/api-tokens)",
    unsafe_allow_html=True,
)

# Initialise session state keys on first load
if "jira_email" not in st.session_state:
    st.session_state["jira_email"] = ""
if "jira_token" not in st.session_state:
    st.session_state["jira_token"] = ""
if "creds_saved" not in st.session_state:
    st.session_state["creds_saved"] = False

jira_email = st.sidebar.text_input(
    "Jira Email",
    value=st.session_state["jira_email"],
    placeholder="you@example.com",
)
jira_token = st.sidebar.text_input(
    "Jira API Token",
    value=st.session_state["jira_token"],
    type="password",
    placeholder="paste token here",
)

col_save, col_clear = st.sidebar.columns(2)
if col_save.button("💾 Remember", width="stretch", help="Save credentials for this browser session"):
    st.session_state["jira_email"] = jira_email
    st.session_state["jira_token"] = jira_token
    st.session_state["creds_saved"] = True
    st.sidebar.success("✅ Saved for this session!")

if col_clear.button("🗑️ Clear", width="stretch", help="Remove saved credentials"):
    st.session_state["jira_email"] = ""
    st.session_state["jira_token"] = ""
    st.session_state["creds_saved"] = False
    st.sidebar.info("Credentials cleared.")
    st.rerun()

if st.session_state["creds_saved"]:
    st.sidebar.caption("🟢 Credentials remembered for this session")

# ── Sidebar – board selector ──────────────────────────────────────────────────
ALL_BOARDS_LABEL = "🌐 All Boards (combined)"

st.sidebar.divider()
st.sidebar.title("📋 Board")
selected_board_name = st.sidebar.selectbox(
    "Select Board",
    options=[ALL_BOARDS_LABEL] + list(BOARDS.keys()),
    index=0,
)
selected_board_id = BOARDS.get(selected_board_name)  # None when "All Boards" is selected
if selected_board_id:
    board_url = f"{JIRA_BASE_URL}/jira/software/c/projects/{JIRA_PROJECT}/boards/{selected_board_id}"
else:
    board_url = f"{JIRA_BASE_URL}/jira/software/projects/{JIRA_PROJECT}/boards"
st.sidebar.caption(f"[🔗 Open board]({board_url})")

def get_auth():
    return HTTPBasicAuth(jira_email, jira_token)

def adf_to_text(node):
    """Flatten an Atlassian Document Format (ADF) body into plain text."""
    if not node:
        return ""
    parts = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "text":
                parts.append(n.get("text", ""))
            for child in n.get("content", []) or []:
                walk(child)
        elif isinstance(n, list):
            for item in n:
                walk(item)

    walk(node)
    return " ".join(p for p in parts if p).strip()

def fetch_issue_comments(auth, key):
    resp = requests.get(
        f"{JIRA_BASE_URL}/rest/api/3/issue/{key}/comment",
        auth=auth,
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if resp.status_code != 200:
        return []
    out = []
    for c in resp.json().get("comments", []):
        out.append({
            "key":     key,
            "author":  (c.get("author") or {}).get("displayName", ""),
            "created": (c.get("created") or "")[:10],
            "text":    adf_to_text(c.get("body")),
        })
    return out

def fetch_board_issues(auth, board_id, jql_clause, fields, max_results=1000):
    """Fetch issues for the given board_id (agile board API), or across the whole
    project when board_id is None (the "All Boards" selection), paginating either way.
    Returns (issues, error_response) — error_response is None on success."""
    issues = []
    if board_id is None:
        jql = f'project = {JIRA_PROJECT} AND {jql_clause}'
        next_page_token = None
        while True:
            body = {
                "jql":        jql,
                "maxResults": min(100, max_results - len(issues)),
                "fields":     fields.split(","),
            }
            if next_page_token:
                body["nextPageToken"] = next_page_token
            resp = requests.post(
                f"{JIRA_BASE_URL}/rest/api/3/search/jql",
                auth=auth,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json=body,
                timeout=30,
            )
            if resp.status_code != 200:
                return issues, resp
            raw = resp.json()
            batch = raw.get("issues", [])
            issues.extend(batch)
            next_page_token = raw.get("nextPageToken")
            if not next_page_token or not batch or len(issues) >= max_results:
                break
        return issues, None
    else:
        start_at = 0
        while True:
            resp = requests.get(
                f"{JIRA_BASE_URL}/rest/agile/1.0/board/{board_id}/issue",
                auth=auth,
                headers={"Accept": "application/json"},
                params={
                    "jql":        jql_clause,
                    "startAt":    start_at,
                    "maxResults": min(100, max_results - len(issues)),
                    "fields":     fields,
                },
                timeout=30,
            )
            if resp.status_code != 200:
                return issues, resp
            raw = resp.json()
            batch = raw.get("issues", [])
            issues.extend(batch)
            start_at += len(batch)
            if raw.get("isLast", True) or not batch or len(issues) >= max_results:
                break
        return issues, None

@st.cache_data(show_spinner=False)
def get_story_points_field(email, token):
    """Auto-detect the story points custom field ID for this Jira instance."""
    resp = requests.get(
        f"{JIRA_BASE_URL}/rest/api/3/field",
        auth=HTTPBasicAuth(email, token),
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

def validate_credentials():
    if not jira_email or not jira_token:
        st.warning("⚠️ Enter your Jira email and API token in the sidebar.")
        return False
    resp = requests.get(
        f"{JIRA_BASE_URL}/rest/api/3/myself",
        auth=get_auth(),
        headers={"Accept": "application/json"},
        timeout=10,
    )
    if resp.status_code == 200:
        return True
    st.error(f"❌ Authentication failed ({resp.status_code}). Check your email / token.")
    return False

def normalize_column_name(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")

def read_story_upload(uploaded_file):
    dataframe = pd.read_excel(uploaded_file)
    aliases = {
        "board_name": {"board", "board_name", "boardname"},
        "summary": {"summary", "title"},
        "priority": {"priority"},
        "parent_issue": {"parent", "parent_issue", "parent_key"},
        "description": {"description", "desc"},
        "assignee_email": {"assignee", "assignee_email", "assignee_mail"},
        "story_points": {"story_points", "story_point", "points"},
    }
    normalized = {}
    for column in dataframe.columns:
        normalized_name = normalize_column_name(column)
        for target, accepted_names in aliases.items():
            if normalized_name in accepted_names and target not in normalized:
                normalized[target] = column
                break

    missing = [name for name in ("summary",) if name not in normalized]
    if missing:
        raise ValueError("Required column missing: Summary")

    rows = []
    for row_number, (_, row) in enumerate(dataframe.iterrows(), start=2):
        get_value = lambda name: str(row[normalized[name]]).strip() if name in normalized and pd.notna(row[normalized[name]]) else ""
        if not get_value("summary"):
            continue
        rows.append({
            "row_number": row_number,
            "board_name": get_value("board_name"),
            "summary": get_value("summary"),
            "priority": get_value("priority") or "Medium",
            "parent_key": get_value("parent_issue"),
            "description": get_value("description"),
            "assignee_email": get_value("assignee_email"),
            "story_points": get_value("story_points"),
        })
    return rows

def canonical_priority(value):
    priorities = {"highest", "high", "medium", "low", "lowest"}
    value = value.strip().lower()
    return next((item.title() for item in priorities if item == value), "Medium")

def validate_board_name(value):
    if not value:
        return
    known_boards = {name.casefold() for name in BOARDS}
    if value.casefold() not in known_boards:
        raise ValueError(f"Unknown board name: {value}")

def create_story(email, token, story):
    validate_board_name(story["board_name"])
    payload = {
        "fields": {
            "project": {"key": JIRA_PROJECT},
            "summary": story["summary"],
            "issuetype": {"name": "Story"},
            "priority": {"name": canonical_priority(story["priority"])},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": story["description"] or " "}]}],
            },
        }
    }

    if story["story_points"]:
        sp_field = get_story_points_field(email, token)
        try:
            story_points = float(story["story_points"])
        except ValueError:
            story_points = 0
        if sp_field and story_points:
            payload["fields"][sp_field] = story_points

    if story["parent_key"]:
        payload["fields"]["parent"] = {"key": story["parent_key"].upper()}

    if story["assignee_email"]:
        user_resp = requests.get(
            f"{JIRA_BASE_URL}/rest/api/3/user/search",
            params={"query": story["assignee_email"]},
            auth=HTTPBasicAuth(email, token),
            headers={"Accept": "application/json"},
            timeout=10,
        )
        if user_resp.status_code == 200 and user_resp.json():
            payload["fields"]["assignee"] = {"accountId": user_resp.json()[0]["accountId"]}

    response = requests.post(
        f"{JIRA_BASE_URL}/rest/api/3/issue",
        auth=HTTPBasicAuth(email, token),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    if response.status_code != 201:
        raise RuntimeError(response.text)
    return response.json()

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(
    ["📝 Create Stories", "📊 Jira Data Sync", "🗑️ Delete Tickets", "📈 Manager Dashboard"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 – CREATE STORIES
# ═══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.header("📝 Create Jira Stories")
    st.caption(f"Board: **{selected_board_name}** — [Open in Jira]({board_url})")

    st.subheader("Create from Excel")
    uploaded_file = st.file_uploader("Upload an Excel sheet", type=["xlsx", "xls"], key="story_upload")
    if uploaded_file:
        try:
            uploaded_stories = read_story_upload(uploaded_file)
        except (KeyError, TypeError, ValueError, ImportError) as error:
            st.error(f"❌ Could not read the Excel sheet: {error}")
            uploaded_stories = []

        if uploaded_stories:
            st.dataframe(
                pd.DataFrame(uploaded_stories).drop(columns=["row_number"]),
                width="stretch",
                hide_index=True,
            )
            if st.button("🚀 Create Uploaded Stories", type="primary", width="stretch"):
                if not validate_credentials():
                    st.stop()
                created, failed = [], []
                with st.spinner("Creating Jira stories..."):
                    for story in uploaded_stories:
                        try:
                            data = create_story(jira_email, jira_token, story)
                            created.append((story, data))
                        except (KeyError, requests.RequestException, RuntimeError, ValueError) as error:
                            failed.append((story, str(error)))
                if created:
                    st.success(f"✅ Created {len(created)} ticket(s).")
                    for story, data in created:
                        key = data["key"]
                        st.markdown(f"- **[{key}]({JIRA_BASE_URL}/browse/{key})** — {story['summary']}")
                if failed:
                    st.error(f"❌ {len(failed)} row(s) failed.")
                    for story, error in failed:
                        st.write(f"Row {story['row_number']} — {story['summary']}: {error}")
        else:
            st.warning("No rows with a Summary value were found.")

    st.divider()
    st.subheader("Create manually")
    # ── How many stories? ────────────────────────────────────────────────────
    num_stories = st.number_input("Number of stories to create", min_value=1, max_value=20, value=1, step=1)

    stories = []
    for i in range(int(num_stories)):
        st.divider()
        st.subheader(f"Story {i + 1}")
        col1, col2 = st.columns([3, 1])
        with col1:
            summary = st.text_input(f"Summary (title) #{i+1}", key=f"summary_{i}", placeholder="As a user, I want to ...")
        with col2:
            priority = st.selectbox(f"Priority #{i+1}", ["Medium", "Highest", "High", "Low", "Lowest"], key=f"priority_{i}")

        parent_key = st.text_input(
            f"Parent Issue #{i+1} (optional)",
            key=f"parent_{i}",
            placeholder="e.g. MID1-1221",
        )

        description_text = st.text_area(
            f"Description #{i+1}",
            key=f"desc_{i}",
            placeholder="Detailed description, acceptance criteria, etc.",
            height=120,
        )

        col3, col4 = st.columns(2)
        with col3:
            sp_options = {
                "0 – Not set": 0, "1 – Trivial (1-2 hrs)": 1, "2 – Small (half day)": 2,
                "3 – Medium (1 day)": 3, "5 – Large (2-3 days)": 5,
                "8 – Very Large (near sprint)": 8, "13 – Too big, split it": 13,
            }
            sp_label = st.selectbox(f"Story Points #{i+1} — How much effort does this task require?", options=list(sp_options.keys()), key=f"sp_{i}")
            story_points = sp_options[sp_label]
        with col4:
            assignee_email = st.text_input(
                f"Assignee Email #{i+1} (optional)",
                key=f"assignee_{i}",
                placeholder="assignee@example.com",
            )

        stories.append({
            "summary": summary,
            "description": description_text,
            "priority": priority,
            "story_points": story_points,
            "assignee_email": assignee_email,
            "parent_key": parent_key,
        })

    st.divider()
    if st.button("🚀 Create Stories in Jira", type="primary", width="stretch"):
        if not validate_credentials():
            st.stop()

        created, failed = [], []

        for idx, story in enumerate(stories):
            if not story["summary"].strip():
                st.warning(f"⚠️ Story {idx+1} has no summary — skipped.")
                continue

            payload = {
                "fields": {
                    "project":   {"key": JIRA_PROJECT},
                    "summary":   story["summary"],
                    "issuetype": {"name": "Story"},
                    "priority":  {"name": story["priority"]},
                    "description": {
                        "type":    "doc",
                        "version": 1,
                        "content": [
                            {
                                "type":    "paragraph",
                                "content": [{"type": "text", "text": story["description"] or " "}],
                            }
                        ],
                    },
                }
            }

            # Story points — auto-detect the correct custom field ID
            if story["story_points"]:
                sp_field = get_story_points_field(jira_email, jira_token)
                if sp_field:
                    payload["fields"][sp_field] = float(story["story_points"])
                else:
                    st.warning("⚠️ Story points field not found on this Jira instance — skipped.")

            # Parent issue (optional)
            if story["parent_key"].strip():
                payload["fields"]["parent"] = {"key": story["parent_key"].strip().upper()}

            # Resolve assignee account ID from email
            if story["assignee_email"].strip():
                user_resp = requests.get(
                    f"{JIRA_BASE_URL}/rest/api/3/user/search",
                    params={"query": story["assignee_email"]},
                    auth=get_auth(),
                    headers={"Accept": "application/json"},
                    timeout=10,
                )
                if user_resp.status_code == 200 and user_resp.json():
                    payload["fields"]["assignee"] = {"accountId": user_resp.json()[0]["accountId"]}

            resp = requests.post(
                f"{JIRA_BASE_URL}/rest/api/3/issue",
                auth=get_auth(),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json=payload,
                timeout=15,
            )

            if resp.status_code == 201:
                data = resp.json()
                created.append({
                    "story_index": idx + 1,
                    "key":         data["key"],
                    "id":          data["id"],
                    "url":         f"{JIRA_BASE_URL}/browse/{data['key']}",
                    "summary":     story["summary"],
                })
            else:
                failed.append({
                    "story_index": idx + 1,
                    "summary":     story["summary"],
                    "error":       resp.text,
                })

        if created:
            st.success(f"✅ {len(created)} ticket(s) created successfully!")
            for t in created:
                st.markdown(f"- **[{t['key']}]({t['url']})** — {t['summary']}")
            with st.expander("📋 Created tickets JSON"):
                st.json(created)

        if failed:
            st.error(f"❌ {len(failed)} ticket(s) failed.")
            for f_item in failed:
                with st.expander(f"Story {f_item['story_index']} error"):
                    st.code(f_item["error"])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 – JIRA DATA SYNC
# ═══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.header("📊 Jira Data Sync")
    st.caption(f"Fetching from board **{selected_board_name}** — project **{JIRA_PROJECT}**. [Open in Jira]({board_url})")

    col1, col2 = st.columns(2)
    with col1:
        start_date = st.date_input("From date", value=datetime.today() - timedelta(days=30))
    with col2:
        end_date = st.date_input("To date", value=datetime.today())

    issue_types = st.multiselect(
        "Issue Types",
        ["Story", "Bug", "Task", "Epic", "Sub-task"],
        default=["Story", "Bug", "Task"],
    )

    statuses = st.multiselect(
        "Statuses (leave empty for all)",
        ["To Do", "In Progress", "In Review", "Done", "Blocked"],
        default=[],
    )

    max_results = st.slider("Max results", min_value=10, max_value=500, value=100, step=10)

    parent_filter = st.text_input(
        "Filter by Parent Issue (optional)",
        placeholder="e.g. MID1-1221",
        help="Only fetch child issues under this parent/epic key. Leave empty to fetch all.",
    )

    include_comments = st.checkbox(
        "💬 Also pull comments for each issue",
        value=False,
        help="Fetches all comments per issue via an extra API call each — slower for large result sets.",
    )

    if st.button("🔄 Sync Jira Data", type="primary", width="stretch"):
        if not validate_credentials():
            st.stop()

        # Build JQL — scoped to the selected board via the agile API below,
        # so switching boards in the sidebar actually changes what gets fetched here.
        type_clause   = " OR ".join([f'issuetype = "{t}"' for t in issue_types]) if issue_types else 'issuetype in standardIssueTypes()'
        status_clause = (" AND (" + " OR ".join([f'status = "{s}"' for s in statuses]) + ")") if statuses else ""
        parent_clause = f' AND parent = {parent_filter.strip().upper()}' if parent_filter.strip() else ""
        # Skip date filter when parent is specified — child issues may fall outside the range
        date_clause   = (f' AND created >= "{start_date}" AND created <= "{end_date}"') if not parent_filter.strip() else ""
        jql = (
            f'({type_clause})'
            f'{date_clause}'
            f'{status_clause}'
            f'{parent_clause}'
            f' ORDER BY created DESC'
        )

        all_issues, total = [], 0
        with st.spinner(f"Fetching data from {selected_board_name}..."):
            all_issues, err_resp = fetch_board_issues(
                get_auth(),
                selected_board_id,
                jql,
                "summary,status,issuetype,priority,assignee,reporter,created,updated,labels,components",
                max_results=max_results,
            )
            if err_resp is not None:
                st.error(f"❌ Failed to fetch data: {err_resp.status_code}\n{err_resp.text}")
                st.stop()
            total = len(all_issues)

        issues = []
        for issue in all_issues:
            f = issue.get("fields", {})
            issues.append({
                "key":         issue["key"],
                "id":          issue["id"],
                "url":         f"{JIRA_BASE_URL}/browse/{issue['key']}",
                "summary":     f.get("summary"),
                "issuetype":   f.get("issuetype", {}).get("name"),
                "status":      f.get("status", {}).get("name"),
                "priority":    f.get("priority", {}).get("name"),
                "assignee":    f.get("assignee", {}).get("displayName") if f.get("assignee") else None,
                "reporter":    f.get("reporter", {}).get("displayName") if f.get("reporter") else None,
                "labels":      f.get("labels", []),
                "components":  [c["name"] for c in f.get("components", [])],
                "created":     f.get("created"),
                "updated":     f.get("updated"),
            })

        st.success(f"✅ Fetched {len(issues)} matching issues on **{selected_board_name}**.")

        comments_by_key = {}
        all_comments = []
        if include_comments and issues:
            with st.spinner(f"Fetching comments for {len(issues)} issue(s)..."):
                for i in issues:
                    c = fetch_issue_comments(get_auth(), i["key"])
                    comments_by_key[i["key"]] = c
                    all_comments.extend(c)
            for i in issues:
                i["comments"] = comments_by_key.get(i["key"], [])
            st.success(f"✅ Fetched {len(all_comments)} comment(s) across {len(issues)} issue(s).")

        # Summary table
        if issues:
            import pandas as pd
            summary_cols = ["key", "summary", "issuetype", "status", "priority", "assignee", "created"]
            df = pd.DataFrame(issues)
            if include_comments:
                def _join_comments(k):
                    return "\n".join(f"{c['author']} ({c['created']}): {c['text']}" for c in comments_by_key.get(k, []))
                df["comments"] = df["key"].map(_join_comments)
                summary_cols = summary_cols + ["comments"]
            st.dataframe(df[summary_cols], width="stretch", row_height=100)

        if include_comments and all_comments:
            with st.expander(f"💬 Comments ({len(all_comments)})", expanded=False):
                st.dataframe(pd.DataFrame(all_comments)[["key", "author", "created", "text"]], width="stretch", row_height=100)

        # JSON output
        with st.expander("🗂️ Full JSON Output", expanded=True):
            st.json(issues)

        json_str = json.dumps(issues, indent=2, ensure_ascii=False)
        st.download_button(
            label="⬇️ Download JSON",
            data=json_str,
            file_name=f"jira_{JIRA_PROJECT}_{start_date}_{end_date}.json",
            mime="application/json",
            width="stretch",
        )

        # JQL used — helpful for debugging
        with st.expander("🔍 JQL used"):
            st.code(jql, language="sql")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 – DELETE TICKETS
# ═══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.header("🗑️ Delete Jira Tickets")
    st.warning("⚠️ Deletion is **permanent** and cannot be undone. Please double-check before deleting.")

    if "tickets_to_delete" not in st.session_state:
        st.session_state["tickets_to_delete"] = []
    if "delete_preview" not in st.session_state:
        st.session_state["delete_preview"] = {}

    # ── Input ticket keys ────────────────────────────────────────────────────
    ticket_input = st.text_area(
        "Enter ticket key(s) to delete",
        placeholder="MID1-1221\nMID1-1222\nMID1-1223",
        height=120,
        help="One ticket key per line",
    )

    if st.button("🔍 Preview Tickets", width="stretch"):
        if not validate_credentials():
            st.stop()

        keys = [k.strip().upper() for k in ticket_input.splitlines() if k.strip()]
        if not keys:
            st.warning("⚠️ Enter at least one ticket key.")
        else:
            previews = {}
            with st.spinner("Fetching ticket details..."):
                for key in keys:
                    r = requests.get(
                        f"{JIRA_BASE_URL}/rest/api/3/issue/{key}",
                        auth=get_auth(),
                        headers={"Accept": "application/json"},
                        params={"fields": "summary,status,issuetype,assignee"},
                        timeout=10,
                    )
                    if r.status_code == 200:
                        f = r.json().get("fields", {})
                        previews[key] = {
                            "key":       key,
                            "summary":   f.get("summary", "—"),
                            "type":      f.get("issuetype", {}).get("name", "—"),
                            "status":    f.get("status", {}).get("name", "—"),
                            "assignee":  f.get("assignee", {}).get("displayName", "Unassigned") if f.get("assignee") else "Unassigned",
                            "url":       f"{JIRA_BASE_URL}/browse/{key}",
                            "found":     True,
                        }
                    else:
                        previews[key] = {"key": key, "found": False, "error": r.status_code}
            st.session_state["delete_preview"] = previews
            st.session_state["tickets_to_delete"] = list(previews.keys())

    # ── Show preview & confirm ───────────────────────────────────────────────
    if st.session_state["delete_preview"]:
        st.divider()
        st.subheader("Preview")

        found    = {k: v for k, v in st.session_state["delete_preview"].items() if v.get("found")}
        notfound = {k: v for k, v in st.session_state["delete_preview"].items() if not v.get("found")}

        if notfound:
            for k, v in notfound.items():
                st.error(f"❌ **{k}** — not found or no access (HTTP {v.get('error')})")

        if found:
            import pandas as pd
            df_del = pd.DataFrame([
                {"Key": v["key"], "Summary": v["summary"], "Type": v["type"],
                 "Status": v["status"], "Assignee": v["assignee"]}
                for v in found.values()
            ])
            st.dataframe(df_del, width="stretch")

            st.error(f"You are about to **permanently delete {len(found)} ticket(s)**. This cannot be undone.")
            confirm = st.checkbox("✅ I understand, proceed with deletion")

            if confirm:
                if st.button("🗑️ Delete Tickets", type="primary", width="stretch"):
                    if not validate_credentials():
                        st.stop()

                    deleted, errors = [], []
                    with st.spinner("Deleting tickets..."):
                        for key in found:
                            r = requests.delete(
                                f"{JIRA_BASE_URL}/rest/api/3/issue/{key}",
                                auth=get_auth(),
                                timeout=10,
                            )
                            if r.status_code == 204:
                                deleted.append(key)
                            else:
                                errors.append({"key": key, "error": r.text})

                    if deleted:
                        st.success(f"✅ Successfully deleted: {', '.join(deleted)}")
                    if errors:
                        st.error(f"❌ Failed to delete {len(errors)} ticket(s):")
                        for e in errors:
                            with st.expander(f"{e['key']} error"):
                                st.code(e["error"])

                    # Clear preview after deletion
                    st.session_state["delete_preview"] = {}
                    st.session_state["tickets_to_delete"] = []


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 – MANAGER DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.header("📈 Manager Dashboard")
    st.caption(f"Overview for board **{selected_board_name}** — project **{JIRA_PROJECT}**. [Open in Jira]({board_url})")

    dash_col1, dash_col2, dash_col3 = st.columns(3)
    with dash_col1:
        dash_start = st.date_input("From date", value=datetime.today() - timedelta(days=90), key="dash_start")
    with dash_col2:
        dash_end = st.date_input("To date", value=datetime.today(), key="dash_end")
    with dash_col3:
        stale_days = st.number_input(
            "Stale threshold (days)", min_value=1, max_value=90, value=7, key="dash_stale_days",
            help="Issues in In Progress/Blocked with no update for this many days are flagged Stale.",
        )

    if st.button("🔄 Load Dashboard", type="primary", width="stretch", key="dash_load"):
        if not validate_credentials():
            st.stop()

        # Scope the query to the currently selected board (not just the project),
        # so switching boards in the sidebar actually changes what the dashboard shows.
        jql = (
            f'issuetype in ("Epic", "Story", "Bug", "Task", "Sub-task")'
            f' AND created >= "{dash_start}" AND created <= "{dash_end}"'
            f' ORDER BY created DESC'
        )

        with st.spinner(f"Fetching data from {selected_board_name}..."):
            all_issues, err_resp = fetch_board_issues(
                get_auth(),
                selected_board_id,
                jql,
                "summary,issuetype,status,priority,assignee,parent,created,updated,resolutiondate",
                max_results=1000,
            )
            if err_resp is not None:
                st.error(f"❌ Failed to fetch data: {err_resp.status_code}\n{err_resp.text}")
                st.stop()

        issues = []
        now = datetime.now()
        for issue in all_issues:
            f = issue.get("fields", {})
            status = f.get("status", {}) or {}
            status_name = status.get("name", "Unknown")
            status_cat  = (status.get("statusCategory", {}) or {}).get("key")
            updated_raw = f.get("updated")
            updated_days = None
            if updated_raw:
                try:
                    updated_days = (now - datetime.strptime(updated_raw[:19], "%Y-%m-%dT%H:%M:%S")).days
                except ValueError:
                    updated_days = None
            is_blocked     = "block" in status_name.lower()
            is_in_progress = status_cat == "indeterminate"
            is_stale = bool(updated_days is not None and updated_days >= stale_days and (is_in_progress or is_blocked))
            issues.append({
                "key":          issue["key"],
                "summary":      f.get("summary"),
                "type":         f.get("issuetype", {}).get("name") if f.get("issuetype") else "Unknown",
                "status":       status_name,
                "is_done":      status_cat == "done",
                "is_blocked":   is_blocked,
                "is_stale":     is_stale,
                "priority":     f.get("priority", {}).get("name") if f.get("priority") else "None",
                "assignee":     f.get("assignee", {}).get("displayName") if f.get("assignee") else "Unassigned",
                "parent":       f.get("parent", {}).get("key") if f.get("parent") else None,
                "created":      (f.get("created") or "")[:10],
            })

        if not issues:
            st.warning("⚠️ No issues found for the selected board/date range.")
            st.session_state.pop("dash_df", None)
        else:
            st.session_state["dash_df"] = pd.DataFrame(issues)
            st.session_state["dash_board"] = selected_board_name

    if st.session_state.get("dash_df") is not None and not st.session_state["dash_df"].empty:
        df = st.session_state["dash_df"]

        epics   = df[df["type"] == "Epic"]
        stories = df[df["type"].isin(["Story", "Bug", "Task", "Sub-task"])]

        open_count    = int((~df["is_done"]).sum())
        closed_count  = int(df["is_done"].sum())
        blocked_count = int(df["is_blocked"].sum())
        stale_count   = int(df["is_stale"].sum())

        open_epics   = int((~epics["is_done"]).sum()) if not epics.empty else 0
        closed_epics = int(epics["is_done"].sum()) if not epics.empty else 0

        # ── KPI cards — epics ─────────────────────────────────────────────
        st.subheader("📦 Epics")
        st.markdown(
            '<div class="kpi-grid">'
            f'<div class="kpi-card"><div class="kpi-label">Total epics</div><div class="kpi-value">{len(epics)}</div></div>'
            f'<div class="kpi-card kpi-open"><div class="kpi-label">Open</div><div class="kpi-value">{open_epics}</div></div>'
            f'<div class="kpi-card kpi-closed"><div class="kpi-label">Closed</div><div class="kpi-value">{closed_epics}</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )

        # ── KPI cards — issues ────────────────────────────────────────────
        st.subheader("🧾 Issues")
        st.markdown(
            '<div class="kpi-grid">'
            f'<div class="kpi-card kpi-open"><div class="kpi-label">Open</div><div class="kpi-value">{open_count}</div></div>'
            f'<div class="kpi-card kpi-stale"><div class="kpi-label">Stale ({stale_days}+ days)</div><div class="kpi-value">{stale_count}</div></div>'
            f'<div class="kpi-card kpi-blocked"><div class="kpi-label">Blocked</div><div class="kpi-value">{blocked_count}</div></div>'
            f'<div class="kpi-card kpi-closed"><div class="kpi-label">Closed</div><div class="kpi-value">{closed_count}</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )

        st.divider()

        # ── Status & type breakdown ──────────────────────────────────────
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Status Breakdown")
            st.bar_chart(df["status"].value_counts())
        with c2:
            st.subheader("Issue Type Breakdown")
            st.bar_chart(df["type"].value_counts())

        st.divider()

        # ── Filters ───────────────────────────────────────────────────────
        st.subheader("Filters")
        f1, f2, f3 = st.columns(3)
        with f1:
            epic_labels = {f"{e['key']} — {e['summary']}": e["key"] for _, e in epics.iterrows()}
            epic_choice = st.selectbox("Epic", ["All epics"] + sorted(epic_labels.keys()), key="dash_epic_filter")
        with f2:
            # Pull assignees from ALL issues (not just epics) so every reporter/lead/assignee shows up.
            assignee_opts = sorted(a for a in df["assignee"].dropna().unique().tolist() if a)
            assignee_choice = st.selectbox("Assignee", ["All assignees"] + assignee_opts, key="dash_assignee_filter")
        with f3:
            # Pull statuses from ALL issues so To Do / In Progress / Blocked / Done etc. all appear,
            # not just the (often single) status epics themselves sit in.
            status_opts = sorted(s for s in df["status"].dropna().unique().tolist() if s)
            status_choice = st.selectbox("Status", ["All statuses"] + status_opts, key="dash_status_filter")

        filtered_epics = epics.copy()
        if epic_choice != "All epics":
            filtered_epics = filtered_epics[filtered_epics["key"] == epic_labels[epic_choice]]

        st.divider()

        # ── Epics overview ────────────────────────────────────────────────
        st.subheader("Epics overview")
        if filtered_epics.empty:
            st.markdown('<div class="empty-state">No epics match the selected filters.</div>', unsafe_allow_html=True)
        else:
            import html as _html
            rows_html = []
            assignee_or_status_active = assignee_choice != "All assignees" or status_choice != "All statuses"
            for _, epic in filtered_epics.iterrows():
                children = df[df["parent"] == epic["key"]]
                if assignee_choice != "All assignees":
                    children = children[children["assignee"] == assignee_choice]
                if status_choice != "All statuses":
                    children = children[children["status"] == status_choice]
                if assignee_or_status_active and children.empty:
                    continue  # hide epics with no stories matching the assignee/status filter

                total_children = len(children)
                done_children = int(children["is_done"].sum())
                pct = round((done_children / total_children * 100), 1) if total_children else 0.0

                # Stale/Blocked reflect the epic's child stories, matching how a lead reads epic health.
                has_stale = bool(children["is_stale"].any()) if total_children else False
                has_blocked = bool(children["is_blocked"].any()) if total_children else False

                border_class = "stale-left-border" if has_stale else ("blocked-left-border" if has_blocked else "")
                badges = ""
                if has_stale:
                    badges += '<span class="badge badge-stale">Stale</span>'
                if has_blocked:
                    badges += '<span class="badge badge-blocked">Blocked</span>'

                if pct >= 100:
                    fill_class = "progress-fill-done"
                elif pct >= 50:
                    fill_class = "progress-fill-in-progress"
                else:
                    fill_class = "progress-fill-pending"

                summary = _html.escape(str(epic["summary"] or ""))
                lead = _html.escape(str(epic["assignee"] or "Unassigned"))
                badges_html = f'<div class="epic-badges">{badges}</div>' if badges else ""
                epic_url = f"{JIRA_BASE_URL}/browse/{epic['key']}"

                rows_html.append(
                    f'<div class="epic-row {border_class}">'
                    f'<div class="epic-header">'
                    f'<div style="flex:1;">'
                    f'<div class="epic-title"><a href="{epic_url}" target="_blank" rel="noopener noreferrer" style="color:inherit; text-decoration:none;">{summary}</a></div>'
                    f'{badges_html}'
                    f'<div class="epic-meta">{total_children} stories • Lead: {lead}</div>'
                    f'</div>'
                    f'<div class="epic-completion">'
                    f'<div class="epic-percentage">{pct:.0f}%</div>'
                    f'<div class="epic-done">{done_children} of {total_children} done</div>'
                    f'</div>'
                    f'</div>'
                    f'<div class="progress-bar"><div class="progress-fill {fill_class}" style="width:{pct:.0f}%;"></div></div>'
                    f'</div>'
                )

            if not rows_html:
                st.markdown('<div class="empty-state">No epics match the selected filters.</div>', unsafe_allow_html=True)
            else:
                st.markdown(f'<div class="epics-overview">{"".join(rows_html)}</div>', unsafe_allow_html=True)

        st.divider()

        # ── Workload by assignee ─────────────────────────────────────────
        st.subheader("👤 Open Work by Assignee")
        open_df = df[~df["is_done"]]
        if open_df.empty:
            st.info("No open issues 🎉")
        else:
            st.bar_chart(open_df["assignee"].value_counts())

        st.divider()

        # ── Raw table ─────────────────────────────────────────────────────
        with st.expander("🗂️ All Issues"):
            st.dataframe(
                df[["key", "type", "summary", "status", "priority", "assignee", "created"]],
                width="stretch",
            )
