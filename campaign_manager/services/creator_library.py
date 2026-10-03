"""Niche vocabulary and per-creator records for the Creator Library.

The vocabulary is deliberately data, not a constant: Rising Tides books
against niches that are invented on the spot ("pinterest moodboard",
"urban face creator"), and waiting on a deploy to add one meant nobody
tagged anything. `SEED_NICHES` is only a starting set — anything typed into
the picker joins the vocabulary immediately.

Two normalisation rules keep the data from fragmenting:
  * niche names are lowercased and whitespace-collapsed, so "Gym" and
    "gym  " can never become two entries;
  * usernames are lowercased, because that is the only identifier shared
    across campaigns, trackers and Cobrand.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Iterable, List, Optional

from sqlalchemy import func

from campaign_manager.models import CreatorNiche, CreatorProfile, Niche

# Jake's starting vocabulary. Order is his, and it is preserved as the
# tie-break when usage counts are equal so the picker reads the way he
# thinks about creators until real usage reorders it.
SEED_NICHES: List[str] = [
    "POV",
    "dark POV",
    "face creator",
    "female face creator",
    "urban face creator",
    "meme",
    "urban meme",
    "cat meme",
    "celebrity meme",
    "celebrity gossip",
    "lyric page",
    "nature",
    "movie/tv show edits",
    "country-leaning",
    "trucktok",
    "travel edits",
    "pinterest moodboard",
    "anime",
]

_SEED_ORDER = {name.lower(): i for i, name in enumerate(SEED_NICHES)}

_WHITESPACE = re.compile(r"\s+")


def normalize_niche(name: str) -> str:
    """Lowercase and collapse whitespace. Raises on an empty result."""
    cleaned = _WHITESPACE.sub(" ", str(name or "").strip()).lower()
    if not cleaned:
        raise ValueError("Niche name cannot be empty.")
    return cleaned[:80]


def normalize_username(username: str) -> str:
    return str(username or "").strip().lstrip("@").rstrip("/").lower()


# ── vocabulary ─────────────────────────────────────────────────────────

def ensure_seed_niches(session) -> int:
    """Install the starting vocabulary. Returns how many were new."""
    existing = {n.name for n in session.query(Niche).all()}
    added = 0
    for raw in SEED_NICHES:
        name = normalize_niche(raw)
        if name not in existing:
            session.add(Niche(name=name))
            existing.add(name)
            added += 1
    if added:
        session.commit()
    return added


def _counts(session) -> Dict[int, int]:
    rows = (
        session.query(CreatorNiche.niche_id, func.count(CreatorNiche.id))
        .group_by(CreatorNiche.niche_id)
        .all()
    )
    return {niche_id: count for niche_id, count in rows}


def list_niches(session) -> List[Dict]:
    """Every niche with its usage count, most-used first.

    Unused niches are still returned — an empty vocabulary is unusable, and
    a niche at zero is exactly the one you want to see in the picker.
    """
    counts = _counts(session)
    niches = session.query(Niche).all()
    out = [n.to_dict(counts.get(n.id, 0)) for n in niches]
    out.sort(
        key=lambda n: (
            -n["count"],
            _SEED_ORDER.get(n["name"], len(SEED_NICHES)),
            n["name"],
        )
    )
    return out


def get_niche(session, niche_id: int) -> Optional[Niche]:
    return session.get(Niche, niche_id)


def create_niche(session, name: str) -> Dict:
    """Get-or-create by normalised name, so re-adding is harmless."""
    normalized = normalize_niche(name)
    existing = session.query(Niche).filter(Niche.name == normalized).first()
    if existing:
        return existing.to_dict(_counts(session).get(existing.id, 0))

    niche = Niche(name=normalized)
    session.add(niche)
    session.commit()
    return niche.to_dict(0)


def rename_niche(session, niche_id: int, new_name: str) -> Dict:
    """Rename in place, carrying every tagged creator along.

    Renaming onto a name that already exists merges into it rather than
    failing — that is what the user meant, and refusing would leave two
    near-identical niches sitting side by side.
    """
    niche = session.get(Niche, niche_id)
    if niche is None:
        raise LookupError(f"No niche with id {niche_id}")

    normalized = normalize_niche(new_name)
    clash = (
        session.query(Niche)
        .filter(Niche.name == normalized, Niche.id != niche_id)
        .first()
    )
    if clash:
        return merge_niches(session, niche_id, clash.id)

    niche.name = normalized
    session.commit()
    return niche.to_dict(_counts(session).get(niche.id, 0))


def merge_niches(session, source_id: int, target_id: int) -> Dict:
    """Fold `source` into `target`, then delete `source`.

    Creators carrying both keep a single tag: the unique constraint on
    (username, niche_id) would reject the duplicate, so shared creators are
    filtered out before the re-point.
    """
    if source_id == target_id:
        raise ValueError("Cannot merge a niche into itself.")

    source = session.get(Niche, source_id)
    target = session.get(Niche, target_id)
    if source is None or target is None:
        raise LookupError("Both niches must exist to merge.")

    already = {
        row.username
        for row in session.query(CreatorNiche).filter(
            CreatorNiche.niche_id == target_id
        )
    }
    for row in session.query(CreatorNiche).filter(
        CreatorNiche.niche_id == source_id
    ):
        if row.username in already:
            session.delete(row)
        else:
            row.niche_id = target_id
            already.add(row.username)

    session.delete(source)
    session.commit()
    return target.to_dict(_counts(session).get(target.id, 0))


def delete_niche(session, niche_id: int) -> bool:
    """Remove a niche and every tag pointing at it."""
    niche = session.get(Niche, niche_id)
    if niche is None:
        return False
    session.query(CreatorNiche).filter(
        CreatorNiche.niche_id == niche_id
    ).delete(synchronize_session=False)
    session.delete(niche)
    session.commit()
    return True


# ── tagging ────────────────────────────────────────────────────────────

def niches_for(session, usernames: Iterable[str]) -> Dict[str, List[str]]:
    """Map each username to its niche names, sorted.

    Always returns a key per requested username so callers can index
    without guarding for absence.
    """
    wanted = [normalize_username(u) for u in usernames]
    out: Dict[str, List[str]] = {u: [] for u in wanted if u}
    if not out:
        return {}

    rows = (
        session.query(CreatorNiche.username, Niche.name)
        .join(Niche, Niche.id == CreatorNiche.niche_id)
        .filter(CreatorNiche.username.in_(list(out.keys())))
        .all()
    )
    for username, name in rows:
        out.setdefault(username, []).append(name)
    for names in out.values():
        names.sort()
    return out


def all_niches_by_creator(session) -> Dict[str, List[str]]:
    """Every tag in one query — for building the full library listing."""
    rows = (
        session.query(CreatorNiche.username, Niche.name)
        .join(Niche, Niche.id == CreatorNiche.niche_id)
        .all()
    )
    out: Dict[str, List[str]] = {}
    for username, name in rows:
        out.setdefault(username, []).append(name)
    for names in out.values():
        names.sort()
    return out


def set_niches(session, username: str, names: Iterable[str]) -> List[str]:
    """Replace this creator's tags, creating vocabulary entries as needed."""
    user = normalize_username(username)
    if not user:
        raise ValueError("Username is required.")

    wanted: List[str] = []
    for raw in names or []:
        try:
            normalized = normalize_niche(raw)
        except ValueError:
            continue
        if normalized not in wanted:
            wanted.append(normalized)

    ids: List[int] = []
    for name in wanted:
        niche = session.query(Niche).filter(Niche.name == name).first()
        if niche is None:
            niche = Niche(name=name)
            session.add(niche)
            session.flush()
        ids.append(niche.id)

    session.query(CreatorNiche).filter(
        CreatorNiche.username == user
    ).delete(synchronize_session=False)
    for niche_id in ids:
        session.add(CreatorNiche(username=user, niche_id=niche_id))

    get_or_create_profile(session, username, commit=False)
    session.commit()
    return sorted(wanted)


def apply_niche_to(session, niche_id: int, usernames: Iterable[str]) -> int:
    """Add one niche to many creators. Returns how many were newly tagged.

    This is the bulk-tagging path: 300+ creators is unworkable one at a
    time, so the UI selects a batch and applies a tag once.
    """
    niche = session.get(Niche, niche_id)
    if niche is None:
        raise LookupError(f"No niche with id {niche_id}")

    users = [normalize_username(u) for u in usernames]
    users = [u for u in users if u]
    if not users:
        return 0

    existing = {
        row.username
        for row in session.query(CreatorNiche).filter(
            CreatorNiche.niche_id == niche_id,
            CreatorNiche.username.in_(users),
        )
    }
    added = 0
    for user in users:
        if user in existing:
            continue
        session.add(CreatorNiche(username=user, niche_id=niche_id))
        get_or_create_profile(session, user, commit=False)
        existing.add(user)
        added += 1

    if added:
        session.commit()
    return added


def remove_niche_from(session, niche_id: int, username: str) -> bool:
    user = normalize_username(username)
    deleted = session.query(CreatorNiche).filter(
        CreatorNiche.niche_id == niche_id,
        CreatorNiche.username == user,
    ).delete(synchronize_session=False)
    if deleted:
        session.commit()
    return bool(deleted)


# ── profiles ───────────────────────────────────────────────────────────

def get_or_create_profile(
    session, username: str, commit: bool = True
) -> CreatorProfile:
    """Fetch this creator's library record, creating an empty one if needed."""
    user = normalize_username(username)
    if not user:
        raise ValueError("Username is required.")

    profile = session.get(CreatorProfile, user)
    if profile is None:
        profile = CreatorProfile(
            username=user,
            display_username=str(username).strip().lstrip("@").rstrip("/"),
        )
        session.add(profile)
        if commit:
            session.commit()
        else:
            session.flush()
    return profile


# Fields a caller may set directly. `rate_override_at` is excluded on
# purpose — it is stamped here so the rate-memory rule can trust it.
_WRITABLE = {"slow", "note", "paypal_email", "platform", "display_username"}


def update_profile(session, username: str, **fields) -> CreatorProfile:
    """Patch a profile. Setting `rate_override` stamps the current time.

    That timestamp is what lets a later booking supersede a hand-set rate —
    see `creator_library_stats.effective_rate`.
    """
    profile = get_or_create_profile(session, username, commit=False)

    if "rate_override" in fields:
        rate = fields.pop("rate_override")
        profile.rate_override = rate
        profile.rate_override_at = datetime.now() if rate is not None else None

    for key, value in fields.items():
        if key in _WRITABLE:
            setattr(profile, key, value)

    session.commit()
    return profile


def profiles_by_username(session) -> Dict[str, CreatorProfile]:
    return {p.username: p for p in session.query(CreatorProfile).all()}
