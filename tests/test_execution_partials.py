from core.execution.partials import PartialSlicer


def test_partials_geometric_slicing_and_keys():
    s = PartialSlicer(alpha=0.5, q_min=0.05, q_max=1.0, use_p_fill=True)
    s.start("ORD1", target_qty=1.0)

    # 1st slice (p=1): q=0.5
    sl1 = s.next_slice("ORD1", p_fill=1.0)
    assert sl1 is not None and abs(sl1.qty - 0.5) < 1e-12 and sl1.key == "ORD1:1"
    # Register fill and check remaining
    rem = s.register_fill("ORD1", sl1.qty)
    assert abs(rem - 0.5) < 1e-12

    # 2nd slice (p=0.5): q=alpha*rem*p = 0.5*0.5*0.5 = 0.125
    sl2 = s.next_slice("ORD1", p_fill=0.5)
    assert sl2 is not None and abs(sl2.qty - 0.125) < 1e-12 and sl2.key == "ORD1:2"
    rem = s.register_fill("ORD1", sl2.qty)
    assert abs(rem - (0.5 - 0.125)) < 1e-12

    # 3rd slice (p=0) -> clamped by q_min = 0.05
    sl3 = s.next_slice("ORD1", p_fill=0.0)
    assert sl3 is not None and abs(sl3.qty - 0.05) < 1e-12 and sl3.key == "ORD1:3"
    rem = s.register_fill("ORD1", sl3.qty)
    assert abs(rem - (0.375 - 0.05)) < 1e-12

    # Continue until completion
    filled = sl1.qty + sl2.qty + sl3.qty
    while True:
        sl = s.next_slice("ORD1", p_fill=1.0)
        if sl is None:
            break
        filled += sl.qty
        s.register_fill("ORD1", sl.qty)

    assert filled <= 1.0000001  # numerical slack


def test_partials_cancel_and_restart():
    s = PartialSlicer(alpha=0.6, q_min=0.01, q_max=0.5)
    s.start("X", target_qty=0.3)
    a = s.next_slice("X", p_fill=1.0)
    assert a and a.key == "X:1"
    s.cancel("X")
    # restart should reset index
    s.start("X", target_qty=0.3)
    b = s.next_slice("X", p_fill=1.0)
    assert b and b.key == "X:1"