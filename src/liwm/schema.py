"""A small, dependency-free JSON Schema validator (draft 2020-12 subset).

LIWM ships zero runtime dependencies on purpose: it must run wherever the host
agent runs, including machines where ``pip install`` is not on the table.  That
rules out ``jsonschema``, so this module implements the subset the LIWM schemas
actually use.

Supported: ``type``, ``enum``, ``const``, ``properties``,
``patternProperties``, ``additionalProperties``, ``required``,
``dependentRequired``, ``items``, ``prefixItems``, ``minItems``, ``maxItems``,
``uniqueItems``, ``contains``, ``minimum``, ``maximum``,
``exclusiveMinimum``/``Maximum``, ``multipleOf``, ``minLength``, ``maxLength``,
``pattern``, ``minProperties``, ``maxProperties``, ``allOf``, ``anyOf``,
``oneOf``, ``not``, ``if``/``then``/``else``, ``$ref`` (local ``#/...``
pointers), ``$defs``, and ``format`` for ``date-time`` / ``uri`` / ``uuid``.

Unsupported keywords are ignored rather than silently failing, and
:func:`validate` reports every error it finds with a JSON-Pointer-ish path, so
CI messages are actionable.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

__all__ = ["ValidationError", "validate", "validate_or_raise", "load_schema", "SchemaStore"]


class ValidationError(ValueError):
    """Raised by :func:`validate_or_raise` with all discovered errors."""

    def __init__(self, errors, subject=""):
        self.errors = list(errors)
        self.subject = subject
        head = "%s failed validation" % (subject or "document")
        detail = "\n".join("  - %s: %s" % (e["path"] or "/", e["message"]) for e in self.errors[:25])
        extra = "" if len(self.errors) <= 25 else "\n  ... and %d more" % (len(self.errors) - 25)
        super().__init__("%s (%d error%s)\n%s%s"
                         % (head, len(self.errors), "" if len(self.errors) == 1 else "s", detail, extra))


_TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}

_DATE_TIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_URI_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:")


def _is_type(value, type_name):
    expected = _TYPE_MAP.get(type_name)
    if expected is None:
        return True
    if type_name == "integer":
        # JSON has no int/float distinction; 2.0 is a valid integer.
        if isinstance(value, bool):
            return False
        if isinstance(value, float):
            return value.is_integer()
        return isinstance(value, int)
    if type_name in ("number",):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool) and type_name in ("object", "array", "string", "null"):
        return False
    return isinstance(value, expected)


def _resolve_ref(ref, root):
    if not ref.startswith("#"):
        raise ValueError("only local $ref pointers are supported, got %r" % ref)
    pointer = ref[1:].lstrip("/")
    node = root
    if not pointer:
        return node
    for token in pointer.split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        else:
            node = node[token]
    return node


def _err(path, message):
    return {"path": path, "message": message}


def _validate(value, schema, root, path, errors, depth=0):
    if depth > 60:  # pragma: no cover - guards against pathological $refs
        errors.append(_err(path, "schema recursion limit exceeded"))
        return
    if schema is True or schema == {}:
        return
    if schema is False:
        errors.append(_err(path, "schema forbids any value here"))
        return
    if not isinstance(schema, dict):
        return

    if "$ref" in schema:
        try:
            target = _resolve_ref(schema["$ref"], root)
        except (KeyError, IndexError, ValueError) as exc:
            errors.append(_err(path, "unresolvable $ref %r (%s)" % (schema["$ref"], exc)))
            return
        _validate(value, target, root, path, errors, depth + 1)
        siblings = {k: v for k, v in schema.items() if k != "$ref"}
        if siblings:
            _validate(value, siblings, root, path, errors, depth + 1)
        return

    # -- type -------------------------------------------------------------
    if "type" in schema:
        types = schema["type"]
        types = types if isinstance(types, list) else [types]
        if not any(_is_type(value, t) for t in types):
            errors.append(_err(path, "expected type %s, got %s"
                               % ("/".join(types), type(value).__name__)))
            return

    # -- enum / const -----------------------------------------------------
    if "enum" in schema and value not in schema["enum"]:
        errors.append(_err(path, "value %r not in enum %r" % (value, schema["enum"])))
    if "const" in schema and value != schema["const"]:
        errors.append(_err(path, "value %r != const %r" % (value, schema["const"])))

    # -- combinators ------------------------------------------------------
    for key in ("allOf",):
        for i, sub in enumerate(schema.get(key, [])):
            _validate(value, sub, root, "%s/%s[%d]" % (path, key, i), errors, depth + 1)

    if "anyOf" in schema:
        if not any(not _collect(value, sub, root, path, depth + 1) for sub in schema["anyOf"]):
            errors.append(_err(path, "value matches none of the anyOf branches"))

    if "oneOf" in schema:
        matches = sum(1 for sub in schema["oneOf"]
                      if not _collect(value, sub, root, path, depth + 1))
        if matches != 1:
            errors.append(_err(path, "value matched %d oneOf branches, expected exactly 1" % matches))

    if "not" in schema and not _collect(value, schema["not"], root, path, depth + 1):
        errors.append(_err(path, "value must not match the 'not' schema"))

    if "if" in schema:
        if not _collect(value, schema["if"], root, path, depth + 1):
            if "then" in schema:
                _validate(value, schema["then"], root, path, errors, depth + 1)
        elif "else" in schema:
            _validate(value, schema["else"], root, path, errors, depth + 1)

    # -- numbers ----------------------------------------------------------
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(_err(path, "%r < minimum %r" % (value, schema["minimum"])))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(_err(path, "%r > maximum %r" % (value, schema["maximum"])))
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(_err(path, "%r <= exclusiveMinimum %r" % (value, schema["exclusiveMinimum"])))
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(_err(path, "%r >= exclusiveMaximum %r" % (value, schema["exclusiveMaximum"])))
        if "multipleOf" in schema and schema["multipleOf"]:
            quotient = value / schema["multipleOf"]
            if abs(quotient - round(quotient)) > 1e-9:
                errors.append(_err(path, "%r is not a multiple of %r" % (value, schema["multipleOf"])))

    # -- strings ----------------------------------------------------------
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(_err(path, "string shorter than minLength %d" % schema["minLength"]))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(_err(path, "string longer than maxLength %d" % schema["maxLength"]))
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(_err(path, "string does not match pattern %r" % schema["pattern"]))
        fmt = schema.get("format")
        if fmt == "date-time" and value and not _DATE_TIME_RE.match(value):
            errors.append(_err(path, "not a valid RFC3339 date-time: %r" % value))
        elif fmt == "uuid" and value and not _UUID_RE.match(value):
            errors.append(_err(path, "not a valid uuid: %r" % value))
        elif fmt == "uri" and value and not _URI_RE.match(value):
            errors.append(_err(path, "not a valid uri: %r" % value))

    # -- arrays -----------------------------------------------------------
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(_err(path, "array shorter than minItems %d" % schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(_err(path, "array longer than maxItems %d" % schema["maxItems"]))
        if schema.get("uniqueItems"):
            seen = []
            for item in value:
                key = json.dumps(item, sort_keys=True)
                if key in seen:
                    errors.append(_err(path, "array items must be unique"))
                    break
                seen.append(key)
        prefix = schema.get("prefixItems") or []
        for i, sub in enumerate(prefix):
            if i < len(value):
                _validate(value[i], sub, root, "%s[%d]" % (path, i), errors, depth + 1)
        if "items" in schema:
            for i, item in enumerate(value[len(prefix):], start=len(prefix)):
                _validate(item, schema["items"], root, "%s[%d]" % (path, i), errors, depth + 1)
        if "contains" in schema:
            if not any(not _collect(item, schema["contains"], root, path, depth + 1) for item in value):
                errors.append(_err(path, "no array item matches the 'contains' schema"))

    # -- objects ----------------------------------------------------------
    if isinstance(value, dict):
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            errors.append(_err(path, "fewer than minProperties %d" % schema["minProperties"]))
        if "maxProperties" in schema and len(value) > schema["maxProperties"]:
            errors.append(_err(path, "more than maxProperties %d" % schema["maxProperties"]))
        for prop in schema.get("required", []):
            if prop not in value:
                errors.append(_err(path, "missing required property %r" % prop))
        for prop, subs in (schema.get("dependentRequired") or {}).items():
            if prop in value:
                for dep in subs:
                    if dep not in value:
                        errors.append(_err(path, "property %r requires %r" % (prop, dep)))

        props = schema.get("properties") or {}
        pattern_props = schema.get("patternProperties") or {}
        addl = schema.get("additionalProperties", True)

        for key, item in value.items():
            child = "%s/%s" % (path, key)
            handled = False
            if key in props:
                _validate(item, props[key], root, child, errors, depth + 1)
                handled = True
            for pat, sub in pattern_props.items():
                if re.search(pat, key):
                    _validate(item, sub, root, child, errors, depth + 1)
                    handled = True
            if not handled:
                if addl is False:
                    errors.append(_err(path, "additional property %r is not allowed" % key))
                elif isinstance(addl, dict):
                    _validate(item, addl, root, child, errors, depth + 1)


def _collect(value, schema, root, path, depth):
    sub_errors = []
    _validate(value, schema, root, path, sub_errors, depth)
    return sub_errors


def validate(instance, schema):
    """Validate *instance* against *schema*; return a list of error dicts."""
    errors = []
    _validate(instance, schema, schema, "", errors, 0)
    return errors


def validate_or_raise(instance, schema, subject=""):
    """Validate and raise :class:`ValidationError` on failure; return *instance*."""
    errors = validate(instance, schema)
    if errors:
        raise ValidationError(errors, subject=subject or schema.get("title", ""))
    return instance


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------

def _schema_dirs():
    """Candidate directories holding the shipped ``*.schema.json`` files."""
    here = Path(__file__).resolve().parent
    return [
        here / "schemas",            # installed package data
        here.parent.parent / "schemas",  # running from a source checkout
        Path(sys.prefix) / "share" / "liwm" / "schemas",  # installed wheel
    ]


class SchemaStore:
    """Loads and caches the schemas that ship with LIWM."""

    def __init__(self, extra_dirs=None):
        self._cache = {}
        self.dirs = [Path(d) for d in (extra_dirs or [])] + _schema_dirs()

    def path_for(self, name):
        filename = name if name.endswith(".json") else "%s.schema.json" % name
        for d in self.dirs:
            candidate = d / filename
            if candidate.is_file():
                return candidate
        return None

    def load(self, name):
        if name in self._cache:
            return self._cache[name]
        p = self.path_for(name)
        if p is None:
            raise FileNotFoundError(
                "schema %r not found in %s" % (name, [str(d) for d in self.dirs])
            )
        with open(p, "r", encoding="utf-8") as fh:
            schema = json.load(fh)
        self._cache[name] = schema
        return schema

    def validate(self, instance, name):
        return validate(instance, self.load(name))

    def validate_or_raise(self, instance, name):
        return validate_or_raise(instance, self.load(name), subject=name)

    def available(self):
        found = {}
        for d in self.dirs:
            if d.is_dir():
                for f in sorted(d.glob("*.schema.json")):
                    found.setdefault(f.name.replace(".schema.json", ""), f)
        return found


_DEFAULT_STORE = SchemaStore()


def load_schema(name):
    """Load a shipped schema by short name (e.g. ``"user"``)."""
    return _DEFAULT_STORE.load(name)
