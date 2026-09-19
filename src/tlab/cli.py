"""tlab komut satiri arayuzu.

Faz 0 kapsami tamamen SALT OKUNURDUR: hesap okur, veri ceker, journal
hazirlar. Emir gonderen hicbir komut yoktur - risk kapisi (Faz 1)
tamamlanmadan sisteme emir yetkisi verilmiyor.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tlab import __version__
from tlab.config import Config, Secrets, load_config, load_secrets
from tlab.core.types import Timeframe
from tlab.data.cache import BarCache
from tlab.data.market import AlpacaMarketData
from tlab.errors import TradingLabError
from tlab.execution.alpaca_broker import AlpacaBroker
from tlab.journal.db import apply_migrations, connect, schema_version

OK = "  [ok] "
FAIL = "  [!!] "


def _load(root: Path) -> tuple[Config, Secrets]:
    return load_config(root), load_secrets(root)


# --------------------------------------------------------------------------
# Komutlar
# --------------------------------------------------------------------------


def cmd_config(args: argparse.Namespace) -> int:
    """Cozumlenmis yapilandirmayi gosterir (anahtarlar maskelenir)."""
    config, secrets = _load(args.root)
    print(f"tlab {__version__}  |  kok: {config.root}")
    print("\n[app]")
    print(f"  borsa saat dilimi : {config.app.exchange_timezone}")
    print("\n[data]")
    print(f"  feed              : {config.data.feed}")
    print(f"  varsayilan periyot: {config.data.default_timeframe.value}")
    print(f"  onbellek          : {config.cache_dir}")
    print("\n[session]")
    print(f"  seans             : {config.session.regular_open} - {config.session.regular_close}")
    print(f"  kapanis tamponu   : {config.session.flatten_before_close_minutes} dk")
    print(f"  uzatilmis seans   : {config.session.allow_extended_hours}")
    print("\n[risk]")
    print(f"  islem basi risk   : %{config.risk.max_risk_per_trade_pct}")
    print(f"  gunluk zarar siniri: %{config.risk.max_daily_loss_pct}")
    print(f"  es zamanli pozisyon: {config.risk.max_concurrent_positions}")
    print(f"  azami spread      : {config.risk.max_spread_bps} bps")
    print(f"  PDT kurali        : {'acik' if config.risk.enforce_pdt else 'kapali'}")
    print("\n[journal]")
    print(f"  veritabani        : {config.journal_path}")
    print(f"\n[evren] {len(config.symbols)} sembol")
    print(f"  {', '.join(config.symbols)}")
    print("\n[anahtarlar]")
    for key, value in secrets.masked().items():
        print(f"  {key:18}: {value}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Sistemin calismaya hazir olup olmadigini bastan sona kontrol eder."""
    problems: list[str] = []

    print("1. Yapilandirma")
    try:
        config, secrets = _load(args.root)
    except TradingLabError as exc:
        print(f"{FAIL}{exc}")
        return 1
    print(f"{OK}config/base.yaml ve config/universe.yaml gecerli")
    print(f"{OK}{len(config.symbols)} sembol tanimli, feed: {config.data.feed}")

    print("\n2. Anahtarlar")
    if secrets.is_configured:
        print(f"{OK}.env icinde Alpaca anahtarlari bulundu")
        print(f"{OK}mod: {'PAPER (guvenli)' if secrets.alpaca_paper else 'CANLI PARA'}")
    else:
        print(f"{FAIL}.env dosyasi yok veya anahtarlar bos (.env.example dosyasina bak)")
        problems.append("anahtarlar")

    print("\n3. Journal")
    try:
        conn = connect(config.journal_path)
        applied = apply_migrations(conn)
        version = schema_version(conn)
        if applied:
            print(f"{OK}goc uygulandi: {', '.join(applied)}")
        print(f"{OK}sema surumu {version} - {config.journal_path}")
        conn.close()
    except TradingLabError as exc:
        print(f"{FAIL}{exc}")
        problems.append("journal")

    if not secrets.is_configured:
        print("\n4. Broker / veri baglantisi\n  (anahtar olmadan atlandi)")
        return _doctor_summary(problems)

    print("\n4. Broker baglantisi")
    try:
        broker = AlpacaBroker(
            secrets.alpaca_api_key, secrets.alpaca_secret_key, paper=secrets.alpaca_paper
        )
        account = broker.get_account()
        print(f"{OK}baglanti kuruldu - ozsermaye {account.equity:,.2f} {account.currency}")
        if not account.is_healthy:
            print(f"{FAIL}hesap islem yapmaya kapali (trading/account blocked)")
            problems.append("hesap kilitli")
        clock = broker.get_market_clock()
        state = "ACIK" if clock.is_open else "KAPALI"
        print(f"{OK}borsa {state}, sonraki acilis {clock.next_open}")
    except TradingLabError as exc:
        print(f"{FAIL}{exc}")
        problems.append("broker")

    print("\n5. Piyasa verisi")
    try:
        market = AlpacaMarketData(
            secrets.alpaca_api_key, secrets.alpaca_secret_key, feed=config.data.feed
        )
        probe = config.symbols[0] if config.symbols else "SPY"
        bars = market.bars(
            probe, Timeframe.D1, start=datetime.now(UTC) - timedelta(days=10), end=None
        )
        if bars:
            print(f"{OK}{probe}: {len(bars)} gunluk bar, son kapanis {bars[-1].close}")
        else:
            print(f"{FAIL}{probe} icin bar donmedi (feed veya tarih araligi)")
            problems.append("veri")
    except TradingLabError as exc:
        print(f"{FAIL}{exc}")
        problems.append("veri")

    return _doctor_summary(problems)


def _doctor_summary(problems: list[str]) -> int:
    print()
    if problems:
        print(f"SONUC: {len(problems)} sorun var -> {', '.join(problems)}")
        return 1
    print("SONUC: sistem hazir.")
    return 0


def cmd_account(args: argparse.Namespace) -> int:
    """Hesap ozetini ve acik pozisyonlari gosterir."""
    config, secrets = _load(args.root)
    secrets.require()
    broker = AlpacaBroker(
        secrets.alpaca_api_key, secrets.alpaca_secret_key, paper=secrets.alpaca_paper
    )

    account = broker.get_account()
    mode = "PAPER" if secrets.alpaca_paper else "CANLI"
    print(f"Hesap ({mode})")
    print(f"  ozsermaye   : {account.equity:>14,.2f} {account.currency}")
    print(f"  nakit       : {account.cash:>14,.2f}")
    print(f"  alim gucu   : {account.buying_power:>14,.2f}")
    print(f"  gunluk P/L  : {account.daily_pl:>14,.2f}  (%{account.daily_pl_pct:.2f})")
    print(f"  day trade   : {account.daytrade_count} (PDT: {account.pattern_day_trader})")
    print(f"  durum       : {'islem yapabilir' if account.is_healthy else 'KILITLI'}")

    positions = broker.get_positions()
    print(f"\nAcik pozisyonlar: {len(positions)}")
    for position in positions:
        print(
            f"  {position.symbol:<6} {position.side.value:<4} {position.qty:>6} adet"
            f" @ {position.avg_entry_price:>9,.2f}"
            f"  simdi {position.current_price:>9,.2f}"
            f"  P/L {position.unrealized_pl:>+10,.2f}"
        )

    clock = broker.get_market_clock()
    print(f"\nBorsa: {'ACIK' if clock.is_open else 'KAPALI'}")
    print(f"  sonraki acilis : {clock.next_open}")
    print(f"  sonraki kapanis: {clock.next_close}")
    _ = config
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    """Gecmis bar verisi ceker ve onbellege yazar."""
    config, secrets = _load(args.root)
    secrets.require()

    timeframe = Timeframe(args.timeframe)
    symbols = [s.upper() for s in args.symbols] if args.symbols else list(config.symbols)
    if not symbols:
        print("Sembol verilmedi ve universe.yaml bos.", file=sys.stderr)
        return 1

    market = AlpacaMarketData(
        secrets.alpaca_api_key, secrets.alpaca_secret_key, feed=config.data.feed
    )
    cache = BarCache(config.cache_dir)

    end = datetime.now(UTC)
    start = end - timedelta(days=args.days)
    print(f"{timeframe.value} | {args.days} gun | feed={config.data.feed} | {len(symbols)} sembol")

    failures = 0
    for symbol in symbols:
        try:
            bars = market.bars(symbol, timeframe, start=start, end=end)
            total = cache.save(symbol, timeframe, bars)
            span = f"{bars[0].ts:%Y-%m-%d} -> {bars[-1].ts:%Y-%m-%d}" if bars else "veri yok"
            print(f"  {symbol:<6} +{len(bars):>6} bar   onbellek toplam {total:>7}   {span}")
        except TradingLabError as exc:
            print(f"  {symbol:<6} HATA: {exc}", file=sys.stderr)
            failures += 1

    print(f"\nOnbellek: {config.cache_dir}")
    return 1 if failures else 0


def cmd_journal_init(args: argparse.Namespace) -> int:
    """Journal veritabanini olusturur veya gunceller."""
    config, _ = _load(args.root)
    conn = connect(config.journal_path)
    applied = apply_migrations(conn)
    version = schema_version(conn)
    if applied:
        print(f"Uygulanan gocler: {', '.join(applied)}")
    else:
        print("Bekleyen goc yok.")
    print(f"Sema surumu {version} - {config.journal_path}")
    conn.close()
    return 0


# --------------------------------------------------------------------------
# Arguman ayristirma
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tlab",
        description="Alpaca tabanli trading sistemi (Faz 0: salt okunur)",
    )
    parser.add_argument("--version", action="version", version=f"tlab {__version__}")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Proje koku (varsayilan: bulunulan dizin)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="Cozumlenmis yapilandirmayi goster").set_defaults(func=cmd_config)
    sub.add_parser("doctor", help="Kurulumu bastan sona kontrol et").set_defaults(func=cmd_doctor)
    sub.add_parser("account", help="Hesap ozeti ve acik pozisyonlar").set_defaults(func=cmd_account)

    fetch = sub.add_parser("fetch", help="Gecmis bar verisi cek ve onbellege yaz")
    fetch.add_argument("symbols", nargs="*", help="Semboller (bos birakilirsa tum evren)")
    fetch.add_argument("--days", type=int, default=30, help="Kac gun geriye (varsayilan 30)")
    fetch.add_argument(
        "--timeframe",
        default=Timeframe.M1.value,
        choices=[tf.value for tf in Timeframe],
        help="Bar periyodu",
    )
    fetch.set_defaults(func=cmd_fetch)

    journal = sub.add_parser("journal", help="Journal veritabani islemleri")
    journal_sub = journal.add_subparsers(dest="journal_command", required=True)
    journal_sub.add_parser("init", help="Veritabanini olustur/guncelle").set_defaults(
        func=cmd_journal_init
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result: int = args.func(args)
    except TradingLabError as exc:
        # Beklenen hatalar kullaniciya duz mesaj olarak gosterilir;
        # stack trace sadece beklenmeyen hatalarda anlamli.
        print(f"\nHATA: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nIptal edildi.", file=sys.stderr)
        return 130
    return result


if __name__ == "__main__":
    raise SystemExit(main())
