# Partie 1 : générateur ABA / ABA+

Ce document explique ce qui a été fait pour la partie 1 du projet, afin que les autres membres du groupe puissent le relire, l'utiliser et le défendre.

## 1. Le contexte en quelques lignes

L'**ABA** (Assumption-Based Argumentation) construit des arguments à partir de :
- **littéraux** (le vocabulaire),
- **hypothèses** (ce qu'on suppose vrai sauf preuve du contraire),
- **contraires** (chaque hypothèse a un contraire, qui la réfute),
- **règles** (« si corps alors tête »).

Un **argument** est une conclusion (claim) avec les hypothèses qui la soutiennent (support). On le note `{b,c} ⊢ r` : « en supposant b et c, on obtient r ».

Un argument **attaque** un autre si son claim est le contraire d'une hypothèse du support de l'autre.

Les **préférences** (`a > b`) disent qu'une hypothèse est plus fiable qu'une autre. Elles transforment certaines attaques en attaques **inversées** (ABA+).

Le travail demandé : écrire un programme qui lit un framework au format texte et produit tous les arguments et toutes les attaques, puis le mettre en ligne.

## 2. Ce qui a été fait

| Exigence du sujet | Où dans le code |
|---|---|
| Littéraux, règles, hypothèses | `ABAFramework.from_text` (parseur) |
| Contraires | `C(a): r` dans le parseur, vérifié par `validate()` |
| Conversion non circulaire et atomique | `to_non_circular()`, `to_atomic()`, `prepare()` |
| Tous les arguments | `arguments()` |
| Toutes les attaques | `attacks()` |
| Préférences, attaques normales / inversées | `_geq()`, `strictly_preferred()`, `attacks()`, `set_attacks()` |
| Application en ligne | `app.py` (Streamlit) |

Fichiers du dossier :
- `aba.py` : le moteur (toute la logique)
- `app.py` : l'application web, qui importe `aba.py`
- `part1_aba.ipynb` : la démonstration, avec les sorties conservées (ne pas les effacer)
- `test_aba.py` : les tests automatiques (`python -m pytest test_aba.py`)
- `requirements.txt` : dépendances pour le déploiement
- `make_nb.py` : script qui a généré le notebook (peut être ignoré)

## 3. Comment fonctionne le code

**Parseur (`from_text`).** Chaque ligne est reconnue par son début (`L:`, `A:`, `C(x):`, `[rN]:`, `PREF:`). Les titres `##` sont ignorés. Les commentaires commencent par `%`. Une erreur de syntaxe ou une hypothèse sans contraire lève une `ABAError` avec un message clair.

**Conversions.**
- `to_flat` : si une hypothèse `a` est tête d'une règle, elle est remplacée par une nouvelle hypothèse `a'` et on ajoute la règle `a <- a'`.
- `find_cycle` / `is_circular` : détection des cycles de règles (parcours en profondeur).
- `to_non_circular` : en cas de cycle, tous les littéraux non-hypothèses sont copiés sur `k` niveaux, avec `k = |X|`. Une règle atomique est copiée à tous les niveaux ; une autre règle lit le niveau précédent. Les niveaux précédents sont suffixés (`p_1`, `p_2`, ...) et le niveau `k` garde le nom original.
- `to_atomic` : transformation sensitive du cours. Pour chaque littéral non-hypothèse `s`, elle ajoute les hypothèses `s_d` et `s_nd`, remplace chaque occurrence de `s` dans un corps par `s_d`, et ajoute les contraires `s_d -> s_nd` et `s_nd -> s`.
- `prepare` : enchaîne plat, non circulaire, atomique.

**Arguments (`arguments`).** Point fixe : on part d'un argument par hypothèse, puis on combine les arguments existants avec chaque règle dont tout le corps est déjà couvert, jusqu'à ce qu'il n'y ait plus rien de nouveau. Chaque argument garde son arbre de dérivation (`tree_str()`). Les arguments sont les paires support-claim de tous les arbres, y compris dans un framework circulaire.

**Préférences.** `PREF: a,b > c` signifie que a et b sont équivalentes et toutes deux préférées à c. `a > b > c` est aussi accepté. `_geq()` construit la relation « au moins aussi préférée » avec la transitivité, `strictly_preferred(x,y)` en déduit la préférence stricte, et `less(a,b)` signifie `a < b`.

**Attaques (`attacks`).** Pour un argument A dont le claim est le contraire d'une hypothèse `b` présente dans le support d'un argument B :
- si aucune hypothèse `a` du support de A ne vérifie `a < b`, A attaque B (attaque **normale**) ;
- sinon, c'est B qui attaque A (attaque **inversée**).

Sans préférences, toutes les attaques sont normales.

**Attaques ABA+ entre ensembles (`set_attacks`).** Cette vue construit tous les sous-ensembles d'hypothèses. Pour un argument de support `S` dont le claim réfute `z` : si aucune hypothèse de `S` n'est moins préférée que `z`, tout ensemble contenant `S` attaque tout ensemble contenant `z`. Sinon, l'attaque est inversée. Un même couple peut appartenir aux deux catégories. Le calcul est limité à 10 hypothèses.

## 4. Exemple de l'énoncé

Avec `PREF: a > b`, on obtient 8 arguments (`{} ⊢ q`, `{a} ⊢ a`, `{b} ⊢ b`, `{c} ⊢ c`, `{a} ⊢ p`, `{b,c} ⊢ r`, `{a,c} ⊢ s`, `{a,c} ⊢ t`) et 10 attaques. La transformation atomique sensitive contient 13 hypothèses, 5 règles et 18 arguments. Les attaques ABA+ entre ensembles contiennent 12 attaques normales et 8 inversées. Tout est visible dans `part1_aba.ipynb`.

## 5. Définitions utilisées

1. **Atomique** : le corps de chaque règle ne contient que des hypothèses ; la transformation utilisée est la transformation sensitive du cours.
2. **Non circulaire** : aucun cycle entre atomes non-hypothèses ; `to_non_circular()` utilise tous les littéraux non-hypothèses, pas seulement les têtes de règles.
3. **Arguments core** : les paires (feuilles, claim) de tous les arbres sont conservées, même lorsque le framework d'origine est circulaire.
4. **Attaque inversée** : définition ABA+ (Čyras et Toni), appliquée aux arguments et aux ensembles d'hypothèses.

## 6. Utilisation

En local :

    pip install -r requirements.txt
    streamlit run app.py

Dans l'appli :
1. coller le texte du framework (l'exemple de l'énoncé est préchargé),
2. cocher ou décocher « Utiliser les préférences »,
3. cliquer sur « Générer » : propriétés, framework non circulaire éventuel, framework atomique et nombre d'arguments atomiques,
4. consulter l'onglet « ABA (arguments) » pour les arguments et attaques entre arguments,
5. consulter l'onglet « ABA+ (sets) » pour les attaques normales/inversées entre ensembles et leur graphe (disponible jusqu'à 4 hypothèses).

Format attendu :

    ## Literals
    L: [a,b,c,q,p,r,s,t]
    ## Assumptions
    A: [a,b,c]
    ## Contraries
    C(a): r
    C(b): s
    C(c): t
    ## Rules
    [r1]: p <- q,a
    [r2]: q <-
    [r3]: r <- b,c
    [r4]: t <- p,c
    [r5]: s <- t
    ## Preferences
    PREF: a > b

## 7. Déploiement (question 2 du sujet)

1. Créer un miroir public GitHub et y pousser la branche `main`.
2. Sur https://share.streamlit.io : Create app, choisir le dépôt, la branche `main` et `app.py`.
3. Dans Advanced settings, sélectionner Python 3.12.
4. Reporter le lien public ici et dans le PDF.

Lien de l'application : **à compléter après déploiement**

## 8. État d'avancement de la partie 1

- [x] Implémenter et tester le moteur ABA/ABA+ avec les valeurs du TD4.
- [x] Mettre à jour l'application, le notebook et la documentation.
- [ ] Créer le miroir GitHub public et déployer l'application sur Streamlit Cloud avec Python 3.12.
- [ ] Reporter le lien public dans ce README et dans le PDF.
- [ ] Rédiger la partie 1 du PDF (max 15 pages pour tout le projet), avec le lien et les instructions d'usage.
