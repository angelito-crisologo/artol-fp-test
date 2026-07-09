"""artol-ai interactive tester — Streamlit front end.

Five-step flow:
  1. Free-text description of the house the buyer wants.
  2. A narrow Claude call (ai/extract.py) turns it into structured fields.
  3. Those fields render as an editable form (extraction is a first guess,
     not a commitment).
  4. "Find topologies" hard-filters the hand-authored catalog by
     (bedroom_count, lot shape) and lists candidates as checkboxes,
     unchecked by default.
  5. "Run selected" solves + validates + renders each checked topology
     against the (possibly-edited) requirements, one tab per topology.

Reuses the existing pipeline directly (run.py::_run_hand_authored) rather
than reimplementing solve/validate/render — same code path the CLI test
suite exercises.

Run locally:   streamlit run floorplan_v1/app.py
"""
import os
import sys

import streamlit as st

_HERE = os.path.dirname(os.path.abspath(__file__))
for _sub in ("core", "solver", "ai"):
    _p = os.path.join(_HERE, _sub)
    if _p not in sys.path:
        sys.path.insert(0, _p)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from brief import Brief                      # noqa: E402  (ai)
from extract import extract_requirements     # noqa: E402  (ai)
from match import match_topologies            # noqa: E402  (ai)
from render import archplan_to_svg            # noqa: E402  (core)
from run import _run_hand_authored, _run_ai_with_cache  # noqa: E402

# Carport type semantics per CLAUDE.md — spelled out here since "ccp"/"fcp"
# mean nothing to a non-technical reviewer.
CARPORT_TYPE_LABELS = {
    "none": "No carport",
    "ccp": "Claimed carport — 3 m wide for the first 6 m of depth, then "
           "narrows to 2 m (L-shaped cutout, smaller footprint impact)",
    "fcp": "Full carport — full 3 m setback for the entire depth of the "
           "lot on that side (larger footprint impact than claimed)",
}


# --------------------------------------------------------------------- #
# Password gate — cheap protection since "Describe it" spends real
# Claude API calls. Set APP_PASSWORD in Streamlit secrets (or the
# environment for local runs). If unset, the app is open (local dev).
# --------------------------------------------------------------------- #
def _get_secret(key: str):
    """st.secrets raises if no secrets.toml exists at all (e.g. local dev
    without one) rather than behaving like a normal empty mapping, so this
    has to be defensive."""
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key)


def _check_password() -> bool:
    required = _get_secret("APP_PASSWORD")
    if not required:
        return True
    if st.session_state.get("authed"):
        return True
    st.title("artol-ai — floor plan tester")
    with st.form("login"):
        pw = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Enter")
    if submitted:
        if pw == required:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Wrong password.")
    return False


st.set_page_config(page_title="artol-ai floor plan tester", layout="wide")

if not _check_password():
    st.stop()

_title_col, _reset_col = st.columns([8, 1])
with _title_col:
    st.title("artol-ai — floor plan tester")
with _reset_col:
    st.write("")
    if st.button("Reset", key="reset_btn", use_container_width=True):
        for _k in [k for k in list(st.session_state.keys()) if k != "authed"]:
            del st.session_state[_k]
        st.rerun()
st.caption(
    "Describe a house, review/edit what got extracted, pick which existing "
    "topologies to try it against, and see the solved + validated result."
)

for _key, _default in (
    ("extracted", None), ("extraction_reason", ""), ("intent_text", ""),
    ("candidates", None), ("shell", None), ("results", None), ("brief", None),
):
    st.session_state.setdefault(_key, _default)

# --------------------------------------------------------------------- #
# Step 1+2 — free text -> extraction
# --------------------------------------------------------------------- #
st.subheader("1. Describe the house")
with st.form("intent_form"):
    intent = st.text_area(
        "Free-text description", height=110,
        placeholder="e.g. 2BR bungalow on a 12x12 lot, wife wants an open "
                    "kitchen, carport on the left, needs a powder room",
        label_visibility="collapsed",
    )
    parse_clicked = st.form_submit_button("Parse")

if parse_clicked:
    if not intent.strip():
        st.error("Type a description first.")
    else:
        with st.spinner("Reading the description..."):
            try:
                fields, reason = extract_requirements(intent)
            except Exception as e:
                st.error(f"Extraction failed: {e}")
                fields, reason = None, ""
        if fields is not None:
            st.session_state["extracted"] = fields
            st.session_state["extraction_reason"] = reason
            st.session_state["intent_text"] = intent
            st.session_state["candidates"] = None
            st.session_state["results"] = None
            # Push extracted values into widget state so the form resets
            # even if the user had manually edited fields before re-parsing.
            st.session_state["req_lot_width"] = float(fields["lot_width"])
            st.session_state["req_lot_depth"] = float(fields["lot_depth"])
            st.session_state["req_bedroom_count"] = int(fields["bedroom_count"])
            st.session_state["req_occupancy_class"] = fields.get("occupancy_class", "R-1")
            st.session_state["req_carport_side"] = fields.get("carport_side") or "none"
            st.session_state["req_carport_type"] = fields.get("carport_type") or "none"
            st.session_state["req_num_baths"] = int(fields.get("num_baths") or 0)
            st.session_state["req_swap_master"] = bool(fields.get("swap_master_standard", False))
            st.session_state["req_no_master"] = bool(fields.get("no_master", False))
            st.session_state["req_powder_room"] = bool(fields.get("powder_room", False))
            st.session_state["req_dirty_kitchen"] = bool(fields.get("dirty_kitchen", False))
            st.session_state["req_service_area"] = bool(fields.get("service_area", False))
            st.session_state["req_lanai"] = bool(fields.get("lanai", False))
            st.session_state["req_patio"] = bool(fields.get("patio", False))
            st.session_state["req_kitchen_back_door"] = bool(fields.get("kitchen_back_door", True))
            st.session_state["req_must_haves"] = ", ".join(fields.get("must_haves", []))
            st.session_state["req_avoid"] = ", ".join(fields.get("avoid", []))

# --------------------------------------------------------------------- #
# Step 3 — editable structured fields
# --------------------------------------------------------------------- #
brief = None
if st.session_state["extracted"]:
    st.subheader("2. Requirements")
    st.caption(st.session_state["extraction_reason"])
    f = st.session_state["extracted"]

    req_fields_tab, req_json_tab = st.tabs(["Fields", "JSON"])

    with req_fields_tab:
        c1, c2, c3 = st.columns(3)
        with c1:
            lot_width = st.number_input("Lot width (m)", value=float(f["lot_width"]),
                                         min_value=5.0, max_value=30.0, step=0.5,
                                         key="req_lot_width")
            lot_depth = st.number_input("Lot depth (m)", value=float(f["lot_depth"]),
                                         min_value=5.0, max_value=40.0, step=0.5,
                                         key="req_lot_depth")
            bedroom_count = st.number_input("Bedrooms", value=int(f["bedroom_count"]),
                                             min_value=1, max_value=6, step=1,
                                             key="req_bedroom_count")
            occ_opts = ["R-1", "R-2", "R-3"]
            occupancy_class = st.selectbox("Occupancy class", occ_opts,
                                            index=occ_opts.index(f.get("occupancy_class", "R-1")),
                                            key="req_occupancy_class")
        with c2:
            side_opts = ["none", "left", "right", "front"]
            carport_side = st.selectbox("Carport side", side_opts,
                                         index=side_opts.index(f.get("carport_side") or "none"),
                                         key="req_carport_side")
            type_opts = ["none", "fcp"] if carport_side == "front" else ["none", "ccp", "fcp"]
            _ct_default = f.get("carport_type") or "none"
            if _ct_default not in type_opts:
                _ct_default = "none"
            if st.session_state.get("req_carport_type", "none") not in type_opts:
                st.session_state["req_carport_type"] = "none"
            carport_type = st.selectbox(
                "Carport type", type_opts,
                index=type_opts.index(_ct_default),
                format_func=lambda v: CARPORT_TYPE_LABELS[v],
                key="req_carport_type",
            )
            num_baths = st.number_input("Explicit bath count (0 = auto)",
                                         value=int(f.get("num_baths") or 0),
                                         min_value=0, max_value=4, step=1,
                                         key="req_num_baths")
            swap_master_standard = st.checkbox("Master bedroom at rear",
                                                value=bool(f.get("swap_master_standard", False)),
                                                key="req_swap_master")
            no_master = st.checkbox("No distinguished master (all equal bedrooms)",
                                     value=bool(f.get("no_master", False)),
                                     key="req_no_master")
        with c3:
            powder_room = st.checkbox("Powder room", value=bool(f.get("powder_room", False)),
                                       key="req_powder_room")
            dirty_kitchen = st.checkbox("Dirty kitchen", value=bool(f.get("dirty_kitchen", False)),
                                         key="req_dirty_kitchen")
            service_area = st.checkbox("Service / laundry area",
                                        value=bool(f.get("service_area", False)),
                                        key="req_service_area")
            lanai = st.checkbox("Lanai", value=bool(f.get("lanai", False)), key="req_lanai")
            patio = st.checkbox("Patio", value=bool(f.get("patio", False)), key="req_patio")
            kitchen_back_door = st.checkbox("Kitchen back door",
                                             value=bool(f.get("kitchen_back_door", True)),
                                             key="req_kitchen_back_door")

        must_haves_text = st.text_input("Must-haves (comma separated)",
                                         value=", ".join(f.get("must_haves", [])),
                                         key="req_must_haves")
        avoid_text = st.text_input("Avoid (comma separated)",
                                    value=", ".join(f.get("avoid", [])),
                                    key="req_avoid")

        find_clicked = st.button("Find topologies", type="primary")

    with req_json_tab:
        st.json({
            "intent": st.session_state["intent_text"],
            "lot_width": lot_width,
            "lot_depth": lot_depth,
            "bedroom_count": int(bedroom_count),
            "occupancy_class": occupancy_class,
            "carport_side": None if carport_side == "none" else carport_side,
            "carport_type": None if carport_type == "none" else carport_type,
            "num_baths": int(num_baths) or None,
            "swap_master_standard": swap_master_standard,
            "no_master": no_master,
            "powder_room": powder_room,
            "dirty_kitchen": dirty_kitchen,
            "service_area": service_area,
            "lanai": lanai,
            "patio": patio,
            "kitchen_back_door": kitchen_back_door,
            "must_haves": [s.strip() for s in must_haves_text.split(",") if s.strip()],
            "avoid": [s.strip() for s in avoid_text.split(",") if s.strip()],
        })

    if find_clicked:
        brief = Brief(
            intent=st.session_state["intent_text"],
            lot_width=lot_width, lot_depth=lot_depth,
            bedroom_count=int(bedroom_count),
            must_haves=[s.strip() for s in must_haves_text.split(",") if s.strip()],
            avoid=[s.strip() for s in avoid_text.split(",") if s.strip()],
            carport_side=None if carport_side == "none" else carport_side,
            carport_type=None if carport_type == "none" else carport_type,
            occupancy_class=occupancy_class,
            swap_master_standard=swap_master_standard,
            no_master=no_master,
            num_baths=num_baths or None,
            powder_room=powder_room,
            dirty_kitchen=dirty_kitchen,
            service_area=service_area,
            lanai=lanai, patio=patio,
            kitchen_back_door=kitchen_back_door,
        )
        st.session_state["brief"] = brief
        candidates, shell = match_topologies(brief)
        st.session_state["candidates"] = candidates
        st.session_state["shell"] = shell
        st.session_state["results"] = None

# --------------------------------------------------------------------- #
# Step 4 — candidate topology checklist
# --------------------------------------------------------------------- #
if st.session_state["candidates"] is not None:
    st.subheader("3. Matching topologies")
    st.caption(f"lot shape category: **{st.session_state['shell']}**")
    candidates = st.session_state["candidates"]

    if not candidates:
        st.warning(
            "No existing topology matches this bedroom count + lot shape yet. "
            "That's expected outside today's catalog (1-storey, 2BR, "
            "squarish/wide lots only) — not a bug."
        )

    checked_ids = []
    if candidates:
        for c in candidates:
            checked = st.checkbox(f"**{c.id}**  \n{c.label}", value=False, key=f"cb_{c.id}")
            if checked:
                checked_ids.append(c.id)
        st.divider()

    ai_checked = st.checkbox(
        "**Generate with AI** — let Claude compose a new topology from scratch "
        "(calls the Anthropic API; may take 10–30 s)",
        value=False, key="cb_ai",
    )
    if ai_checked:
        checked_ids.append("ai-generated")

    run_clicked = st.button("Run selected", type="primary", disabled=not checked_ids)

    if run_clicked:
        selected_catalog = [c for c in candidates if c.id in checked_ids]
        run_ai = "ai-generated" in checked_ids
        run_items = selected_catalog + (["ai-generated"] if run_ai else [])
        results = []
        progress = st.progress(0.0, text="Solving...")
        for n, item in enumerate(run_items, start=1):
            is_ai = item == "ai-generated"
            label = "AI-generated" if is_ai else item.id
            progress.progress(n / len(run_items), text=f"Solving {label}...")
            try:
                if is_ai:
                    layout, topo, reason = _run_ai_with_cache(
                        st.session_state["brief"], verbose=False)
                    result_id = "ai-generated"
                else:
                    layout, topo, reason = _run_hand_authored(
                        st.session_state["brief"], item.filename, verbose=False,
                        deterministic=True)
                    result_id = item.id
                plan = getattr(layout, "archplan", None)
                svg = archplan_to_svg(plan)
                results.append({
                    "id": result_id, "ok": True, "svg": svg,
                    "issues": layout.issues, "score": layout.score,
                    "reason": reason,
                })
            except RuntimeError as e:
                results.append({
                    "id": "ai-generated" if is_ai else item.id,
                    "ok": False, "error": str(e),
                })
        progress.empty()
        st.session_state["results"] = results

# --------------------------------------------------------------------- #
# Step 5 — results
# --------------------------------------------------------------------- #
if st.session_state["results"]:
    st.subheader("4. Results")
    results = st.session_state["results"]
    topo_tabs = st.tabs([r["id"] for r in results])
    for topo_tab, r in zip(topo_tabs, results):
        with topo_tab:
            if not r["ok"]:
                st.error(f"Solve failed: {r['error']}")
                continue
            svg_tab, eval_tab = st.tabs(["Floor Plan", "Evaluation"])
            with svg_tab:
                st.iframe(r["svg"], height=680)
                st.download_button(
                    "Download SVG", data=r["svg"], file_name=f"{r['id']}.svg",
                    mime="image/svg+xml", key=f"dl_{r['id']}",
                )
            with eval_tab:
                st.caption(r["reason"])
                errs = [i for i in r["issues"] if i.severity == "error"]
                warns = [i for i in r["issues"] if i.severity == "warning"]
                suggs = [i for i in r["issues"] if i.severity == "suggestion"]
                status = "PASS" if not errs else "FAIL"
                st.markdown(
                    f"**{status}** — score `{r['score']:.2f}` — "
                    f"{len(errs)} error(s), {len(warns)} warning(s), {len(suggs)} suggestion(s)"
                )
                for i in errs:
                    st.error(i.msg)
                for i in warns:
                    st.warning(i.msg)
                for i in suggs:
                    st.info(i.msg)
