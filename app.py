"""Finance Assistant Chatbot - Streamlit UI.

Run:  streamlit run app.py
"""
from __future__ import annotations

import json
from datetime import datetime

import streamlit as st

from bots import FinanceBot
from core.config import get_settings
from core.data_loader import SUPPORTED_EXT, Dataset, load_bytes, load_pasted
from core.errors import ChatbotError
from core.llm import PROVIDER_LABELS, LLMRouter
from core.logger import get_logger

log = get_logger("app")
st.set_page_config(page_title="Finance Assistant Chatbot", page_icon="💰", layout="wide")


# ----------------------------------------------------------------------------- resources
@st.cache_resource
def get_bots(db_path: str) -> dict:
    bots = [FinanceBot()]
    return {b.key: b for b in bots}


@st.cache_data(show_spinner=False)
def cached_samples(bot_key: str, db_path: str) -> list[Dataset]:
    return get_bots(db_path)[bot_key].load_samples()


def ss(key, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


base_settings = get_settings()
BOTS = get_bots(base_settings.db_path)

# ----------------------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("💰 Finance Assistant Chatbot")
    bot_key = "finance"
    bot = BOTS[bot_key]

    with st.expander("⚙️ LLM settings", expanded=False):
        order = st.multiselect(
            "Provider order (pehla fail ho to agla try hoga)",
            options=["gemini", "groq", "ollama", "mock"],
            default=base_settings.providers(),
            format_func=lambda p: PROVIDER_LABELS[p],
        )
        gemini_key = st.text_input("Gemini API key (optional override)", type="password",
                                   help="Khali chhodein to .env wali key use hogi.")
        gemini_model = st.text_input("Gemini model", value=base_settings.gemini_model)
        groq_key = st.text_input("Groq API key (free)", type="password")
        groq_model = st.text_input("Groq model", value=base_settings.groq_model)
        ollama_model = st.text_input("Ollama model (local, free)", value=base_settings.ollama_model)

    settings = get_settings(
        gemini_api_key=gemini_key, gemini_model=gemini_model, groq_api_key=groq_key,
        groq_model=groq_model, ollama_model=ollama_model,
        provider_order=",".join(order) if order else base_settings.provider_order,
    )
    status = []
    status.append(("Gemini", bool(settings.gemini_api_key)))
    status.append(("Groq", bool(settings.groq_api_key)))
    st.caption(" · ".join(f"{'✅' if ok else '⚪'} {n} key" for n, ok in status) + " · Ollama: local")
    if not settings.gemini_api_key and not settings.groq_api_key and "ollama" not in settings.providers() and "mock" not in settings.providers():
        st.warning("Koi API key nahi mili. `.env` me GEMINI_API_KEY ya GROQ_API_KEY daalein.")

    # ---- data
    st.divider()
    st.subheader("📂 Data")
    use_samples = st.checkbox("Sample data use karein", value=True, key=f"samples_{bot_key}")
    uploads = st.file_uploader(
        "Files upload karein", type=[e.lstrip(".") for e in sorted(SUPPORTED_EXT)],
        accept_multiple_files=True, key=f"upload_{bot_key}",
    )
    with st.form(f"paste_form_{bot_key}", clear_on_submit=True):
        pasted = st.text_area("Ya data yahan paste karein (CSV / JSON / text)", height=120)
        fmt = st.selectbox("Format", ["auto", "csv", "json", "text"])
        add = st.form_submit_button("➕ Add pasted data")
    pasted_list: list[Dataset] = ss(f"pasted_{bot_key}", [])
    if add:
        try:
            ds = load_pasted(pasted, fmt, name=f"pasted_{len(pasted_list) + 1}")
            pasted_list.append(ds)
            st.success(f"Added: {ds.summary()}")
        except ChatbotError as exc:
            st.error(exc.user_message)
    if pasted_list and st.button("🗑️ Pasted data hatayein", key=f"clear_paste_{bot_key}"):
        pasted_list.clear()
        st.rerun()

    st.divider()
    if st.button("🧹 Chat clear karein", use_container_width=True):
        st.session_state[f"history_{bot_key}"] = []
        st.rerun()


# ----------------------------------------------------------------------------- assemble datasets
def collect_datasets() -> tuple[list[Dataset], list[str]]:
    datasets, errors = [], []
    if use_samples:
        datasets.extend(cached_samples(bot_key, settings.db_path))
    cache: dict = ss(f"parsed_{bot_key}", {})
    for f in uploads or []:
        cache_key = f"{f.name}:{f.size}"
        if cache_key not in cache:
            try:
                cache[cache_key] = load_bytes(f.getvalue(), f.name, max_mb=settings.max_upload_mb)
            except ChatbotError as exc:
                cache[cache_key] = exc.user_message
            except Exception as exc:  # noqa: BLE001
                log.exception("Upload parse failed")
                cache[cache_key] = f"'{f.name}' load nahi ho payi: {type(exc).__name__}"
        item = cache[cache_key]
        (datasets.append(item) if isinstance(item, Dataset) else errors.append(item))
    datasets.extend(pasted_list)
    return datasets, errors


datasets, load_errors = collect_datasets()

# ----------------------------------------------------------------------------- main area
st.header(f"{bot.icon} {bot.name}")
st.caption(bot.description)
for err in load_errors:
    st.error(err)

with st.expander(f"📊 Loaded data ({len(datasets)})", expanded=False):
    if not datasets:
        st.info("Koi data load nahi hai. Bot general knowledge se jawab dega.")
    for ds in datasets:
        st.markdown(f"**{ds.summary()}**")
        if ds.df is not None:
            st.dataframe(ds.df.head(50), use_container_width=True, hide_index=True)
        else:
            st.text((ds.text or "")[:1500] + ("..." if len(ds.text or "") > 1500 else ""))


def render_chat():
    history: list[dict] = ss(f"history_{bot_key}", [])
    for msg in history:
        with st.chat_message(msg["role"], avatar=bot.icon if msg["role"] == "assistant" else None):
            if msg.get("is_error"):
                st.error(msg["content"])
            else:
                st.markdown(msg["content"])
            if msg.get("provider"):
                st.caption(f"via {msg['provider']}")

    query = st.chat_input(bot.placeholder, key=f"chat_{bot_key}")
    if not query:
        if history:
            st.download_button(
                "⬇️ Chat download (JSON)", json.dumps(history, ensure_ascii=False, indent=2),
                file_name=f"{bot_key}_chat_{datetime.now():%Y%m%d_%H%M}.json", mime="application/json",
            )
        return

    with st.chat_message("user"):
        st.markdown(query)
    with st.chat_message("assistant", avatar=bot.icon):
        with st.spinner("Soch raha hoon..."):
            router = LLMRouter(settings)
            reply = bot.respond(query, history, datasets, router)
        for note in reply.notices:
            st.info(note)
        (st.error if reply.is_error else st.markdown)(reply.text)
        if reply.provider:
            st.caption(f"via {reply.provider}")
    history.append({"role": "user", "content": query})
    history.append({"role": "assistant", "content": reply.text, "provider": reply.provider, "is_error": reply.is_error})


try:
    render_chat()
except Exception as exc:  # noqa: BLE001 - final safety net so the page never shows a traceback
    log.exception("UI error")
    st.error(f"Unexpected error: {type(exc).__name__}. Page refresh karein; problem rahe to logs dekhein.")
