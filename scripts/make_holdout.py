"""Generate the held-out QBR PDFs in data/holdout/.

These documents were written (with their ground truth in eval/holdout_ground_truth/)
before the model ever processed them, and are never used to tune the prompt. They
deliberately cover cases the six sample reports do not: fiscal quarters, an email
recap, a half-year period, a two-column layout, owner initials with a legend, and a
conflict hidden in an appendix.

    python scripts/make_holdout.py
"""

from pathlib import Path

import pymupdf

OUT = Path(__file__).resolve().parent.parent / "data/holdout"

CSS = """
body { font-family: sans-serif; font-size: 10pt; line-height: 1.35; }
h1 { font-size: 18pt; margin-bottom: 2pt; }
h2 { font-size: 12pt; margin-top: 10pt; margin-bottom: 3pt; }
p { margin-top: 2pt; margin-bottom: 4pt; }
table { border-collapse: collapse; margin-top: 4pt; margin-bottom: 6pt; }
td, th { border: 1px solid #999; padding: 3pt 6pt; vertical-align: top; text-align: left; }
th { background-color: #eee; }
.meta { color: #444; }
.mono { font-family: monospace; font-size: 9pt; }
"""

ORION = """
<h1>Orion Insurance Group</h1>
<p class="meta"><b>Quarterly Business Review &mdash; Q3 FY2026</b></p>
<p class="meta">Reporting period: Q3 of fiscal year 2026 (October 1 &ndash; December 31, 2025).
Orion's fiscal year starts on July 1.</p>
<p class="meta">Prepared by Helix Consulting on behalf of the Customer Success team &middot; January 12, 2026</p>

<h2>1. Executive summary</h2>
<p>Claims automation went live for the Motor line in November, and straight-through processing
improved for the second consecutive quarter. SLA performance dipped in December because of the
seasonal claims peak. Orion's leadership confirmed budget for the Home line rollout in Q4 FY2026.</p>

<h2>2. Objectives for the quarter</h2>
<ul>
<li>Launch claims automation for the Motor line.</li>
<li>Reach 40% straight-through processing (STP) for eligible claims.</li>
<li>Keep claims processed within SLA at or above 95%.</li>
</ul>

<h2>3. Scorecard</h2>
<table>
<tr><th>Metric</th><th>Target</th><th>Q2 FY26</th><th>Q3 FY26</th><th>Status</th></tr>
<tr><td>Straight-through processing</td><td>40%</td><td>31%</td><td>42%</td><td>Achieved</td></tr>
<tr><td>Claims processed within SLA</td><td>&ge; 95%</td><td>96.2%</td><td>93.1%</td><td>Missed</td></tr>
<tr><td>Average claim cycle time (days)</td><td>&mdash;</td><td>6.8</td><td>5.9</td><td>&mdash;</td></tr>
<tr><td>Customer complaints</td><td>&mdash;</td><td>57</td><td>61</td><td>&mdash;</td></tr>
<tr><td>Active adjusters on platform</td><td>&mdash;</td><td>210</td><td>248</td><td>&mdash;</td></tr>
</table>

<h2>4. Action items from the previous QBR (Q2 FY26)</h2>
<table>
<tr><th>Action</th><th>Owner</th><th>Status</th></tr>
<tr><td>Finalize Motor claims rules</td><td>Orion Claims Ops</td><td>Done</td></tr>
<tr><td>Train adjusters on the new workflow</td><td>Helix Consulting</td><td>Done</td></tr>
<tr><td>Migrate historical claims data</td><td>Orion IT</td><td>In progress (see Next steps)</td></tr>
</table>

<h2>5. Challenges</h2>
<p>The December claims peak pushed SLA performance below target. Complaints rose slightly, mainly
about status notifications not being sent for automated claims.</p>

<h2>6. Risks</h2>
<p>If the historical data migration slips beyond February 2026, the Home line rollout may be delayed.
Mitigation: weekly migration checkpoint.</p>
<p>Key-person dependency: only one Orion analyst maintains the automation rules.</p>

<h2>7. Next steps</h2>
<table>
<tr><th>Action</th><th>Owner</th><th>Due</th></tr>
<tr><td>Fix status notifications for automated claims</td><td>Helix Consulting</td><td>by Jan 31</td></tr>
<tr><td>Complete historical claims data migration</td><td>Orion IT</td><td>February 2026</td></tr>
<tr><td>Home line rollout plan</td><td>VP Operations (Orion)</td><td>March 15, 2026</td></tr>
<tr><td>Assign a second automation rules analyst</td><td>Orion HR</td><td>TBD</td></tr>
</table>
"""

MERIDIAN = """
<p class="mono">From: Dana Weiss &lt;dana.weiss@vendor.example&gt;<br/>
To: Meridian Hotels account team<br/>
Sent: April 3, 2026<br/>
Subject: Q1 2026 review recap &mdash; Meridian Hotels &amp; Resorts</p>

<p>Hi all,</p>
<p>Thanks for a productive session on Tuesday. Quick recap below.</p>

<p><b>Where we landed this quarter</b></p>
<p>Direct bookings through the platform reached 12.4k, up from 8.7k in Q4. Note: in the last QBR we
reported 9.1k for Q4; the corrected figure is 8.7k after removing duplicate test bookings. The
target for Q1 was 15k, so we're behind, mostly because the Lisbon and Porto properties only went
live in mid-March.</p>
<p>Guest NPS moved from 31 to 38. Average check-in time at the kiosks is now under 2 minutes
(it was around 4 minutes before the upgrade).</p>

<p><b>What went well</b></p>
<p>The kiosk upgrade is live in all 14 properties. The loyalty integration passed UAT on the first
attempt.</p>

<p><b>What didn't</b></p>
<p>Lisbon and Porto went live late (vendor hardware delay). Front-desk staff in two properties are
still printing paper registration cards.</p>

<p><b>Risks</b></p>
<p>No major risks identified this quarter.</p>

<p><b>Next steps</b></p>
<ul>
<li>I'll send the updated integration spec by end of next week.</li>
<li>Marco (Meridian IT) to confirm the Wi-Fi upgrade schedule for Porto.</li>
<li>Joint workshop on the Q2 upsell campaign &mdash; date to be agreed.</li>
<li>Q2 target: 18k direct bookings.</li>
</ul>
<p>Best,<br/>Dana</p>
"""

KESTREL = """
<h1>KESTREL ENERGY &mdash; RETAIL DIVISION</h1>
<p class="meta"><b>Half-Year Business Review &middot; H1 2026 (January&ndash;June)</b></p>
<p class="meta">The Trading Division is reviewed separately.</p>

<table>
<tr><th>Highlights</th><th>Watch items</th></tr>
<tr>
<td>Smart-meter self-service portal launched in February.<br/><br/>
Digital billing adoption reached 71%, up from 58% at the end of 2025.<br/><br/>
Call-center volume down 18% year over year.</td>
<td>Billing-run failures in April affected ~3,200 customers; credits were issued.<br/><br/>
A portal accessibility audit found 12 issues (4 critical).<br/><br/>
A regulator inquiry on estimated bills is still open.</td>
</tr>
</table>

<h2>Goals for H1</h2>
<table>
<tr><th>Goal</th><th>Result</th></tr>
<tr><td>Digital billing adoption &ge; 70%</td><td>71% &mdash; met</td></tr>
<tr><td>Platform uptime &ge; 99.5%</td><td>99.5% &mdash; met</td></tr>
<tr><td>Launch self-service portal</td><td>Launched Feb 2026</td></tr>
</table>

<h2>Operational KPIs</h2>
<table>
<tr><th>Metric</th><th>H2 2025</th><th>H1 2026</th></tr>
<tr><td>Digital billing adoption</td><td>58%</td><td>71%</td></tr>
<tr><td>Avg. API response time (ms)</td><td>340</td><td>220</td></tr>
<tr><td>Billing-run success rate</td><td>99.1%</td><td>97.8%</td></tr>
<tr><td>Monthly active portal users</td><td>&mdash;</td><td>84,500</td></tr>
</table>

<h2>Risks</h2>
<ul>
<li>The regulator inquiry could result in a fine or mandated process changes.</li>
<li>Billing-run failures may recur when the new tariff structure launches in Q3.</li>
</ul>

<h2>Actions</h2>
<table>
<tr><th>Action</th><th>Owner</th><th>Due</th></tr>
<tr><td>Fix critical accessibility issues</td><td>JM</td><td>2026-07-31</td></tr>
<tr><td>Root-cause analysis of April billing failures</td><td>PR</td><td>15/07/2026</td></tr>
<tr><td>Prepare response to regulator inquiry</td><td>Legal (Kestrel)</td><td>TBC</td></tr>
</table>
<p class="meta">Owners: JM = Jonas Meyer (Portal team), PR = Priya Raman (Billing ops).</p>

<h2>Appendix &mdash; platform uptime by month</h2>
<table>
<tr><th>Jan</th><th>Feb</th><th>Mar</th><th>Apr</th><th>May</th><th>Jun</th><th>H1 average</th></tr>
<tr><td>99.8%</td><td>99.7%</td><td>99.6%</td><td>97.4%</td><td>99.6%</td><td>99.7%</td><td>99.3%</td></tr>
</table>
"""

DOCS = {
    "07_Orion_Insurance_QBR_Q3_FY2026.pdf": ORION,
    "08_Meridian_Hotels_Q1_2026_Recap_Email.pdf": MERIDIAN,
    "09_Kestrel_Energy_Retail_H1_2026_Review.pdf": KESTREL,
}


def render(html: str, path: Path) -> None:
    story = pymupdf.Story(html=html, user_css=CSS)
    page_rect = pymupdf.paper_rect("a4")
    content = page_rect + (50, 50, -50, -50)
    writer = pymupdf.DocumentWriter(str(path))
    more = True
    while more:
        device = writer.begin_page(page_rect)
        more, _ = story.place(content)
        story.draw(device)
        writer.end_page()
    writer.close()


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, html in DOCS.items():
        render(html, OUT / name)
        print(f"wrote {OUT / name}")
