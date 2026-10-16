# ABA / ABA+ generator

## Fichiers
- `aba.py` : moteur (parseur, conversions, arguments, attaques, préférences)
- `app.py` : application Streamlit
- `part1_aba.ipynb` : démonstration (sorties conservées)
- `test_aba.py` : tests (`pytest`)

## Lancer en local
    pip install -r requirements.txt
    streamlit run app.py

## Déploiement (Streamlit Community Cloud)
1. Pousser ce dossier sur un dépôt GitHub public.
2. Sur https://share.streamlit.io : New app → dépôt, branche, fichier `app.py`.
3. Le lien public obtenu est celui à fournir dans le PDF.

## Utilisation
1. Coller le texte (format ci-dessous) dans la zone de saisie, ou garder l'exemple.
2. Cocher/décocher « Utiliser les préférences ».
3. Cliquer sur « Générer » : propriétés, framework converti, arguments (avec arbres), attaques et graphe.

## Format
    ## Literals
    L: [a,b,c,q,p,r,s,t]
    ## Assumptions
    A: [a,b,c]
    ## Contraries
    C(a): r
    ## Rules
    [r1]: p <- q,a
    [r2]: q <-
    ## Preferences
    PREF: a > b          (a,b > c : a et b équivalentes, toutes deux préférées à c ; a > b > c autorisé)
Les commentaires commencent par `%`. Chaque hypothèse doit avoir un contraire.

## Conventions
- Atomique : corps de règles = hypothèses uniquement. Non circulaire : pas de cycle de règles.
- Attaque normale : X⊢p attaque Y⊢q via b si p = contraire(b), b ∈ Y, et aucune a ∈ X avec a < b.
- Attaque inversée : si une telle a existe, c'est Y⊢q qui attaque X⊢p (via a).
