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


def weighted_h_categorizer(arguments: List[str], attacks: List[Attack],
                           weights: Dict[str, float], epsilon: float = 1e-6) -> Dict[str, float]:
    """Return weighted h-categorizer scores indexed by argument ID."""
    if epsilon <= 0 or not float("-inf") < epsilon < float("inf"):
        raise ValueError("epsilon must be a finite positive number")

    nodes = set(arguments)
    if set(weights) != nodes:
        raise ValueError("weights must contain exactly one weight per argument")
    if any(not 0 <= weight <= 1 for weight in weights.values()):
        raise ValueError("argument weights must be in [0, 1]")

    attackers = {argument: set() for argument in nodes}
    for attack in attacks:
        if attack.attacker not in nodes or attack.target not in nodes:
            raise ValueError("attacks must reference known argument IDs")
        attackers[attack.target].add(attack.attacker)

    scores = dict(weights)
    while scores:
        updated = {
            argument: weights[argument] / (1 + sum(scores[a] for a in attackers[argument]))
            for argument in nodes
        }
        if max(abs(updated[a] - scores[a]) for a in nodes) <= epsilon:
            return updated
        scores = updated
    return scores


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
        """Supprime les cycles par copies indexées de tous les littéraux non-hypothèses.

        Un atome s de X = non_assumptions() s'appelle s au niveau k et s_i aux
        niveaux précédents. Les règles atomiques sont copiées à tous les niveaux,
        tandis que les autres règles sont décalées d'un niveau. Sans cycle, une
        copie du framework est renvoyée.
        """
        if not self.is_circular():
            return self.copy()
        assum = set(self.assumptions)
        X = self.non_assumptions()
        k = len(X)
        xs = set(X)

        def name(atom: str, level: int) -> str:
            return atom if atom in assum or level == k else f"{atom}_{level}"

        rules: List[Rule] = []
        for r in self.rules:
            atomic = all(b in assum for b in r.body)
            levels = range(1, k + 1) if atomic else range(2, k + 1)
            for i in levels:
                body = tuple(
                    b if b in assum else name(b, i - 1)
                    for b in r.body
                ) if not atomic else r.body
                rules.append(Rule(f"{r.id}.{i}", name(r.head, i), body))
        contraries = dict(self.contraries)
        lits = list(self.literals)
        for s in X:
            for i in range(1, k):
                lits.append(f"{s}_{i}")
        return ABAFramework(lits, self.assumptions, contraries, rules, self.preferences)

    def to_atomic(self) -> "ABAFramework":
        """Transforme un framework non circulaire en framework atomique sensitive.

        La transformation suppose un framework non circulaire, ce que prepare()
        garantit. Elle ne vérifie pas que chaque littéral non-hypothèse possède
        un argument, conformément au corrigé.
        """
        assumptions = list(self.assumptions)
        X = self.non_assumptions()
        used = set(self.literals)
        for s in X:
            if f"{s}_d" in used or f"{s}_nd" in used:
                raise ABAError(f"Noms réservés déjà présents pour '{s}'.")

        new_assumptions = assumptions + [name for s in X for name in (f"{s}_d", f"{s}_nd")]
        contraries = dict(self.contraries)
        for s in X:
            contraries[f"{s}_d"] = f"{s}_nd"
            contraries[f"{s}_nd"] = s
        assum = set(assumptions)
        rules = [
            Rule(r.id, r.head, tuple(b if b in assum else f"{b}_d" for b in r.body))
            for r in self.rules
        ]
        literals = list(dict.fromkeys(self.literals + new_assumptions))
        return ABAFramework(literals, new_assumptions, contraries, rules, self.preferences)

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
        Les arguments sont les paires (feuilles, claim) de tous les arbres,
        y compris lorsque le framework contient des cycles."""
        raw = self._raw_arguments()
        found: Dict[Tuple[str, frozenset], tuple] = {}
        for (c, s), t in raw.items():
            found.setdefault((c, s), t)
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

    def set_attacks(self, use_preferences=True):
        """Calcule les attaques ABA+ entre tous les sous-ensembles d'hypothèses.

        Renvoie deux ensembles de couples (X, Y), pour les attaques normales et
        inversées. Un framework de plus de dix hypothèses est refusé car les
        sous-ensembles produisent rapidement trop de couples à examiner.
        """
        if len(self.assumptions) > 10:
            raise ABAError("Le calcul ABA+ entre ensembles est limité à 10 hypothèses.")

        prefs = use_preferences and bool(self.preferences)
        geq = self._geq() if prefs else set()
        lt = lambda a, b: (b, a) in geq and (a, b) not in geq
        by_contrary: Dict[str, List[str]] = {}
        for assumption, contrary in self.contraries.items():
            by_contrary.setdefault(contrary, []).append(assumption)

        assumptions = tuple(self.assumptions)
        subsets = [
            frozenset(combo)
            for size in range(len(assumptions) + 1)
            for combo in itertools.combinations(assumptions, size)
        ]
        normal: Set[Tuple[frozenset, frozenset]] = set()
        reverse: Set[Tuple[frozenset, frozenset]] = set()
        for argument in self.arguments():
            for contrary_assumption in by_contrary.get(argument.claim, []):
                if any(lt(s, contrary_assumption) for s in argument.support):
                    for X in subsets:
                        if contrary_assumption in X:
                            for Y in subsets:
                                if argument.support <= Y:
                                    reverse.add((X, Y))
                else:
                    for X in subsets:
                        if argument.support <= X:
                            for Y in subsets:
                                if contrary_assumption in Y:
                                    normal.add((X, Y))
        return normal, reverse

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
