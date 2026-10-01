---
name: dealroom-api-analysis description: >- The correctness layer for analysis done through the Dealroom API: the default filters that make a number match Dealroom's own, the attribution and definitional choices that silently change what you counted, and the tag-family map that decides whether "SaaS" means 43,000 companies or
  950. Read it whenever the NUMBER has to be right — a funding trend, a ranking, a share, a count,
anything going into a chart or a product. It assumes you can already call the API; for endpoints, filter syntax, auth and pagination, use the API reference.
---

# Dealroom API — getting the number right

This is how Dealroom analysts use the API.

It is **not** an API guide. It contains nothing about authentication, filter syntax, pagination or which endpoints exist — the API reference has all of that, and it is better at it. This document covers only the part no reference can tell you: **which population you should have counted.**

That gap is where the errors live. The API almost never refuses an analytical question — it answers it, with *a* number, computed over whatever population your filters happened to describe. Every wrong figure we have shipped came back `200 OK` and looked entirely plausible. There was no error to notice, and no amount of API fluency would have caught it.

Rules and figures below were verified live on 2026-09-17, on beta. Filter names updated on 2026-09-30 for API version 2026-10-02: `taxonomy_id` (was `tag_id`), `classification[in_any]:vc_backed` (was `is_vc_backed`), `classification[in_any]:unicorn` (was `is_unicorn`).

---

## 1. Default filters — the ones that make your number match Dealroom's

These are not preferences. They are what the Dealroom platform applies to its own VC and valuation views, and they are the single biggest reason a raw API pull disagrees with an analyst. **Apply them by query type.**

### VC funding

Anything summing or trending venture funding:

1. **Venture rounds only** — `is_vc_round[eq]:true`, or the `vc_funding` metric on the timeseries. This is **complete**: it already excludes grants, SPAC private placements, debt and convertibles. Do **not** add round-name exclusions on top — they are redundant, and a hand-listed set misses variants the flag already handles.
2. **Exclude Mature** — `growth_stage[nin_any]:412`
3. **Exclude Outside Tech** — `taxonomy_id[nin_any]:1102801`

```
and(<geo>,is_vc_round[eq]:true,growth_stage[nin_any]:412,taxonomy_id[nin_any]:1102801)
```

Each leg does real work. UK funding, 2024:

| Filter | 2024 total |
|---|---|
| No defaults | $20.30B |
| `is_vc_round` only | $18.56B |
| `growth_stage[nin_any]:412` only | $20.02B |
| `taxonomy_id[nin_any]:1102801` only | $19.80B |
| **All three** | **$18.25B** |

Publish the unfiltered figure and you are 11% high.

### Valuation / enterprise value / unicorns

Any query that filters, sorts or aggregates on a valuation field, or uses `classification[in_any]:unicorn`:

1. **Exclude Mature** — `growth_stage[nin_any]:412`
2. **Exclude Outside Tech** — `taxonomy_id[nin_any]:1102801`
3. **Founded 1990 or later** — `launch_date[gte]:1990`, deliberately strict: it also drops companies with no founding date

```
and(<geo>,growth_stage[nin_any]:412,taxonomy_id[nin_any]:1102801,launch_date[gte]:1990)
```

UK unicorns: 204 unfiltered → **201** with all three.

Two notes that reliably cause arguments:

- **The `mature company` *sector tag* is not a default.** It was dropped in August 2026 because the platform's EV view never applied it. Apply it only when asked, and say that you did.
- **Mirroring a specific platform view?** Add `company_status[nin_any]:closed` (the `not_closed` chip) and `classification[in_any]:vc_backed` if the view carries the VC Backed chip. When someone shows you their filter chips, match **their** chips, not these defaults.

**Exit valuations are separate** and do not take the EV defaults.

### Everything else

**No default exclusions.** Do not apply the VC or EV packs to a plain company count, a people query or a jobs query. Let the question specify.

---

## 2. Attribution — where a company counts, and for what

A company has an HQ, a founding location and offices. Which one you attribute by changes the answer, and the right choice depends on the metric, not on taste:

| Query type | Default scope | Why |
|---|---|---|
| **VC funding** | **HQ only** | Matches the platform's VC flow: a round is attributed to where the company is headquartered |
| **Enterprise value** | **HQ or founding** | Captures "value originated here" — a unicorn founded in a country that later moved HQ still counts for that ecosystem |
| **Mixed** | HQ or founding | The entity-scope question dominates the funding-attribution one |
| Anything else | State what you chose | — |

Two consequences worth internalising:

- **Pick one key.** Mixing HQ with office locations, or stacking overlapping regions, double-counts. Use office location only when someone explicitly asks about operating footprint.
- **HQ-or-founding does not sum.** A company founded in one target country and headquartered in another counts in both, so per-country columns will exceed the de-duplicated total. That is correct for platform-matching per-country stats — but say so, and compute any grand total separately rather than adding the column up.

### The three Europes

"Europe" resolves to several IDs, and they are different populations: one is the **continent** (excludes Türkiye and Israel), one the **region** (includes Türkiye), and a third includes both. Default to the region when someone just says "Europe", and **state which you used**. A European total that silently changed definition between two charts is worse than no total at all.

---

## 3. The tag map — which family holds your answer

**Everything is a `taxonomy_id`.** There is no `industry`, `business_model` or `sub_industry` filter key — they all fail as unknown filters. So the filter you write cannot express which *kind* of tag you meant; only the ID can. Pick from the wrong family and the query is still valid, still returns rows, and counts a different population.

Nine client-facing families:

| Family | API `type` | Meaning | Size |
|---|---|---|---|
| Industry | `industry` | Top-level industry; max 2 per company | 31 |
| Sub-industry | `sub_industry` | Vertical inside an industry; requires a parent | ~85 |
| Sector | `sector` | Cross-cutting theme. Flat, overlapping, thousands, many near-empty | ~4,400 |
| Technology | `technology` | Underlying technology | ~98 |
| SDG | `sdg` | UN Sustainable Development Goal | 17 |
| Business model | `business_model` | How the business operates | 3 |
| Income stream | `income_stream` | Revenue mechanism | 4 |
| Client focus | `client_focus` | b2b / b2c | 2 |
| Ownership | `ownership` | Ownership structure | 9 |

Plus one you will meet and must never use as a classification: **`techstack_category`** (~555) is website-technology detection — what a company's *site runs*, not what it does. It collides with real tag names constantly.

### Read the family off the ID

IDs are built `id * 100 + family`, so **the last two digits name the family**:

`01` sector · `02` technology · `03` industry · `04` sub-industry · `05` SDG · `06` techstack · `07` ownership · `08` business model · `09` income stream · `11` client focus

`602` is a technology, `125403` an industry, `83608` a business model, `39306` a techstack decoy. Verified live against 17 IDs across six families — 17/17. **Decode every ID before you send it.** It costs nothing and it is the cheapest guard here.

### When a name exists in two families, prefer the typed one

Many concepts have both a proper typed tag and a same-named grey `sector` tag. Sector is the catch-all: flat, overlapping, full of one-off and test tags. Prefer, in this order:

`business_model` → `client_focus` → `income_stream` → `industry` → `sub_industry` → `technology` → `sdg` → `ownership` → **`sector` last**

SaaS, marketplace, b2b, b2c and subscription are business-model / client-focus / income-stream values. Reach for the grey tag for any of them and you are wrong by roughly the margin above.

### Industry beats a same-named sector tag

For a broad vertical — "robotics", "health", "fintech" — take the **`industry`** row. A same-named `sector` tag is usually niche: robotics as an industry covers ~40,000 companies, the same-named sector tag about 51. **A `"<X> tech"` tag is the classic trap** — Food Tech has about 2 companies; you want the **Food** industry. If a slice comes back suspiciously thin, suspect the tag before you report that the data is missing.

### Repeating a key means AND. Piping values means OR.

This silently changes your population. Swiss robotics:

| Filter | Companies | Means |
|---|---|---|
| `taxonomy_id[in_any]:10009203` | **443** | robotics |
| `and(taxonomy_id[in_any]:10009203,taxonomy_id[in_any]:602)` | **199** | robotics **AND** deep tech |
| `taxonomy_id[in_any]:10009203\|602` | **1,449** | robotics **OR** *anything* deep tech |

Asked for "Swiss deep-tech robotics", the pipe hands you 1,449 — over 3× the robotics universe itself. Cross-cutting themes (deep tech, AI, climate) **layer on top of** an industry: a second `taxonomy_id` leg, never an extra value in the first one. And do not drop the theme as redundant — over half of Swiss robotics companies are not deep tech.

---

## 4. Definitions that get conflated

Each of these returns a healthy number for the wrong question.

- **VC funding is not total funding.** Total funding includes grants, debt and non-venture rounds. Never reconstruct "VC funding" by summing all transactions.
- **Company funding totals are all-time.** There is no period total on a company, so "who raised the most in 2026" cannot be answered by sorting companies — see §5.
- **Stage: use the standardised round, not the reported one.** The self-reported round name is largely marketing — a self-labelled Series A may be a seed by size and timing. The standardised label re-derives the true stage. Use it for any cross-company stage comparison.
- **Unclassified rounds are deliberate.** A round with no standardised stage did not meet the definition. Exclude it from stage analysis and report the excluded share — never backfill it from the reported name.
- **Unicorn status is a valuation threshold**, so a unicorn query is an EV query and takes the EV defaults.
- **Counting companies is not counting valued companies.** A company count should include companies with no valuation. Filtering on "has a valuation" conflates "matches the filters" with "we have a number for it", and undercounts.
- **Deep tech is narrow.** It is a strict technology tag, not a mood, and it materially shrinks a slice — which is the point. State the tag and family you used; it changes every count.

### Silent-zero traps

Three ways to get zero rows and conclude, wrongly, that nothing exists:

- an ID that was never resolved;
- an enum spelled the way a *different* filter wants it — one takes the lowercase code, its sibling takes the display name, and **only one of them errors**; the other just returns nothing;
- a niche sector tag where you meant the industry.

**When a slice comes back empty, suspect the query before you believe the emptiness.**

### Nulls that are not missing data

The API serves **redacted** rows to a lower-tier principal: fields arrive as `null` rather than absent, flagged by a `locked` array and a non-premium tier on the response. A correctly authenticated call has neither. If either marker is present your credentials did not apply — the nulls are redactions, and reporting them as "no data" is a wrong answer rather than a thin one.

---

## 5. Review before you trust it

Every item here returns a plausible number rather than an error.

**VC funding**
1. ☐ Venture rounds only, via the flag or the VC metric?
2. ☐ Mature excluded?
3. ☐ Outside Tech excluded?
4. ☐ No redundant round-name exclusions bolted on?

**Valuation / EV / unicorns**
5. ☐ All three EV defaults applied?
6. ☐ `mature company` tag *not* excluded unless asked?
7. ☐ Mirroring a platform view? Then match their chips, and exclude closed.

**Any query**
8. ☐ Attribution right for the metric — HQ for VC, HQ-or-founding for EV — and stated?
9. ☐ One geography key only?
10. ☐ Per-country columns not summed into a total that double-counts?
11. ☐ Which "Europe"? Named in the answer?
12. ☐ **Decoded every tag ID's last two digits** — is it the family you meant?
13. ☐ SaaS / marketplace / b2b / b2c / subscription taken from the typed family, never the grey sector tag?
14. ☐ Broad vertical taken from the industry, not a same-named sector tag?
15. ☐ Cross-cutting theme on its own `taxonomy_id` leg, not piped into the industry's values?
16. ☐ Stage analysis on the standardised round, with the unclassified share reported?
17. ☐ VC funding not confused with total funding? Period totals not taken from an all-time field?
18. ☐ Empty result interrogated before being believed?
19. ☐ Current year excluded or labelled partial?
20. ☐ Paged results complete, or the truncation reported?

---

