"""tlab komut satiri arayuzu.

`run` disindaki tum komutlar salt okunurdur. `run` emir gonderir ve
varsayilan olarak PAPER hesapta calisir; ilk kez calistirirken
--dry-run ile baslamak tavsiye edilir: sistem her seyi yapar, emri
gondermez ve kararlari journal'a yazar.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from tlab import __version__
from tlab.backtest.engine import Backtest
from tlab.backtest.metrics import Metrics
from tlab.backtest.sim_broker import SimFillModel
from tlab.config import Config, Secrets, load_config, load_secrets
from tlab.core.clock import LiveClock
from tlab.core.types import Timeframe
from tlab.data.cache import BarCache
from tlab.data.cached import CachedMarketData
from tlab.data.market import AlpacaMarketData
from tlab.engine.runner import SessionRunner
from tlab.errors import TradingLabError
from tlab.execution.alpaca_broker import AlpacaBroker
from tlab.journal.db import apply_migrations, connect, schema_version
from tlab.journal.queries import session_summary, top_veto_reasons
from tlab.journal.writer import JournalWriter, current_git_sha
from tlab.risk.gate import RiskGate
from tlab.strategies.orb import OpeningRangeBreakout, ORBParams

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
    print(f"  giris emri omru   : {config.session.entry_order_ttl_minutes} dk")
    print(f"  uzatilmis seans   : {config.session.allow_extended_hours}")
    print("\n[risk]")
    print(f"  islem basi risk   : %{config.risk.max_risk_per_trade_pct}")
    print(f"  gunluk zarar siniri: %{config.risk.max_daily_loss_pct}")
    print(f"  es zamanli pozisyon: {config.risk.max_concurrent_positions}")
    print(f"  azami spread      : {config.risk.max_spread_bps} bps")
    print(f"  asgari stop       : {config.risk.min_stop_bps} bps")
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
    secrets = load_secrets(args.root).require()
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
            f"  {position.symbol:<6} {position.side.value:<4} {position.qty:>9,.4g} adet"
            f" @ {position.avg_entry_price:>9,.2f}"
            f"  simdi {position.current_price:>9,.2f}"
            f"  P/L {position.unrealized_pl:>+10,.2f}"
        )

    clock = broker.get_market_clock()
    print(f"\nBorsa: {'ACIK' if clock.is_open else 'KAPALI'}")
    print(f"  sonraki acilis : {clock.next_open}")
    print(f"  sonraki kapanis: {clock.next_close}")
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


def cmd_run(args: argparse.Namespace) -> int:
    """Seans dongusunu baslatir.

    Varsayilan olarak surekli calisir; --once tek tur yapar.
    --dry-run her seyi yapar ama emir GONDERMEZ: kararlar journal'a
    yazilir, boylece sistemin ne yapacagi once gozlemlenebilir.
    """
    _setup_logging(args.verbose, args.log_file)
    config, secrets = _load(args.root)
    secrets.require()

    if not secrets.alpaca_paper and not args.i_understand_live:
        print(
            "\nALPACA_PAPER=false ayarli, yani GERCEK PARA kullanilacak.\n"
            "Bunu bilerek istiyorsan --i-understand-live bayragini ekle.",
            file=sys.stderr,
        )
        return 1

    broker = AlpacaBroker(
        secrets.alpaca_api_key, secrets.alpaca_secret_key, paper=secrets.alpaca_paper
    )
    market = AlpacaMarketData(
        secrets.alpaca_api_key, secrets.alpaca_secret_key, feed=config.data.feed
    )

    conn = connect(config.journal_path)
    apply_migrations(conn)
    clock = LiveClock()
    writer = JournalWriter(conn, clock)

    strategy = OpeningRangeBreakout(ORBParams())
    mode = "paper" if secrets.alpaca_paper else "live"
    run_id = writer.start_run(
        mode=mode,
        data_feed=config.data.feed,
        params_version=strategy.params_version,
        config=config.model_dump(mode="json"),
        git_sha=current_git_sha(args.root),
        notes="dry-run" if args.dry_run else None,
    )

    runner = SessionRunner(
        broker=broker,
        market=market,
        strategies=[strategy],
        gate=RiskGate(config.risk),
        writer=writer,
        conn=conn,
        config=config,
        clock=clock,
        run_id=run_id,
        opening_range_minutes=strategy.params.opening_range_minutes,
        timeframe=config.data.default_timeframe,
        entry_order_ttl_minutes=config.session.entry_order_ttl_minutes,
        dry_run=args.dry_run,
    )

    print(f"Kosu {run_id[:12]} | mod={mode} | strateji={strategy.params_version}")
    print(f"Evren: {', '.join(config.symbols)}")
    if args.dry_run:
        print("DRY-RUN: emir gonderilmeyecek, kararlar yine de kaydedilecek.\n")

    try:
        if args.once:
            print(runner.run_once().summary())
        else:
            runner.run_forever(poll_seconds=args.poll)
    except KeyboardInterrupt:
        print("\nDurduruldu.")
    finally:
        writer.end_run(run_id)
        _print_summary(conn, run_id)
        conn.close()
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    """Gecmis veri uzerinde stratejiyi calistirir.

    Veri ONBELLEKTEN okunur; once `tlab fetch` ile indirilmis olmali.
    Bu bilincli: backtest'in ag erisimine ihtiyaci olmamasi, ayni
    veri uzerinde ayni sonucu tekrar tekrar alabilmek demek.
    """
    _setup_logging(args.verbose)
    config, _ = _load(args.root)

    if args.symbols:
        config = config.model_copy(update={"symbols": tuple(s.upper() for s in args.symbols)})

    end = datetime.now(UTC) if args.to is None else _parse_day(args.to)
    start = end - timedelta(days=args.days) if args.since is None else _parse_day(args.since)

    journal_path = args.journal or config.journal_path
    conn = connect(journal_path)
    apply_migrations(conn)

    strategy = OpeningRangeBreakout(ORBParams())
    market = CachedMarketData(
        BarCache(config.cache_dir),
        timeframe=config.data.default_timeframe,
        synthetic_spread_bps=args.spread_bps,
    )
    backtest = Backtest(
        config=config,
        strategy=strategy,
        market=market,
        conn=conn,
        starting_equity=args.equity,
        fill_model=SimFillModel(slippage_bps=args.slippage_bps, commission_bps=args.commission_bps),
        timeframe=config.data.default_timeframe,
        opening_range_minutes=strategy.params.opening_range_minutes,
        notes=args.notes,
    )

    print(f"Strateji: {strategy.params_version}")
    print(f"Veri    : {config.cache_dir}")
    print(
        f"Varsayim: kayma {args.slippage_bps} bps, komisyon {args.commission_bps} bps, "
        f"sentetik spread {args.spread_bps} bps\n"
    )

    result = backtest.run(start, end)
    print(result.report())

    if result.metrics is not None:
        print()
        for line in _backtest_notes(result.metrics):
            print(line)

    conn.close()
    return 0


MIN_MEANINGFUL_TRADES = 30
"""Altinda sonucun tesadufle ayirt edilemedigi islem sayisi."""


def _backtest_notes(metrics: Metrics) -> list[str]:
    """Sonucun nasil okunmasi gerektigine dair uyarilar.

    Bir backtest raporunun en tehlikeli tarafi guzel rakamlarin
    sorgusuz kabul edilmesidir. Rakamin yanina onu nasil
    okuyacagini da koyuyoruz.
    """
    if metrics.trades == 0:
        return [
            "Hic islem acilmadi.",
            "  'tlab summary --run-id ...' ile veto sebeplerine bak: sistemin neden",
            "  islem acmadigi orada yazili.",
        ]

    notes: list[str] = []
    if metrics.is_profitable:
        notes.append("Beklenen deger POZITIF.")
    else:
        notes.append("Beklenen deger NEGATIF: bu parametrelerle strateji para kaybettiriyor.")

    if metrics.trades < MIN_MEANINGFUL_TRADES:
        notes.append(
            f"  UYARI: yalnizca {metrics.trades} islem. Bu sayida sonuc tesadufle ayirt edilemez;"
        )
        notes.append(f"  en az ~{MIN_MEANINGFUL_TRADES} islem olmadan bu rakama gore karar verme.")

    if metrics.is_profitable:
        notes.append("  Sonraki adim: farkli donemlerde de tutuyor mu (walk-forward).")

    notes.append(
        "  Unutma: sentetik spread ve sabit kayma varsayildi; gercek maliyetler daha yuksek olur."
    )
    return notes


def _parse_day(raw: str) -> datetime:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as exc:
        msg = f"Tarih 'YYYY-MM-DD' biciminde olmali: {raw!r}"
        raise TradingLabError(msg) from exc


def cmd_summary(args: argparse.Namespace) -> int:
    """Bir kosunun ozetini gosterir (varsayilan: en son kosu)."""
    config, _ = _load(args.root)
    conn = connect(config.journal_path)
    apply_migrations(conn)

    run_id = args.run_id
    if run_id is None:
        row = conn.execute("SELECT run_id FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
        if row is None:
            print("Henuz kayitli kosu yok.")
            return 0
        run_id = str(row["run_id"])

    _print_summary(conn, run_id)
    conn.close()
    return 0


def _print_summary(conn: Any, run_id: str) -> None:
    """Kosu ozeti: sabah kalkinca bakilacak rakamlar."""
    stats = session_summary(conn, run_id)
    print(f"\nKosu ozeti ({run_id[:12]})")
    print(f"  degerlendirilen karar : {stats['decisions_allowed'] + stats['decisions_vetoed']}")
    print(f"    izin verilen        : {stats['decisions_allowed']}")
    print(f"    veto edilen         : {stats['decisions_vetoed']}")
    print(f"  kapanan islem         : {stats['trades']}")
    if stats["trades"]:
        print(f"    kazanan             : {stats['wins']} (%{stats['win_rate']:.0f})")
        print(f"    net kar/zarar       : {stats['net_pnl']:+,.2f}")
        print(f"    toplam R            : {stats['total_r']:+.2f}")

    reasons = top_veto_reasons(conn, run_id)
    if reasons:
        print("\n  En sik veto sebepleri:")
        for reason, count in reasons:
            print(f"    {count:>3}x  {reason}")


def _setup_logging(verbose: bool, log_file: Path | None = None) -> None:
    """Gunluk yapilandirmasi.

    Dosyaya yazarken donen dosya (rotating) kullaniliyor: gunlerce
    calisan bir surecin gunlugu sinirsiz buyuyup diski doldurmamali.
    Disk dolarsa journal yazamaz, journal yazamazsa sistem islem
    acmayi birakir - yani gunluk dosyasi dolayli olarak isleme
    engel olabilir.
    """
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
        )
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


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

    run = sub.add_parser("run", help="Seans dongusunu baslat")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Emir gonderme, sadece degerlendir ve kaydet (ilk calistirma icin onerilir)",
    )
    run.add_argument("--once", action="store_true", help="Tek tur calistir ve cik")
    run.add_argument("--poll", type=int, default=60, help="Turlar arasi bekleme (saniye)")
    run.add_argument("--verbose", action="store_true", help="Ayrintili gunluk")
    run.add_argument(
        "--log-file",
        type=Path,
        help="Gunlugu dosyaya da yaz (donen dosya, 10 MB x 5). Uzun kosular icin.",
    )
    run.add_argument(
        "--i-understand-live",
        action="store_true",
        help="ALPACA_PAPER=false iken gercek parayla calismayi onayla",
    )
    run.set_defaults(func=cmd_run)

    backtest = sub.add_parser("backtest", help="Stratejiyi gecmis veri uzerinde calistir")
    backtest.add_argument("symbols", nargs="*", help="Semboller (bos: universe.yaml)")
    backtest.add_argument("--days", type=int, default=30, help="Kac gun geriye (varsayilan 30)")
    backtest.add_argument("--since", help="Baslangic tarihi (YYYY-MM-DD)")
    backtest.add_argument("--to", help="Bitis tarihi (YYYY-MM-DD)")
    backtest.add_argument("--equity", type=float, default=100_000.0, help="Baslangic sermayesi")
    backtest.add_argument(
        "--slippage-bps", type=float, default=1.0, help="Dolum basina kayma (varsayilan 1)"
    )
    backtest.add_argument(
        "--commission-bps", type=float, default=0.0, help="Komisyon (Alpaca hissede 0)"
    )
    backtest.add_argument("--spread-bps", type=float, default=2.0, help="Sentetik spread genisligi")
    backtest.add_argument("--journal", type=Path, help="Ayri bir journal dosyasi kullan")
    backtest.add_argument("--notes", help="Kosuya not ekle")
    backtest.add_argument("--verbose", action="store_true", help="Ayrintili gunluk")
    backtest.set_defaults(func=cmd_backtest)

    summary = sub.add_parser("summary", help="Kosu ozetini goster")
    summary.add_argument("--run-id", help="Kosu kimligi (varsayilan: en son kosu)")
    summary.set_defaults(func=cmd_summary)

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
