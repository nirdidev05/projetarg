import nbformat as nbf
nb = nbf.v4.new_notebook()

def C(s):
	cell = nbf.v4.new_code_cell(s)
	cell.metadata["language"] = "python"
	nb.cells.append(cell)

def M(s):
	cell = nbf.v4.new_markdown_cell(s)
	cell.metadata["language"] = "markdown"
	nb.cells.append(cell)
M("# Partie 1 : ABA generator\nLe moteur est dans `aba.py` ; ce notebook démontre chaque capacité demandée.")
M("## 1. Parsing de l'exemple du sujet")
C("from aba import *\nfw = ABAFramework.from_text(EXAMPLE)\nprint(fw.to_text())\nprint('plat:', fw.is_flat(), '| circulaire:', fw.is_circular(), '| atomique:', fw.is_atomic())")
M("## 2. Conversion atomique sensitive")
C("at = fw.prepare()\nprint(at.to_text())\nprint('atomique:', at.is_atomic())")
M("## 3. Arguments (avec arbres de dérivation) et attaques sans préférences")
C("args = fw.arguments()\nfor a in args: print(a)\nprint()\nprint(args[7].tree_str())\nprint()\nfor t in fw.attacks(args, use_preferences=False): print(t)")
M("## 4. Préférences `a > b` : attaques normales / inversées")
C("for t in fw.attacks(args): print(t)")
C("from collections import Counter\nprint(Counter(t.kind for t in fw.attacks(args)))")
M("## 5. Cas supplémentaires\n### 5a. Règles circulaires")
C("""circ = ABAFramework.from_text('''
L: [a,b,p,q,r]
A: [a,b]
C(a): q
C(b): r
[r1]: p <- q,a
[r2]: q <- p
[r3]: q <- b
''')
print('cycle:', circ.find_cycle())
nc = circ.to_non_circular(); print('non circulaire après conversion:', not nc.is_circular())
print(nc.to_atomic().to_text())
for a in circ.arguments(): print(a)""")
M("### 5b. Hypothèse en tête de règle (conversion en ABA plat)")
C("""nf = ABAFramework.from_text('''
L: [a,b,c,x]
A: [a,b]
C(a): c
C(b): x
[r1]: a <- b
[r2]: c <-
''')
print('plat:', nf.is_flat()); print(nf.to_flat().to_text())""")
M("### 5c. Préférences d'équivalence `a,b > c` et chaînes `a > b > c`")
C("""p = ABAFramework.from_text('''
L: [a,b,c,x,y,z]
A: [a,b,c]
C(a): x
C(b): y
C(c): z
[r1]: x <- b
[r2]: y <- a
[r3]: z <- a
PREF: a,b > c
''')
print('a>c', p.strictly_preferred('a','c'), '| b>c', p.strictly_preferred('b','c'), '| a>b', p.strictly_preferred('a','b'))
A = p.arguments()
for a in A: print(a)
for t in p.attacks(A): print(t)""")
M("## 6. Vérification TD4 : conversion non circulaire et framework atomique")
C("""td4 = ABAFramework.from_text('''
L: [a,b,x,y,z]
A: [a,b]
C(a): y
C(b): x
[r1]: y <- b
[r2]: y <- y
[r3]: x <- a
[r4]: x <- x
[r5]: z <- x,y
''')
td4_nc = td4.to_non_circular()
print(td4_nc.to_text())
print('arguments non circulaires:', len(td4_nc.arguments()))
td4_atomic = td4_nc.to_atomic()
print('hypothèses atomiques:', len(td4_atomic.assumptions))
print('règles atomiques:', len(td4_atomic.rules))
print('arguments atomiques:', len(td4_atomic.arguments()))
print('vérification du compte atomique:', len(td4_atomic.arguments()) == len(td4_atomic.assumptions) + len(td4_atomic.rules))""")
M("## 7. Vérification TD4 : attaques ABA+ entre ensembles")
C("""def format_set(values):
	return '∅' if not values else '{' + ','.join(sorted(values)) + '}'

normal, reverse = fw.set_attacks()
print('attaques normales:', len(normal))
print('attaques inversées:', len(reverse))
for X, Y in sorted(normal): print('normal:', format_set(X), '->', format_set(Y))
for X, Y in sorted(reverse): print('reverse:', format_set(X), '->', format_set(Y))""")
M("## 8. Graphe (Graphviz)")
C("print(fw.to_dot(args))")
nbf.write(nb, "part1_aba.ipynb")
