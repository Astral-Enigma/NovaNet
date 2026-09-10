"""Template rendering.

Pages were built by reading an .html file and chaining .replace() calls over {{ name }}
markers. That meant every value had to be escaped by hand on the way in, every page
repeated the same head and chrome, and a value containing a marker could substitute into
the next replacement.

Jinja does the substitution instead, with autoescaping on, so values are escaped because
they are values rather than because somebody remembered. HTML assembled in Python is
marked safe explicitly at the point it is passed in, which makes those places obvious.
"""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup, escape

TEMPLATE_DIR = Path(__file__).parent

env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(default_for_string=True, default=True),
    # A missing variable should fail loudly in a template rather than render as an empty
    # string and leave a page quietly half-built.
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template_name, **context):
    return env.get_template(template_name).render(**context)


def esc(value):
    """Escape a value for HTML text or a quoted attribute.

    Templates no longer need this. It remains for the handful of fragments still assembled
    as strings in Python, which are handed to templates as Markup and so skip autoescaping.
    """
    return str(escape("" if value is None else str(value)))


def js_string(value):
    """A JS string literal that is safe inside a double-quoted HTML attribute.

    HTML-escaping alone is not enough: the parser decodes entities inside the attribute
    before the JavaScript is parsed, so an apostrophe would still close the string. Going
    through a JSON literal first means the quotes are already escaped for JavaScript.
    """
    import json

    return str(escape(json.dumps("" if value is None else str(value))))


def safe(html):
    """Mark Python-assembled HTML as already escaped."""
    return Markup(html)
