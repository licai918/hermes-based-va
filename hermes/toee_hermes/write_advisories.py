"""Write-time advisories on a memory proposal (0.0.5 S13, FR-18).

Tier-3 enforcement, owner decision ③ -- **annotate-only**. When a proposal is
written, two cheap deterministic questions are asked of it and the answers ride
the row as metadata a human reads in the inbox:

1. *Is this L6 note actually lexicon-shaped?* -- "2055516 means 205/55R16" is an
   L7 entry wearing an L6 costume. Answered by
   :func:`~toee_hermes.lexicon.structurable_shape`, the SAME function S20's
   graduation sweep applies to confirmed rows. One heuristic, so a note the
   sweep would graduate and a note this annotates can never be two different
   sets; two regexes would let them disagree.
2. *Does this already exist somewhere?* -- an exact surface-form match against
   the confirmed L7 vocabulary, and a trigram-similar match against confirmed L6
   notes.

**Advisory ONLY (NFR-3).** Nothing here blocks a propose, rewrites content, or
re-files anything. The proposal persists exactly as written whether it is
annotated or not; the human re-files with S15's Re-classify. A false positive
costs one ignored line beside a row somebody was already reading.

**Pure -- no store, no I/O**, the ``toee_hermes.lexicon`` discipline. Each twin
supplies candidate rows from its own store and this decides; that is the ONE
shared resolver NFR-7 asks for, and it is why the mock and Postgres paths cannot
drift on what counts as a duplicate.

## Which way the comparison runs, and what it reveals to whom

Both propose handlers ask the same two questions of the same two row sets:

    L6 propose  ->  confirmed L7 surface forms  +  confirmed L6 notes
    L7 propose  ->  confirmed L7 surface forms  +  confirmed L6 notes

Every arrow starts and ends inside the two **shared** layers. **L4 is never
read**, and that is the load-bearing part rather than an omission. L4 is
per-customer PII by design (NFR-6); an advisory telling an admin reviewing a
shared-layer proposal "this resembles something in a customer's memory" would
have carried that customer's data across the exact boundary the architecture is
built on -- onto a row every admin sees, on a layer whose whole rule is
operational-only/no-PII. L5 is left out for the duller reason that it is an
authored corpus with no surface forms to match.

So what an advisory discloses is: to an admin who is already reading a
shared-layer proposal, that another shared-layer entry exists -- by id, by its
own surface form, and by a similarity score. Nothing customer-identifying, and
nothing that was not already on a governed surface that reader can open. The
resolver takes exactly two row sets and has no seam through which an L4 row
could enter; the Postgres twin's candidate SQL is pinned by a test to name only
``semantic_lexicon`` and ``agent_experience``.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from .lexicon import STATUS_CONFIRMED, structurable_shape

# D8 (BINDING): the proposal row's `annotations` JSONB has exactly two reserved
# top-level keys -- `heuristic` (this slice) and `copilot` (S16, landing later).
# Each writer assigns its own WHOLE key and never touches the other's, so the two
# cannot lost-update each other on one row.
ANNOTATION_KEY_HEURISTIC = "heuristic"

ADVISORY_REFILE_TO_L7 = "refile_to_l7"
ADVISORY_DUPLICATE_L7_SURFACE = "duplicate_l7_surface"
ADVISORY_SIMILAR_L6_NOTE = "similar_l6_note"

# D16: named from day one so S22's knob panel reads it rather than hunting a
# magic number; per D14 it moves by deploy-time config commit.
#
# MEASURED, not chosen. Trigram-Jaccard over the sentence pairs a real L6 store
# produces:
#
#     reworded duplicate      0.85     "...quoting a winter set." / "...quoting winter sets"
#     same words, reordered   0.84
#     ONE word swapped        0.78     "delivery address" / "billing address"
#     same template, other subject   0.60-0.67
#     neighbouring tire size  0.57     "2055516 = 205/55R16" / "2055517 = 205/55R17"
#     unrelated notes         0.03-0.24
#
# The 0.78 row is above the line and is the known false-positive shape: one word
# changed inside an otherwise identical sentence reads as a duplicate. It was
# found by a test fixture that assumed otherwise, and it is left firing on
# purpose -- two notes differing by one word usually ARE the same note, and the
# cost of being wrong is one line an admin ignores.
#
# 0.75 sits in the empty gap between 0.67 and 0.78. It is deliberately on the
# PRECISION side of that gap: a missed near-duplicate costs nothing (S20's sweep
# and the human both still see the row), while an advisory that fires on the
# same-template case fires on most of L6 -- and an advisory that fires on
# everything is noise, and noise gets turned off.
SIMILAR_NOTE_MIN_SIMILARITY = 0.75

# The one spelling both sides of a mapping comparison are put into, so "TOEE =
# TOEE TIRE" and "TOEE means TOEE TIRE" are one string by the time they meet.
_MAPPING_CONNECTIVE = " = "

_TRIGRAM = 3


def _trigrams(text: str) -> set[str]:
    """Character trigrams over whitespace-collapsed, case-folded text.

    Padded so the first and last characters carry as much weight as the middle
    ones -- without it, a difference at the very start of two otherwise
    identical notes barely registers.
    """
    padded = "  " + " ".join(text.lower().split()) + "  "
    return {padded[i : i + _TRIGRAM] for i in range(len(padded) - _TRIGRAM + 1)}


def note_similarity(left: Any, right: Any) -> float:
    """Jaccard overlap of character trigrams, ``0.0`` .. ``1.0``.

    ponytail: deterministic, stdlib-only, no embeddings and no index -- the
    brief's "trigram-ish". Its known ceiling is that it measures SHAPE, not
    meaning: two notes saying opposite things about the same subject score high,
    and a paraphrase with no shared vocabulary scores near zero. That is the
    right trade for an advisory a human reads and can ignore; do not reach for a
    model. Order-insensitive by construction (it compares sets), which is why a
    reordered restatement still matches.
    """
    if not isinstance(left, str) or not isinstance(right, str):
        return 0.0
    a, b = _trigrams(left), _trigrams(right)
    # An empty (or whitespace-only) text is padding alone. Scoring it against
    # anything must be 0, not "matches whatever shares two spaces".
    if not left.strip() or not right.strip():
        return 0.0
    return len(a & b) / len(a | b)


def _confirmed(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """The rows that are actually vocabulary.

    Only ``confirmed`` rows are compared against -- the same rule S03/S05/S06
    apply on the read side. A proposed row is inert by construction (S01), so
    advising an admin that their note duplicates something nobody has accepted
    would be advice about a row that may never exist; a rejected one is a row
    somebody already said no to.

    The filter lives HERE rather than in each twin's query on purpose: with it
    pushed into SQL, a test pinning "a proposed row is not a candidate" would be
    satisfied by the query and stay green with this rule deleted.
    """
    return [row for row in rows if row.get("status") == STATUS_CONFIRMED]


def _mapping_text(surface_form: Any, canonical_form: Any) -> str:
    return f"{surface_form}{_MAPPING_CONNECTIVE}{canonical_form}"


def _comparable(content: Any) -> str:
    """The text an L6 note is compared AS.

    A note that is itself a mapping is normalized to the mapping's own two
    halves, so an L7 proposal and an L6 note describing the same mapping compare
    as the same string whichever connective the note used. Prose is compared as
    written. Reuses ``structurable_shape`` a second time rather than parsing the
    note again.
    """
    if not isinstance(content, str):
        return ""
    shape = structurable_shape(content)
    if shape is None:
        return content
    return _mapping_text(shape.surface_form, shape.canonical_form)


def _duplicate_advisories(
    surface_form: Optional[str],
    text: str,
    lexicon_entries: Iterable[Mapping[str, Any]],
    experience_entries: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Cross-layer dedup, both legs. Never raises on a malformed row."""
    found: list[dict[str, Any]] = []
    needle = (surface_form or "").strip().casefold()
    if needle:
        # Exact, case- and whitespace-insensitive -- the same key
        # `lexicon_seam.normalize_product_query` builds its alias map with, so
        # "already in the lexicon" means here what it means at apply time.
        # An EMPTY surface never matches: prose has no surface form, and a blank
        # needle would otherwise annotate every prose note as a duplicate.
        found.extend(
            {
                "code": ADVISORY_DUPLICATE_L7_SURFACE,
                "entry_ref": str(row.get("id") or ""),
                "domain": row.get("domain"),
                "surface_form": row.get("surface_form"),
            }
            for row in _confirmed(lexicon_entries)
            if str(row.get("surface_form") or "").strip().casefold() == needle
        )
    for row in _confirmed(experience_entries):
        score = note_similarity(text, _comparable(row.get("content")))
        if score >= SIMILAR_NOTE_MIN_SIMILARITY:
            found.append(
                {
                    "code": ADVISORY_SIMILAR_L6_NOTE,
                    "entry_ref": str(row.get("id") or ""),
                    # Rounded so the stored JSON is stable across platforms and
                    # a diff of two rows is readable.
                    "similarity": round(score, 2),
                }
            )
    return found


def _annotations(advisories: list[dict[str, Any]]) -> dict[str, Any]:
    """D8's blob, or ``{}`` when there is nothing to say.

    An empty blob rather than an empty advisory list: the inbox renders one
    labelled block per top-level key (S15's ``ReviewInbox``), so a proposal with
    no advice must carry no key at all or every row grows an empty box.
    """
    if not advisories:
        return {}
    return {ANNOTATION_KEY_HEURISTIC: {"advisories": advisories}}


def l6_write_advisories(
    content: Any,
    *,
    lexicon_entries: Iterable[Mapping[str, Any]],
    experience_entries: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Advisories for one ``propose_experience`` write (FR-18).

    Both candidate sets are REQUIRED keywords with no default. A caller that
    forgot one would silently produce a proposal with half the advice and no
    error, which is the divergence NFR-7 exists to prevent -- so forgetting is a
    ``TypeError`` instead.
    """
    shape = structurable_shape(content)
    advisories: list[dict[str, Any]] = []
    if shape is not None:
        # "Consider re-filing to L7" -- with the two halves an admin would file
        # it AS, so the advice is actionable rather than a verdict.
        advisories.append(
            {
                "code": ADVISORY_REFILE_TO_L7,
                "surface_form": shape.surface_form,
                "canonical_form": shape.canonical_form,
            }
        )
    advisories.extend(
        _duplicate_advisories(
            shape.surface_form if shape is not None else None,
            _comparable(content),
            lexicon_entries,
            experience_entries,
        )
    )
    return _annotations(advisories)


def l7_write_advisories(
    surface_form: Any,
    canonical_form: Any,
    *,
    lexicon_entries: Iterable[Mapping[str, Any]],
    experience_entries: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Advisories for one ``propose_lexicon_entry`` write (FR-18).

    No re-file leg: an L7 proposal is already in L7. The surface-form leg is
    still worth running because ``UNIQUE(domain, surface_form)`` only refuses a
    SAME-domain collision -- FR-1 explicitly allows one surface form to exist in
    two domains, and an admin deciding the second one should be told about the
    first rather than discovering it later.
    """
    return _annotations(
        _duplicate_advisories(
            surface_form if isinstance(surface_form, str) else None,
            _mapping_text(surface_form, canonical_form),
            lexicon_entries,
            experience_entries,
        )
    )


__all__ = [
    "ADVISORY_DUPLICATE_L7_SURFACE",
    "ADVISORY_REFILE_TO_L7",
    "ADVISORY_SIMILAR_L6_NOTE",
    "ANNOTATION_KEY_HEURISTIC",
    "SIMILAR_NOTE_MIN_SIMILARITY",
    "l6_write_advisories",
    "l7_write_advisories",
    "note_similarity",
]
