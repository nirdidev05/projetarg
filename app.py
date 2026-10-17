"""Appli Streamlit : générateur ABA / ABA+.  Lancer :  streamlit run app.py"""
import pandas as pd
import streamlit as st
from itertools import combinations

from aba import ABAFramework, ABAError, EXAMPLE

st.set_page_config(page_title="ABA Generator", layout="wide")
st.title("ABA / ABA+ generator")
st.caption("Collez un framework au format texte, puis cliquez sur « Générer ».")


def _set_label(values):
    return "∅" if not values else "{" + ",".join(sorted(values)) + "}"


def _set_id(values):
    return "S_empty" if not values else "S_" + "_".join(sorted(values))


def _sets_dot(assumptions, normal, reverse):
    subsets = [
        frozenset(combo)
        for size in range(len(assumptions) + 1)
        for combo in combinations(assumptions, size)
    ]
    lines = ["digraph ABAPlus {", "  rankdir=LR;", '  node [shape=box, style=rounded, fontname="Helvetica"];']
    for subset in subsets:
        lines.append(f'  {_set_id(subset)} [label="{_set_label(subset)}"];')
    for attacker, target in sorted(normal, key=lambda pair: (_set_id(pair[0]), _set_id(pair[1]))):
        lines.append(f"  {_set_id(attacker)} -> {_set_id(target)} [color=black];")
    for attacker, target in sorted(reverse, key=lambda pair: (_set_id(pair[0]), _set_id(pair[1]))):
        lines.append(f"  {_set_id(attacker)} -> {_set_id(target)} [color=red, style=dashed];")
    lines.append("}")
    return "\n".join(lines)

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
        with st.expander("Framework non circulaire"):
            st.code(fw.to_non_circular().to_text(), language="text")
    atomic = fw.prepare()
    with st.expander("Framework atomique"):
        st.metric("Arguments du framework atomique", len(atomic.assumptions) + len(atomic.rules))
        st.code(atomic.to_text(), language="text")

    args = fw.arguments()
    atts = fw.attacks(args, use_preferences=use_pref)

    tab_arguments, tab_sets = st.tabs(["ABA (arguments)", "ABA+ (sets)"])
    with tab_arguments:
        st.subheader(f"Arguments d'origine ({len(args)})")
        st.dataframe(pd.DataFrame([{"Argument": a.id, "Claim": a.claim,
                                    "Support": _set_label(a.support),
                                    "Arbre": a.tree_str()} for a in args]), width="stretch")
        if fw.is_circular():
            nc_args = fw.to_non_circular().arguments()
            st.subheader(f"Arguments du framework non circulaire ({len(nc_args)})")
            st.dataframe(pd.DataFrame([{"Argument": a.id, "Claim": a.claim,
                                        "Support": _set_label(a.support),
                                        "Arbre": a.tree_str()} for a in nc_args]), width="stretch")
        st.subheader(f"Attaques entre arguments ({len(atts)})")
        st.dataframe(pd.DataFrame([{"Attaquant": t.attacker, "Cible": t.target, "Type": t.kind,
                                    "Via": t.via} for t in atts]), width="stretch")
        st.subheader("Graphe (rouge pointillé = attaque inversée)")
        st.graphviz_chart(fw.to_dot(args, atts))

    with tab_sets:
        try:
            normal, reverse = fw.set_attacks(use_preferences=use_pref)
        except ABAError as e:
            st.error(str(e))
            st.stop()
        all_pairs = normal | reverse
        sorted_pairs = sorted(all_pairs, key=lambda pair: (_set_id(pair[0]), _set_id(pair[1])))
        display_limit = 5000
        rows = []
        for attacker, target in sorted_pairs[:display_limit]:
            kind = "both" if (attacker, target) in normal and (attacker, target) in reverse else (
                "normal" if (attacker, target) in normal else "reverse")
            rows.append({"X": _set_label(attacker), "Y": _set_label(target), "Type": kind})
        st.metric("Attaques normales", len(normal))
        st.metric("Attaques inversées", len(reverse))
        if len(all_pairs) > display_limit:
            st.info(f"{len(all_pairs)} couples au total : affichage limité aux {display_limit} premiers.")
        st.dataframe(pd.DataFrame(rows), width="stretch")
        if len(fw.assumptions) <= 4:
            st.graphviz_chart(_sets_dot(fw.assumptions, normal, reverse))
