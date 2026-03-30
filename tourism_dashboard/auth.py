import hmac

import streamlit as st


def require_password() -> None:
    if "APP_PASSWORD" not in st.secrets:
        st.error("Manjka APP_PASSWORD v Streamlit Secrets.")
        st.stop()

    if st.session_state.get("authenticated", False):
        return

    st.title("Prijava")

    with st.form("login_form", clear_on_submit=False):
        password = st.text_input("Geslo", type="password")
        submitted = st.form_submit_button("Vstopi")

        if submitted:
            expected_password = str(st.secrets["APP_PASSWORD"])
            if hmac.compare_digest(password, expected_password):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Napačno geslo.")

    st.stop()

