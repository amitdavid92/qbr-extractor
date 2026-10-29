"""Compare pipeline output with hand-labelled ground truth (eval/ground_truth/*.json).

Matching is deterministic and free (no LLM judge): items match when their keyword stems
overlap enough. Lists use a lenient many-to-many match so that an item the model split
in two, or merged from two, still counts as found; KPIs and action items use one-to-one
matching because their fields (value, owner, due date) are compared afterwards.

Generated text (executive summary) is not scored.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .normalize import is_no_value
from .record import QbrRecord

_STOPWORDS = set(
    "a an the and or of to in on for with by at from as is are was were be been this that these those "
    "it its into during per than more less our their will would could should may can has have had not no".split()
)
MATCH_THRESHOLD = 0.6


def _filled(raw: str | None, num: float | None):
    """What the prediction put in a slot; a copied '—' or 'TBD' counts as empty."""
    if num is not None:
        return num
    return None if is_no_value(raw) else raw


def _stems(text: str) -> set[str]:
    return {t[:5] for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS}


def similarity(a: str, b: str) -> float:
    """Overlap coefficient of keyword stems: shared / size of the smaller set."""
    sa, sb = _stems(a), _stems(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


def name_similarity(a: str, b: str) -> float:
    """Jaccard on stems: stricter, so 'Users' does not match 'Weekly active users'."""
    sa, sb = _stems(a), _stems(b)
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def _pairs(gt: list[str], pred: list[str], score, threshold: float) -> list[tuple[int, int]]:
    """Greedy one-to-one matching, best scores first."""
    candidates = sorted(
        ((score(g, p), i, j) for i, g in enumerate(gt) for j, p in enumerate(pred)), reverse=True
    )
    used_g, used_p, pairs = set(), set(), []
    for s, i, j in candidates:
        if s >= threshold and i not in used_g and j not in used_p:
            used_g.add(i)
            used_p.add(j)
            pairs.append((i, j))
    return pairs


@dataclass
class Counts:
    gt_found: int = 0  # ground-truth items matched by a prediction (recall numerator)
    gt_total: int = 0
    pred_correct: int = 0  # predictions matching some ground-truth item (precision numerator)
    pred_total: int = 0

    def add(self, other: "Counts") -> None:
        for k in asdict(self):
            setattr(self, k, getattr(self, k) + getattr(other, k))

    @property
    def recall(self) -> float | None:
        return self.gt_found / self.gt_total if self.gt_total else None

    @property
    def precision(self) -> float | None:
        return self.pred_correct / self.pred_total if self.pred_total else None


@dataclass
class Tally:
    correct: int = 0
    total: int = 0

    def check(self, ok: bool) -> bool:
        self.correct += ok
        self.total += 1
        return ok

    def add(self, other: "Tally") -> None:
        self.correct += other.correct
        self.total += other.total

    @property
    def rate(self) -> float | None:
        return self.correct / self.total if self.total else None


@dataclass
class DocResult:
    file: str
    lists: dict[str, Counts] = field(default_factory=dict)  # goals, achievements, challenges, risks, kpis, action_items
    fields: dict[str, Tally] = field(default_factory=dict)  # scalar + per-item field accuracy
    invented: Tally = field(default_factory=Tally)  # slots that are null in GT: correct = stayed null
    conflicts: Counts = field(default_factory=Counts)
    errors: list[str] = field(default_factory=list)

    def tally(self, name: str) -> Tally:
        return self.fields.setdefault(name, Tally())


# Ground truth may list several acceptable answers where the document is genuinely
# ambiguous (e.g. owner "JM" with a legend "JM = Jonas Meyer"); any of them counts.


def _alternatives(expected) -> list:
    return expected if isinstance(expected, list) else [expected]


def _num_equal(a: float | None, expected) -> bool:
    for b in _alternatives(expected):
        if a is None or b is None:
            if a is None and b is None:
                return True
        elif abs(a - b) <= 1e-6 * max(1.0, abs(b)):
            return True
    return False


def _text_equal(a: str | None, expected) -> bool:
    norm = lambda s: " ".join(s.lower().split()) if s else None  # noqa: E731
    return any(norm(a) == norm(b) for b in _alternatives(expected))


def _name_equal(a: str | None, expected: str) -> bool:
    """Case-sensitive (casing is part of the requirement), but punctuation/dash style is ignored."""
    norm = lambda s: re.sub(r"[^\w]+", " ", s).strip() if s else None  # noqa: E731
    return norm(a) == norm(expected)


def evaluate_document(gt: dict, rec: QbrRecord) -> DocResult:
    res = DocResult(file=gt["file"])
    err = res.errors.append

    def field_check(name: str, ok: bool, expected, got) -> None:
        if not res.tally(name).check(ok):
            err(f"{name}: expected {expected!r}, got {got!r}")

    def null_slot(name: str, gt_value, pred_value) -> None:
        """Count a slot that should be empty; a filled value there is an invented one."""
        if gt_value is None and not res.invented.check(pred_value is None):
            err(f"INVENTED {name}: {pred_value!r} (ground truth is null)")

    # --- scalar fields
    field_check("customer_name", _name_equal(rec.customer.name, gt["customer_name"]), gt["customer_name"], rec.customer.name)
    gp = gt["period"]
    field_check("period_year", rec.period.year == gp["year"], gp["year"], rec.period.year)
    field_check("period_quarter", rec.period.quarter == gp["quarter"], gp["quarter"], rec.period.quarter)
    field_check("period_status", rec.period.status == gp["status"], gp["status"], rec.period.status)
    null_slot("period_year", gp["year"], rec.period.year)
    got_rd = rec.report_date.value.isoformat() if rec.report_date.value else None
    field_check("report_date", got_rd == gt["report_date"], gt["report_date"], got_rd)
    null_slot("report_date", gt["report_date"], got_rd)
    field_check("needs_review", rec.needs_review == gt["needs_review"], gt["needs_review"], rec.needs_review)

    # --- text lists (lenient many-to-many). A prediction matches on its description or on its
    # verbatim source quote, so a paraphrased description is not penalized.
    def item_score(g: str, p) -> float:
        return max(similarity(g, p.description), similarity(g, p.source_quote))

    def score_list(name: str, gt_items: list[str], preds: list) -> list[tuple[int, int]]:
        c = Counts(gt_total=len(gt_items), pred_total=len(preds))
        for g in gt_items:
            if any(item_score(g, p) >= MATCH_THRESHOLD for p in preds):
                c.gt_found += 1
            else:
                err(f"MISSED {name}: {g}")
        for p in preds:
            if any(item_score(g, p) >= MATCH_THRESHOLD for g in gt_items):
                c.pred_correct += 1
            else:
                err(f"EXTRA {name}: {p.description}")
        res.lists[name] = c
        return _pairs(gt_items, preds, item_score, MATCH_THRESHOLD)

    items = lambda t: [i for i in rec.items if i.item_type == t]  # noqa: E731
    pred_goals = items("goal")
    pairs = score_list("goals", [g["text"] for g in gt["goals"]], pred_goals)
    for i, j in pairs:
        field_check("goal_scope", pred_goals[j].scope == gt["goals"][i]["scope"],
                    f"{gt['goals'][i]['text']} -> {gt['goals'][i]['scope']}", pred_goals[j].scope)
    score_list("achievements", gt["achievements"], items("achievement"))
    score_list("challenges", gt["challenges"], items("challenge"))
    # Inferred risks are allowed but not scored; only explicit ('found') risks count.
    score_list("risks", gt["risks"], [i for i in items("risk") if i.status == "found"])

    # --- KPIs (one-to-one by name, then values)
    gk, pk = gt["kpis"], rec.kpis
    pairs = _pairs([k["name"] for k in gk], [k.name for k in pk], name_similarity, 0.5)
    res.lists["kpis"] = Counts(gt_found=len(pairs), gt_total=len(gk), pred_correct=len(pairs), pred_total=len(pk))
    matched_g, matched_p = {i for i, _ in pairs}, {j for _, j in pairs}
    for i in set(range(len(gk))) - matched_g:
        err(f"MISSED kpi: {gk[i]['name']}")
    for j in set(range(len(pk))) - matched_p:
        err(f"EXTRA kpi: {pk[j].name} = {pk[j].value_raw}")
    for i, j in pairs:
        g, p = gk[i], pk[j]
        field_check("kpi_value", _num_equal(p.value_num, g["value"]), f"{g['name']}={g['value']}", p.value_num)
        field_check("kpi_previous", _num_equal(p.previous_num, g["previous"]), f"{g['name']} prev={g['previous']}", p.previous_num)
        field_check("kpi_target", _num_equal(p.target_num, g["target"]), f"{g['name']} target={g['target']}", p.target_num)
        null_slot(f"kpi previous ({g['name']})", g["previous"], _filled(p.previous_raw, p.previous_num))
        null_slot(f"kpi target ({g['name']})", g["target"], _filled(p.target_raw, p.target_num))

    # --- action items (one-to-one by text, then owner / due date)
    ga, pa = gt["action_items"], rec.action_items
    pairs = _pairs([a["text"] for a in ga], pa, item_score, MATCH_THRESHOLD)
    res.lists["action_items"] = Counts(gt_found=len(pairs), gt_total=len(ga), pred_correct=len(pairs), pred_total=len(pa))
    for i in set(range(len(ga))) - {i for i, _ in pairs}:
        err(f"MISSED action: {ga[i]['text']}")
    for j in set(range(len(pa))) - {j for _, j in pairs}:
        err(f"EXTRA action: {pa[j].description}")
    for i, j in pairs:
        g, p = ga[i], pa[j]
        due = p.due_date.isoformat() if p.due_date else None
        field_check("action_owner", _text_equal(p.owner, g["owner"]), f"{g['text']} owner={g['owner']}", p.owner)
        field_check("action_due_date", due == g["due_date"], f"{g['text']} due={g['due_date']}", due)
        null_slot(f"owner ({g['text']})", g["owner"], p.owner)
        null_slot(f"due date ({g['text']})", g["due_date"], due)

    # --- conflicts (doc-level: each GT conflict should be found; any other is a false alarm)
    gc, pc = gt["conflicts"], rec.conflicts
    # Match on the topic or on the conflicting values, whichever agrees more.
    gc_keys = [f"{c['topic']}|{' '.join(c['values'])}" for c in gc]
    pc_keys = [f"{c.topic}|{' '.join(c.values)}" for c in pc]
    conflict_score = lambda g, p: max(  # noqa: E731
        similarity(g.split("|")[0], p.split("|")[0]), similarity(g.split("|")[1], p.split("|")[1]))
    pairs = _pairs(gc_keys, pc_keys, conflict_score, 0.5)
    res.conflicts = Counts(gt_found=len(pairs), gt_total=len(gc), pred_correct=len(pairs), pred_total=len(pc))
    for i in set(range(len(gc))) - {i for i, _ in pairs}:
        err(f"MISSED conflict: {gc[i]['topic']}")
    for j in set(range(len(pc))) - {j for _, j in pairs}:
        err(f"FALSE conflict: {pc[j].topic}: {' vs '.join(pc[j].values)}")
    return res


@dataclass
class EvalReport:
    model: str
    prompt_version: str
    docs: list[DocResult]

    def totals(self) -> tuple[dict[str, Counts], dict[str, Tally], Tally, Counts]:
        lists: dict[str, Counts] = {}
        fields: dict[str, Tally] = {}
        invented, conflicts = Tally(), Counts()
        for d in self.docs:
            for k, c in d.lists.items():
                lists.setdefault(k, Counts()).add(c)
            for k, t in d.fields.items():
                fields.setdefault(k, Tally()).add(t)
            invented.add(d.invented)
            conflicts.add(d.conflicts)
        return lists, fields, invented, conflicts

    def summary(self) -> dict:
        lists, fields, invented, conflicts = self.totals()
        r = lambda x: None if x is None else round(x, 3)  # noqa: E731
        return {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "lists": {k: {"precision": r(c.precision), "recall": r(c.recall)} for k, c in lists.items()},
            "fields": {k: {"accuracy": r(t.rate), "n": t.total} for k, t in fields.items()},
            "invented_values": {"count": invented.total - invented.correct, "null_slots": invented.total},
            "conflicts": {"detected": conflicts.gt_found, "expected": conflicts.gt_total,
                          "false_alarms": conflicts.pred_total - conflicts.pred_correct},
            "errors": {d.file: d.errors for d in self.docs},
        }

    def format(self) -> str:
        lists, fields, invented, conflicts = self.totals()
        pct = lambda x: "  n/a" if x is None else f"{x * 100:5.1f}%"  # noqa: E731
        out = [f"Evaluation  model={self.model}  prompt={self.prompt_version}  documents={len(self.docs)}", ""]
        out.append(f"{'LIST':<14}{'PRECISION':>10}{'RECALL':>9}   (found / expected)")
        for k, c in lists.items():
            out.append(f"{k:<14}{pct(c.precision):>10}{pct(c.recall):>9}   ({c.gt_found}/{c.gt_total})")
        out += ["", f"{'FIELD':<18}{'ACCURACY':>9}   (correct / checked)"]
        for k, t in fields.items():
            out.append(f"{k:<18}{pct(t.rate):>9}   ({t.correct}/{t.total})")
        out += [
            "",
            f"Invented values : {invented.total - invented.correct} of {invented.total} slots that should be empty",
            f"Conflicts       : {conflicts.gt_found}/{conflicts.gt_total} detected, "
            f"{conflicts.pred_total - conflicts.pred_correct} false alarm(s)",
            "",
            "Mismatches:",
        ]
        for d in self.docs:
            if d.errors:
                out.append(f"  {d.file}")
                out += [f"    - {e}" for e in d.errors]
        return "\n".join(out)


def load_ground_truth(directory: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted(directory.glob("*.json"))]
