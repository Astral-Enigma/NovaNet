"""Page chrome and the HTML fragments still assembled in Python.

Templates own most of the markup now. What remains here is the handful of fragments a
route builds before handing them to a template as Markup - table rows and the enemy panel
- plus page(), which fills in the chrome every page shares.
"""

import json

from config import CREATURE_FIELDS, FIELDS, TECHNIQUE_FIELDS
from queries import format_stamp, get_current_player, read_creatures
from render import esc, js_string, render, safe
from rules import MAX_DICE, RANK_DICE, RANK_ORDER, rank_for_threat

def render_technique_row(t):
    return (
        "<tr>" + "".join(f"<td>{esc(t[f])}</td>" for f in TECHNIQUE_FIELDS) +
        f"<td><a href='/technique/{t['id']}/edit'>Edit</a></td>"
        f"<td><form method='post' action='/technique/{t['id']}/delete' style='display:inline' "
        f"onsubmit=\"return confirm({js_string('Delete ' + str(t['name']) + '?')})\">"
        f"<button type='submit'>Delete</button></form></td></tr>"
    )


def render_creature_row(c):
    return (
        "<tr>" + "".join(f"<td>{esc(c[f])}</td>" for f in CREATURE_FIELDS) +
        f"<td><form method='post' action='/enemy/{c['id']}/generate' style='display:inline'>"
        f"<input type='number' name='threat_level' value='{c['default_threat_level']}' min='1' max='6' style='width:3em' />"
        f"<button type='submit'>Generate</button></form></td>"
        f"<td><a href='/enemy/{c['id']}/edit'>Edit</a></td>"
        f"<td><form method='post' action='/enemy/{c['id']}/delete' style='display:inline' "
        f"onsubmit=\"return confirm({js_string('Delete ' + str(c['name']) + '?')})\">"
        f"<button type='submit'>Delete</button></form></td></tr>"
    )


def render_room_messages(messages):
    if not messages:
        return "<p class='quotes'>Nothing has happened here yet.</p>"
    out = []
    for m in messages:
        stamp = esc(format_stamp(m["created_at"]))
        who = esc(m["enemy_name"] or m["character_name"] or "Unknown")
        if m["kind"] == "system":
            out.append(f"<p class='log-system'><span class='log-time'>{stamp}</span> {esc(m['body'])}</p>")
        elif m["kind"] == "roll":
            # Roll bodies are built by the server from rendered dice markup, not user input.
            out.append(
                f"<p class='log-roll'><span class='log-time'>{stamp}</span> "
                f"<strong>{who}</strong> {m['body']}</p>"
            )
        else:
            out.append(
                f"<p class='log-text'><span class='log-time'>{stamp}</span> "
                f"<strong>{who}:</strong> {esc(m['body'])}</p>"
            )
    return "".join(out)


def render_enemy_panel(room_id, enemies, is_hm, is_closed):
    """The enemy field. Everyone sees who is on it; only the HM gets the controls."""
    if not enemies and not is_hm:
        return ""
    rows = []
    for e in enemies:
        try:
            stats = json.loads(e["stats"])
        except (TypeError, ValueError):
            stats = {}
        stat_text = ", ".join(f"{k} {v}" for k, v in stats.items())
        roll_count, keep_count = RANK_DICE[rank_for_threat(e["threat_level"])]
        actions = ""
        if is_hm and not is_closed:
            actions = (
                f"<form class='control-row' method='post' action='/play/room/{room_id}/enemy/{e['id']}/roll'>"
                "<select name='mode'>"
                f"<option value='threat'>Threat ({roll_count}d6 keep {keep_count})</option>"
                "<option value='d20'>1d20</option></select>"
                "<button type='submit'>Roll</button></form>"
                f"<form class='control-row' method='post' action='/play/room/{room_id}/enemy/{e['id']}/dismiss' "
                "onsubmit=\"return confirm('Remove this enemy from the field?')\">"
                "<button type='submit'>Dismiss</button></form>"
            )
        talent = f"{esc(e['talent_name'])}"
        if e["talent_uses"]:
            talent += f" ({e['talent_uses']} uses, {e['talent_cooldown']} round cooldown)"
        rows.append(
            f"<tr><td>{esc(e['name'])}</td>"
            f"<td>{esc(rank_for_threat(e['threat_level']))} ({e['threat_level']})</td>"
            f"<td>{esc(stat_text)}</td><td>{talent}</td><td>{actions}</td></tr>"
        )
    table = (
        "<div class='table-wrap'><table>"
        "<tr><th>Enemy</th><th>Threat</th><th>Skills</th><th>Talent</th><th></th></tr>"
        + "".join(rows) + "</table></div>"
    ) if rows else "<p class='quotes'>No enemies on the field.</p>"

    spawn = ""
    if is_hm and not is_closed:
        creatures = read_creatures()
        if creatures:
            options = "".join(
                f"<option value='{c['id']}'>{esc(c['name'])} "
                f"({esc(rank_for_threat(c['default_threat_level']))})</option>"
                for c in creatures
            )
            spawn = (
                f"<form class='control-row' method='post' action='/play/room/{room_id}/enemy'>"
                f"<label>Send in: <select name='creature_id' required>{options}</select></label>"
                "<label>Threat level: <input type='number' name='threat_level' min='1' max='6' "
                "value='' placeholder='catalog default' /></label>"
                "<button type='submit'>Generate</button></form>"
            )
        else:
            spawn = ("<p class='quotes'>The Creature Catalog is empty. "
                     "<a href='/enemies' class='section-link'>Add a creature</a> to send one in.</p>")
    return "<h2>Enemies</h2>" + table + spawn


def render_dice_result(all_rolls, keep_count):
    sorted_rolls = sorted(all_rolls, reverse=True)
    kept, dropped = sorted_rolls[:keep_count], sorted_rolls[keep_count:]
    return (
        "".join(f"<span class='die'>{d}</span>" for d in kept) +
        "".join(f"<span class='die die-dropped'>{d}</span>" for d in dropped)
    )


def nav_links_for(current_player):
    links = [
        ("Home", "/"),
        ("Create a Character", "/characters/new"),
        ("Characters", "/characters"),
        ("Players", "/players"),
    ]
    if current_player and current_player["is_hm"]:
        links.append(("Enemies", "/enemies"))
    links.append(("Play", "/play"))
    links.append(("Nova News Network", "#"))
    return links


def page(request, template, **context):
    """Render a page with the chrome every page shares already filled in."""
    current_player = get_current_player(request)
    return render(
        template,
        current_player=current_player,
        nav_links=nav_links_for(current_player),
        **context,
    )


# One list drives both the header row and the cells, so a column added in one place cannot
# fall out of step with the other. Each entry is (header, how to show it).
CHARACTER_COLUMNS = [
    ("Name", lambda c: c["name"]),
    ("Age", lambda c: c["age"]),
    ("Rank", lambda c: c["rank"]),
    ("Clan", lambda c: c["clan"]),
    ("House", lambda c: c["house"]),
    ("Trait", lambda c: c["trait"]),
    ("Trauma", lambda c: f"{c['trauma']} / {c['trauma_limit']}"),
    ("Pneuma", lambda c: f"{c['pneuma']} / {c['pneuma_limit']}"),
    ("Deftness", lambda c: c["deftness"]),
    ("Handling", lambda c: c["handling"]),
    ("Tenacity", lambda c: c["tenacity"]),
    ("Wit", lambda c: c["wit"]),
    ("Perception", lambda c: c["perception"]),
    ("Composure", lambda c: c["composure"]),
    ("Pluck", lambda c: c["pluck"]),
    ("Potential", lambda c: c["potential"]),
    ("AP", lambda c: c["academy_points"]),
    ("Zel", lambda c: c["zel"]),
]
CHARACTER_HEADERS = [header for header, _ in CHARACTER_COLUMNS]


def render_character_row(c, show_player):
    player_cell = f"<td>{esc(c['player_name'])}</td>" if show_player else ""
    return (
        "<tr>" + player_cell + "".join(f"<td>{esc(show(c))}</td>" for _, show in CHARACTER_COLUMNS) +
        f"<td><a href='/character/{c['id']}/techniques'>Techniques</a></td>"
        f"<td><a href='/character/{c['id']}/edit'>Edit</a></td>"
        f"<td><form method='post' action='/character/{c['id']}/delete' style='display:inline' "
        f"onsubmit=\"return confirm({js_string('Delete ' + str(c['name']) + '?')})\">"
        f"<button type='submit'>Delete</button></form></td></tr>"
    )


def render_player_options(players, selected_id=None):
    return "".join(
        f"<option value='{p['id']}'{' selected' if p['id'] == selected_id else ''}>{esc(p['name'])}</option>"
        for p in players
    )


def render_error_page(request, status, detail):
    try:
        current_player = get_current_player(request)
    except Exception:
        # Never let a failure while looking up the session mask the original error.
        current_player = None
    return render(
        "error.html",
        status=status,
        detail=detail,
        current_player=current_player,
        nav_links=nav_links_for(current_player),
    )
