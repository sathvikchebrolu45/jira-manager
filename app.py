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
st.sidebar.divider()
st.sidebar.title("📋 Board")
selected_board_name = st.sidebar.selectbox(
    "Select Board",
    options=list(BOARDS.keys()),
    index=0,
)
selected_board_id = BOARDS[selected_board_name]
board_url = f"{JIRA_BASE_URL}/jira/software/c/projects/{JIRA_PROJECT}/boards/{selected_board_id}"
st.sidebar.caption(f"[🔗 Open board]({board_url})")

def get_auth():
    return HTTPBasicAuth(jira_email, jira_token)

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

    if st.button("🔄 Sync Jira Data", type="primary", width="stretch"):
        if not validate_credentials():
            st.stop()

        # Build JQL
        type_clause   = " OR ".join([f'issuetype = "{t}"' for t in issue_types]) if issue_types else 'issuetype in standardIssueTypes()'
        status_clause = (" AND (" + " OR ".join([f'status = "{s}"' for s in statuses]) + ")") if statuses else ""
        parent_clause = f' AND parent = {parent_filter.strip().upper()}' if parent_filter.strip() else ""
        # Skip date filter when parent is specified — child issues may fall outside the range
        date_clause   = (f' AND created >= "{start_date}" AND created <= "{end_date}"') if not parent_filter.strip() else ""
        jql = (
            f'project = {JIRA_PROJECT}'
            f' AND ({type_clause})'
            f'{date_clause}'
            f'{status_clause}'
            f'{parent_clause}'
            f' ORDER BY created DESC'
        )

        with st.spinner("Fetching data from Jira..."):
            resp = requests.post(
                f"{JIRA_BASE_URL}/rest/api/3/search/jql",
                auth=get_auth(),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json={
                    "jql":        jql,
                    "maxResults": max_results,
                    "fields":     ["summary", "status", "issuetype", "priority", "assignee", "reporter", "created", "updated", "labels", "components"],
                },
                timeout=30,
            )

        if resp.status_code != 200:
            st.error(f"❌ Failed to fetch data: {resp.status_code}\n{resp.text}")
            st.stop()

        raw = resp.json()
        issues = []
        for issue in raw.get("issues", []):
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

        total = raw.get("total", 0)
        st.success(f"✅ Fetched {len(issues)} of {total} total matching issues.")

        # Summary table
        if issues:
            import pandas as pd
            df = pd.DataFrame(issues)[["key", "summary", "issuetype", "status", "priority", "assignee", "created"]]
            st.dataframe(df, width="stretch")

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
    st.caption(f"Overview for project **{JIRA_PROJECT}**. [Open in Jira]({board_url})")

    dash_col1, dash_col2 = st.columns(2)
    with dash_col1:
        dash_start = st.date_input("From date", value=datetime.today() - timedelta(days=90), key="dash_start")
    with dash_col2:
        dash_end = st.date_input("To date", value=datetime.today(), key="dash_end")

    if st.button("🔄 Load Dashboard", type="primary", width="stretch", key="dash_load"):
        if not validate_credentials():
            st.stop()

        jql = (
            f'project = {JIRA_PROJECT}'
            f' AND issuetype in ("Epic", "Story", "Bug", "Task", "Sub-task")'
            f' AND created >= "{dash_start}" AND created <= "{dash_end}"'
            f' ORDER BY created DESC'
        )

        all_issues, next_page_token = [], None
        with st.spinner("Fetching data from Jira..."):
            while True:
                body = {
                    "jql": jql,
                    "maxResults": 100,
                    "fields": ["summary", "issuetype", "status", "priority", "assignee", "parent", "created", "resolutiondate"],
                }
                if next_page_token:
                    body["nextPageToken"] = next_page_token
                resp = requests.post(
                    f"{JIRA_BASE_URL}/rest/api/3/search/jql",
                    auth=get_auth(),
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    json=body,
                    timeout=30,
                )
                if resp.status_code != 200:
                    st.error(f"❌ Failed to fetch data: {resp.status_code}\n{resp.text}")
                    st.stop()
                raw = resp.json()
                all_issues.extend(raw.get("issues", []))
                next_page_token = raw.get("nextPageToken")
                if not next_page_token or len(all_issues) >= 1000:
                    break

        issues = []
        for issue in all_issues:
            f = issue.get("fields", {})
            status = f.get("status", {}) or {}
            issues.append({
                "key":        issue["key"],
                "summary":    f.get("summary"),
                "type":       f.get("issuetype", {}).get("name") if f.get("issuetype") else "Unknown",
                "status":     status.get("name", "Unknown"),
                "is_done":    (status.get("statusCategory", {}) or {}).get("key") == "done",
                "priority":   f.get("priority", {}).get("name") if f.get("priority") else "None",
                "assignee":   f.get("assignee", {}).get("displayName") if f.get("assignee") else "Unassigned",
                "parent":     f.get("parent", {}).get("key") if f.get("parent") else None,
                "created":    (f.get("created") or "")[:10],
            })

        if not issues:
            st.warning("⚠️ No issues found for the selected date range.")
            st.stop()

        df = pd.DataFrame(issues)

        epics  = df[df["type"] == "Epic"]
        stories = df[df["type"].isin(["Story", "Bug", "Task", "Sub-task"])]

        open_count   = int((~df["is_done"]).sum())
        closed_count = int(df["is_done"].sum())

        # ── KPI cards ─────────────────────────────────────────────────────
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Total Issues", len(df))
        k2.metric("Epics", len(epics))
        k3.metric("Stories/Tasks/Bugs", len(stories))
        k4.metric("🟢 Open", open_count)
        k5.metric("✅ Closed", closed_count)

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

        # ── Epic progress ────────────────────────────────────────────────
        st.subheader("📦 Epic Progress")
        if epics.empty:
            st.info("No epics found in this date range.")
        else:
            epic_rows = []
            for _, epic in epics.iterrows():
                children = df[df["parent"] == epic["key"]]
                total_children = len(children)
                done_children = int(children["is_done"].sum())
                pct = round((done_children / total_children * 100), 1) if total_children else 0.0
                epic_rows.append({
                    "Epic":       epic["key"],
                    "Summary":    epic["summary"],
                    "Status":     epic["status"],
                    "Total Items": total_children,
                    "Done":       done_children,
                    "Open":       total_children - done_children,
                    "% Complete": pct,
                })
            epic_df = pd.DataFrame(epic_rows)
            st.dataframe(
                epic_df,
                width="stretch",
                column_config={
                    "% Complete": st.column_config.ProgressColumn(
                        "% Complete", min_value=0, max_value=100, format="%.1f%%"
                    )
                },
            )

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
