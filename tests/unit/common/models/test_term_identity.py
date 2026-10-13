import hashlib
import itertools
import re
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.common.models.test_definition import TERM_ID_MAX_LENGTH, TestDefinition, slugify_term_id
from tests.unit.sql_assertions import conjuncts, is_not_null_conjunct, is_null_conjunct

pytestmark = pytest.mark.unit

TERM_ID_PATTERN = r"^[A-Za-z0-9_-]+$"
DIGEST_SUFFIX = re.compile(r"-[0-9a-f]{8}$")


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("Row_Ct", "public", "orders", "order_id"), "Row_Ct-public-orders-order_id"),
        (("Volume_Trend", "public", "orders", None), "Volume_Trend-public-orders"),
        (("Schema_Drift", "public", None, None), "Schema_Drift-public"),
    ],
)
def test_a_key_the_slug_renders_exactly_keeps_the_readable_identity(parts, expected):
    assert slugify_term_id(*parts) == expected


@pytest.mark.parametrize(
    ("parts", "stem"),
    [
        # A metric-trend term carries a display label, not a column name.
        (("Metric_Trend", "public", "orders", "Average Product Price"),
         "Metric_Trend-public-orders-Average_Product_Price"),
        # An aggregate-balance term carries an expression.
        (("Aggregate_Balance", "public", "orders", "SUM(total_amount)"),
         "Aggregate_Balance-public-orders-SUM_total_amount"),
        (("Row_Ct", "public", "orders", "  spaced  out  "), "Row_Ct-public-orders-spaced_out"),
        (("Row_Ct", "public", "orders", "a//b\\c"), "Row_Ct-public-orders-a_b_c"),
        # Non-ASCII is dropped rather than transliterated: no dependency, and the identity is
        # kept unique by its index rather than by being readable.
        (("Row_Ct", "public", "orders", "çafé"), "Row_Ct-public-orders-af"),
        # A '-' inside a part is indistinguishable from the one joining parts.
        (("Row_Ct", "public", "orders", "already-valid_1"), "Row_Ct-public-orders-already-valid_1"),
        # An absent part in the middle shifts the ones after it.
        (("Row_Ct", None, "orders", "order_id"), "Row_Ct-orders-order_id"),
    ],
)
def test_a_key_the_slug_reduces_carries_a_digest(parts, stem):
    slug = slugify_term_id(*parts)

    assert slug.startswith(f"{stem}-")
    assert DIGEST_SUFFIX.search(slug)


@pytest.mark.parametrize(
    "parts",
    [
        ("Row_Ct", "public", "orders", "order_id"),
        ("Metric_Trend", "public", "orders", "Average Product Price"),
        ("Aggregate_Balance", "public", "orders", "SUM(total_amount)"),
        ("Row_Ct", "public", "orders", "!!!"),
        ("Row_Ct", "public", "orders", "çafé"),
        ("Row_Ct", "public", "orders", "a" * 300),
    ],
)
def test_every_slug_matches_the_odcs_identifier_pattern(parts):
    assert re.match(TERM_ID_PATTERN, slugify_term_id(*parts))


def test_a_slug_is_bounded_to_the_column_width():
    slug = slugify_term_id("Row_Ct", "public", "o" * 200, "c" * 200)

    assert len(slug) <= TERM_ID_MAX_LENGTH
    assert re.match(TERM_ID_PATTERN, slug)


def test_an_input_that_slugs_to_nothing_raises():
    with pytest.raises(ValueError):
        slugify_term_id("!!!", None, None, None)


def test_no_parts_at_all_raises():
    with pytest.raises(ValueError):
        slugify_term_id()


@pytest.mark.parametrize(
    ("left", "right"),
    [
        # A run of disallowed characters collapses to one '_', whatever it was.
        (("Row_Ct", "public", "orders", "order id"), ("Row_Ct", "public", "orders", "order_id")),
        (("Row_Ct", "public", "orders", "total (usd)"), ("Row_Ct", "public", "orders", "total%usd")),
        (("Row_Ct", "public", "orders", "a  b"), ("Row_Ct", "public", "orders", "a??b")),
        # The join separator is lossy independently of that.
        (("Row_Ct", "sales", "q1-2026", "net"), ("Row_Ct", "sales", "q1", "2026-net")),
        # So is dropping an absent part.
        (("Row_Ct", "public", "orders", None), ("Row_Ct", "public", None, "orders")),
        # And so is the bound.
        (("Value_Match", "analytics_prod", "customer_subscription_billing_events",
          "monthly_recurring_revenue_usd_amount_net"),
         ("Value_Match", "analytics_prod", "customer_subscription_billing_events",
          "monthly_recurring_revenue_usd_amount_gross")),
    ],
)
def test_keys_the_slug_maps_onto_one_string_stay_distinct(left, right):
    """The identity sits in a unique index, so two natural keys the reduction cannot tell apart
    would make the second term's stamp fail it and wedge the contract permanently.
    """
    assert slugify_term_id(*left) != slugify_term_id(*right)


def _adversarial_keys() -> set[tuple[str | None, ...]]:
    """Keys spanning every way the reduction loses information, and their near misses."""
    alphabet = ["a", "b", "_", "-", " ", "%", None, "a_b", "a-b", "a b", "__", "--", " a "]
    long_part = "z" * 45
    keys = {("Row_Ct", *combo) for combo in itertools.product(alphabet, repeat=3)}
    keys |= {
        ("Value_Match", *combo, None)
        for combo in itertools.product([long_part, long_part + "x", long_part + "-", long_part + " "], repeat=2)
    }
    return keys


def test_distinct_keys_never_share_an_identity():
    slugs = {}
    for key in _adversarial_keys():
        try:
            slug = slugify_term_id(*key)
        except ValueError:
            continue
        assert slug not in slugs, f"{key} and {slugs[slug]} both slug to {slug}"
        slugs[slug] = key

    assert len(slugs) > 2000, "the corpus stopped covering the key space"


def test_every_adversarial_key_stays_within_the_column_and_the_pattern():
    for key in _adversarial_keys():
        try:
            slug = slugify_term_id(*key)
        except ValueError:
            continue
        assert len(slug) <= TERM_ID_MAX_LENGTH, f"{key} slugs past the column width"
        assert re.match(TERM_ID_PATTERN, slug), f"{key} slugs outside the identifier pattern"


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("Row_Ct", "public", "orders", "order_id"), "Row_Ct-public-orders-order_id"),
        (("Row_Ct", "public", "orders", "order id"), "Row_Ct-public-orders-order_id-ee41a2af"),
        (("Metric_Trend", "public", "orders", "Average Product Price"),
         "Metric_Trend-public-orders-Average_Product_Price-3ef06dea"),
    ],
)
def test_an_identity_is_pinned_to_its_key(parts, expected):
    """A stamped identity is never recomputed, and a frozen document carries it, so a change to
    what a key slugs to splits terms stamped before it from terms stamped after.
    """
    assert slugify_term_id(*parts) == expected


def _mint_session(taken: tuple[str, ...] = ()) -> MagicMock:
    """A session reporting ``taken`` as the identities the version already holds.

    An unconfigured ``MagicMock`` would answer the taken-check with a mock rather than with
    rows, so every test below states its taken set explicitly rather than relying on the
    default.
    """
    session = MagicMock()
    session.scalars.return_value.all.return_value = list(taken)
    return session


@pytest.mark.parametrize(
    "column_name",
    ["SUM(total_amount)", "Average Product Price"],
)
def test_a_minted_id_matches_the_identifier_pattern(column_name):
    session = _mint_session()
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        minted = TestDefinition.mint_term_id(uuid4(), "Aggregate_Balance", "public", "orders", column_name)

    assert re.match(TERM_ID_PATTERN, minted)


def test_two_subjects_that_slugify_alike_do_not_collide():
    session = _mint_session()
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        first = TestDefinition.mint_term_id(uuid4(), "Aggregate_Balance", "public", "orders", "SUM(total_amount)")
        second = TestDefinition.mint_term_id(uuid4(), "Aggregate_Balance", "public", "orders", "SUM total_amount")

    assert first != second


def test_a_truncated_natural_key_is_disambiguated():
    long_a = "a" * 90 + "_first"
    long_b = "a" * 90 + "_second"
    session = _mint_session()
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        first = TestDefinition.mint_term_id(uuid4(), "Value_Match", "public", "orders", long_a)
        second = TestDefinition.mint_term_id(uuid4(), "Value_Match", "public", "orders", long_b)

    assert first != second


def test_a_disambiguated_id_still_matches_the_identifier_pattern():
    session = _mint_session(taken=("Row_Ct-public-orders-order_id",))
    term_id = uuid4()
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        minted = TestDefinition.mint_term_id(uuid4(), "Row_Ct", "public", "orders", "order_id", term_id)

    assert len(minted) <= TERM_ID_MAX_LENGTH
    assert re.match(TERM_ID_PATTERN, minted)
    assert DIGEST_SUFFIX.search(minted)


def test_a_taken_suffixed_candidate_is_also_disambiguated():
    """``slugify_term_id``'s plain and digested forms are not disjoint: a natural key that
    itself ends in something shaped like a hex digest can already own the exact string the
    first suffixed candidate would mint. The candidate is checked for freedom like any other,
    not assumed free from its shape, so minting must still land on something distinct from
    both the bare slug and that first candidate rather than repeat the same collision.
    """
    version_id = uuid4()
    term_id = uuid4()
    digest = hashlib.sha256(str(term_id).encode()).hexdigest()
    bare = "Row_Ct-public-orders-order_id"
    # 8 is the module's starting digest length (_DIGEST_LENGTH); kept out of the test's own
    # import surface so it stays a plain reconstruction of what mint_term_id would try first.
    first_candidate = f"{bare[: TERM_ID_MAX_LENGTH - 8 - 1]}-{digest[:8]}"
    session = _mint_session(taken=(bare, first_candidate))
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        minted = TestDefinition.mint_term_id(version_id, "Row_Ct", "public", "orders", "order_id", term_id)

    assert minted != bare
    assert minted != first_candidate
    assert re.match(TERM_ID_PATTERN, minted)
    assert len(minted) <= TERM_ID_MAX_LENGTH


def test_minting_without_a_primary_key_refuses_to_disambiguate():
    """``term_id=None`` is unreached by both production call sites, which always pass a real
    primary key. Left unchecked, hashing ``None`` would mint the same colliding id on every
    call -- a deterministic collision generator on exactly the property this task closes.
    """
    session = _mint_session(taken=("Row_Ct-public-orders-order_id",))
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        pytest.raises(ValueError),
    ):
        TestDefinition.mint_term_id(uuid4(), "Row_Ct", "public", "orders", "order_id")


def test_two_terms_with_an_identical_natural_key_are_disambiguated_by_the_row():
    """Two hand-added Pattern_Match terms on one column: ``uix_td_autogen_column`` carries
    ``WHERE last_auto_gen_date IS NOT NULL``, so duplicate natural keys are legal.
    """
    version_id = uuid4()
    first_id, second_id = uuid4(), uuid4()
    # The first term persists its identity before the second is minted.
    with patch("testgen.common.models.test_definition.get_current_session", return_value=_mint_session()):
        first = TestDefinition.mint_term_id(version_id, "Pattern_Match", "public", "orders", "email", first_id)
    with patch(
        "testgen.common.models.test_definition.get_current_session", return_value=_mint_session(taken=(first,))
    ):
        second = TestDefinition.mint_term_id(version_id, "Pattern_Match", "public", "orders", "email", second_id)

    assert first == "Pattern_Match-public-orders-email"
    assert second != first
    assert second.startswith("Pattern_Match-public-orders-email-")
    assert re.match(TERM_ID_PATTERN, second)


def test_a_regenerated_term_keeps_the_identity_it_had():
    """Delete, regenerate, same id. Holds because generation never collides with itself --
    ``uix_td_autogen_column`` dedupes autogen rows on the natural key -- so a generated term
    takes the bare slug, which is a pure function of that key. An ordinal suffix fails this
    whenever the minting order differs.
    """
    version_id = uuid4()
    session = _mint_session()
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        first = TestDefinition.mint_term_id(version_id, "Row_Ct", "public", "orders", "order_id", uuid4())
        second = TestDefinition.mint_term_id(version_id, "Row_Ct", "public", "orders", "order_id", uuid4())

    assert first == second == "Row_Ct-public-orders-order_id"


def test_a_generated_term_whose_key_a_manual_term_squats_does_not_survive_regeneration():
    """The stated exception, asserted so it is a decision rather than a surprise.

    The autogen indexes are partial, so a manual term can hold the bare slug for a key
    generation later produces; the generated term takes the primary-key suffix and its id moves
    when it is regenerated. Reversing the preference would move an id that is already
    persisted and possibly already published.
    """
    version_id = uuid4()
    # The manual term squats the bare slug for both attempts.
    session = _mint_session(taken=("Row_Ct-public-orders-order_id",))
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        first = TestDefinition.mint_term_id(version_id, "Row_Ct", "public", "orders", "order_id", uuid4())
        second = TestDefinition.mint_term_id(version_id, "Row_Ct", "public", "orders", "order_id", uuid4())

    assert first != second
    assert first.startswith("Row_Ct-public-orders-order_id-")
    assert second.startswith("Row_Ct-public-orders-order_id-")


def test_minting_is_order_independent_for_distinct_natural_keys():
    """Mint the same pair in both orders; each term gets the same id either way.

    Scoped to distinct natural keys: with "first free slug wins", two terms sharing a key
    would get different ids depending on which is minted first, which
    ``test_two_terms_with_an_identical_natural_key_are_disambiguated_by_the_row`` already covers.
    """
    version_id = uuid4()
    session = _mint_session()
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        first_then_second = (
            TestDefinition.mint_term_id(version_id, "Row_Ct", "public", "orders", "order_id"),
            TestDefinition.mint_term_id(version_id, "Volume_Trend", "public", "orders", "row_count"),
        )
        second_then_first = (
            TestDefinition.mint_term_id(version_id, "Volume_Trend", "public", "orders", "row_count"),
            TestDefinition.mint_term_id(version_id, "Row_Ct", "public", "orders", "order_id"),
        )

    assert first_then_second[0] == second_then_first[1]
    assert first_then_second[1] == second_then_first[0]


def test_saving_a_new_term_on_a_contract_mints_its_identity():
    version_id = uuid4()
    definition = TestDefinition(
        test_suite_id=uuid4(), test_type="Row_Ct", schema_name="public",
        table_name="orders", column_name="order_id", version_id=version_id,
    )
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=MagicMock()),
        patch("testgen.common.models.entity.get_current_session", return_value=MagicMock()),
        patch("testgen.common.models.test_definition.SuiteVersion.is_frozen_agreement", return_value=False),
        patch("testgen.common.models.test_definition.SuiteVersion.is_suite_owned", return_value=True),
        patch.object(TestDefinition, "mint_term_id", return_value="Row_Ct-public-orders-order_id") as mint,
    ):
        definition.save()

    assert definition.contract_term_id == "Row_Ct-public-orders-order_id"
    mint.assert_called_once()
    args = mint.call_args.args
    assert args[0] == version_id
    assert args[1:5] == ("Row_Ct", "public", "orders", "order_id")
    # The primary key does not exist until flush -- save() must mint it explicitly first, since
    # a SQLAlchemy column default is evaluated at flush, not at construction.
    assert args[5] == definition.id
    assert definition.id is not None


def test_saving_a_new_term_on_a_regular_suite_mints_nothing():
    """The placeholder is not suite-owned; a regular suite's terms carry no contract identity."""
    definition = TestDefinition(
        test_suite_id=uuid4(), test_type="Row_Ct", schema_name="public",
        table_name="orders", column_name="order_id", version_id=uuid4(),
    )
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=MagicMock()),
        patch("testgen.common.models.entity.get_current_session", return_value=MagicMock()),
        patch("testgen.common.models.test_definition.SuiteVersion.is_frozen_agreement", return_value=False),
        patch("testgen.common.models.test_definition.SuiteVersion.is_suite_owned", return_value=False),
        patch.object(TestDefinition, "mint_term_id") as mint,
    ):
        definition.save()

    mint.assert_not_called()
    assert definition.contract_term_id is None


def test_editing_a_terms_column_name_leaves_its_identity_unchanged():
    session = MagicMock()
    session.scalar.return_value = None
    definition = TestDefinition(
        id=uuid4(), test_suite_id=uuid4(), test_type="Row_Ct", version_id=uuid4(),
        column_name="order_id", contract_term_id="Row_Ct-public-orders-order_id",
    )
    definition.column_name = "renamed_order_id"

    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch("testgen.common.models.entity.get_current_session", return_value=session),
        patch("testgen.common.models.test_definition.SuiteVersion.is_frozen_agreement", return_value=False),
    ):
        definition.save()

    statement = session.execute.call_args.args[0]
    assert "contract_term_id" not in {column.key for column in statement._values}
    assert definition.contract_term_id == "Row_Ct-public-orders-order_id"


def test_copying_terms_mints_identities_on_the_target_version():
    """``copy`` is an INSERT...SELECT that nulls ``contract_term_id`` deliberately -- a copy is a
    new term and must not carry the source's identity. Nothing went on to mint one, so copying
    into a contract left terms that render ``id: null``."""
    session = MagicMock()
    target_version = uuid4()
    session.scalar.return_value = target_version
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch.object(TestDefinition, "assert_version_writable"),
        patch.object(TestDefinition, "_assert_no_managed_definitions"),
        patch.object(TestDefinition, "assign_missing_term_ids") as sweep,
    ):
        TestDefinition.copy([uuid4()], uuid4(), uuid4(), target_schema="public", qualifies_table_refs=True)

    sweep.assert_called_once_with(target_version)


@pytest.fixture
def contract_version():
    with patch("testgen.common.models.test_definition.SuiteVersion.is_suite_owned", return_value=True):
        yield


def test_assigning_missing_identities_on_the_placeholder_touches_no_term():
    """Every regular and monitor suite resolves to the shared placeholder, so a sweep over it
    would mint an identity for every such term in the install."""
    session = MagicMock()
    session.scalar.return_value = None
    with (
        patch("testgen.common.models.test_definition.get_current_session", return_value=session),
        patch("testgen.common.models.suite_version.get_current_session", return_value=session),
    ):
        count = TestDefinition.assign_missing_term_ids(uuid4())

    assert count == 0
    session.scalars.assert_not_called()
    session.execute.assert_not_called()


@pytest.mark.usefixtures("contract_version")
def test_assigning_missing_identities_skips_terms_that_already_have_one():
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        count = TestDefinition.assign_missing_term_ids(uuid4())

    statement = session.scalars.call_args.args[0]
    terms = conjuncts(statement.whereclause)
    assert any(is_null_conjunct(term, "contract_term_id", "test_definitions") for term in terms)
    assert count == 0


@pytest.mark.usefixtures("contract_version")
def test_assigning_missing_identities_sweeps_manual_terms_too():
    """The natural-key dedup indexes are partial on ``last_auto_gen_date``, so a manual term is
    deduped against nothing; the sweep no longer restricts to generated terms, which is what
    leaves manual terms unidentified otherwise.
    """
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        TestDefinition.assign_missing_term_ids(uuid4())

    statement = session.scalars.call_args.args[0]
    terms = conjuncts(statement.whereclause)
    assert not any(is_not_null_conjunct(term, "last_auto_gen_date", "test_definitions") for term in terms)


@pytest.mark.usefixtures("contract_version")
def test_assigning_missing_identities_sweeps_in_a_stable_order():
    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        TestDefinition.assign_missing_term_ids(uuid4())

    statement = session.scalars.call_args.args[0]
    order_by_columns = [str(clause) for clause in statement._order_by_clauses]
    assert order_by_columns == [
        "test_definitions.test_type",
        "test_definitions.schema_name",
        "test_definitions.table_name",
        "test_definitions.column_name",
    ]


def _suffixed_candidates(slug: str, term_id) -> list[str]:
    """Rebuild the suffixed identities a term could mint, shortest digest first.

    Reconstructed from the term's primary key rather than imported, so the ladder's shape is
    asserted here rather than restated from the module under test. 8 is its starting digest
    length (``_DIGEST_LENGTH``).
    """
    digest = hashlib.sha256(str(term_id).encode()).hexdigest()
    return [f"{slug[: TERM_ID_MAX_LENGTH - length - 1].rstrip('-_')}-{digest[:length]}"
            for length in range(8, len(digest) + 1)]


def test_minting_against_an_empty_taken_set_returns_the_bare_slug():
    minted = TestDefinition._mint_against(set(), "Row_Ct", "public", "orders", "order_id", uuid4())

    assert minted == "Row_Ct-public-orders-order_id"


@pytest.mark.parametrize("depth", [0, 1, 2, 5])
def test_minting_climbs_the_digest_ladder_past_every_taken_candidate(depth):
    term_id = uuid4()
    bare = "Row_Ct-public-orders-order_id"
    ladder = _suffixed_candidates(bare, term_id)

    minted = TestDefinition._mint_against(
        {bare, *ladder[:depth]}, "Row_Ct", "public", "orders", "order_id", term_id
    )

    assert minted == ladder[depth]
    assert re.match(TERM_ID_PATTERN, minted)
    assert len(minted) <= TERM_ID_MAX_LENGTH


def test_minting_against_an_exhausted_ladder_raises():
    term_id = uuid4()
    bare = "Row_Ct-public-orders-order_id"
    taken = {bare, *_suffixed_candidates(bare, term_id)}

    with pytest.raises(ValueError):
        TestDefinition._mint_against(taken, "Row_Ct", "public", "orders", "order_id", term_id)


def test_minting_against_a_taken_slug_without_a_primary_key_raises():
    with pytest.raises(ValueError):
        TestDefinition._mint_against(
            {"Row_Ct-public-orders-order_id"}, "Row_Ct", "public", "orders", "order_id", None
        )


def test_a_ladder_candidate_is_trimmed_to_the_column_width():
    term_id = uuid4()
    bare = slugify_term_id("Value_Match", "public", "o" * 200, "c" * 200)
    ladder = _suffixed_candidates(bare, term_id)

    minted = TestDefinition._mint_against(
        {bare, *ladder[:3]}, "Value_Match", "public", "o" * 200, "c" * 200, term_id
    )

    assert len(bare) == TERM_ID_MAX_LENGTH
    assert len(minted) <= TERM_ID_MAX_LENGTH
    assert re.match(TERM_ID_PATTERN, minted)


def test_minting_against_a_taken_set_reads_no_session():
    with patch(
        "testgen.common.models.test_definition.get_current_session",
        side_effect=AssertionError("the taken set is the whole input"),
    ):
        minted = TestDefinition._mint_against(
            {"Row_Ct-public-orders-order_id"}, "Row_Ct", "public", "orders", "order_id", uuid4()
        )

    assert minted.startswith("Row_Ct-public-orders-order_id-")


def _sweep_session(terms: list[TestDefinition], taken: tuple[str, ...] = ()) -> MagicMock:
    """A session answering the select over terms with ``terms`` and any other with ``taken``.

    Dispatches on the statement rather than on call order, so the mock states what the database
    holds without also fixing how many queries the sweep issues or in which order. ``scalar`` is
    configured because an unconfigured ``MagicMock`` returns a truthy mock, which a taken-check
    written as ``is not None`` reads as "taken" for the wrong reason.
    """
    session = MagicMock()

    def scalars(statement):
        result = MagicMock()
        selects_terms = statement.column_descriptions[0]["expr"] is TestDefinition
        result.all.return_value = list(terms) if selects_terms else list(taken)
        return result

    session.scalars.side_effect = scalars
    session.scalar.return_value = None
    return session


def _unidentified_term(version_id, column_name: str = "email") -> TestDefinition:
    return TestDefinition(
        id=uuid4(), test_suite_id=uuid4(), test_type="Pattern_Match", schema_name="public",
        table_name="orders", column_name=column_name, version_id=version_id,
    )


@pytest.mark.usefixtures("contract_version")
def test_one_sweep_gives_two_terms_with_one_natural_key_distinct_identities():
    """Two hand-added terms on one column inside a single sweep: the ids they mint must differ
    without either having been written to the database first.
    """
    version_id = uuid4()
    terms = [_unidentified_term(version_id), _unidentified_term(version_id)]
    session = _sweep_session(terms)

    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        count = TestDefinition.assign_missing_term_ids(version_id)

    minted = [term.contract_term_id for term in terms]
    assert count == 2
    assert minted[0] != minted[1]
    assert "Pattern_Match-public-orders-email" in minted
    assert all(re.match(TERM_ID_PATTERN, identity) for identity in minted)


@pytest.mark.usefixtures("contract_version")
def test_a_sweep_avoids_the_identities_the_version_already_holds():
    version_id = uuid4()
    terms = [_unidentified_term(version_id)]
    session = _sweep_session(terms, taken=("Pattern_Match-public-orders-email",))

    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        TestDefinition.assign_missing_term_ids(version_id)

    assert terms[0].contract_term_id != "Pattern_Match-public-orders-email"
    assert terms[0].contract_term_id.startswith("Pattern_Match-public-orders-email-")


@pytest.mark.usefixtures("contract_version")
def test_a_sweep_asks_the_database_twice_whatever_the_term_count():
    version_id = uuid4()
    terms = [_unidentified_term(version_id, f"column_{index}") for index in range(5)]
    session = _sweep_session(terms)

    with patch("testgen.common.models.test_definition.get_current_session", return_value=session):
        TestDefinition.assign_missing_term_ids(version_id)

    assert session.scalars.call_count == 2
    assert session.scalar.call_count == 0
    assert session.execute.call_count == 0
