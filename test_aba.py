from aba import *

def pairs(fw): return {(a.claim, a.support) for a in fw.arguments()}

def test_example():
    fw = ABAFramework.from_text(EXAMPLE)
    assert not fw.is_circular() and not fw.is_atomic()
    assert len(fw.arguments()) == 8
    assert len(fw.attacks()) == 10
    at = fw.to_atomic()
    assert at.is_atomic()
    assert len(at.assumptions) == 13
    assert len(at.rules) == 5
    assert len(at.arguments()) == 18

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
    assert [str(r) for r in nc.rules] == [
        "[r1.2]: p_2 <- q_1,a", "[r1.3]: p <- q_2,a",
        "[r2.2]: q_2 <- p_1", "[r2.3]: q <- p_2",
        "[r3.1]: q_1 <- b", "[r3.2]: q_2 <- b", "[r3.3]: q <- b",
    ]
    assert nc.contraries == {"a": "q", "b": "r"}
    assert len(nc.arguments()) == 8
    assert len(nc.attacks()) == 8

    at = nc.to_atomic()
    assert at.is_atomic()
    assert len(at.assumptions) == 20
    assert len(at.rules) == 7

def test_td4_circular_conversion():
    txt = """L: [a,b,x,y,z]
A: [a,b]
C(a): y
C(b): x
[r1]: y <- b
[r2]: y <- y
[r3]: x <- a
[r4]: x <- x
[r5]: z <- x,y
"""
    fw = ABAFramework.from_text(txt)
    nc = fw.to_non_circular()
    assert not nc.is_circular()
    assert [str(r) for r in nc.rules] == [
        "[r1.1]: y_1 <- b", "[r1.2]: y_2 <- b", "[r1.3]: y <- b",
        "[r2.2]: y_2 <- y_1", "[r2.3]: y <- y_2",
        "[r3.1]: x_1 <- a", "[r3.2]: x_2 <- a", "[r3.3]: x <- a",
        "[r4.2]: x_2 <- x_1", "[r4.3]: x <- x_2",
        "[r5.2]: z_2 <- x_1,y_1", "[r5.3]: z <- x_2,y_2",
    ]
    assert nc.contraries == {"a": "y", "b": "x"}
    assert len(nc.arguments()) == 10
    assert len(nc.attacks()) == 12
    at = nc.to_atomic()
    assert at.is_atomic()
    assert len(at.assumptions) == 20
    assert len(at.rules) == 12

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

def test_set_attacks():
    fw = ABAFramework.from_text(EXAMPLE)
    normal, reverse = fw.set_attacks()
    expected_normal = {
        (frozenset(x), frozenset(y))
        for x in ({"a", "c"}, {"a", "b", "c"})
        for y in ({"b"}, {"c"}, {"a", "b"}, {"a", "c"}, {"b", "c"}, {"a", "b", "c"})
    }
    expected_reverse = {
        (frozenset(x), frozenset(y))
        for x in ({"a"}, {"a", "b"}, {"a", "c"}, {"a", "b", "c"})
        for y in ({"b", "c"}, {"a", "b", "c"})
    }
    assert normal == expected_normal
    assert reverse == expected_reverse

def test_errors():
    import pytest
    with pytest.raises(ABAError): ABAFramework.from_text("L: [a]\nA: [a]\n")
    with pytest.raises(ABAError): ABAFramework.from_text("blabla")

def test_weighted_h_categorizer():
    arguments = ["A1", "A2"]
    attacks = [Attack("A1", "A2", "normal", "a")]
    scores = weighted_h_categorizer(arguments, attacks, {"A1": 1.0, "A2": 1.0})
    assert scores == {"A1": 1.0, "A2": 0.5}

    mutual_attacks = [Attack("A1", "A2", "normal", "a"),
                      Attack("A2", "A1", "normal", "b")]
    mutual_scores = weighted_h_categorizer(arguments, mutual_attacks,
                                           {"A1": 1.0, "A2": 1.0})
    expected = (5 ** 0.5 - 1) / 2
    assert all(abs(score - expected) < 1e-6 for score in mutual_scores.values())
