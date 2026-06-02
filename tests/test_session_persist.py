"""Auth token (reload persistence) and query-param state restore."""
import streamlit_app as app


def test_auth_token_stable_and_secret():
    t1 = app._auth_token("hunter2")
    t2 = app._auth_token("hunter2")
    assert t1 == t2 and len(t1) == 32
    assert "hunter2" not in t1                 # non-reversible (no raw password)
    assert app._auth_token("other") != t1
