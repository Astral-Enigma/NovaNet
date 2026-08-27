# NovaNet Roadmap

_Last updated: 2026-08-27_

A top-to-bottom plan for building NovaNet: a web-based roleplaying platform for **Nova**,
built around DeathHaven University. This roadmap starts from the code that already exists
in `nova-blank/character/` and works outward to the full vision in the original NovaNet
design doc.

## Source documents

This plan is built against the complete ruleset:

| Document | Role in this plan |
| --- | --- |
| _Nova: Headmaster's Handbook (Ver 1.2)_ | Character creation, Clans/Traits/Houses, the school year, ranking, the combat framework, death. |
| _Merchant's Manual_ | Techniques, Bursts, Styles, Transformations, Incantations, the Technique Builder, equipment, forging, and all 11 status effects. |
| _Creature Catalog_ | Enemy stat formulas, combat rewards, and 17 fully specified creatures. |
| Original NovaNet design doc | The product vision — forums, messaging, yearbook, discovery. |

Nothing in this roadmap is blocked on missing content any more. Every phase below has the
rules text it needs.

---

## Part I — Where things stand

### What's built

`nova-blank/character/main.py` is a ~950-line single-file FastAPI app with SQLite
(`characters.db`) and hand-written HTML files filled by string substitution.

| Area | State |
| --- | --- |
| Auth | Enroll/login by name only, no password. Session cookie holds `player_id`. |
| Roles | One site-wide `is_hm` flag on `players`; first claimer wins, permanently. |
| Players | Player list, player profile listing that player's characters. |
| Characters | Full CRUD, ownership checks (`require_owner_or_hm`), auto-computed Pluck/Potential. |
| Techniques | Per-character CRUD — name, description, toll, type, category, effect, burst, duration. |
| Creatures | HM-only catalog CRUD + formula-driven stat generation by threat level. |
| Dice | Roll/keep roller wired to `RANK_DICE` (Novice 1d6/1d6 → Master 6d6/5d6). |
| UI | Shared nav (`render_nav`), Nova-branded `style.css`, Home page. |

### Current schema

```
players     (id, name, is_hm)
characters  (id, player_id, name, age, rank, clan, house, trait,
             trauma, pneuma, deftness, handling, tenacity, wit,
             perception, composure, pluck, potential)
techniques  (id, character_id, name, description, toll, type,
             category, effect, burst, duration)
creatures   (id, name, description, habitat, main_skill,
             default_threat_level, talent_name, talent_effect, drops)
```

### What's already right — build on these, don't replace them

- **`RANK_DICE`** matches the Handbook's Roll/Keep table exactly.
- **`roll_and_keep()`** is the correct primitive for Effectiveness Rolls.
- **`compute_derived_fields()`** correctly derives Pluck from the six skills, Potential from Pluck.
- **The `techniques` schema was designed against the Merchant's Manual and holds up.**
  `toll`, `type`, `category`, `effect`, `burst`, `duration` are exactly the six fields a
  Manual technique carries. It needs additions, not a redesign.
- **`HABITATS`** exactly matches the Catalog's five groupings (Land Dwelling, Sky-Faring,
  Sea-Faring, Celestial, Damned).
- **Creature talent math is correct** — `2d6 × Threat Level` uses, `ceil(TL / 2)` round cooldown.

### Two concrete bugs found while reading the manuals

**1. Non-main creature skills are generated wrong.** `generate_creature_stats()` in
`main.py:339` computes non-main skills as `TL d6 + (TL - 1)`. The Catalog specifies that
creatures start with a flat **1** in every non-main skill at Novice, then gain `1d6 + 1`
for **each rank above Novice**:

```python
# current  — wrong at every threat level, and badly wrong at Novice (1d6+0 instead of 1)
stats[skill] = sum(roll_dice(threat_level, 6)) + (threat_level - 1)

# correct
stats[skill] = 1 + sum(roll_dice(threat_level - 1, 6)) + (threat_level - 1)
```

The main-skill branch (`TL d6 + TL`) is correct and matches "Novice is 1d6+1, Master is 6d6+6".

**2. The session secret is regenerated at import.** `secrets.token_hex(32)` runs on every
start, so every restart silently logs out every user. Move it to an env var with a
persisted local fallback.

### The gap, in one list

1. **Trauma and Pneuma are single integers.** Trauma is a counter rising from 0 toward a
   **Trauma Limit** (starts 15); Pneuma is a **Pool** falling from a limit (starts 10).
2. **`rank` is free text.** Needs to be an enum with AP thresholds attached.
3. **No Academy Points, no Zel.** Both are load-bearing in nearly every subsystem.
4. **Clan, House, and Trait are free text with no mechanical effect.**
5. **No House Reputation** — it starts at 1 and multiplies directly into the weekly stipend.
6. **No character status** — Active / Expelled / Destabilized / Deceased / Graduated / Ascended.
7. **No status effects.** The Manual specifies 11, each with precise duration and stacking rules.
8. **No Bursts as mechanics** — the field exists, but nothing evaluates a Burst condition.
9. **No Styles, Transformations, Incantations, or Spirit Techniques.**
10. **No Technique Builder** — the point-buy custom-technique system with an exact AP cost table.
11. **No equipment at all** — no weapons, armor, items, quality ranks, durability, or charges.
12. **No forging, materials, or catalysts.**
13. **No creature seed data** — 17 creatures are fully specified and sitting unentered.
14. **No school system** — semesters, weeks, actions, classes, trials, exams, graduation.
15. **No combat engine.** The Play page is a dead nav link.
16. **No campaigns.** Everything is one global, flat pool.
17. **No social layer** — no posts, messaging, battle requests, or yearbook.
18. **No passwords.**

---

## Part II — The plan

Ten phases. 0–3 are foundational and sequential. 4–6 are the rules content layer and can
run in parallel. 7 is the payoff. 8 is the biggest. 9–10 are the platform.

---

### Phase 0 — Make the codebase able to hold the rest of this

**Why first:** the manuals roughly quintuple the app's scope. A single 950-line file with
string-concatenated HTML, no tests, and ad-hoc `migrate_*_if_needed()` helpers will not
survive Phase 4's technique engine, let alone Phase 7's combat state machine.

- **Split `main.py` into modules** — `db.py`, `models/`, `routes/`, `rules/`, `render.py`.
  Keep the app runnable at every commit; move one router at a time.
- **Adopt Jinja2 templates.** The `.html` files become real templates; the row-rendering
  helpers (`render_character_row`, `render_creature_row`, `render_technique_row`) become partials.
- **Real migrations** — numbered SQL files plus a `schema_version` table. Fold
  `migrate_player_id_if_needed` / `migrate_is_hm_if_needed` / `migrate_csv_if_needed` into
  migration 001 and close out the CSV era.
- **pytest + FastAPI `TestClient`.** The rules engine is almost entirely pure functions over
  integers — it is exceptionally cheap to test, and it is about to become the heart of the app.
- **Fix the session secret** (see bug 2 above).
- **Create a `rules/` package** as the single home for every constant the four manuals
  specify: `RANKS`, `RANK_DICE`, `RANK_AP_THRESHOLDS`, `CLANS`, `HOUSES`, `TRAITS`,
  `TRAIT_MATCHUPS`, `CLASSES`, `SKILL_CHECK_DCS`, `STATUS_EFFECTS`, `QUALITY_RANKS`,
  `CATALYST_RARITIES`, `MATERIAL_TYPES`, `BUILDER_COSTS`. Every later phase reads from here.

---

### Phase 1 — A character sheet true to the Handbook

**Depends on:** Phase 0's migration system.

The highest-value phase in the document. Nothing downstream is correct until the sheet
models what the Handbook actually says.

#### 1.1 Resource pairs

- `trauma_current` (starts 0, **counts up**), `trauma_limit` (starts 15)
- `pneuma_current` (starts 10, **counts down**), `pneuma_limit` (starts 10)
- Rank Up grants **+3 to both limits**.
- **Pneuma regen:** each round a character spends no Pneuma, regain `ceil(composure / 2)`.
- **Toll overflow:** a technique can still be used at 0 Pneuma — **the Toll is paid in
  Trauma instead.** This single rule is why the pair split matters so much.

#### 1.2 Rank as an enum with thresholds

| Rank | AP | Roll/Keep | Conduit equivalent | Conduit Roll/Keep |
| --- | --- | --- | --- | --- |
| Novice | start | 1d6 / 1d6 | Lesser | 1d12 / 1d12 |
| Rookie | 13 | 2d6 / 1d6 | Minor | 2d12 / 1d12 |
| Genius | 20 | 3d6 / 2d6 | Greater | 3d12 / 2d12 |
| Expert | 34 | 4d6 / 3d6 | Major | 4d12 / 3d12 |
| Veteran | 48 | 5d6 / 4d6 | Higher | 5d12 / 4d12 |
| Master | 88 | 6d6 / 5d6 | Master | 6d12 / 5d12 |

Rank Up is available when AP thresholds are met **or when Pluck matches/exceeds the required
value**, and costs an action. On Rank Up: dice pool increases, +1 weekly action, +1 AP from
Attending Class and Studying, +3 Trauma and Pneuma Limits, **and one new Spirit Technique
unlocks** (see 4.5 — this happens whether or not the character has ever died). At **Genius**,
gain 1 extra Major and 1 extra Minor action; extra actions cause **Winded** at every rank
except Master.

#### 1.3 New character fields

`academy_points`, `zel`, `status` (`active` | `expelled` | `destabilized` | `deceased` |
`graduated` | `ascended`), `house_reputation` (starts at 1), `morality`,
`destabilized_until_week`, `instant_links_used`, `pluck_saves_used`.

#### 1.4 Clans as mechanics

| Clan | Zel | Bonus |
| --- | --- | --- |
| Varna | 400 | Composure-based technique Tolls cost 1 less per rank |
| Kin | 350 | Take 2 less damage per rank from Tenacity attacks |
| Forged | 300 | +2 per rank to all mental rolls |
| Stricken | 300 | +2 per rank to all Perception rolls |
| Haunted | 300 | +1 AP per rank up, +1 starting AP |

Creation separates **appearance clan** from **mechanical clan** — the Handbook explicitly
allows looking Varna while taking the Kin bonus.

#### 1.5 Traits, matchups, and Shaping

```
Shin  → strong vs Zin      Zin  → strong vs Smog
Smog  → strong vs Pyre     Pyre → strong vs Shin
Null  → choose 1 Trait; keep 1 more d6 per rank defending against it
```

Strong matchup = **keep 1 more d6 per rank**. Shaping costs 5 Pneuma (−1 per rank past
Novice) and, when used *without* a technique, **applies your Trait's status effect if you
exceed the target's Pluck — once per rank.**

#### 1.6 Houses as mechanics

| House | Zel | Leader | Free technique |
| --- | --- | --- | --- |
| Zealot | 50 | Jazmine Stark (Pyre) | Crushing Blow |
| Hermit | 60 | Eidelia Leven (Shin) | Nerves of Steel |
| Patron | 75 | Samantha Sinclair (Null) | Lifelink |
| Serpent | 55 | Spell (Zin) | Draining Strike |
| Alchemist | 75 | Edson & Alexander Spintz | Unstable Insight |
| Emperor | 70 | Solo King | Royal Decree |

The free House technique is **auto-inserted into `techniques`** at creation.

#### 1.7 The creation wizard

Four guided steps replacing the flat form:

1. **Allocate Academy Points** — 10 to start (11 for Haunted), 1 AP per skill point. Skills
   cap at **Potential**; exceeding the cap costs **2 AP per point**. Because Potential
   derives from Pluck which derives from the skills, the cap *moves as you spend* — this
   needs live client-side recalculation and full server-side re-validation on submit.
   Trauma and Pneuma do not affect Potential.
2. **Choose a Clan** (appearance and mechanical bonus separately).
3. **Select a Trait** (plus the resisted Trait if Null).
4. **Pick a House** (applies Zel, skill bonus choice, free technique).

#### 1.8 Quirks, Curses, and Talents

`quirks` table + `character_quirks` join, seeded from the Handbook:

- **Quirks (cost AP):** Foreign Influence 5, Beast Shape 4, Biased Cognition 7 (2 less for
  Forged), Quick Study 4 (1 less if Wit is highest), Lay of the Land (earned via Exploring).
- **Curses (grant AP):** Half-Sight/Blind, Wounded, Clumsy, Dim-Witted, Slow-Starter,
  Vertigo, Anxiety, Fiscal Insecurity.
- **Major Talents (ReTraits):** Tinsyr (Shin/metal), Umbrah (Null/shadow). Replaces the base
  Trait; requires source material present to Shape.
- **Minor Talents:** Air Born 2, Soul Reader 2, Charismatic Karma 3.

#### 1.9 Morality is mechanical, not flavor

The 3×3 Morality Menu (Honorable/Neutral/Devious × Passionate/Neutral/Ambitious) is a
**required** field, not an optional rule, because **Regalia and Noxia weapons Sync based on
morality alignment** (see 5.4). Store it on the character and expose it to the equipment
system.

---

### Phase 2 — Accounts, roles, and permissions

**Depends on:** Phase 0.

`is_hm` conflates two unrelated jobs: running a game (fiction, scoped to a table) and
administering the platform (technical). Split them.

- **Passwords** — `password_hash` via `passlib` (argon2), real registration, password reset.
- **`is_site_admin`** — platform-level, rare, seeded by a one-time setup step rather than a
  checkbox on the enroll form. Grants: manage accounts, moderate content, promote/demote admins.
- **`is_hm` moves off `players`** onto `campaign_members` (Phase 3). A player can be HM of
  one campaign and a Student in another.
- **Site admin console** — list/search players, deactivate, grant/revoke admin, grant/revoke
  HM on any campaign.
- **Migration** — the existing global HM becomes HM of a "Legacy" campaign so nothing is orphaned.

---

### Phase 3 — Campaigns (the forums)

**Depends on:** Phase 2.

The original design doc describes "player profiles capable of housing multiple characters
tied to different forum based games." A campaign *is* that forum, and it's the scope
boundary for the school clock, encounters, and the economy.

- **Schema** — `campaigns` (name, description, status, created_at, optional-rule flags),
  `campaign_members` (campaign_id, player_id, role HM/Student, joined_at),
  `characters.campaign_id`.
- **Campaign directory** — browse active campaigns, who runs them, player count, open vs. invite.
- **Join / leave** — HM-approved invites by default, open sign-up as a per-campaign option.
  Leaving must never delete characters.
- **"Current campaign" session state** alongside `player_id`; switching is a first-class nav action.
- **Reference-data scoping decision:** creature templates, technique lists, and the item
  catalog stay **site-wide shared reference** — they're published manuals, not table secrets.
  *Instances* — generated enemies, owned items, live encounters, forged gear — are
  campaign-scoped. Confirm before building; it's awkward to reverse.
- **Optional-rule toggles per campaign** from the Handbook: no passive healing, Reputation
  (−6…6, ±2 per rank), Lore Points, multiracial characters, weapon durability.

---

### Phase 4 — Techniques, Styles, and Transformations

**Depends on:** Phase 1. **New in this revision** — the Merchant's Manual turned what was
one line of the old roadmap into a subsystem the size of the character sheet.

The existing `techniques` table is the right shape. This phase turns it from a notepad into
an engine.

#### 4.1 Technique model extensions

Add: `is_basic`, `source` (`house` | `manual` | `trained` | `purchased` | `built`),
`ap_cost`, `trait` (for Shaping techniques), `style_id` (arsenal membership), `charges_used`.

**Core rules the engine must enforce:**

- **Toll** is paid in Pneuma; at 0 Pneuma it is **paid in Trauma**.
- **Type** is `Method/Stat` (e.g. `Physical/Handling`) — the default stat, overridable by the
  HM. **Physical beats Pneumatic defense and vice versa: keep 1 more d6 per rank when
  attacking the type you're strong against.**
- **Category** (Offensive, Defensive, Utility, Shaping, Style, Weapon, Spirit,
  Transformation) is intent, not restriction — any technique may be used any way at HM discretion.
- **Purchase cost** for training or buying a technique is derived from its **Toll**.

#### 4.2 Seed the manual's techniques

All of it is specified and should be loaded as shared reference data:

- **Basic** (free, never recorded on a sheet): Empowered Strike 2, Swift Strike 3, Endure 3,
  Grapple 4, Trait Shaping 5 (−1/rank).
- **Offensive:** Assault & Battery 2, Spirit Shot 2, Steady Strike 3, Heedless Swing 3,
  Astral Bullets 3, Sleight of Hand 4, Ambidexterity 5, Ardent Stream 5, Pneumatic Crash 6.
- **Defensive:** Crossguard 3, Spirit Shell 4 (+2/round upkeep), Quickstep 4.
- **Utility:** Transfusion 3, Mirrored Sensation 3, Encore/Reprise 4, Twin Soul 5.
- **Shaping, by Trait:** Shin (Cryomancy, Diamond Dust, Glacial Armor), Zin (Return Stroke,
  Thunder Shot, Static Steps), Smog (Virulent Bullets, Creeping Fog, Venom Eater, Flu
  Season), Pyre (Incinerate, Scorching Clouds, Firebreak), Null (Empty Strike, Equilibrium, Splice).

#### 4.3 Bursts

Every seeded technique carries a **Burst condition** and a **Burst effect**. Model them as
structured data where the condition is machine-checkable (`first success`, `last to act`,
`below trauma limit`, `outnumbered`, `consumed last Pneuma`, `rolled doubles`, `failed
Possibility`) and free text where it isn't. In combat, the engine should *detect and offer*
a Burst rather than auto-firing it — several Bursts are optional or come with a cost.

Many Bursts have **usage limits** (`once per target`, `once per battle`, `once per rank`,
`x times where x is Rank`). These need per-encounter and per-target counters.

#### 4.4 Combat Styles

A Style pays its Toll **once, on activation**. Learning both a Style and a Technique lets a
player pay the Style's Toll to add that Technique to the Style's **arsenal**, granting it the
Style's effect. **Non-arsenal techniques (except Basic ones) cannot be used while a Style is
active, and vice versa** — a real constraint the UI must surface, not just record.

Seed: Prismatic Fists (Toll 5), Rhythm of Eruption (Toll 10, arsenal: Haven Fist, Quickstep).

#### 4.5 Spirit Techniques

Usable **only while dead** (destabilized), and a character **unlocks one per Rank Up whether
or not they have ever died** — so a living Master already has six banked. Seed: Veiled
Presence, Ghastly Whispers, Unholy Swarm, Haunting Visage, Impure Animation, Impure
Resurrection. This is what makes Phase 7's destabilized state playable instead of a
spectator seat.

#### 4.6 Transformations

Consume a **Minor Action**. While transformed, **exceeding your Trauma Limit does not kill
you until the transformation ends** — a significant exception the damage pipeline must know about.

- **Limit Boost** — +x to one stat where x = Rank. Toll: x per round.
- **Overlay** — double the Limit Boost Toll to double the effect; **the Toll is paid in
  Trauma**, usable x times per rank.
- **The Exceed State** — below half health, +xd6 to all rolls for x rounds.
- **Star Signature** — Toll x×2. Emotional Resonance unlocks a redefinition of the Trait
  (freezing things → freezing time), with an activation phrase.
- **Steel Signature** — Toll x×2, lasts x rounds where x is **Weapon** Rank. Requires a
  Synced Regalia/Noxia (5.4).

#### 4.7 Incantations

Three words = one line. `+x` to a technique's effectiveness where x is the number of lines;
**lines cannot exceed current Rank**; using one consumes your Minor Action. Store per
character, validate the line cap against rank, and offer them at roll time.

#### 4.8 The Technique Builder — the flagship feature

A point-buy creator where **Toll = (AP spent) − Rank**. This is miserable to do on paper and
delightful in software: live cost total, live Toll preview, validation against rank, and a
finished technique written straight into the character's sheet.

**Dice modifiers** (stackable): Roll +1d6 (1) · Roll +1d6/rank (2) · Target rolls −1d6 (2) ·
Target rolls −1d6/rank (3) · Keep +1d6 (2) · Keep +1d6/rank (3) · Target keeps −1d6 (2) ·
Target keeps −1d6/rank (4) · +1 Possibility **or** Effectiveness (1) · +1 to **both** (2) ·
+1/rank to one (3) · +1/rank to both (4) · −1 to target's one (1) · −1 to target's both (2) ·
−1/rank to target's one (3) · −1/rank to target's both (4).

**Effects:** Build Up (2) — requires 2 hits or 2 rounds. Instant (4) — applies on any successful hit.

**Bonuses:** Passive (3, caps effectiveness at 2d6) · AoE (cost = Rank, affects up to Rank
targets) · Persisting (player-chosen cost x = rounds, caps at 2d6) · Transformation (4, +2
per uncovered effect) · Style (4, +2 per uncovered effect).

Build this as a **shared point-buy engine**, because Phase 5's forging system reuses the
identical dice table with a different bonus block.

---

### Phase 5 — Equipment, items, and forging

**Depends on:** Phase 1 (Zel/AP) and Phase 4 (the point-buy engine). **No longer blocked** —
the Merchant's Manual supplies every number.

#### 5.1 Weapons

Quality Rank runs **Novicework → Masterwork** (1–6) and adds its rank as a flat bonus to
damage. Attacks use **Handling**, but each weapon's unique effect triggers only on its own
listed stat, **scales with the user's rank**, and is usable `ceil(rank / 2)` times.
**A weapon above the user's rank costs −2 Possibility per rank of excess.**

| Weapon | Stat | Zel/rank | Effect |
| --- | --- | --- | --- |
| Katana | Handling | 100 | Roll +1d6 |
| Threshing Scythe | Deftness | 125 | Roll +2d6 |
| Fire Axe | Tenacity | 150 | Keep +1d6 attacking |
| Iron Buckler | Handling | 150 | Keep +1 guarding; Burst on trading blows |
| Compact Revolver | Perception | 150 | Keep +1d6; 6 shots; Burst skips Possibility |
| Rapier | Deftness | 175 | Keep +2d6 attacking, −1 guarding |
| Knuckle Dusters | Tenacity | 200 | Roll and keep +1d6; Burst rerolls a low die |
| Ranger's Rifle | Wit | 250 | Keep +2d6; Burst ignores an accuracy penalty |

#### 5.2 Armor

Mitigates damage equal to **quality rank + wearer's Handling**. Armor **health** =
`(quality rank)d6 + Handling`; an attack exceeding that health **breaks** the armor, which
then needs Forging to repair. Armor above the user's rank costs **−2 Deftness per rank of
excess**. Seed: Prismatic Plates (150 Zel/rank) — reduces Pneumatic damage by 1d6 per rank.

#### 5.3 Items and charges

**Max charges = the Rank of the character using the item**, and items must be recharged.
Seed: Stitch Kit (150/rank), Quick Stitch Kit (100), Pep Pills (100), Ember / Frost / Spark /
Venom Charge (200 each), Ignition Coil (150), Ignition Hammer (200), Rebound Rounds (200),
plus two creature-drop-only items — Swath of Void and Essence Stone.

#### 5.4 Regalia and Noxia

Seven named artifacts (Regalia: Starcutter, The Fool's Braid, The Sky Sabre. Noxia: Hand of
the Valkyrie, The Crested Dawn, The Djinn's Hourglass, Relief of Restriction). They function
as **Masterwork with no over-rank penalty** and must be found in character.

**Syncing** requires the wielder to make decisions aligned with the **morality of the spirit
in the weapon** — this is the mechanical payoff for Phase 1.9. Model a sync-progress track
the HM advances when a character acts in alignment; a completed Sync unlocks the weapon's
**Steel Signature** (Phase 4.6).

#### 5.5 Forging

- **Materials**, gathered via Exploring and drops, in five types: Offensive, Defensive,
  Medicinal, Mechanical, Electrical.
- **Catalysts** — creature parts, six rarities: Basic → Common → Uncommon → Rare → Exotic → Mythic.
- **The recipe:** materials needed = `rarity × 2`; Zel owed to Teuchi the Forgemaster =
  `100 × rarity`. Teuchi always makes the item, but you must pay to collect it.
- **Crafted item power** starts equal to the player's own, plus `ceil(Handling / 2)` to rolls
  involving it. Bonus effects use the **same dice cost table as the Technique Builder**, with
  its own bonus block: Passive 3 · AoE (cost = rarity) · Persisting 4 · Transformation 4.
  Every purchased effect raises the material requirement.
- Forging also **repairs** broken armor and **recharges** spent items — both are weekly
  actions in Phase 8.

#### 5.6 Status effects — the shared vocabulary

Eleven effects, each fully specified. Model as a real `status_effects` table with duration,
stacking, and escalation rules; Phases 4, 5, 6, and 7 all reference it.

| Effect | Mechanic |
| --- | --- |
| **Bound** | Cannot move, may only try to break free. `1d6 + attacker's rank` rounds. |
| **Blinded** | −1d6/rank on Possibility rolls using Perception, for `rank` rounds. |
| **Dazed** | −1d6/rank on Possibility rolls using Tenacity and Handling, for `rank` rounds. |
| **Rattled** | −1d6/rank on Possibility rolls using Composure and Wit, for `rank` rounds. |
| **Winded** | −2/rank to **all** rolls for the rest of combat, **doubling** each re-application. |
| **Dusted** (Shin) | No bonuses on offensive actions, 1d6 rounds. Three stacks = frozen solid. |
| **Blighted** (Smog) | `xd6` damage for `xd6` rounds at turn start. Damage +1d6 per additional blighted opponent, capped at rank. |
| **Shocked** (Zin) | No bonuses on defensive/movement actions, 1d6 rounds. Three stacks = Winded. |
| **Seared** (Pyre) | 1d6 damage for 1d6 rounds at turn end; restacking adds 1d6 (caps at rank); three stacks lets the attacker dump all remaining damage at once and clear the status. |
| **Marked** | No Pneuma regen and no Composure bonuses for 1d6 rounds; stacks add 1d6, capped at rank. |
| **Obscured** | Attackers must win a contested Wit roll to hit; your next attack applies its bonuses twice. Ends on attacking or being attacked. |

---

### Phase 6 — The Creature Catalog, properly

**Depends on:** Phase 0. Small, high-value, and mostly data entry — good parallel work.

- **Fix `generate_creature_stats()`** (bug 1 above).
- **Extend the `creatures` schema** — add `trait`, `rarity` (drives Catalyst drops),
  `talent_type` (passive vs. activated — many creatures have both), and support for
  **dual main skills** conditioned on environment (Harpy: Deftness/Tenacity when grounded;
  Kelpie: Composure on land / Deftness in water; Takdyl: Tenacity/Deftness while airborne;
  Wyvern: **Any**, dynamically set to the opponent's lowest skill).
- **Seed all 17 creatures**, keyed to the existing `HABITATS`:
  - **Land Dwelling** — Minotaur (1), Gorgon (2), Alkalym (4), Chimera (5)
  - **Sky-Faring** — Mechanicrow (1), Harpy (3), Takdyls (4), Wyverns (5)
  - **Sea-Faring** — Kelpie (1), Siren (3), Kraken (5)
  - **Celestial** — Phoenix (6), Magnus Dragon (6)
  - **Damned** — The Afflicted (2), Fleshspinners (5), Zeitghast (5), Kah'clth-Kahban (6)
- **Automate combat rewards**, which the Catalog specifies exactly:
  - **AP** = creature Threat Level + highest party member's rank.
  - **Catalyst** = a d6 roll on the rarity ladder, with **lower faces replaced by the
    defeated creature's own rarity** (so tough enemies can't drop junk).
  - **Zel** = `(1d6 + creature rank) × highest party member's rank`.
- **Note the drop→item links** already implied by the data: Zeitghast drops **Swath of Void**,
  Phoenix drops **Essence Stone**, Kah'clth-Kahban drops **Relief of Restriction** (a Noxia).
  The Catalog and the Manual are already wired together; the schema should reflect it with
  real foreign keys rather than a free-text `drops` column.

---

### Phase 7 — The Play page: combat

**Depends on:** Phases 1, 3, 4, 5, 6. This is where everything above becomes a game.

#### 7.1 Turn structure

Teams alternate; the team holding the single highest **Deftness** goes first, and members
order themselves within the team. Each character gets one **Major** and one **Minor** action,
plus a **Reaction** whenever an action directly affects them — and **a defender must react
with the same skill the attacker used**.

#### 7.2 The roll pipeline

1. **Intent** — actor declares action and target; target declares a reaction.
2. **Possibility Roll** — each side chooses whether to load their bonuses onto the d20 or the
   d6 (attacker chooses first); **the unchosen die gets half the bonus**. Both roll 1d20.
   A higher reacting roll means the reaction succeeds; ties reroll without modifiers.
3. **Instant Link** *(optional)* — after the d20s are visible but before Effectiveness
   resolves, either side may rewind to the start of the Possibility Roll. Both may choose a
   new Major Action; the initiator **must**. A new action makes you **Winded** and **does not
   refund the original Toll**. Usable `ceil(rank / 2)` times.
4. **Effectiveness Roll** — roll/keep per `RANK_DICE`, modified by technique, Burst, weapon,
   armor, Clan, House, Trait matchup, Physical-vs-Pneumatic advantage, status effects,
   Style, Transformation, and Incantation. **Flash Dice:** if you'd keep more dice than you
   may roll, roll the extras for that action only and swap kept dice for them.

`roll_and_keep()` is the core of step 4. Step 3 is the architectural constraint of the whole
phase: **an Instant Link is a rewind, so encounters need persisted, resumable, reconstructible
state** — not a stateless roll endpoint. Design the encounter as an event log from day one.

#### 7.3 The modifier stack

By Phase 7 a single Effectiveness roll can be touched by a dozen sources. Implement it as an
**ordered, inspectable pipeline** where every contributor names itself, and render the
breakdown in the UI ("3d6 base, +1d6 Katana, +2d6 Rapier Burst, −2 Winded, +1d6 Trait
advantage"). Without this, nobody will trust the numbers and the HM will be unable to adjudicate.

#### 7.4 Damage, defense, and death

- **Dodging** is all-or-nothing: win Possibility and take zero, lose and take full.
- **Guarding** is easier but softer: winning Possibility lets you add your skill modifier to
  the Effectiveness you subtract from incoming damage; losing still subtracts the unmodified roll.
- **Death** occurs when damage exceeds the Trauma Limit — unless the attacker declares
  otherwise, a **Transformation** is active, or the defender makes a **Pluck Save** (Pluck
  exceeds the damage; max 2 per encounter).
- **Flash Save** — once per battle, react without penalty to an action that would kill an
  ally. Further Flash Saves cause **Winded**.
- **Destabilized** — a dead character's soul persists for weeks equal to their Potential
  (rounded up), invisible and intangible, still earning AP and acting through **Spirit
  Techniques** (4.5) while hunting a new body. **Impure Resurrection** is the way back.

#### 7.5 NPC battles

Wire the Catalog into encounters: HM picks a creature and threat level, the corrected
`generate_creature_stats()` produces the block, creature Talents run on their `2d6 × TL` use
budget and `ceil(TL / 2)` cooldown, and rewards pay out per 6's formulas. This finally
connects the original Phase III "battle against NPCs" end to end.

---

### Phase 8 — The school system

**Depends on:** Phases 1, 3, and 7 (Trials and Exams are combat). The largest phase here;
expect it to want its own sub-roadmap.

#### 8.1 The clock

Per-campaign: `semester` (1–2), `quarter` (1–4), `week` (1–4), plus a Summer Break flag.
2 semesters × 4 quarters × 4 weeks, with 4 free Summer weeks between semesters. The HM
advances the clock; advancing pays stipends, rolls classes, and fires any pending Trial or Exam.

#### 8.2 The weekly loop

**1 action per week, +1 per Rank.**

| Action | Effect |
| --- | --- |
| **Attending Class** | +1 AP; +1 more if the class matches your highest skill. Perfect attendance across a quarter: +1 to your lowest skill **or** +1 Trauma/Pneuma Limit. |
| **Training** | Spend actions equal to a technique's or transformation's Toll to learn it. Progress carries across weeks. |
| **Studying** | +1 AP; next AP gain +1 more; +x to all rolls on the next Exam or Trial (x = Rank). |
| **Shopping** | Buy techniques and equipment with Zel or AP (Phase 5). |
| **Resting** | Restore Trauma and Pneuma, raise skills, Rank Up if eligible. |
| **Forging** | Craft, repair broken armor, recharge spent items (Phase 5.5). |
| **Exploring** | Pick a location type, then take **one**: discover/create a permanent new area, **or** gain `xd6` crafting materials (x = Rank). Material *type* is a d6 whose faces map to the five categories, and the HM may replace an implausible face to weight by location. |

**Weekly stipend, paid automatically:** `House Reputation × Rank × 10` Zel.

A full quarter spent Exploring grants the **Lay of the Land** quirk: permanently +x (x =
Rank) to d6 results while exploring and in previously explored areas.

#### 8.3 Classes

| d6 | Class | Skill | Location |
| --- | --- | --- | --- |
| 1 | History | Wit | Grand Library |
| 2 | Woodshop | Handling | Engineering Wing |
| 3 | Archery | Perception | Bow Yard |
| 4 | P.E. | Tenacity | Dojo |
| 5 | Aquatics | Deftness | Pool Hall |
| 6 | Pneumatics | Composure | Null Space |

Classes available each week = the **highest Rank among the campaign's players**; the HM rolls
that many d6 and the faces become the week's offerings. Automate the roll (reusing
`roll_dice`), store it on the week, surface it on the campaign dashboard.

#### 8.4 Trials, Exams, and Expulsion

- **End of each Quarter — a Trial.** Grudge Match (teams of three, last team standing),
  Pop Quiz (1 AP per correct answer), Scavenger Hunt (retrieve a hidden item, usually within
  3 rounds, for 3 AP), Ring Recess (free-form, terms set by the proposing student with HM
  approval). Each has a **readmission clause** for expelled students. **Failing a Trial
  triggers expulsion.**
- **End of each Semester — a combat Exam against your House Leader.** Failure expels. The
  campaign typically ends if every student is expelled.
- **Expulsion is academic limbo, not removal** — Studying, Forging, and Attending Class are
  replaced by **Free Time**; events and Trials can readmit you.
- Build Trials and Exams as **HM-facilitated flows** (set up, track participants, record
  results, apply consequences), not full automation.

#### 8.5 Summer, Graduation, Ascension

- Summer's 4 weeks turn Attending Class into **Free Time**: restore Trauma and Pneuma, gain a
  temporary skill bonus reflecting how the time was spent.
- **Graduation** = year's end, alive, un-expelled, Final Exam passed. Afterward the school
  runs on Summer rules.
- **Ascension** — a graduate Contracts with a Deity and becomes a **Conduit**. All stats
  except three of the player's choosing are set to 10, AP resets to 0, **Pluck is unchanged**.
  Conduits use the d12 ladder in 1.2, get 3 of each action type, a 4th at Greater with a
  reaction penalty, and lose that penalty at Master.

#### 8.6 HM tooling

- **Fate-World-Mega-Meta-Reality Die** — a d20 world-event roller: 1 critical negative,
  2–9 negative, 10–11 neutral, 12–19 positive, 20 major positive, seeded with the Handbook's
  examples and extensible per campaign.
- **Skill Check DC reference** — Novice 10, Rookie 15, Genius 20, Expert 25, Veteran 30,
  Master 35, shown relative to the acting character's rank.
- **AP award helper** — `defeated party's highest rank + player party's highest rank`, plus a
  1-AP discretionary button for clever/cool/in-character play.
- **Unlocked locations** per campaign, seeded with the established four: The Pit (train
  skills), Altar of the Frozen Phoenix (restore Pneuma, contact Deities), The Hellspire Cafe
  (unique consumables), **Firebrand Forge (Teuchi's forge — the physical home of Phase 5.5)**.

---

### Phase 9 — The social layer

**Depends on:** Phase 3. Where NovaNet stops being a character manager and becomes the
platform the design doc describes.

- **Nova News Network** — the in-fiction public feed, per campaign plus a site-wide view.
  Already a nav link waiting for a page.
- **Private messaging** — player to player, carrying over outside a game with limitations.
- **Battle requests** — challenge another character; acceptance opens a Phase 7 encounter.
- **Discovery** — surfacing relevant posts and finding people to RP with. Start with simple
  heuristics (shared campaigns, recency, matching interests); ranking is a later refinement.
- **Yearbook** — a browsable gallery of current characters per campaign, with a **memorial**
  view for the deceased. Implies image upload and storage.
- **Music overlay and voice chat** — the furthest items from the current stack. Voice means
  WebRTC plus signaling and TURN; music means synced playback with licensing questions
  attached. Scope as their own project after the text features ship.

---

### Phase 10 — Production readiness

A track running alongside Phase 3 onward, not a final gate.

- Deployment: a real ASGI setup behind a reverse proxy. SQLite is fine for a long while;
  keep the data layer swappable to Postgres.
- Database backups — a campaign is months of a group's play.
- Rate limiting and input validation on every public form.
- Mobile-responsive CSS — people will check their sheet on a phone mid-session.
- Accessibility pass on forms, the builder, and the combat UI.
- Character sheet export (PDF or print stylesheet) for tables playing in person.
- Audit logging for HM and site-admin actions.

---

## Part III — Sequencing

1. **Phase 0** — refactor, templates, migrations, tests. Everything after is cheaper.
2. **Phase 1** — a truthful character sheet. Highest value in the document.
3. **Phase 2** — passwords and the admin/HM split.
4. **Phase 3** — campaigns, the structural backbone.
5. **Phases 4, 5, 6 in parallel** — the rules content layer. Phase 6 is the smallest and
   most self-contained (start there for momentum); Phase 4 is the deepest; Phase 5 depends
   on Phase 4's point-buy engine.
6. **Phase 7** — combat. The payoff, and the phase that validates 4–6.
7. **Phase 8** — the school system, which needs combat for Trials and Exams.
8. **Phase 9** — the social platform.
9. **Phase 10** — throughout, from Phase 3 onward.

### Recommended first slice

If you want one vertical slice that proves the architecture before committing to all ten
phases: **Phase 0 → Phase 1 → Phase 6 → a two-character Phase 7 duel.** That path touches
migrations, the rules engine, seed data, and the encounter state machine without needing
campaigns, the economy, or the school clock. If an Instant Link works correctly in that
duel, everything else is filling in tables.

### Open questions

- **How much does the app enforce vs. record?** The Handbook says outright that "a unanimous
  decision trumps the rulebook," and both manuals repeatedly say "at HM's discretion."
  Recommendation: automate all arithmetic (AP, Zel, stipends, dice, limits, status durations)
  and make **every** automated result HM-overridable. An engine that can't be overruled will
  fight the table.
- **How structured should Burst conditions be?** Roughly two thirds are machine-checkable;
  the rest are narrative. A hybrid — structured where possible, free text otherwise, with the
  engine *prompting* rather than *deciding* — is the pragmatic answer.
- **Campaign join model** — open, invite-only, or per-campaign. Per-campaign is assumed above.
- **Real-time or not.** Phase 7 encounters and Phase 9's feed both improve a lot with
  WebSockets and get considerably more complex. Polling is an acceptable v1 for both.
- **Do the Regalia/Noxia belong in shared reference data or per-campaign?** They're
  named, unique, story-bearing artifacts with fixed canonical locations — arguably each
  campaign should get its own copies to place and destroy independently.
