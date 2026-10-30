"""scripts/payout_backfill.py end to end against a throwaway SQLite file."""
from __future__ import annotations

import csv
import importlib.util
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from campaign_manager.models import Base, Campaign, Creator, CreatorPayoutEvent, CreatorProfile

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "payout_backfill.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("payout_backfill_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(url):
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    a, b = Campaign(slug="a", title="A"), Campaign(slug="b", title="B")
    s.add_all([a, b])
    s.flush()
    s.add_all([
        Creator(campaign_id=a.id, username="solo", paypal_email="Solo@Gmail.com"),
        Creator(campaign_id=b.id, username="@solo", paypal_email="solo@gmail.com"),
        Creator(campaign_id=a.id, username="split", paypal_email="one@gmail.com"),
        Creator(campaign_id=b.id, username="split", paypal_email="two@gmail.com"),
        Creator(campaign_id=a.id, username="junk", paypal_email="-@cashapp"),
        Creator(campaign_id=a.id, username="blank", paypal_email=""),
    ])
    s.add_all([CreatorProfile(username=u) for u in ("solo", "split", "junk", "blank")])
    s.commit()
    return engine


def test_dry_run_writes_nothing_and_apply_fills_only_clean(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path / 'hub.db'}"
    engine = _seed(url)
    monkeypatch.delenv("DATABASE_PUBLIC_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", url)
    script = _load_script()

    assert script.main(["--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "to_fill: 1" in out
    s = sessionmaker(bind=engine)()
    assert (s.get(CreatorProfile, "solo").payout_destination or "") == ""

    diff = next(tmp_path.glob("backfill_diff_*.csv"))
    actions = {r["creator"]: r["action"] for r in csv.DictReader(diff.open())}
    assert actions == {"solo": "FILL", "split": "SKIP_CONFLICTED",
                       "junk": "SKIP_UNPARSEABLE", "blank": "NEEDS_LINK"}
    assert oct(diff.stat().st_mode)[-3:] == "600"

    assert script.main(["--apply", "--out-dir", str(tmp_path)]) == 0
    s.expire_all()
    solo = s.get(CreatorProfile, "solo")
    assert (solo.payout_method, solo.payout_destination) == ("paypal", "solo@gmail.com")
    assert solo.payout_confirmed_by_creator is False
    assert (s.get(CreatorProfile, "split").payout_destination or "") == ""
    assert [e.event for e in s.query(CreatorPayoutEvent)] == ["backfilled"]

    # Re-running is a no-op: solo is now already_set.
    assert script.main(["--apply", "--out-dir", str(tmp_path)]) == 0
    assert "Filled 0" in capsys.readouterr().out
