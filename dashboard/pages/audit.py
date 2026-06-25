"""7. Audit Package Viewer — per-quarter packages + governance docs (read-only)."""
from __future__ import annotations

import streamlit as st

from dashboard.components import layout
from dashboard.utils import data_loader as dl
from dashboard.utils import paths

layout.page_header("Audit Package Viewer",
                   "Per-quarter audit packages and project governance documents. "
                   "Read-only.")

tab_pkg, tab_docs, tab_results = st.tabs(
    ["Quarterly Packages", "Governance Docs", "Generated Artifacts"])

# --- Per-quarter immutable packages ---------------------------------------
with tab_pkg:
    packages = dl.list_audit_packages()
    if not packages:
        layout.no_data(
            "No audit packages under paper_trading/audit/.",
            "Each quarter archives a folder (e.g. 2026-Q3/) with the data "
            "snapshot, ranks, trade list, fills, commit hash and logs.")
    else:
        pick = st.selectbox("Audit package", packages)
        files = dl.audit_package_files(pick)
        st.caption(f"{len(files)} file(s) in {pick}")
        for f in files:
            rel = f.relative_to(paths.AUDIT_DIR)
            with st.expander(str(rel)):
                if f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                    st.image(str(f), use_container_width=True)
                elif f.suffix.lower() in (".md", ".txt", ".csv", ".json", ".log"):
                    text = dl.read_text(f)
                    if text is None:
                        st.caption("(could not read file)")
                    elif f.suffix.lower() == ".csv":
                        st.text(text[:10000])
                    else:
                        st.code(text, language=None)
                else:
                    st.caption(f"(binary / unsupported preview: {f.name})")

# --- Root governance / audit markdown -------------------------------------
with tab_docs:
    found = False
    for name in paths.AUDIT_DOCS:
        path = paths.PROJECT_ROOT / name
        if path.exists():
            found = True
            with st.expander(name):
                text = dl.read_text(path)
                st.markdown(text if text else "(could not read file)")
    if not found:
        layout.no_data("No governance documents found at the project root.")

# --- Existing research artifacts ------------------------------------------
with tab_results:
    if not paths.RESULTS_DIR.exists():
        layout.no_data("No results/ directory found.")
    else:
        report_txts = sorted(paths.RESULTS_DIR.rglob("report.txt"))
        comp_csvs = sorted(paths.RESULTS_DIR.rglob("comparison.csv"))
        st.write(f"**{len(report_txts)}** report.txt · "
                 f"**{len(comp_csvs)}** comparison.csv under results/")
        for f in report_txts + comp_csvs:
            with st.expander(str(f.relative_to(paths.PROJECT_ROOT))):
                text = dl.read_text(f)
                st.text(text[:10000] if text else "(could not read file)")
