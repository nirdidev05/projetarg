"""Appli Streamlit : générateur ABA / ABA+.  Lancer :  streamlit run app.py"""
import pandas as pd
import streamlit as st

from aba import ABAFramework, ABAError, EXAMPLE

st.set_page_config(page_title="ABA Generator", layout="wide")
st.title("ABA / ABA+ generator")
st.caption("Collez un framework au format texte, puis cliquez sur « Générer ».")

text = st.text_area("Framework ABA", EXAMPLE, height=380)
use_pref = st.checkbox("Utiliser les préférences (attaques normales / inversées)", value=True)

if st.button("Générer", type="primary"):
    try:
        fw = ABAFramework.from_text(text)
    except ABAError as e:
        st.error(f"Erreur : {e}")
        st.stop()
    for w in fw.warnings:
        st.warning(w)

    st.subheader("1. Propriétés et conversions")
    c1, c2, c3 = st.columns(3)
    c1.metric("Plat", "oui" if fw.is_flat() else "non")
    c2.metric("Non circulaire", "oui" if not fw.is_circular() else "non")
    c3.metric("Atomique", "oui" if fw.is_atomic() else "non")
    if fw.is_circular():
        st.info("Cycle de règles détecté : " + " → ".join(fw.find_cycle()))
    with st.expander("Framework converti (plat → non circulaire → atomique)"):
        st.code(fw.prepare().to_text(), language="text")

    args = fw.arguments()
    atts = fw.attacks(args, use_preferences=use_pref)

    st.subheader(f"2. Arguments ({len(args)})")
    st.dataframe(pd.DataFrame([{"Argument": a.id, "Claim": a.claim,
                                "Support": "{" + ",".join(sorted(a.support)) + "}",
                                "Arbre": a.tree_str()} for a in args]), use_container_width=True)

    st.subheader(f"3. Attaques ({len(atts)})")
    st.dataframe(pd.DataFrame([{"Attaquant": t.attacker, "Cible": t.target, "Type": t.kind,
                                "Via": t.via} for t in atts]), use_container_width=True)

    st.subheader("4. Graphe (rouge pointillé = attaque inversée)")
    st.graphviz_chart(fw.to_dot(args, atts))
