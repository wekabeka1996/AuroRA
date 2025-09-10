from core.universe.hysteresis import EmaSmoother, Hysteresis


def test_hysteresis_add_drop_with_dwell():
    h = Hysteresis(add_thresh=0.6, drop_thresh=0.4, min_dwell=3, start_active=False)

    # below add for < min_dwell -> remain inactive
    for _ in range(2):
        st = h.update(0.55)
        assert st.active is False and st.changed is False

    # cross add threshold and hold for >= min_dwell -> activate once
    changed_up = False
    for _ in range(3):
        st = h.update(0.70)
        if st.changed:
            changed_up = True
            assert st.active is True
            break
    assert changed_up is True

    # now below drop for >= min_dwell -> deactivate once
    changed_down = False
    for _ in range(3):
        st = h.update(0.20)
        if st.changed:
            changed_down = True
            assert st.active is False
            break
    assert changed_down is True


def test_ema_smoother_simple():
    s = EmaSmoother(alpha=0.5)
    y0 = s.update(0.0)
    assert abs(y0 - 0.0) < 1e-12
    y1 = s.update(1.0)
    assert abs(y1 - 0.5) < 1e-12
    y2 = s.update(1.0)
    assert abs(y2 - 0.75) < 1e-12
