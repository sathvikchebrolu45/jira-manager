import streamlit as st
import requests
import json
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
if col_save.button("💾 Remember", use_container_width=True, help="Save credentials for this browser session"):
    st.session_state["jira_email"] = jira_email
    st.session_state["jira_token"] = jira_token
    st.session_state["creds_saved"] = True
    st.sidebar.success("✅ Saved for this session!")

if col_clear.button("🗑️ Clear", use_container_width=True, help="Remove saved credentials"):
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

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📝 Create Stories", "📊 Jira Data Sync", "🗑️ Delete Tickets"])

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 – CREATE STORIES
# ═══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.header("📝 Create Jira Stories")
    st.caption(f"Board: **{selected_board_name}** — [Open in Jira]({board_url})")

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
            assignee_email = st.text_input(f"Assignee Email #{i+1} (optional)", key=f"assignee_{i}", placeholder="assignee@example.com")

        stories.append({
            "summary": summary,
            "description": description_text,
            "priority": priority,
            "story_points": story_points,
            "assignee_email": assignee_email,
            "parent_key": parent_key,
        })

    st.divider()
    if st.button("🚀 Create Stories in Jira", type="primary", use_container_width=True):
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

    if st.button("🔄 Sync Jira Data", type="primary", use_container_width=True):
        if not validate_credentials():
            st.stop()

        # Build JQL
        type_clause   = " OR ".join([f'issuetype = "{t}"' for t in issue_types]) if issue_types else 'issuetype in standardIssueTypes()'
        status_clause = (" AND (" + " OR ".join([f'status = "{s}"' for s in statuses]) + ")") if statuses else ""
        jql = (
            f'project = {JIRA_PROJECT}'
            f' AND ({type_clause})'
            f' AND created >= "{start_date}"'
            f' AND created <= "{end_date}"'
            f'{status_clause}'
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
            st.dataframe(df, use_container_width=True)

        # JSON output
        with st.expander("🗂️ Full JSON Output", expanded=True):
            st.json(issues)

        json_str = json.dumps(issues, indent=2, ensure_ascii=False)
        st.download_button(
            label="⬇️ Download JSON",
            data=json_str,
            file_name=f"jira_{JIRA_PROJECT}_{start_date}_{end_date}.json",
            mime="application/json",
            use_container_width=True,
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

    if st.button("🔍 Preview Tickets", use_container_width=True):
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
            st.dataframe(df_del, use_container_width=True)

            st.error(f"You are about to **permanently delete {len(found)} ticket(s)**. This cannot be undone.")
            confirm = st.checkbox("✅ I understand, proceed with deletion")

            if confirm:
                if st.button("🗑️ Delete Tickets", type="primary", use_container_width=True):
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
