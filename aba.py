"""
aba.py - Générateur ABA / ABA+ (moteur partagé par le notebook et l'appli web).

Capacités :
  * parsing du format texte du sujet (littéraux, hypothèses, contraires, règles, préférences)
  * conversion en ABA plat, non circulaire, puis atomique
  * construction de tous les arguments (arbres de dérivation) et de toutes les attaques
  * préférences entre hypothèses, attaques normales / inversées (ABA+)

Conventions (à comparer avec celles de votre cours) :
  * Atomique  : le corps de chaque règle ne contient que des hypothèses (dépliage complet).
  * Non circulaire : aucun cycle dans le graphe de dépendance des atomes non-hypothèses.
  * Préférence : "a > b" signifie a strictement préférée à b ; "a,b > c" : a et b équivalentes,
    toutes deux préférées à c. On écrit a < b quand b est strictement préférée à a.
  * Attaque normale : X |- p attaque Y |- q (via b) si p est le contraire de b dans Y
    et il n'existe aucune hypothèse a dans X avec a < b.
  * Attaque inversée : si p est le contraire de b dans Y mais qu'il existe a dans X avec a < b,
    alors c'est Y |- q qui attaque X |- p (attaque inversée, via a).
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


class ABAError(Exception):
    """Erreur de syntaxe ou de cohérence dans un framework ABA."""


@dataclass(frozen=True)
class Rule:
    id: str
    head: str
    body: Tuple[str, ...]

    def __str__(self) -> str:
        return f"[{self.id}]: {self.head} <-" + (" " + ",".join(self.body) if self.body else "")


@dataclass(frozen=True)
class Argument:
    id: str
    claim: str
    support: frozenset
    tree: tuple = field(compare=False, default=())  # (claim, rule_id|None, (enfants...))

    @property
    def key(self):
        return (self.claim, self.support)

    def __str__(self) -> str:
        return f"{self.id}: {{{','.join(sorted(self.support))}}} ⊢ {self.claim}"

    def tree_str(self) -> str:
        lines: List[str] = []

        def rec(t, depth):
            claim, rid, children = t
            lines.append("  " * depth + claim + (f"   [{rid}]" if rid else "   (hypothèse)"))
            for c in children:
                rec(c, depth + 1)

        rec(self.tree, 0)
        return "\n".join(lines)


@dataclass(frozen=True)
class Attack:
    attacker: str   # id d'argument
    target: str     # id d'argument
    kind: str       # "normal" | "reverse"
    via: str        # hypothèse visée (normal) ou hypothèse affaiblie (reverse)

    def __str__(self) -> str:
        return f"{self.attacker} -> {self.target}  ({self.kind}, via {self.via})"


# --------------------------------------------------------------------------- #
IDENT = r"[A-Za-z0-9_']+"


def _split_list(s: str) -> List[str]:
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    return [x.strip() for x in s.split(",") if x.strip()]


class ABAFramework:
    def __init__(self, literals=(), assumptions=(), contraries=None, rules=(), preferences=(),
                 origin=None):
        self.literals: List[str] = list(dict.fromkeys(literals))
        self.assumptions: List[str] = list(dict.fromkeys(assumptions))
        self.contraries: Dict[str, str] = dict(contraries or {})
        self.rules: List[Rule] = list(rules)
        # liste de chaînes de préférence ; chaque chaîne = liste de niveaux (du plus préféré au moins préféré),
        # chaque niveau = liste d'hypothèses équivalentes
        self.preferences: List[List[List[str]]] = [list(map(list, ch)) for ch in preferences]
        self.origin: Dict[str, str] = dict(origin or {})
        self.warnings: List[str] = []
        self._complete_literals()

    # ------------------------------------------------------------------ parsing
    @classmethod
    def from_text(cls, text: str) -> "ABAFramework":
        literals: List[str] = []
        assumptions: List[str] = []
        contraries: Dict[str, str] = {}
        rules: List[Rule] = []
        prefs: List[List[List[str]]] = []
        for n, raw in enumerate(text.splitlines(), 1):
            line = raw.split("%")[0].strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^L\s*:\s*(.*)$", line)
            if m:
                literals += _split_list(m.group(1)); continue
            m = re.match(r"^A\s*:\s*(.*)$", line)
            if m:
                assumptions += _split_list(m.group(1)); continue
            m = re.match(rf"^C\(\s*({IDENT})\s*\)\s*:\s*({IDENT})\s*$", line)
            if m:
                if m.group(1) in contraries:
                    raise ABAError(f"Ligne {n}: contraire de {m.group(1)} défini deux fois")
                contraries[m.group(1)] = m.group(2); continue
            m = re.match(rf"^\[\s*({IDENT})\s*\]\s*:\s*({IDENT})\s*(?:<-|←|:-)\s*(.*)$", line)
            if m:
                body = tuple(_split_list(m.group(3)))
                rules.append(Rule(m.group(1), m.group(2), body)); continue
            m = re.match(r"^PREF\s*:\s*(.+)$", line)
            if m:
                levels = [_split_list(p) for p in m.group(1).split(">")]
                if len(levels) < 2 or any(not lv for lv in levels):
                    raise ABAError(f"Ligne {n}: préférence mal formée : {line!r}")
                prefs.append(levels); continue
            raise ABAError(f"Ligne {n}: syntaxe non reconnue : {line!r}")
        fw = cls(literals, assumptions, contraries, rules, prefs)
        fw.validate()
        return fw

    def to_text(self) -> str:
        out = ["## Literals", f"L: [{','.join(self.literals)}]", "", "## Assumptions",
               f"A: [{','.join(self.assumptions)}]", "", "## Contraries"]
        out += [f"C({a}): {self.contraries[a]}" for a in self.assumptions if a in self.contraries]
        out += ["", "## Rules"] + [str(r) for r in self.rules]
        if self.preferences:
            out += ["", "## Preferences"]
            for ch in self.preferences:
                out.append("PREF: " + " > ".join(",".join(lv) for lv in ch))
        return "\n".join(out) + "\n"

    # ------------------------------------------------------------------ validation
    def _complete_literals(self):
        known = set(self.literals)
        extra = []
        for a in self.assumptions:
            extra.append(a)
        for r in self.rules:
            extra += [r.head, *r.body]
        extra += list(self.contraries.values())
        for x in extra:
            if x not in known:
                known.add(x)
                self.literals.append(x)
                self.warnings.append(f"Littéral '{x}' absent de L : ajouté automatiquement.")

    def validate(self):
        for a in self.assumptions:
            if a not in self.contraries:
                raise ABAError(f"L'hypothèse '{a}' n'a pas de contraire (ligne C({a}): ...).")
        for a in self.contraries:
            if a not in self.assumptions:
                raise ABAError(f"C({a}) défini mais '{a}' n'est pas une hypothèse.")
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ABAError("Identifiants de règles dupliqués.")
        for ch in self.preferences:
            for lv in ch:
                for x in lv:
                    if x not in self.assumptions:
                        raise ABAError(f"Préférence sur '{x}', qui n'est pas une hypothèse.")
        return True

    # ------------------------------------------------------------------ utilitaires
    def copy(self, **kw) -> "ABAFramework":
        d = dict(literals=self.literals, assumptions=self.assumptions, contraries=self.contraries,
                 rules=self.rules, preferences=self.preferences, origin=self.origin)
        d.update(kw)
        fw = ABAFramework(**d)
        fw.warnings = list(self.warnings)
        return fw

    def base(self, x: str) -> str:
        return self.origin.get(x, x)

    def non_assumptions(self) -> List[str]:
        s = set(self.assumptions)
        return [x for x in self.literals if x not in s]

    # ------------------------------------------------------------------ propriétés
    def is_flat(self) -> bool:
        return not any(r.head in set(self.assumptions) for r in self.rules)

    def find_cycle(self) -> Optional[List[str]]:
        """Renvoie un cycle de dépendance entre atomes non-hypothèses (ou None)."""
        assum = set(self.assumptions)
        g: Dict[str, Set[str]] = {}
        for r in self.rules:
            g.setdefault(r.head, set()).update(b for b in r.body if b not in assum)
        state: Dict[str, int] = {}
        stack: List[str] = []

        def dfs(u):
            state[u] = 1
            stack.append(u)
            for v in sorted(g.get(u, ())):
                if state.get(v, 0) == 0:
                    c = dfs(v)
                    if c:
                        return c
                elif state[v] == 1:
                    return stack[stack.index(v):] + [v]
            stack.pop()
            state[u] = 2
            return None

        for u in sorted(g):
            if state.get(u, 0) == 0:
                c = dfs(u)
                if c:
                    return c
        return None

    def is_circular(self) -> bool:
        return self.find_cycle() is not None

    def is_atomic(self) -> bool:
        assum = set(self.assumptions)
        return all(all(b in assum for b in r.body) for r in self.rules)

    # ------------------------------------------------------------------ transformations
    def to_flat(self) -> "ABAFramework":
        """Si une hypothèse a est tête de règle : on la remplace par une nouvelle hypothèse a'
        (même contraire) et on ajoute la règle a <- a'. a devient un atome ordinaire."""
        if self.is_flat():
            return self.copy()
        heads = {r.head for r in self.rules}
        ren = {}
        used = set(self.literals)
        for a in self.assumptions:
            if a in heads:
                new = a + "'"
                while new in used:
                    new += "'"
                used.add(new)
                ren[a] = new
        sub = lambda x: ren.get(x, x)
        rules = [Rule(r.id, r.head, tuple(sub(b) for b in r.body)) for r in self.rules]
        rules += [Rule(f"f_{a}", a, (n,)) for a, n in ren.items()]
        assumptions = [sub(a) for a in self.assumptions]
        contraries = {sub(a): c for a, c in self.contraries.items()}
        prefs = [[[sub(x) for x in lv] for lv in ch] for ch in self.preferences]
        origin = dict(self.origin)
        for a, n in ren.items():
            origin[n] = self.base(a)
        return ABAFramework(self.literals + list(ren.values()), assumptions, contraries, rules,
                            prefs, origin)

    def to_non_circular(self) -> "ABAFramework":
        """Supprime les cycles par copies indexées p_1..p_N (N = nb d'atomes têtes de règles) :
        h_i <- (corps où chaque atome x est remplacé par x_{i-1}), et h_i <- h_{i-1}.
        Les contraires de non-hypothèses c sont remplacés par c_N. Sans cycle : copie inchangée."""
        if not self.is_circular():
            return self.copy()
        assum = set(self.assumptions)
        heads = sorted({r.head for r in self.rules if r.head not in assum})
        N = len(heads)
        hs = set(heads)
        idx = lambda x, k: f"{x}_{k}" if x in hs else x
        rules: List[Rule] = []
        origin = dict(self.origin)
        for r in self.rules:
            has_derived = any(b in hs for b in r.body)
            for i in range(1, N + 1):
                if has_derived and i == 1:
                    continue
                body = tuple(idx(b, i - 1) if b in hs else b for b in r.body)
                rules.append(Rule(f"{r.id}.{i}", idx(r.head, i), body))
        for h in heads:
            for i in range(2, N + 1):
                rules.append(Rule(f"c_{h}.{i}", f"{h}_{i}", (f"{h}_{i-1}",)))
        contraries = {a: (idx(c, N) if c in hs else c) for a, c in self.contraries.items()}
        lits = list(self.assumptions) + [x for x in self.literals if x not in assum and x not in hs]
        for h in heads:
            for i in range(1, N + 1):
                lits.append(f"{h}_{i}")
                origin[f"{h}_{i}"] = self.base(h)
        return ABAFramework(lits, self.assumptions, contraries, rules, self.preferences, origin)

    def to_atomic(self) -> "ABAFramework":
        """Dépliage complet : chaque règle devient  h <- {hypothèses}  (une règle par support
        minimal dérivable). Les noms issus de to_non_circular sont ramenés à leur nom d'origine."""
        assum = set(self.assumptions)
        derived: Dict[str, Set[frozenset]] = {}
        changed = True
        while changed:
            changed = False
            for r in self.rules:
                options = []
                ok = True
                for b in r.body:
                    if b in assum:
                        options.append([frozenset([b])])
                    else:
                        s = derived.get(b)
                        if not s:
                            ok = False
                            break
                        options.append(list(s))
                if not ok:
                    continue
                for combo in itertools.product(*options):
                    sup = frozenset().union(*combo) if combo else frozenset()
                    tgt = derived.setdefault(r.head, set())
                    if sup not in tgt:
                        tgt.add(sup)
                        changed = True
        seen = set()
        rules: List[Rule] = []
        for h in sorted(derived):
            for sup in sorted(derived[h], key=lambda s: (len(s), sorted(s))):
                key = (self.base(h), sup)
                if key in seen:
                    continue
                seen.add(key)
                rules.append(Rule(f"u{len(rules)+1}", self.base(h), tuple(sorted(sup))))
        contraries = {a: self.base(c) for a, c in self.contraries.items()}
        lits = list(dict.fromkeys(
            [self.base(x) for x in self.literals if x in assum or x not in self.origin]
            + [self.base(c) for c in contraries.values()] + [r.head for r in rules]))
        return ABAFramework(lits, self.assumptions, contraries, rules, self.preferences)

    def prepare(self) -> "ABAFramework":
        """Pipeline complet : plat -> non circulaire -> atomique."""
        return self.to_flat().to_non_circular().to_atomic()

    # ------------------------------------------------------------------ préférences
    def _geq(self) -> Set[Tuple[str, str]]:
        edges: Set[Tuple[str, str]] = set()
        for ch in self.preferences:
            for i, lv in enumerate(ch):
                for x in lv:                       # équivalence dans un niveau
                    for y in lv:
                        edges.add((x, y))
                for lv2 in ch[i + 1:]:             # niveaux précédents > niveaux suivants
                    for x in lv:
                        for y in lv2:
                            edges.add((x, y))
        closure = set(edges)
        changed = True
        while changed:
            changed = False
            for (a, b) in list(closure):
                for (c, d) in list(closure):
                    if b == c and (a, d) not in closure:
                        closure.add((a, d))
                        changed = True
        return closure

    def strictly_preferred(self, x: str, y: str) -> bool:
        g = self._geq()
        return (x, y) in g and (y, x) not in g

    def less(self, a: str, b: str) -> bool:
        """a < b  (b strictement préférée à a)."""
        return self.strictly_preferred(b, a)

    # ------------------------------------------------------------------ arguments
    def _raw_arguments(self):
        assum = set(self.assumptions)
        found: Dict[Tuple[str, frozenset], tuple] = {}
        for a in sorted(assum):
            found[(a, frozenset([a]))] = (a, None, ())
        changed = True
        while changed:
            changed = False
            by_claim: Dict[str, List[Tuple[frozenset, tuple]]] = {}
            for (c, s), t in found.items():
                by_claim.setdefault(c, []).append((s, t))
            for r in self.rules:
                if any(b not in by_claim for b in r.body):
                    continue
                for combo in itertools.product(*[sorted(by_claim[b], key=lambda x: sorted(x[0]))
                                                 for b in r.body]):
                    sup = frozenset().union(*[c[0] for c in combo]) if combo else frozenset()
                    key = (r.head, sup)
                    if key not in found:
                        found[key] = (r.head, r.id, tuple(c[1] for c in combo))
                        changed = True
        return found

    def arguments(self) -> List[Argument]:
        """Tous les arguments (claim, support) avec un arbre de dérivation.
        Un argument est un arbre NON circulaire : si les règles sont circulaires, on passe par
        to_non_circular() (une dérivation qui répète un atome sur une branche ne donne qu'un
        support non minimal, elle est donc écartée), puis on ramène les noms d'origine."""
        fw = self if not self.is_circular() else self.to_non_circular()
        raw = fw._raw_arguments()
        rename = lambda t: (fw.base(t[0]), t[1], tuple(rename(c) for c in t[2]))
        found: Dict[Tuple[str, frozenset], tuple] = {}
        for (c, s), t in raw.items():
            found.setdefault((fw.base(c), s), rename(t))
        ordered = sorted(found.items(), key=lambda kv: (len(kv[0][1]), kv[0][0], sorted(kv[0][1])))
        return [Argument(f"A{i}", c, s, t) for i, ((c, s), t) in enumerate(ordered, 1)]

    # ------------------------------------------------------------------ attaques
    def attacks(self, arguments: Optional[List[Argument]] = None,
                use_preferences: bool = True) -> List[Attack]:
        args = arguments if arguments is not None else self.arguments()
        prefs = use_preferences and bool(self.preferences)
        geq = self._geq() if prefs else set()
        lt = lambda a, b: (b, a) in geq and (a, b) not in geq   # a < b
        by_contrary: Dict[str, List[str]] = {}
        for a, c in self.contraries.items():
            by_contrary.setdefault(c, []).append(a)
        out: Set[Attack] = set()
        for A in args:
            for b in by_contrary.get(A.claim, []):
                for B in args:
                    if b not in B.support:
                        continue
                    weaker = sorted(a for a in A.support if lt(a, b)) if prefs else []
                    if not weaker:
                        out.add(Attack(A.id, B.id, "normal", b))
                    else:
                        out.add(Attack(B.id, A.id, "reverse", weaker[0]))
        num = lambda s: int(s[1:])
        return sorted(out, key=lambda t: (num(t.attacker), num(t.target), t.kind))

    # ------------------------------------------------------------------ export
    def to_dot(self, arguments=None, attacks=None) -> str:
        args = arguments if arguments is not None else self.arguments()
        atts = attacks if attacks is not None else self.attacks(args)
        lines = ["digraph ABA {", "  rankdir=LR;", '  node [shape=box, style=rounded, fontname="Helvetica"];']
        for a in args:
            lab = f"{a.id}\\n{{{','.join(sorted(a.support))}}} ⊢ {a.claim}"
            lines.append(f'  {a.id} [label="{lab}"];')
        for t in atts:
            style = 'color="red", style=dashed' if t.kind == "reverse" else 'color="black"'
            lines.append(f'  {t.attacker} -> {t.target} [{style}];')
        lines.append("}")
        return "\n".join(lines)


EXAMPLE = """## Literals
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
"""

if __name__ == "__main__":
    fw = ABAFramework.from_text(EXAMPLE)
    args = fw.arguments()
    for a in args:
        print(a)
    for t in fw.attacks(args):
        print(t)
