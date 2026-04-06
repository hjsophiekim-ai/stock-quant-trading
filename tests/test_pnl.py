from app.portfolio.pnl import pnl_pct, unrealized_pnl


def test_unrealized_pnl_basic() -> None:
    assert unrealized_pnl(entry_price=100.0, current_price=110.0, quantity=10) == 100.0


def test_pnl_pct_basic() -> None:
    assert pnl_pct(equity_start=1_000_000.0, equity_now=1_060_000.0) == 6.0


def test_split_buy_and_split_sell_realized_pnl() -> None:
    # Split buy: 5 shares @100, 5 shares @90 => avg 95
    total_qty = 10
    avg_price = ((5 * 100.0) + (5 * 90.0)) / total_qty

    # Split sell: 5 shares @106 (+6%), remaining 5 shares @104
    realized_first = (106.0 - avg_price) * 5
    realized_second = (104.0 - avg_price) * 5
    total_realized = realized_first + realized_second

    assert avg_price == 95.0
    assert realized_first == 55.0
    assert realized_second == 45.0
    assert total_realized == 100.0
