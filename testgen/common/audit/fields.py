"""The fields of a model an audit record may carry, and the changes made to them."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sqlalchemy import Column, TypeDecorator, inspect
from sqlalchemy.orm.attributes import PASSIVE_NO_INITIALIZE, get_history

from testgen.common.audit.actions import AuditTargetType
from testgen.common.models.custom_types import EncryptedBytea

SECRET_INFO_KEY = "secret"  # noqa: S105

_UNSET = object()


@dataclass(frozen=True)
class AuditFields:
    """A model's audit declaration, set as its ``__audit__`` class attribute.

    A column appears in a record's changes only when it is declared here.

    :param target_type: the kind of object the record names as affected
    :param name: attribute holding the object's name, or a function that builds a name for an object that has none
    :param id: attribute holding the id records carry
    :param project: attribute holding the object's project code
    :param values: fields recorded with their before and after values
    :param withheld: fields recorded as changed, without their values
    """

    target_type: AuditTargetType
    name: str | Callable[[Any], str | None] | None = None
    id: str = "id"
    project: str | None = None
    values: tuple[str, ...] = ()
    withheld: tuple[str, ...] = ()

    def declared(self) -> tuple[str, ...]:
        return (*self.values, *self.withheld)

    def name_of(self, obj: object) -> str | None:
        if callable(self.name):
            return self.name(obj)
        return getattr(obj, self.name) if self.name else None


def is_secret(column: Column) -> bool:
    """Whether ``column`` holds a secret: an encrypted column, or one marked ``info={"secret": True}``."""
    return isinstance(column.type, EncryptedBytea) or bool(column.info.get(SECRET_INFO_KEY))


def declaration_errors(model: type) -> list[str]:
    """What is wrong with ``model``'s audit declaration: fields that are not columns, and secrets declared with values."""
    declaration: AuditFields = model.__audit__
    columns = inspect(model).columns
    errors = [f"{name} is not a column" for name in declaration.declared() if name not in columns]
    errors += [
        f"{name} holds a secret and can only be withheld"
        for name in declaration.values
        if name in columns and is_secret(columns[name])
    ]
    return errors


@dataclass
class FieldChange:
    """A field's value before the first change and after the last, as Python values."""

    before: Any
    after: Any

    def then(self, later: "FieldChange") -> "FieldChange":
        return FieldChange(before=self.before, after=later.after)


def pending_changes(obj: object, names: tuple[str, ...]) -> dict[str, FieldChange]:
    """The changes to ``names`` that ``obj`` holds and has not yet written. Never loads an attribute."""
    changes = {}
    for name in names:
        history = get_history(obj, name, passive=PASSIVE_NO_INITIALIZE)
        if history.has_changes():
            changes[name] = FieldChange(
                before=history.deleted[0] if history.deleted else _UNSET,
                after=history.added[0] if history.added else None,
            )
    return changes


def current_values(obj: object, names: tuple[str, ...]) -> dict[str, FieldChange]:
    """The values ``obj`` holds for ``names``, as the changes that created it. Never loads an attribute."""
    loaded = inspect(obj).dict
    return {name: FieldChange(before=_UNSET, after=loaded[name]) for name in names if name in loaded}


def to_record(obj: object, declaration: AuditFields, changes: dict[str, FieldChange]) -> dict[str, dict[str, Any]]:
    """A record's ``changes`` map: fields whose stored value changed, with values only where declared.

    A field with no prior value, as on a new object, is reported only when it has a value. A value the column
    stores as NULL, such as a form's ``""``, is reported as ``None``.
    """
    columns = inspect(type(obj)).columns
    entries = {}
    for name, change in changes.items():
        column = columns[name]
        if change.before is _UNSET:
            if _as_stored(column, change.after) is None:
                continue
        elif _as_stored(column, change.before) == _as_stored(column, change.after):
            continue

        if name in declaration.withheld or is_secret(column):
            entries[name] = {}
        elif change.before is _UNSET:
            entries[name] = {"to": _reported(column, change.after)}
        else:
            entries[name] = {"from": _reported(column, change.before), "to": _reported(column, change.after)}
    return entries


def _reported(column: Column, value: Any) -> Any:
    if _as_stored(column, value) is None:
        return None
    return value.value if isinstance(value, Enum) else value


def _as_stored(column: Column, value: Any) -> Any:
    """``value`` as the column writes it, so that a form's ``""`` and a stored NULL compare equal."""
    if isinstance(column.type, TypeDecorator) and not isinstance(column.type, EncryptedBytea):
        return column.type.process_bind_param(value, None)
    return value
