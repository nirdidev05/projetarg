from aba import *

def pairs(fw): return {(a.claim, a.support) for a in fw.arguments()}

def test_example():
    fw = ABAFramework.from_text(EXAMPLE)
    assert not fw.is_circular() and not fw.is_atomic()
    at = fw.to_atomic()
    assert at.is_atomic() and pairs(at) == pairs(fw)
    assert len(fw.arguments()) == 8

def test_circular():
    txt = """L: [a,b,p,q,r]
A: [a,b]
C(a): q
C(b): r
[r1]: p <- q,a
[r2]: q <- p
[r3]: q <- b
"""
    fw = ABAFramework.from_text(txt)
    assert fw.is_circular() and fw.find_cycle()
    nc = fw.to_non_circular()
    assert not nc.is_circular()
    at = nc.to_atomic()
    assert at.is_atomic()
    assert pairs(at) == pairs(fw), (pairs(at), pairs(fw))
    assert pairs(fw.prepare()) == pairs(fw)

def test_flat():
    txt = """L: [a,b,c,x]
A: [a,b]
C(a): c
C(b): x
[r1]: a <- b
[r2]: c <-
"""
    fw = ABAFramework.from_text(txt)
    assert not fw.is_flat()
    fl = fw.to_flat()
    assert fl.is_flat()
    ps = {(c, tuple(sorted(s))) for c, s in pairs(fl)}
    assert ("a", ("b",)) in ps and ("a", ("a'",)) in ps

def test_prefs():
    fw = ABAFramework.from_text("L: [a,b,c,x,y,z]\nA: [a,b,c]\nC(a): x\nC(b): y\nC(c): z\n"
                                "[r1]: x <- b\n[r2]: y <- a\nPREF: a,b > c\n")
    assert fw.strictly_preferred("a", "c") and fw.strictly_preferred("b", "c")
    assert not fw.strictly_preferred("a", "b") and not fw.strictly_preferred("b", "a")
    fw2 = ABAFramework.from_text("L: [a,b,c]\nA: [a,b,c]\nC(a): a\nC(b): b\nC(c): c\nPREF: a > b > c\n")
    assert fw2.strictly_preferred("a", "c")   # transitivité

def test_reverse():
    fw = ABAFramework.from_text("L: [a,b,x]\nA: [a,b]\nC(a): x\nC(b): b\n[r1]: x <- b\nPREF: a > b\n")
    args = fw.arguments(); id_ = {(g.claim): g.id for g in args}
    atts = fw.attacks(args)
    # x{b} attaque a normalement ? b < a => attaque inversée : A{a} attaque x{b}
    assert any(t.kind == "reverse" and t.attacker == id_["a"] and t.target == id_["x"] for t in atts)
    assert not any(t.kind == "normal" and t.target == id_["a"] for t in atts)

def test_errors():
    import pytest
    with pytest.raises(ABAError): ABAFramework.from_text("L: [a]\nA: [a]\n")
    with pytest.raises(ABAError): ABAFramework.from_text("blabla")
